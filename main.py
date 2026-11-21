import os
import re
import time
import secrets
import shutil
import sqlite3
import tempfile
import mimetypes
import asyncio
import urllib.parse
import html
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, LinkPreviewOptions, CallbackQuery
from pyrogram.errors import FloodWait
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
PORT = int(os.getenv("PORT", "3005"))
BASE_URL = os.getenv("BASE_URL", "https://drive.pwxstudy.site").rstrip("/")
ALLOWED_TELEGRAM_USERS = os.getenv("ALLOWED_TELEGRAM_USERS", "").strip()
allowed_user_list = [u.strip().lower() for u in ALLOWED_TELEGRAM_USERS.split(",") if u.strip()]

def is_telegram_user_allowed(user) -> bool:
    if not allowed_user_list:
        return True
    if not user:
        return False
    user_id = str(user.id)
    username = (user.username or "").lower()
    return user_id in allowed_user_list or username in allowed_user_list

def format_size_human(size_bytes: int) -> str:
    if not size_bytes or size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(size_bytes)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    return f"{val:.2f} {units[i]}"

def init_db():
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            size INTEGER NOT NULL,
            mime_type TEXT NOT NULL,
            folder TEXT DEFAULT '/',
            share_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            share_token TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("INSERT OR IGNORE INTO folders (path) VALUES ('/')")
    
    # Check share_token in files
    c.execute("PRAGMA table_info(files)")
    cols = [col[1] for col in c.fetchall()]
    if "share_token" not in cols:
        c.execute("ALTER TABLE files ADD COLUMN share_token TEXT")
        c.execute("SELECT id FROM files WHERE share_token IS NULL")
        for (file_id,) in c.fetchall():
            c.execute("UPDATE files SET share_token = ? WHERE id = ?", (secrets.token_urlsafe(12), file_id))

    # Check share_token in folders
    c.execute("PRAGMA table_info(folders)")
    fcols = [col[1] for col in c.fetchall()]
    if "share_token" not in fcols:
        c.execute("ALTER TABLE folders ADD COLUMN share_token TEXT")

    # Generate share_token for any folders that lack one
    c.execute("SELECT id, path FROM folders WHERE share_token IS NULL")
    for (fid, fpath) in c.fetchall():
        c.execute("UPDATE folders SET share_token = ? WHERE id = ?", (secrets.token_urlsafe(14), fid))

    # Check user_id in files
    c.execute("PRAGMA table_info(files)")
    f_cols = [col[1] for col in c.fetchall()]
    if "user_id" not in f_cols:
        c.execute("ALTER TABLE files ADD COLUMN user_id INTEGER")

    # Check user_id in folders
    c.execute("PRAGMA table_info(folders)")
    fo_cols = [col[1] for col in c.fetchall()]
    if "user_id" not in fo_cols:
        c.execute("ALTER TABLE folders ADD COLUMN user_id INTEGER")

    # User registry table for isolated user folder spaces
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            base_folder TEXT NOT NULL,
            active_folder TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure all distinct folders from files table exist in folders table
    c.execute("SELECT DISTINCT folder FROM files WHERE folder IS NOT NULL")
    for (fld,) in c.fetchall():
        if fld:
            c.execute("SELECT id FROM folders WHERE path = ?", (fld,))
            if not c.fetchone():
                c.execute("INSERT OR IGNORE INTO folders (path, share_token) VALUES (?, ?)", (fld, secrets.token_urlsafe(14)))

    conn.commit()
    conn.close()

init_db()

def get_folder_share_token(path: str, user_id: int | None = None) -> str:
    path = path.rstrip("/") or "/"
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("SELECT share_token FROM folders WHERE path = ?", (path,))
    row = c.fetchone()
    if row and row[0]:
        token = row[0]
        if user_id:
            c.execute("UPDATE folders SET user_id = ? WHERE path = ? AND user_id IS NULL", (user_id, path))
            conn.commit()
    else:
        token = secrets.token_urlsafe(14)
        c.execute("INSERT INTO folders (path, share_token, user_id) VALUES (?, ?, ?) ON CONFLICT(path) DO UPDATE SET share_token = ?", (path, token, user_id, token))
        conn.commit()
    conn.close()
    return token

# ========================================================
# Boosted Telegram MTProto Upload Engine
# ========================================================
import math
import io
from hashlib import md5
import functools
from pyrogram import raw, StopTransmission

async def boosted_save_file(
    self: Client,
    path,
    file_id: int | None = None,
    file_part: int = 0,
    progress=None,
    progress_args: tuple = (),
):
    async with self.save_file_semaphore:
        if path is None:
            return None

        failures: list[Exception] = []

        async def worker(session):
            while True:
                data = await queue.get()
                if data is None:
                    return
                try:
                    await session.invoke(data)
                except Exception as e:
                    failures.append(e)

        part_size = 512 * 1024

        if isinstance(path, (str, os.PathLike)):
            fp = open(path, "rb")
        elif isinstance(path, io.IOBase):
            fp = path
        else:
            raise ValueError("Invalid file. Expected file path or binary pointer")

        file_name = getattr(fp, "name", "file.bin")
        fp.seek(0, os.SEEK_END)
        file_size = fp.tell()
        fp.seek(0)

        if file_size == 0:
            raise ValueError("File size equals to 0 B")

        file_size_limit_mib = 4000 if (self.me and self.me.is_premium) else 2000
        if file_size > file_size_limit_mib * 1024 * 1024:
            raise ValueError(f"Can't upload files bigger than {file_size_limit_mib} MiB")

        file_total_parts = int(math.ceil(file_size / part_size))
        is_big = file_size > 10 * 1024 * 1024
        
        # High-throughput workers: 8 parallel workers for big files, 4 for small files
        workers_count = min(8, file_total_parts) if is_big else min(4, file_total_parts)
        is_missing_part = file_id is not None
        file_id = file_id or self.rnd_id()
        md5_sum = md5() if not is_big and not is_missing_part else None
        dc_id = await self.storage.dc_id()

        session = await self.get_session(dc_id, is_media=True)

        # Buffer queue to keep all workers saturated
        queue = asyncio.Queue(maxsize=workers_count * 2)
        workers = [asyncio.create_task(worker(session)) for _ in range(workers_count)]

        try:
            fp.seek(part_size * file_part)

            while True:
                chunk = fp.read(part_size)
                if not chunk:
                    if not is_big and not is_missing_part:
                        md5_sum = "".join([hex(i)[2:].zfill(2) for i in md5_sum.digest()])
                    break

                if is_big:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=file_id,
                        file_part=file_part,
                        file_total_parts=file_total_parts,
                        bytes=chunk,
                    )
                else:
                    rpc = raw.functions.upload.SaveFilePart(
                        file_id=file_id, file_part=file_part, bytes=chunk
                    )

                await queue.put(rpc)

                if is_missing_part:
                    break

                if not is_big and not is_missing_part:
                    md5_sum.update(chunk)

                file_part += 1

                if progress:
                    func = functools.partial(
                        progress,
                        min(file_part * part_size, file_size),
                        file_size,
                        *progress_args,
                    )
                    if asyncio.iscoroutinefunction(progress):
                        await func()
                    else:
                        await asyncio.get_running_loop().run_in_executor(self.executor, func)
        except StopTransmission:
            raise
        except Exception as e:
            raise
        finally:
            for _ in workers:
                await queue.put(None)
            await asyncio.gather(*workers)
            if isinstance(path, (str, os.PathLike)):
                fp.close()

        if failures:
            raise failures[0]

        if is_missing_part:
            return None

        if is_big:
            return raw.types.InputFileBig(id=file_id, parts=file_total_parts, name=file_name)

        return raw.types.InputFile(
            id=file_id, parts=file_total_parts, name=file_name, md5_checksum=md5_sum
        )

Client.save_file = boosted_save_file

bot = Client(
    "tg_drive_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    max_concurrent_transmissions=10
)

def get_chunk_base_dir():
    # Prefer /dev/shm (RAM disk) for zero-latency I/O if available with at least 2GB free
    shm = "/dev/shm"
    if os.path.exists(shm) and os.access(shm, os.W_OK):
        try:
            stat = os.statvfs(shm)
            free_bytes = stat.f_bavail * stat.f_frsize
            if free_bytes > 2 * 1024 * 1024 * 1024:
                p = os.path.join(shm, "tg_chunks")
                os.makedirs(p, exist_ok=True)
                return p
        except Exception:
            pass
    p = os.path.join(tempfile.gettempdir(), "tg_chunks")
    os.makedirs(p, exist_ok=True)
    return p

chunk_locks: dict[str, asyncio.Lock] = {}
completed_chunk_uploads: dict[str, dict] = {}

def get_chunk_lock(upload_id: str) -> asyncio.Lock:
    if upload_id not in chunk_locks:
        chunk_locks[upload_id] = asyncio.Lock()
    return chunk_locks[upload_id]

async def cleanup_stale_chunks():
    while True:
        try:
            await asyncio.sleep(1800)
            base = get_chunk_base_dir()
            if os.path.exists(base):
                now = time.time()
                for entry in os.scandir(base):
                    if entry.is_dir():
                        try:
                            if now - entry.stat().st_mtime > 7200:
                                shutil.rmtree(entry.path, ignore_errors=True)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Cleanup error: {e}")

media_processing_queue: asyncio.Queue = asyncio.Queue()

async def media_queue_worker():
    while True:
        try:
            job = await media_processing_queue.get()
            try:
                if job.get("mode") == "batch":
                    await process_batch_job(job)
                else:
                    await process_single_job(job)
            except Exception as e:
                print(f"[media_queue_worker job error] {e}")
            finally:
                media_processing_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[media_queue_worker loop error] {e}")
            await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.start()
    try:
        me = await bot.get_me()
        print(f"Telegram MTProto Connected as @{me.username} (ID: {me.id})")
    except Exception:
        print("Telegram MTProto Connected (Subfolder Edition)")
    cleanup_task = asyncio.create_task(cleanup_stale_chunks())
    worker_task = asyncio.create_task(media_queue_worker())
    yield
    cleanup_task.cancel()
    worker_task.cancel()
    await bot.stop()

app = FastAPI(lifespan=lifespan)

# Mount Vite React frontend static assets if available
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
if os.path.exists(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# ========================================================
# Video / Image Thumbnail Generation & Cache
# ========================================================

THUMB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "thumbnails")
os.makedirs(THUMB_DIR, exist_ok=True)
_thumb_locks: dict[int, asyncio.Lock] = {}

async def get_or_create_thumbnail(message_id: int) -> Optional[str]:
    thumb_path = os.path.join(THUMB_DIR, f"{message_id}.jpg")
    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
        return thumb_path

    if message_id not in _thumb_locks:
        _thumb_locks[message_id] = asyncio.Lock()

    async with _thumb_locks[message_id]:
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path

        # 1. Try Telegram native media thumbnail
        try:
            msg = await bot.get_messages(CHANNEL_ID, message_id)
            if msg and msg.media:
                media = getattr(msg, msg.media.value)
                thumbs = getattr(media, "thumbs", None)
                if not thumbs and getattr(msg, "photo", None):
                    thumbs = [msg.photo[-1] if isinstance(msg.photo, list) else msg.photo]

                if thumbs:
                    best_thumb = thumbs[-1]
                    data = await bot.download_media(best_thumb.file_id, in_memory=True)
                    if data and hasattr(data, "getvalue") and len(data.getvalue()) > 0:
                        tmp_path = f"{thumb_path}.tmp.{os.getpid()}"
                        with open(tmp_path, "wb") as f:
                            f.write(data.getvalue())
                        os.replace(tmp_path, thumb_path)
                        return thumb_path
        except Exception as e:
            print(f"[Thumbnail Telegram error] {message_id}: {e}")

        # 2. Try FFmpeg extraction fallback if video
        if shutil.which("ffmpeg"):
            try:
                stream_url = f"http://127.0.0.1:{PORT}/stream/{message_id}?key={ADMIN_PASS}"
                tmp_path = f"{thumb_path}.tmp.{os.getpid()}.jpg"
                cmd = [
                    "ffmpeg", "-y", "-ss", "00:00:02",
                    "-i", stream_url,
                    "-vframes", "1",
                    "-q:v", "3",
                    tmp_path
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await asyncio.wait_for(proc.communicate(), timeout=12)
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    os.replace(tmp_path, thumb_path)
                    return thumb_path
            except Exception as e:
                print(f"[Thumbnail FFmpeg error] {message_id}: {e}")

    return None

@app.api_route("/thumb/{message_id}", methods=["GET", "HEAD"])
async def serve_file_thumbnail(message_id: int, request: Request, token: str = "", key: str = ""):
    if key != ADMIN_PASS:
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT share_token FROM files WHERE message_id = ?", (message_id,))
        row = c.fetchone()
        conn.close()
        if not row or not token or row[0] != token:
            raise HTTPException(status_code=401, detail="Unauthorized")

    thumb_path = await get_or_create_thumbnail(message_id)
    if not thumb_path or not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(
        thumb_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )

@app.api_route("/thumb/f/{token}", methods=["GET", "HEAD"])
async def serve_file_thumbnail_by_token(token: str):
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("SELECT message_id FROM files WHERE share_token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    message_id = row[0]
    thumb_path = await get_or_create_thumbnail(message_id)
    if not thumb_path or not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(
        thumb_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800, immutable"}
    )

# ========================================================
# Telegram Bot Interactive PM Handlers & User Isolation
# ========================================================

def get_link_preview_opts(disable_preview: bool = True):
    try:
        return LinkPreviewOptions(is_disabled=disable_preview)
    except Exception:
        return None

async def reply_text_safe(message: Message, text: str, reply_markup=None, disable_preview: bool = True):
    opts = get_link_preview_opts(disable_preview)
    for attempt in range(4):
        try:
            if opts is not None:
                try:
                    return await message.reply_text(text, reply_markup=reply_markup, link_preview_options=opts)
                except TypeError:
                    pass
            return await message.reply_text(text, reply_markup=reply_markup)
        except FloodWait as e:
            wait_s = int(getattr(e, 'value', 3) or 3)
            print(f"[FloodWait on reply] Waiting {wait_s}s...")
            await asyncio.sleep(wait_s + 1)
        except Exception:
            return None
    return None

async def edit_text_safe(message: Message, text: str, reply_markup=None, disable_preview: bool = True):
    if not message:
        return None
    opts = get_link_preview_opts(disable_preview)
    for attempt in range(4):
        try:
            if opts is not None:
                try:
                    return await message.edit_text(text, reply_markup=reply_markup, link_preview_options=opts)
                except TypeError:
                    pass
            return await message.edit_text(text, reply_markup=reply_markup)
        except FloodWait as e:
            wait_s = int(getattr(e, 'value', 3) or 3)
            print(f"[FloodWait on edit] Waiting {wait_s}s...")
            await asyncio.sleep(wait_s + 1)
        except Exception:
            return None
    return None

def get_or_create_bot_user(user) -> dict:
    if not user:
        return {"user_id": 0, "username": "", "first_name": "Anonymous", "base_folder": "/Telegram", "active_folder": "/Telegram"}
    
    user_id = user.id
    username = getattr(user, "username", "") or ""
    first_name = getattr(user, "first_name", "") or ""

    conn = sqlite3.connect("drive.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM bot_users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        data = dict(row)
        if data.get("username") != username or data.get("first_name") != first_name:
            c.execute(
                "UPDATE bot_users SET username = ?, first_name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (username, first_name, user_id)
            )
            conn.commit()
            data["username"] = username
            data["first_name"] = first_name
        conn.close()
        return data

    # Create new isolated base folder for this user
    if username:
        clean_u = re.sub(r'[^a-zA-Z0-9_]', '', username)
        base_folder = f"/@{clean_u}" if clean_u else f"/user_{user_id}"
    else:
        clean_fn = re.sub(r'[^a-zA-Z0-9_]', '', first_name)
        base_folder = f"/user_{clean_fn}_{user_id}" if clean_fn else f"/user_{user_id}"

    # Check collision with other users
    c.execute("SELECT user_id FROM bot_users WHERE base_folder = ?", (base_folder,))
    if c.fetchone():
        base_folder = f"{base_folder}_{user_id}"

    active_folder = base_folder
    c.execute(
        "INSERT INTO bot_users (user_id, username, first_name, base_folder, active_folder) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, first_name, base_folder, active_folder)
    )
    conn.commit()
    conn.close()

    # Ensure base folder is in folders table with a share token
    get_folder_share_token(base_folder, user_id)

    return {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "base_folder": base_folder,
        "active_folder": active_folder
    }

def set_user_active_folder(user_id: int, folder_path: str):
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("UPDATE bot_users SET active_folder = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (folder_path, user_id))
    conn.commit()
    conn.close()

def get_relative_folder_name(full_path: str, base_folder: str) -> str:
    if not full_path or full_path == base_folder or full_path == "/":
        return "🏠 Root"
    if full_path.startswith(base_folder + "/"):
        rel = full_path[len(base_folder):]
        return rel if rel.startswith("/") else f"/{rel}"
    return full_path

def resolve_user_folder_path(user_base: str, input_path: str) -> str:
    clean = (input_path or "").strip()
    if not clean or clean.lower() in ("/", "root", "home", "/root", "/home"):
        return user_base
    if clean.startswith(user_base + "/") or clean == user_base:
        return clean
    sub = clean.lstrip("/").rstrip("/")
    parts = [p.strip() for p in sub.split("/") if p.strip()]
    if not parts:
        return user_base
    return f"{user_base}/{'/'.join(parts)}"

def parse_folder_command(text: str) -> str | None:
    if not text:
        return None
    clean = text.strip()
    if clean.lower().startswith("/folder"):
        parts = clean.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            f = parts[1].strip()
            if not f.startswith("/"):
                f = "/" + f
            return f.rstrip("/") or "/"
        return None

    if clean.startswith("/") and not clean.startswith("//"):
        cmd = clean.split()[0]
        # Ignore reserved system commands
        if cmd.lower() in (
            "/start", "/help", "/id", "/myid", "/folders", "/myfolders", "/list",
            "/newfolder", "/mkdir", "/create", "/share", "/sharefolder",
            "/root", "/home", "/resetfolder", "/files", "/status",
            "/delfolder", "/deletefolder", "/rmdir",
            "/clone", "/clonechannel", "/stopclone", "/cancelclone"
        ):
            return None
        f = cmd.rstrip("/")
        return f if f else "/"
    return None

async def perform_delete_folder(folder_path: str, user_id: int | None = None) -> tuple[bool, str, int]:
    folder_path = folder_path.rstrip("/") or "/"
    if folder_path == "/":
        return False, "Cannot delete root directory", 0

    conn = sqlite3.connect("drive.db")
    c = conn.cursor()

    # If user_id is provided, enforce security check
    if user_id:
        c.execute("SELECT base_folder FROM bot_users WHERE user_id = ?", (user_id,))
        urow = c.fetchone()
        if not urow:
            conn.close()
            return False, "User not found", 0
        user_base = urow[0]
        if folder_path == user_base:
            conn.close()
            return False, "Aap apna main root folder delete nahi kar sakte!", 0
        if not folder_path.startswith(user_base + "/"):
            conn.close()
            return False, "Aap sirf apna folder hi delete kar sakte hain!", 0

    c.execute("SELECT id, message_id FROM files WHERE folder = ? OR folder LIKE ?", (folder_path, folder_path + "/%"))
    files_to_del = c.fetchall()
    for fid, mid in files_to_del:
        try:
            await bot.delete_messages(CHANNEL_ID, mid)
        except Exception:
            pass
        c.execute("DELETE FROM files WHERE id = ?", (fid,))

    c.execute("DELETE FROM folders WHERE path = ? OR path LIKE ?", (folder_path, folder_path + "/%"))
    c.execute("UPDATE bot_users SET active_folder = base_folder WHERE active_folder = ? OR active_folder LIKE ?", (folder_path, folder_path + "/%"))
    conn.commit()
    conn.close()
    return True, "Success", len(files_to_del)

async def build_folders_view(u: dict):
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("""
        SELECT id, path, share_token FROM folders 
        WHERE path = ? OR path LIKE ? 
        ORDER BY CASE WHEN path = ? THEN 0 ELSE 1 END, path ASC
    """, (u["base_folder"], f"{u['base_folder']}/%", u["base_folder"]))
    user_folders = c.fetchall()

    c.execute("""
        SELECT folder, COUNT(*), COALESCE(SUM(size), 0) FROM files 
        WHERE folder = ? OR folder LIKE ? 
        GROUP BY folder
    """, (u["base_folder"], f"{u['base_folder']}/%"))
    counts_map = {r[0]: (r[1], r[2]) for r in c.fetchall()}
    conn.close()

    rel_active = get_relative_folder_name(u["active_folder"], u["base_folder"])
    msg_lines = [
        "📂 **Aapka Personal TG-Drive Space** 🚀\n",
        f"👤 **User Space:** `{u['base_folder']}`",
        f"🎯 **Active Target:** `{rel_active}`\n",
        "────────────────────────"
    ]

    buttons = []
    for fid, fpath, ftoken in user_folders:
        rel_name = get_relative_folder_name(fpath, u["base_folder"])
        cnt, sz = counts_map.get(fpath, (0, 0))
        is_active = (fpath == u["active_folder"])
        active_badge = " `[Active ✅]`" if is_active else ""
        fshare = f"{BASE_URL}/share/{ftoken}"
        
        icon = "🏠" if rel_name == "🏠 Root" else "📁"
        msg_lines.append(f"\n{icon} **{rel_name}**{active_badge}")
        msg_lines.append(f"   📊 {cnt} files • {format_size_human(sz)}")
        msg_lines.append(f"   🔗 [Open / Share Link]({fshare})")

        if rel_name != "🏠 Root":
            if not is_active:
                btn_switch = InlineKeyboardButton(f"📂 Switch {rel_name}", callback_data=f"cb:sw:{fid}")
                btn_share = InlineKeyboardButton("🔗 Share", callback_data=f"cb:sh:{fid}")
                btn_del = InlineKeyboardButton("🗑️", callback_data=f"cb:del_ask:{fid}")
                buttons.append([btn_switch, btn_share, btn_del])
            else:
                btn_share = InlineKeyboardButton("🔗 Share Active", callback_data=f"cb:sh:{fid}")
                btn_del = InlineKeyboardButton(f"🗑️ Delete {rel_name}", callback_data=f"cb:del_ask:{fid}")
                buttons.append([btn_share, btn_del])

    buttons.append([
        InlineKeyboardButton("🏠 Switch to Root", callback_data="cb:root"),
        InlineKeyboardButton("🔗 Share Active", callback_data="cb:share_active")
    ])

    msg_lines.append("\n────────────────────────")
    msg_lines.append("💡 *Naya folder banane ke liye `/newfolder <name>` likhein.*")
    msg_lines.append("💡 *Folder delete karne ke liye `/delfolder <name>` likhein.*")
    msg_lines.append("💡 *Fast switch ke liye bas command bhejein (jaise `/movies`).*")

    return "\n".join(msg_lines), InlineKeyboardMarkup(buttons[:10])

def generate_progress_bar(percent: int, length: int = 10) -> str:
    filled = int(round(length * percent / 100))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)

# ========================================================
# Telegram Channel Cloning Engine
# ========================================================

def parse_link_or_chat(token: str):
    token = token.strip()
    m_priv = re.match(r'https?://t\.me/c/(\d+)(?:/(\d+))?', token)
    if m_priv:
        chat_id = int('-100' + m_priv.group(1))
        msg_id = int(m_priv.group(2)) if m_priv.group(2) else None
        return chat_id, msg_id

    m_pub = re.match(r'https?://t\.me/([a-zA-Z0-9_]+)(?:/(\d+))?', token)
    if m_pub and m_pub.group(1).lower() not in ('c', 'joinchat'):
        chat_id = m_pub.group(1)
        msg_id = int(m_pub.group(2)) if m_pub.group(2) else None
        return chat_id, msg_id

    if token.startswith('@'):
        return token[1:], None

    if re.match(r'^-?\d+$', token):
        return int(token), None

    return None, None

def parse_clone_args(text: str, reply_msg: Optional[Message] = None):
    tokens = [t.strip() for t in text.split()[1:] if t.strip()]
    source_chat = None
    start_id = 1
    end_id = None
    target_val = None

    if reply_msg and getattr(reply_msg, 'forward_from_chat', None):
        source_chat = reply_msg.forward_from_chat.id or reply_msg.forward_from_chat.username
        start_id = reply_msg.forward_from_message_id or 1
        if tokens:
            target_val = tokens[0]
            if len(tokens) > 1 and tokens[1].isdigit():
                end_id = start_id + int(tokens[1]) - 1
        return source_chat, target_val, start_id, end_id

    if not tokens:
        return None, None, None, None

    # Token 0 is source
    s_chat, s_id = parse_link_or_chat(tokens[0])
    if s_chat:
        source_chat = s_chat
        if s_id:
            start_id = s_id

    if not source_chat:
        return None, None, None, None

    idx = 1
    # Check if Token 1 is second link (for range)
    if idx < len(tokens):
        c2, id2 = parse_link_or_chat(tokens[idx])
        if c2 == source_chat and id2:
            end_id = id2
            idx += 1
        elif id2 and not c2:
            end_id = id2
            idx += 1

    # Next token is target
    if idx < len(tokens):
        target_val = tokens[idx]
        idx += 1

    # Optional start/end numbers
    if idx < len(tokens) and tokens[idx].isdigit():
        num = int(tokens[idx])
        idx += 1
        if idx < len(tokens) and tokens[idx].isdigit():
            start_id = num
            end_id = int(tokens[idx])
        else:
            end_id = num

    return source_chat, target_val, start_id, end_id

class CloneSession:
    def __init__(self, user_id: int, source_chat, target_mode: str, target_val, start_id: int, end_id: Optional[int]):
        self.user_id = user_id
        self.source_chat = source_chat
        self.target_mode = target_mode
        self.target_val = target_val
        self.start_id = start_id
        self.end_id = end_id
        self.is_running = True
        self.total_processed = 0
        self.copied_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.status_msg: Optional[Message] = None
        self.task: Optional[asyncio.Task] = None

active_clones: dict[int, CloneSession] = {}

async def probe_channel_chunk(chat_id, p: int):
    chunk = list(range(max(1, p - 19), p + 1))
    try:
        msgs = await bot.get_messages(chat_id, chunk)
        valid = [m.id for m in msgs if m and not m.empty]
        return p, valid
    except Exception:
        return p, []

async def fast_detect_range(chat_id) -> tuple[int, int]:
    try:
        chat = await bot.get_chat(chat_id)
        hint = chat.pinned_message.id if chat.pinned_message else 1
    except Exception:
        hint = 1

    checkpoints = [100000, 50000, 25000, 10000, 5000, 3000, 2000, 1000, 500, 200, 100]
    if hint > 1:
        checkpoints.append(hint)
    checkpoints = sorted(list(set(checkpoints)), reverse=True)

    tasks = [probe_channel_chunk(chat_id, cp) for cp in checkpoints]
    results = await asyncio.gather(*tasks)

    valid_points = [p for p, val in results if val]
    if not valid_points:
        try:
            init_msgs = await bot.get_messages(chat_id, list(range(1, 51)))
            init_val = [m.id for m in init_msgs if m and not m.empty]
            if init_val:
                return min(init_val), max(init_val)
        except Exception:
            pass
        return 1, hint or 1

    max_p = max(valid_points)
    min_p = min(valid_points)

    # Binary search for exact max
    low = max_p
    high = max_p + 3500
    exact_max = max_p
    while low <= high:
        mid = (low + high) // 2
        chunk = list(range(mid, min(mid + 15, high + 1)))
        try:
            msgs = await bot.get_messages(chat_id, chunk)
            val = [m.id for m in msgs if m and not m.empty]
            if val:
                exact_max = max(exact_max, max(val))
                low = max(val) + 1
            else:
                high = mid - 1
        except Exception:
            high = mid - 1

    # Binary search for exact min
    low = 1
    high = min_p
    exact_min = min_p
    while low <= high:
        mid = (low + high) // 2
        chunk = list(range(mid, min(mid + 15, high + 1)))
        try:
            msgs = await bot.get_messages(chat_id, chunk)
            val = [m.id for m in msgs if m and not m.empty]
            if val:
                exact_min = min(val)
                high = mid - 1
            else:
                low = mid + 15
        except Exception:
            low = mid + 15

    return exact_min, exact_max

async def execute_channel_clone(session: CloneSession, user: dict):
    user_id = session.user_id
    source_chat = session.source_chat
    target_mode = session.target_mode
    target_val = session.target_val
    start_id = session.start_id
    end_id = session.end_id
    status_msg = session.status_msg

    stop_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹️ Stop Cloning", callback_data="cb:stopclone")]
    ])

    try:
        source_chat_obj = await bot.get_chat(source_chat)
        source_title = source_chat_obj.title or str(source_chat)
    except Exception as e:
        await edit_text_safe(
            status_msg,
            f"❌ **Source Channel Error**\n\n"
            f"Channel `{source_chat}` ko access nahi kar paaye: `{e}`\n\n"
            "💡 *Agar private channel hai toh pehle bot ko us channel me Administrator banayein.*"
        )
        active_clones.pop(user_id, None)
        return

    dest_title = ""
    rel_folder = ""
    target_folder = ""

    if target_mode == "channel":
        try:
            target_chat_obj = await bot.get_chat(target_val)
            dest_title = target_chat_obj.title or str(target_val)
        except Exception as e:
            await edit_text_safe(
                status_msg,
                f"❌ **Destination Channel Error**\n\n"
                f"Target channel `{target_val}` ko access nahi kar paaye: `{e}`\n\n"
                "💡 *Bot ko target channel me Administrator banakar 'Post Messages' permission dein.*"
            )
            active_clones.pop(user_id, None)
            return
    else:
        # Drive mode
        target_folder = resolve_user_folder_path(user["base_folder"], str(target_val))
        rel_folder = get_relative_folder_name(target_folder, user["base_folder"])
        dest_title = f"Web Drive ({rel_folder})"

    # Auto-detect channel range if end_id not provided
    if not end_id:
        if status_msg:
            await edit_text_safe(
                status_msg,
                f"🔍 **Scanning Channel Structure...**\n\n"
                f"📡 **Source:** `{source_title}`\n"
                f"🎯 **Target:** `{dest_title}`\n\n"
                "⏳ Finding files and active message range in channel...",
                reply_markup=stop_markup
            )
        try:
            auto_min, auto_max = await fast_detect_range(source_chat)
            if start_id == 1 and auto_min > 1:
                curr_id = auto_min
            else:
                curr_id = start_id
            end_id = auto_max
        except Exception as e:
            print(f"[fast_detect_range error] {e}")
            curr_id = start_id
            end_id = None
    else:
        curr_id = start_id

    batch_size = 50
    consecutive_empty_batches = 0
    max_empty_batches = 10
    last_edit_time = time.time()
    total_to_scan = (end_id - curr_id + 1) if end_id else None

    while session.is_running:
        if end_id and curr_id > end_id:
            break

        this_batch_end = min(curr_id + batch_size - 1, end_id) if end_id else (curr_id + batch_size - 1)
        batch_ids = list(range(curr_id, this_batch_end + 1))
        if not batch_ids:
            break

        try:
            messages = await bot.get_messages(source_chat, batch_ids)
        except FloodWait as e:
            wait_s = int(getattr(e, 'value', 5) or 5)
            if status_msg:
                await edit_text_safe(status_msg, f"⏳ **Telegram rate limit active.** Auto-waiting `{wait_s}s`...", reply_markup=stop_markup)
            await asyncio.sleep(wait_s + 1)
            continue
        except Exception as e:
            print(f"[Clone get_messages error] {e}")
            break

        valid_msgs = [m for m in messages if m and not m.empty and not getattr(m, 'service', False)]
        if not valid_msgs:
            consecutive_empty_batches += 1
            if not end_id and consecutive_empty_batches >= max_empty_batches:
                break
        else:
            consecutive_empty_batches = 0

        for m in messages:
            if not session.is_running:
                break
            session.total_processed += 1

            if not m or m.empty or getattr(m, 'service', False):
                session.skipped_count += 1
                continue

            current_file_name = None

            if target_mode == "channel":
                chan_msg = None
                for attempt in range(5):
                    if not session.is_running:
                        break
                    try:
                        chan_msg = await m.copy(chat_id=target_val)
                        session.copied_count += 1
                        break
                    except FloodWait as e:
                        wait_s = int(getattr(e, 'value', 5) or 5)
                        if status_msg:
                            await edit_text_safe(status_msg, f"⏳ Rate limit: waiting `{wait_s}s`... (Copied: {session.copied_count})", reply_markup=stop_markup)
                        await asyncio.sleep(wait_s + 1)
                    except Exception as e:
                        print(f"[Clone copy to channel error] {e}")
                        session.failed_count += 1
                        break
                await asyncio.sleep(1.2)

            else:
                media = (
                    m.document or m.video or m.audio or
                    m.voice or m.video_note or
                    (m.photo[-1] if isinstance(m.photo, list) else m.photo)
                )
                if not media:
                    session.skipped_count += 1
                    continue

                file_size = getattr(media, "file_size", 0)
                file_name = getattr(media, "file_name", None)

                if not file_name:
                    if m.video:
                        file_name = f"video_{m.id}.mp4"
                    elif m.audio:
                        file_name = f"audio_{m.id}.mp3"
                    elif m.voice:
                        file_name = f"voice_{m.id}.ogg"
                    elif m.video_note:
                        file_name = f"videonote_{m.id}.mp4"
                    elif m.photo:
                        file_name = f"photo_{m.id}.jpg"
                    else:
                        file_name = f"file_{m.id}.bin"

                if m.caption:
                    t_match = re.search(r'(?:Title|Name)\s*:\s*([^\r\n]+)', m.caption, re.IGNORECASE)
                    if t_match:
                        extracted_name = re.sub(r'[*_`]', '', t_match.group(1)).strip()
                        if extracted_name and len(extracted_name) > 3:
                            if "." not in extracted_name and "." in (file_name or ""):
                                extracted_name += os.path.splitext(file_name)[1]
                            file_name = extracted_name

                current_file_name = file_name
                mime_type = getattr(media, "mime_type", None) or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

                chan_msg = None
                for attempt in range(5):
                    if not session.is_running:
                        break
                    try:
                        chan_msg = await m.copy(
                            chat_id=CHANNEL_ID,
                            caption=f"Folder: `{target_folder}` | File: `{file_name}`"
                        )
                        break
                    except FloodWait as e:
                        wait_s = int(getattr(e, 'value', 5) or 5)
                        if status_msg:
                            await edit_text_safe(status_msg, f"⏳ Rate limit: waiting `{wait_s}s`... (Saved: {session.copied_count})", reply_markup=stop_markup)
                        await asyncio.sleep(wait_s + 1)
                    except Exception as e:
                        print(f"[Clone copy to storage error] {e}")
                        break

                if chan_msg:
                    share_token = secrets.token_urlsafe(12)
                    try:
                        conn = sqlite3.connect("drive.db")
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO files (message_id, name, size, mime_type, folder, share_token, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (chan_msg.id, file_name, file_size, mime_type, target_folder, share_token, user["user_id"])
                        )
                        conn.commit()
                        conn.close()
                        session.copied_count += 1
                        if mime_type.startswith("video/") or mime_type.startswith("image/"):
                            asyncio.create_task(get_or_create_thumbnail(chan_msg.id))
                    except Exception as e:
                        print(f"[Clone db error] {e}")
                        session.failed_count += 1
                else:
                    session.failed_count += 1

                await asyncio.sleep(1.2)

            now = time.time()
            if now - last_edit_time > 3.5:
                progress_str = ""
                if total_to_scan:
                    pct = min(100, int((session.total_processed / total_to_scan) * 100))
                    bar = generate_progress_bar(pct)
                    progress_str = f"📊 **Progress:** `[{bar}]` `{pct}%` ({session.total_processed}/{total_to_scan})\n"
                else:
                    progress_str = f"📊 **Scanned:** `{session.total_processed}` messages\n"

                file_display = f"\n📄 **Current:** `{current_file_name[:35].replace('`', '')}`" if current_file_name else ""
                stat_text = (
                    "⚡ **Channel Cloning in Progress...**\n\n"
                    f"📡 **Source:** `{source_title}`\n"
                    f"🎯 **Target:** `{dest_title}`\n"
                    f"{progress_str}"
                    f"✅ **Copied:** `{session.copied_count}`\n"
                    f"⏭️ **Skipped:** `{session.skipped_count}`\n"
                    f"📍 **Message ID:** `#{m.id}`"
                    f"{file_display}\n\n"
                    "🛡️ *Background rate-pacing & FloodWait auto-recovery active.*"
                )
                if status_msg:
                    await edit_text_safe(status_msg, stat_text, reply_markup=stop_markup)
                last_edit_time = now

        curr_id = this_batch_end + 1

    is_cancelled = not session.is_running
    active_clones.pop(user_id, None)

    final_header = "⏹️ **Channel Clone Stopped by User**" if is_cancelled else "🎉 **Channel Clone Completed!** 🚀"
    final_card = (
        f"{final_header}\n\n"
        f"📡 **Source:** `{source_title}`\n"
        f"🎯 **Target:** `{dest_title}`\n"
        f"✅ **Total Copied:** `{session.copied_count}` items\n"
        f"⏭️ **Skipped:** `{session.skipped_count}`\n"
    )
    if session.failed_count > 0:
        final_card += f"⚠️ **Failed:** `{session.failed_count}` items\n"

    final_buttons = []
    if target_mode == "drive":
        folder_token = get_folder_share_token(target_folder, user["user_id"])
        folder_share_url = f"{BASE_URL}/share/{folder_token}"
        final_card += f"\n🌐 **Web Drive Folder Link:**\n`{folder_share_url}`"
        final_buttons.append([InlineKeyboardButton(f"📂 Open Folder ({rel_folder})", url=folder_share_url)])
        final_buttons.append([InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders")])
    else:
        final_buttons.append([InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders")])

    final_markup = InlineKeyboardMarkup(final_buttons)
    if status_msg:
        await edit_text_safe(status_msg, final_card, reply_markup=final_markup, disable_preview=True)
    else:
        await reply_text_safe(status_msg, final_card, reply_markup=final_markup, disable_preview=True)

@bot.on_message(filters.private & filters.text)
async def bot_text_router(client: Client, message: Message):
    text = (message.text or "").strip()
    u = get_or_create_bot_user(message.from_user)

    # Secret Channel Cloning commands (/clone, /clonechannel, /stopclone, /cancelclone)
    if text.lower() in ("/stopclone", "/cancelclone"):
        if not is_telegram_user_allowed(message.from_user):
            await reply_text_safe(message, "⛔ Access Restricted.")
            return
        sess = active_clones.get(message.from_user.id)
        if not sess or not sess.is_running:
            await reply_text_safe(message, "ℹ️ Koi active channel clone task running nahi hai.")
            return
        sess.is_running = False
        await reply_text_safe(message, "⏹️ **Stopping Clone Task...** Current batch complete hote hi ruk jayega.")
        return

    if text.lower().startswith(("/clone", "/clonechannel")):
        if not is_telegram_user_allowed(message.from_user):
            await reply_text_safe(
                message,
                "⛔ **Access Restricted**\n\n"
                "Ye ek secret admin command hai. Aap is command ko use karne ke liye authorized nahi hain."
            )
            return

        source_chat, target_val, start_id, end_id = parse_clone_args(text, message.reply_to_message)
        if not source_chat:
            secret_help = (
                "🔐 **Secret Telegram Channel Cloner** ⚡\n\n"
                "Aap kisi bhi Telegram channel ke sabhi files ya messages ko Web Drive ya kisi aur channel me clone kar sakte hain!\n\n"
                "📌 **Usage Formats:**\n\n"
                "1️⃣ **Clone to Web Drive Folder:**\n"
                "• `/clone @source_channel /Physics`\n"
                "• `/clone @source_channel /Physics 1 100` *(Start to End ID)*\n"
                "• `/clone -100123456789 /Notes` *(Private Channel ID)*\n\n"
                "2️⃣ **Clone to Another Telegram Channel:**\n"
                "• `/clone @source_channel @target_channel`\n"
                "• `/clone @source_channel -100987654321 1 500`\n\n"
                "3️⃣ **Clone via Telegram Message Links:**\n"
                "• `/clone https://t.me/source/10 https://t.me/source/150 /Lectures`\n\n"
                "4️⃣ **Forward & Reply:**\n"
                "• Channel ka koi bhi message forward karke reply karein:\n"
                "  `/clone /Physics`\n\n"
                "🛑 **Stop Clone:** `/stopclone` ya inline button dabayein.\n\n"
                "💡 *Note: Private channels ke liye bot ka us channel me Administrator hona zaroori hai.*"
            )
            await reply_text_safe(message, secret_help)
            return

        if message.from_user.id in active_clones and active_clones[message.from_user.id].is_running:
            await reply_text_safe(
                message,
                "⚠️ **Ek clone task pehle se running hai!**\n\n"
                "Pehle wale task ko cancel karne ke liye `/stopclone` likhein."
            )
            return

        # Determine target mode
        if not target_val:
            target_val = f"/{source_chat}".replace("@", "")

        is_target_channel = (
            str(target_val).startswith("@") or
            bool(re.match(r'^-?100\d+$', str(target_val))) or
            "t.me/" in str(target_val)
        )
        target_mode = "channel" if is_target_channel else "drive"
        if target_mode == "channel":
            c_target, _ = parse_link_or_chat(str(target_val))
            if c_target:
                target_val = c_target

        status_msg = await reply_text_safe(
            message,
            "🔄 **Initializing Channel Clone...** ⚡\n\n"
            f"📡 **Source:** `{source_chat}`\n"
            f"🎯 **Target:** `{target_val}`\n"
            f"📍 **Range:** `#{start_id}` to `{'#' + str(end_id) if end_id else 'Latest'}`\n\n"
            "⏳ Connecting to channel and verifying permissions...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏹️ Stop Cloning", callback_data="cb:stopclone")]
            ])
        )

        session = CloneSession(
            user_id=message.from_user.id,
            source_chat=source_chat,
            target_mode=target_mode,
            target_val=target_val,
            start_id=start_id,
            end_id=end_id
        )
        session.status_msg = status_msg
        active_clones[message.from_user.id] = session

        task = asyncio.create_task(execute_channel_clone(session, u))
        session.task = task
        return

    # 1. /start or /help
    if text.lower() in ("/start", "/help"):
        rel_active = get_relative_folder_name(u["active_folder"], u["base_folder"])
        root_token = get_folder_share_token(u["base_folder"], u["user_id"])
        root_share_url = f"{BASE_URL}/share/{root_token}"

        welcome_text = (
            "👋 **Namaste! Welcome to TG-Cloud Drive Bot** 🚀\n\n"
            f"Aapka personal dedicated drive space tayyar hai:\n"
            f"👤 **User Space:** `{u['base_folder']}`\n"
            f"🎯 **Active Target:** `{rel_active}`\n\n"
            "Mujhe koi bhi **video, movie, document, ya audio** forward ya send kijiye, wo seedha aapke folder me store hogi!\n\n"
            "✨ **Main Commands:**\n"
            "• `/folders` - Apne sabhi folders aur file counts dekhein\n"
            "• `/newfolder <name>` - Naya folder banayein (jaise `/newfolder Movies`)\n"
            "• `/delfolder <name>` - Folder aur uski sabhi files delete karein\n"
            "• `/share` - Apne current active folder ka public share link paayein\n"
            "• `/root` ya `/resetfolder` - Wapas apne main root folder me jayein\n"
            "• `/files` - Current folder ki uploaded files dekhein\n"
            "• *Fast Switch:* Bas `/<folder_name>` likhein (e.g. `/movies` ya `/notes`)\n\n"
            f"🌐 **Aapka Personal Web Drive Link:**\n{root_share_url}"
        )
        await reply_text_safe(
            message,
            welcome_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Open My Drive Space", url=root_share_url)],
                [
                    InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders"),
                    InlineKeyboardButton("🔗 Share Active Folder", callback_data="cb:share_active")
                ]
            ]),
            disable_preview=True
        )
        return

    # 2. /id or /myid
    if text.lower() in ("/id", "/myid"):
        rel_active = get_relative_folder_name(u["active_folder"], u["base_folder"])
        await reply_text_safe(
            message,
            f"👤 **Your Telegram ID:** `{message.from_user.id}`\n"
            f"📛 **Username:** @{message.from_user.username or 'none'}\n"
            f"📂 **Personal Space:** `{u['base_folder']}`\n"
            f"🎯 **Active Folder:** `{rel_active}`"
        )
        return

    # 3. /folders or /myfolders or /list
    if text.lower() in ("/folders", "/myfolders", "/list"):
        msg_text, markup = await build_folders_view(u)
        await reply_text_safe(message, msg_text, reply_markup=markup, disable_preview=True)
        return

    # 4. /newfolder or /mkdir or /create
    if text.lower().startswith(("/newfolder", "/mkdir", "/create")):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await reply_text_safe(
                message,
                "⚠️ **Folder ka naam likhein!**\n\n"
                "Example:\n"
                "• `/newfolder Movies`\n"
                "• `/newfolder Chemistry/Lec1`\n"
                "• `/newfolder WebSeries`"
            )
            return

        raw_name = parts[1].strip()
        target_path = resolve_user_folder_path(u["base_folder"], raw_name)
        token = get_folder_share_token(target_path, u["user_id"])
        set_user_active_folder(u["user_id"], target_path)

        rel_name = get_relative_folder_name(target_path, u["base_folder"])
        share_url = f"{BASE_URL}/share/{token}"

        await reply_text_safe(
            message,
            "✅ **Naya Folder Ban Gaya & Active Set Ho Gaya!** 📂\n\n"
            f"📁 **Folder:** `{rel_name}`\n"
            f"🎯 **Full Path:** `{target_path}`\n\n"
            f"🌐 **Public Web Share Link:**\n`{share_url}`\n\n"
            f"Ab aap jo bhi video ya file send/forward karenge, wo automatically **`{rel_name}`** me save hogi! 🚀",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name} in Web", url=share_url)],
                [InlineKeyboardButton("📂 All Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    # 5. /delfolder or /deletefolder or /rmdir
    if text.lower().startswith(("/delfolder", "/deletefolder", "/rmdir")):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await reply_text_safe(
                message,
                "⚠️ **Folder ka naam likhein jise delete karna hai!**\n\n"
                "Example:\n"
                "• `/delfolder Movies`\n"
                "• `/delfolder Chemistry/Lec1`\n\n"
                "💡 *Apne sabhi folders dekhne ke liye `/folders` likhein.*"
            )
            return

        raw_name = parts[1].strip()
        target_path = resolve_user_folder_path(u["base_folder"], raw_name)
        rel_name = get_relative_folder_name(target_path, u["base_folder"])

        if target_path == u["base_folder"]:
            await reply_text_safe(message, "⛔ **Aap apna main root folder delete nahi kar sakte.**")
            return

        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT id FROM folders WHERE path = ?", (target_path,))
        row = c.fetchone()
        if not row:
            conn.close()
            await reply_text_safe(
                message,
                f"❌ **Folder `{rel_name}` nahi mila!**\n\n"
                "Apne sabhi folders dekhne ke liye `/folders` likhein."
            )
            return

        fid = row[0]
        c.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files WHERE folder = ? OR folder LIKE ?", (target_path, target_path + "/%"))
        cnt, sz = c.fetchone()
        conn.close()

        await reply_text_safe(
            message,
            "⚠️ **Folder Deletion Confirmation** 🗑️\n\n"
            f"📁 **Target Folder:** `{rel_name}`\n"
            f"📊 **Files Inside:** {cnt} files ({format_size_human(sz)})\n\n"
            "❗ *Kya aap sach me is folder aur iski sabhi files ko permanently delete karna chahte hain?*",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑️ Haan, Delete Karein", callback_data=f"cb:del_cf:{fid}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cb:del_cn")
                ]
            ]),
            disable_preview=True
        )
        return

    # 5. /share or /sharefolder
    if text.lower().startswith(("/share", "/sharefolder")):
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            target_path = resolve_user_folder_path(u["base_folder"], parts[1].strip())
        else:
            target_path = u["active_folder"]

        token = get_folder_share_token(target_path, u["user_id"])
        rel_name = get_relative_folder_name(target_path, u["base_folder"])
        share_url = f"{BASE_URL}/share/{token}"

        await reply_text_safe(
            message,
            "🌐 **Public Folder Share Link Tayyar Hai!** 🔗\n\n"
            f"📁 **Folder:** `{rel_name}`\n\n"
            f"🔗 **Link:**\n`{share_url}`\n\n"
            "💡 *Is link ko kisi ke sath bhi share karein. Koi bhi browser me bina login ke sabhi files dekh sakta hai aur video stream kar sakta hai!*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)],
                [InlineKeyboardButton("📂 View All Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    # 6. /resetfolder or /root or /home
    if text.lower() in ("/resetfolder", "/root", "/home"):
        set_user_active_folder(u["user_id"], u["base_folder"])
        root_token = get_folder_share_token(u["base_folder"], u["user_id"])
        root_share_url = f"{BASE_URL}/share/{root_token}"

        await reply_text_safe(
            message,
            "🏠 **Root Folder Selected!**\n\n"
            f"🎯 Active folder wapas root (`{u['base_folder']}`) set ho gaya hai.\n\n"
            "Ab aane wali sabhi files aapke main space me store hongi.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Open My Drive", url=root_share_url)],
                [InlineKeyboardButton("📂 View Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    # 7. /files or /status
    if text.lower() in ("/files", "/status"):
        rel_active = get_relative_folder_name(u["active_folder"], u["base_folder"])
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT name, size, share_token, message_id FROM files WHERE folder = ? ORDER BY id DESC LIMIT 15", (u["active_folder"],))
        files = c.fetchall()
        conn.close()

        if not files:
            await reply_text_safe(
                message,
                f"📂 **Folder:** `{rel_active}`\n\n"
                "*(Is folder me abhi koi files nahi hain.)*\n\n"
                "💡 Video ya koi bhi file bhej kar upload karein!"
            )
            return

        lines = [f"📁 **Files in `{rel_active}` ({len(files)} items):**\n"]
        for name, sz, stk, mid in files:
            stream_link = f"{BASE_URL}/f/{stk}"
            lines.append(f"• `{name}` ({format_size_human(sz)})\n  🎬 [Stream / Watch]({stream_link})")

        token = get_folder_share_token(u["active_folder"], u["user_id"])
        fshare = f"{BASE_URL}/share/{token}"
        await reply_text_safe(
            message,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_active} in Browser", url=fshare)]
            ]),
            disable_preview=True
        )
        return

    # 8. Check if text is a folder path (e.g. "/movies" or "/Chemistry/Lec1" or "/folder /movies")
    folder_cmd = parse_folder_command(text)
    if folder_cmd:
        target_path = resolve_user_folder_path(u["base_folder"], folder_cmd)
        token = get_folder_share_token(target_path, u["user_id"])
        rel_name = get_relative_folder_name(target_path, u["base_folder"])

        # Check if user is replying to an existing file message to MOVE it
        if message.reply_to_message:
            replied = message.reply_to_message
            target_token = None
            m = re.search(r'/f/([a-zA-Z0-9_\-]+)', replied.text or "")
            if m:
                target_token = m.group(1)
            elif replied.reply_markup and replied.reply_markup.inline_keyboard:
                for row in replied.reply_markup.inline_keyboard:
                    for btn in row:
                        if btn.url:
                            bm = re.search(r'/f/([a-zA-Z0-9_\-]+)', btn.url)
                            if bm:
                                target_token = bm.group(1)
                                break
                    if target_token:
                        break

            if target_token:
                conn = sqlite3.connect("drive.db")
                c = conn.cursor()
                c.execute("UPDATE files SET folder = ? WHERE share_token = ?", (target_path, target_token))
                c.execute("SELECT name FROM files WHERE share_token = ?", (target_token,))
                row = c.fetchone()
                conn.commit()
                conn.close()

                file_display_name = row[0] if row else "File"
                set_user_active_folder(u["user_id"], target_path)
                share_url = f"{BASE_URL}/share/{token}"
                await reply_text_safe(
                    message,
                    f"✅ **Moved Successfully!**\n\n"
                    f"📄 `{file_display_name}` ko **`{rel_name}`** folder me move kar diya gaya hai.\n\n"
                    f"🎯 Aane wali sabhi files ke liye bhi active folder **`{rel_name}`** set ho gaya hai!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)]
                    ]),
                    disable_preview=True
                )
                return

        # If not replying, switch active folder
        set_user_active_folder(u["user_id"], target_path)
        share_url = f"{BASE_URL}/share/{token}"
        await reply_text_safe(
            message,
            f"📂 **Active Folder Set:** `{rel_name}`\n\n"
            f"Ab aap jo bhi files ya forwarded videos bhejenge, wo automatically **`{rel_name}`** folder me store hongi! 🚀\n\n"
            f"💡 *Abhi apni video/file forward kijiye!*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)],
                [InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    # Fallback for generic text
    rel_active = get_relative_folder_name(u["active_folder"], u["base_folder"])
    await reply_text_safe(
        message,
        f"📁 **Send or forward any file, video, or document here!**\n\n"
        f"🎯 **Target Folder:** `{rel_active}`\n\n"
        "💡 *Tips:*\n"
        "• Naya folder banane ke liye `/newfolder <name>` likhein.\n"
        "• Folder select karne ke liye bas `/movies` ya `/notes` bhej dijiye.\n"
        "• Sabhi folders dekhne ke liye `/folders` likhein.\n"
        "• Folder ka share link paane ke liye `/share` likhein.\n"
        "• Root folder wapas select karne ke liye `/root` likhein."
    )

@bot.on_callback_query()
async def bot_callback_router(client: Client, query: CallbackQuery):
    data = query.data or ""
    user = query.from_user
    if not user:
        return
    u = get_or_create_bot_user(user)

    if data.startswith("cb:sw:"):
        fid_str = data.split(":", 2)[2]
        try:
            fid = int(fid_str)
        except ValueError:
            return
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT path, share_token FROM folders WHERE id = ?", (fid,))
        row = c.fetchone()
        conn.close()
        if not row:
            await query.answer("Folder not found!", show_alert=True)
            return

        fpath, ftoken = row
        # Security check: verify this folder belongs to this user
        if not (fpath == u["base_folder"] or fpath.startswith(u["base_folder"] + "/")):
            await query.answer("Aap sirf apne folders me switch kar sakte hain!", show_alert=True)
            return

        set_user_active_folder(u["user_id"], fpath)
        rel_name = get_relative_folder_name(fpath, u["base_folder"])
        await query.answer(f"Switched to {rel_name} ✅")
        share_url = f"{BASE_URL}/share/{ftoken}"
        await reply_text_safe(
            query.message,
            f"📂 **Active Folder Switched to:** `{rel_name}`\n\n"
            f"Ab sabhi uploaded/forwarded files yahan save hongi! 🚀",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)],
                [InlineKeyboardButton("📂 View Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    elif data.startswith("cb:sh:"):
        fid_str = data.split(":", 2)[2]
        try:
            fid = int(fid_str)
        except ValueError:
            return
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT path, share_token FROM folders WHERE id = ?", (fid,))
        row = c.fetchone()
        conn.close()
        if not row:
            await query.answer("Folder not found!", show_alert=True)
            return

        fpath, ftoken = row
        rel_name = get_relative_folder_name(fpath, u["base_folder"])
        share_url = f"{BASE_URL}/share/{ftoken}"
        await query.answer("Share link fetched!")
        await reply_text_safe(
            query.message,
            f"🌐 **Public Share Link for `{rel_name}`:**\n\n"
            f"`{share_url}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)]
            ]),
            disable_preview=True
        )
        return

    elif data == "cb:share_active":
        token = get_folder_share_token(u["active_folder"], u["user_id"])
        rel_name = get_relative_folder_name(u["active_folder"], u["base_folder"])
        share_url = f"{BASE_URL}/share/{token}"
        await query.answer("Active folder share link!")
        await reply_text_safe(
            query.message,
            f"🌐 **Share Link for Active Folder (`{rel_name}`):**\n\n"
            f"`{share_url}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🌐 Open {rel_name}", url=share_url)]
            ]),
            disable_preview=True
        )
        return

    elif data == "cb:root":
        set_user_active_folder(u["user_id"], u["base_folder"])
        token = get_folder_share_token(u["base_folder"], u["user_id"])
        share_url = f"{BASE_URL}/share/{token}"
        await query.answer("Switched to Root ✅")
        await reply_text_safe(
            query.message,
            f"🏠 **Switched to Root Folder!**\n\n`{u['base_folder']}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Open Root Drive", url=share_url)],
                [InlineKeyboardButton("📂 View Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    elif data == "cb:myfolders":
        await query.answer()
        msg_text, markup = await build_folders_view(u)
        await reply_text_safe(query.message, msg_text, reply_markup=markup, disable_preview=True)
        return

    elif data.startswith("cb:del_ask:"):
        fid_str = data.split(":", 2)[2]
        try:
            fid = int(fid_str)
        except ValueError:
            return
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT path FROM folders WHERE id = ?", (fid,))
        row = c.fetchone()
        if not row:
            conn.close()
            await query.answer("Folder not found!", show_alert=True)
            return

        fpath = row[0]
        if not fpath.startswith(u["base_folder"] + "/"):
            conn.close()
            await query.answer("Aap sirf apna subfolder delete kar sakte hain!", show_alert=True)
            return

        c.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files WHERE folder = ? OR folder LIKE ?", (fpath, fpath + "/%"))
        cnt, sz = c.fetchone()
        conn.close()

        rel_name = get_relative_folder_name(fpath, u["base_folder"])
        await query.answer()
        await reply_text_safe(
            query.message,
            "⚠️ **Confirm Delete Folder?** 🗑️\n\n"
            f"📁 **Folder:** `{rel_name}`\n"
            f"📊 **Files Inside:** {cnt} files ({format_size_human(sz)})\n\n"
            "❗ *Ye folder aur iski sabhi files Telegram Channel aur TG-Drive se permanent delete ho jayengi.*",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑️ Haan, Delete Karein", callback_data=f"cb:del_cf:{fid}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cb:del_cn")
                ]
            ]),
            disable_preview=True
        )
        return

    elif data.startswith("cb:del_cf:"):
        fid_str = data.split(":", 2)[2]
        try:
            fid = int(fid_str)
        except ValueError:
            return
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT path FROM folders WHERE id = ?", (fid,))
        row = c.fetchone()
        conn.close()
        if not row:
            await query.answer("Folder already deleted or not found!", show_alert=True)
            return

        fpath = row[0]
        rel_name = get_relative_folder_name(fpath, u["base_folder"])
        ok, err_msg, del_cnt = await perform_delete_folder(fpath, u["user_id"])
        if not ok:
            await query.answer(f"Error: {err_msg}", show_alert=True)
            return

        await query.answer("Folder deleted successfully! 🗑️")
        await reply_text_safe(
            query.message,
            f"✅ **Folder Deleted Successfully!** 🗑️\n\n"
            f"📁 Folder **`{rel_name}`** aur uski **{del_cnt} files** delete kar di gayi hain.\n\n"
            f"🎯 Active folder wapas root (`{u['base_folder']}`) set ho gaya hai.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 View Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    elif data == "cb:del_cn":
        await query.answer("Deletion cancelled")
        await reply_text_safe(
            query.message,
            "❌ **Folder Deletion Cancelled**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 View Folders", callback_data="cb:myfolders")]
            ]),
            disable_preview=True
        )
        return

    elif data == "cb:stopclone":
        sess = active_clones.get(user.id)
        if not sess or not sess.is_running:
            await query.answer("Koi active clone task running nahi hai!", show_alert=True)
            return
        sess.is_running = False
        await query.answer("⏹️ Cloning request received, stopping...")
        return

BATCH_DEBOUNCE_DELAY = 2.0

class UserBatchCollector:
    def __init__(self, user_id: int, user: dict, target_folder: str):
        self.user_id = user_id
        self.user = user
        self.target_folder = target_folder
        self.items = []
        self.timer_handle = None
        self.status_msg = None
        self.is_notified = False

active_user_batches: dict[int, UserBatchCollector] = {}

async def finalize_user_batch(user_id: int):
    collector = active_user_batches.pop(user_id, None)
    if not collector or not collector.items:
        return
    if collector.timer_handle:
        try:
            collector.timer_handle.cancel()
        except Exception:
            pass
        collector.timer_handle = None

    if len(collector.items) == 1:
        item = collector.items[0]
        await media_processing_queue.put({
            "mode": "single",
            "message": item["message"],
            "user": collector.user,
            "target_folder": item["target_folder"],
            "file_name": item["file_name"],
            "file_size": item["file_size"],
            "mime_type": item["mime_type"],
            "status_msg": collector.status_msg
        })
    else:
        await media_processing_queue.put({
            "mode": "batch",
            "user": collector.user,
            "target_folder": collector.target_folder,
            "items": collector.items,
            "status_msg": collector.status_msg,
            "first_message": collector.items[0]["message"]
        })

@bot.on_message(
    filters.private & (
        filters.document | filters.video | filters.audio |
        filters.photo | filters.voice | filters.video_note
    )
)
async def bot_media_receiver(client: Client, message: Message):
    if not is_telegram_user_allowed(message.from_user):
        await reply_text_safe(
            message,
            f"⛔ **Access Restricted**\n\n"
            f"Aap is bot par files upload karne ke liye authorized nahi hain.\n"
            f"Aapka Telegram ID: `{message.from_user.id}`\n\n"
            f"Kripya admin ko bolkar `.env` me `ALLOWED_TELEGRAM_USERS` me apna ID add karwayein."
        )
        return

    u = get_or_create_bot_user(message.from_user)
    user_id = message.from_user.id

    # Determine media object
    media = (
        message.document or message.video or message.audio or
        message.voice or message.video_note or
        (message.photo[-1] if isinstance(message.photo, list) else message.photo)
    )

    # Extract file metadata
    file_size = getattr(media, "file_size", 0)
    file_name = getattr(media, "file_name", None)

    if not file_name:
        if message.video:
            file_name = f"video_{message.id}.mp4"
        elif message.audio:
            file_name = f"audio_{message.id}.mp3"
        elif message.voice:
            file_name = f"voice_{message.id}.ogg"
        elif message.video_note:
            file_name = f"videonote_{message.id}.mp4"
        elif message.photo:
            file_name = f"photo_{message.id}.jpg"
        else:
            file_name = f"file_{message.id}.bin"

    # Smart Title Extraction: If caption has Title: ... (common in forwarded bot messages)
    if message.caption:
        t_match = re.search(r'(?:Title|Name)\s*:\s*([^\r\n]+)', message.caption, re.IGNORECASE)
        if t_match:
            extracted_name = re.sub(r'[*_`]', '', t_match.group(1)).strip()
            if extracted_name and len(extracted_name) > 3:
                if "." not in extracted_name and "." in (file_name or ""):
                    extracted_name += os.path.splitext(file_name)[1]
                file_name = extracted_name

    mime_type = getattr(media, "mime_type", None) or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    # Determine target folder:
    target_folder = None
    if message.caption:
        cap = message.caption.strip()
        if cap.startswith("/"):
            target_folder = resolve_user_folder_path(u["base_folder"], cap.split("\n")[0].strip())
        elif cap.lower().startswith("folder:"):
            target_folder = resolve_user_folder_path(u["base_folder"], cap.split(":", 1)[1].strip().split("\n")[0].strip())

    if not target_folder:
        target_folder = u["active_folder"]

    # Add to user batch collector
    if user_id not in active_user_batches:
        collector = UserBatchCollector(user_id=user_id, user=u, target_folder=target_folder)
        active_user_batches[user_id] = collector
    else:
        collector = active_user_batches[user_id]
        if target_folder:
            collector.target_folder = target_folder

    collector.items.append({
        "message": message,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type,
        "target_folder": target_folder
    })

    # If 2 or more files detected and not yet notified, send exactly ONE notification message
    if len(collector.items) == 2 and not collector.is_notified:
        collector.is_notified = True
        rel_folder = get_relative_folder_name(collector.target_folder, u["base_folder"])
        collector.status_msg = await reply_text_safe(
            collector.items[0]["message"],
            f"📦 **Bulk Forwarding Detected!**\n\n"
            f"📂 Target Folder: `{rel_folder}`\n"
            f"⏳ Gathering all files... Ek sath progress card me update hoga (zero chat spam)!"
        )

    # Cancel previous timer and debounce
    if collector.timer_handle:
        try:
            collector.timer_handle.cancel()
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    if len(collector.items) >= 100:
        asyncio.create_task(finalize_user_batch(user_id))
    else:
        collector.timer_handle = loop.call_later(
            BATCH_DEBOUNCE_DELAY,
            lambda uid=user_id: asyncio.create_task(finalize_user_batch(uid))
        )

async def process_single_job(job: dict):
    message = job["message"]
    status_msg = job.get("status_msg")
    u = job["user"]
    target_folder = job["target_folder"]
    file_name = job["file_name"]
    file_size = job["file_size"]
    mime_type = job["mime_type"]

    if not status_msg:
        status_msg = await reply_text_safe(message, "⚡ Processing file & generating stream link...")

    chan_msg = None
    for attempt in range(6):
        try:
            chan_msg = await message.copy(
                chat_id=CHANNEL_ID,
                caption=f"Folder: `{target_folder}` | File: `{file_name}`"
            )
            break
        except FloodWait as e:
            wait_time = int(getattr(e, 'value', 5) or 5)
            print(f"[FloodWait] Telegram asked to wait {wait_time}s for '{file_name}'")
            if status_msg:
                await edit_text_safe(
                    status_msg,
                    f"⏳ **Telegram rate limit active.**\n\nAuto-waiting `{wait_time}s` before saving `{file_name}`..."
                )
            await asyncio.sleep(wait_time + 1)
        except Exception as e:
            if status_msg:
                await edit_text_safe(status_msg, f"❌ Failed to store file in Telegram Channel: {e}")
            return

    if not chan_msg:
        if status_msg:
            await edit_text_safe(status_msg, "❌ Failed to store file after multiple retries.")
        return

    # Generate unique share tokens
    share_token = secrets.token_urlsafe(12)
    folder_token = get_folder_share_token(target_folder, u["user_id"])

    # Save in SQLite drive.db
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO files (message_id, name, size, mime_type, folder, share_token, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (chan_msg.id, file_name, file_size, mime_type, target_folder, share_token, u["user_id"])
    )
    conn.commit()
    conn.close()

    if mime_type.startswith("video/") or mime_type.startswith("image/"):
        asyncio.create_task(get_or_create_thumbnail(chan_msg.id))

    # Build links
    quoted_name = urllib.parse.quote(file_name)
    web_stream_url = f"{BASE_URL}/f/{share_token}"
    direct_stream_url = f"{BASE_URL}/stream/{chan_msg.id}/{quoted_name}?token={share_token}"
    direct_download_url = f"{BASE_URL}/dl/{chan_msg.id}/{quoted_name}?token={share_token}"
    folder_share_url = f"{BASE_URL}/share/{folder_token}"

    rel_folder = get_relative_folder_name(target_folder, u["base_folder"])
    safe_file_name = file_name.replace("`", "'")
    size_str = format_size_human(file_size)

    response_text = (
        "✅ **File Stored in Your Cloud Folder!** 🚀\n\n"
        f"📁 **File Name:** `{safe_file_name}`\n"
        f"📦 **Size:** `{size_str}`\n"
        f"📂 **Folder:** `{rel_folder}`\n\n"
        f"🎬 **Web Stream (Online Video Player):**\n`{web_stream_url}`\n\n"
        f"⚡ **Direct Stream (VLC/Player):**\n`{direct_stream_url}`\n\n"
        f"📥 **Fast Download Link:**\n`{direct_download_url}`\n\n"
        f"🌐 **Folder Share Link ({rel_folder}):**\n`{folder_share_url}`\n\n"
        "💡 *Folder change karne ke liye /folders use karein ya naya folder banane ke liye `/newfolder <naam>` likhein.*"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Watch / Stream in Browser", url=web_stream_url)
        ],
        [
            InlineKeyboardButton(f"📂 Open Folder ({rel_folder})", url=folder_share_url),
            InlineKeyboardButton("📥 Fast Download", url=direct_download_url)
        ],
        [
            InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders")
        ]
    ])

    if status_msg:
        await edit_text_safe(status_msg, response_text, reply_markup=keyboard, disable_preview=True)
    else:
        await reply_text_safe(message, response_text, reply_markup=keyboard, disable_preview=True)

    await asyncio.sleep(1.2)

async def process_batch_job(job: dict):
    u = job["user"]
    target_folder = job["target_folder"]
    items = job["items"]
    status_msg = job.get("status_msg")
    first_message = job["first_message"]
    total = len(items)

    rel_folder = get_relative_folder_name(target_folder, u["base_folder"])

    if not status_msg:
        status_msg = await reply_text_safe(
            first_message,
            f"📦 **Starting Batch Upload ({total} Files)...**\n📂 Target Folder: `{rel_folder}`"
        )

    processed_files = []
    failed_files = 0
    last_edit_time = 0.0

    for idx, item in enumerate(items, 1):
        file_name = item["file_name"]
        file_size = item["file_size"]
        mime_type = item["mime_type"]
        item_folder = item.get("target_folder") or target_folder
        msg = item["message"]

        chan_msg = None
        for attempt in range(6):
            try:
                chan_msg = await msg.copy(
                    chat_id=CHANNEL_ID,
                    caption=f"Folder: `{item_folder}` | File: `{file_name}`"
                )
                break
            except FloodWait as e:
                wait_time = int(getattr(e, 'value', 5) or 5)
                print(f"[FloodWait] Telegram asked to wait {wait_time}s on '{file_name}'")
                if status_msg:
                    await edit_text_safe(
                        status_msg,
                        f"⏳ **Telegram rate limit active.**\nAuto-waiting `{wait_time}s`... ({len(processed_files)}/{total} files saved)"
                    )
                await asyncio.sleep(wait_time + 1)
            except Exception as e:
                print(f"[process_batch_job copy error] {file_name}: {e}")
                break

        if chan_msg:
            share_token = secrets.token_urlsafe(12)
            try:
                conn = sqlite3.connect("drive.db")
                c = conn.cursor()
                c.execute(
                    "INSERT INTO files (message_id, name, size, mime_type, folder, share_token, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (chan_msg.id, file_name, file_size, mime_type, item_folder, share_token, u["user_id"])
                )
                conn.commit()
                conn.close()
                processed_files.append({"name": file_name, "size": file_size, "token": share_token})
                if mime_type.startswith("video/") or mime_type.startswith("image/"):
                    asyncio.create_task(get_or_create_thumbnail(chan_msg.id))
            except Exception as e:
                print(f"[process_batch_job db error] {e}")
                failed_files += 1
        else:
            failed_files += 1

        # Throttle progress edits: update every 3 seconds or on first/last item
        now = time.time()
        if (now - last_edit_time > 3.0) or (idx == 1) or (idx == total):
            percent = int((idx / total) * 100)
            bar = generate_progress_bar(percent)
            safe_name = file_name[:35].replace("`", "'")
            status_text = (
                f"📦 **Bulk Uploading to Cloud Drive...** ⚡\n\n"
                f"📂 **Folder:** `{rel_folder}`\n"
                f"📊 **Progress:** `[{bar}]` `{percent}%`\n"
                f"📁 **Processed:** `{idx}/{total}` files\n"
                f"📄 **Current:** `{safe_name}`\n\n"
                f"🛡️ *Flood protection active (Single live status message).* "
            )
            if status_msg:
                await edit_text_safe(status_msg, status_text)
            last_edit_time = now

        # Pacing between copies avoids triggering Telegram channel flood limit
        await asyncio.sleep(1.2)

    # All files in batch processed! Build final summary card
    folder_token = get_folder_share_token(target_folder, u["user_id"])
    folder_share_url = f"{BASE_URL}/share/{folder_token}"
    total_size = sum(f["size"] for f in processed_files)
    total_size_str = format_size_human(total_size)

    final_card = (
        "🎉 **Bulk Upload Complete!** 🚀\n\n"
        f"📂 **Folder:** `{rel_folder}`\n"
        f"✅ **Files Saved:** `{len(processed_files)} / {total}`\n"
        f"💾 **Total Size:** `{total_size_str}`\n\n"
        f"🌐 **Open Folder in Web Drive:**\n`{folder_share_url}`\n\n"
        f"💡 *Saare {len(processed_files)} files aapke `{rel_folder}` folder me organize ho chuke hain.*"
    )
    if failed_files > 0:
        final_card += f"\n⚠️ *{failed_files} file(s) could not be saved.*"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"📂 Open Folder ({rel_folder})", url=folder_share_url)
        ],
        [
            InlineKeyboardButton("📂 My Folders", callback_data="cb:myfolders")
        ]
    ])

    if status_msg:
        await edit_text_safe(status_msg, final_card, reply_markup=keyboard, disable_preview=True)
    else:
        await reply_text_safe(first_message, final_card, reply_markup=keyboard, disable_preview=True)

def verify_auth(password: str):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid Admin Password")

@app.api_route("/api/files", methods=["GET", "HEAD"])
async def list_files(folder: str = "/", all_files: bool = False, x_auth: str = Header("")):
    # Public read access allowed for viewing courses and library materials
    conn = sqlite3.connect("drive.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Exact files in this folder or all files if requested
    if all_files or folder in ("all", "*"):
        c.execute("SELECT * FROM files ORDER BY id DESC")
    else:
        c.execute("SELECT * FROM files WHERE folder = ? ORDER BY id DESC", (folder,))
    rows = [dict(r) for r in c.fetchall()]
    
    # Extract all unique folders from both files and folders table
    c.execute("""
        SELECT DISTINCT folder FROM (
            SELECT folder FROM files
            UNION
            SELECT path as folder FROM folders
        ) WHERE folder IS NOT NULL ORDER BY folder ASC
    """)
    all_folders = [r["folder"] for r in c.fetchall()]
    if "/" not in all_folders:
        all_folders.insert(0, "/")

    # Compute immediate subfolders for current folder
    subfolders = set()
    norm_folder = folder.rstrip("/") + "/"
    for f in all_folders:
        if f.startswith(norm_folder) and f != folder:
            rel = f[len(norm_folder):]
            first_part = rel.split("/")[0]
            if first_part:
                subfolders.add(norm_folder + first_part)

    c.execute("SELECT COUNT(*) as total_files, COALESCE(SUM(size), 0) as total_size FROM files")
    stats = dict(c.fetchone())
    conn.close()

    sorted_subfolders = sorted(list(subfolders))
    subfolders_meta = []
    for sf in sorted_subfolders:
        subfolders_meta.append({
            "path": sf,
            "name": sf.split("/")[-1],
            "share_token": get_folder_share_token(sf)
        })

    return {
        "files": rows,
        "folders": all_folders,
        "subfolders": sorted_subfolders,
        "subfolders_meta": subfolders_meta,
        "stats": stats,
        "folder_token": get_folder_share_token(folder),
        "base_path": folder,
        "folder_name": folder.split("/")[-1] if folder != "/" else "PWX Study Library"
    }

@app.get("/api/folders/share-token")
async def get_folder_token_api(path: str = "/", x_auth: str = Header("")):
    verify_auth(x_auth)
    token = get_folder_share_token(path)
    return {"path": path, "share_token": token, "share_url": f"/share/{token}"}

@app.post("/api/folders/share-token/regenerate")
async def regenerate_folder_token_api(request: Request, x_auth: str = Header("")):
    verify_auth(x_auth)
    data = await request.json()
    path = data.get("path", "/").rstrip("/") or "/"
    new_token = secrets.token_urlsafe(14)
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("INSERT INTO folders (path, share_token) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET share_token = ?", (path, new_token, new_token))
    conn.commit()
    conn.close()
    return {"path": path, "share_token": new_token, "share_url": f"/share/{new_token}"}

@app.api_route("/api/batches", methods=["GET", "HEAD"])
async def get_batches_api():
    conn = sqlite3.connect("drive.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT f.path, f.share_token, 
               (SELECT count(*) FROM files WHERE folder = f.path OR folder LIKE f.path || '/%') as file_count,
               (SELECT count(*) FROM files WHERE (folder = f.path OR folder LIKE f.path || '/%') AND mime_type LIKE 'video/%') as video_count,
               (SELECT count(*) FROM files WHERE (folder = f.path OR folder LIKE f.path || '/%') AND mime_type NOT LIKE 'video/%') as note_count
        FROM folders f
    """)
    all_f = [dict(r) for r in c.fetchall() if r["file_count"] > 0]
    conn.close()

    excluded_paths = {'/', '/Code', '/Code/tg-drive', '/Code/tg-drive/templates', '/@gouravpwx', '/@gouravpwx/PW'}
    excluded_names = {'Physics', 'Chemistry', 'Mathematics', 'Tests & Guidance'}

    batches = []
    for f in all_f:
        p = f["path"]
        name = p.split("/")[-1]
        if p in excluded_paths or name in excluded_names:
            continue
        parts = [part for part in p.split("/") if part]
        if len(parts) > 2 and parts[1] == "Lakshya_JEE_2026":
            continue
        
        clean_name = name.replace("_", " ")
        batches.append({
            "id": f["share_token"],
            "name": clean_name,
            "path": p,
            "share_token": f["share_token"],
            "file_count": f["file_count"],
            "video_count": f["video_count"],
            "note_count": f["note_count"],
            "url": f"/share/{f['share_token']}"
        })

    def batch_sort_key(b):
        p = b["path"]
        if "Lakshya_JEE_2026" in p:
            return (0, -b["file_count"])
        if "Prayas_JEE_2026" in p:
            return (1, -b["file_count"])
        return (2, -b["file_count"])

    batches.sort(key=batch_sort_key)
    return batches

@app.api_route("/api/share/{token}", methods=["GET", "HEAD"])
async def get_shared_folder_files(token: str, subfolder: str = "", all_files: bool = False):
    conn = sqlite3.connect("drive.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT path FROM folders WHERE share_token = ?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Shared folder not found or link has expired")

    base_path = row["path"].rstrip("/") or "/"

    # Determine target directory
    if subfolder and subfolder.strip():
        clean_sub = subfolder.strip().rstrip("/") or "/"
        if clean_sub == base_path or clean_sub.startswith(base_path.rstrip("/") + "/"):
            target_folder = clean_sub
        else:
            target_folder = base_path
    else:
        target_folder = base_path

    # Files query
    if all_files:
        if base_path == "/":
            c.execute("SELECT * FROM files ORDER BY id DESC")
        else:
            c.execute("SELECT * FROM files WHERE folder = ? OR folder LIKE ? ORDER BY id DESC", 
                      (base_path, base_path.rstrip("/") + "/%"))
    else:
        c.execute("SELECT * FROM files WHERE folder = ? ORDER BY id DESC", (target_folder,))
    
    files = [dict(r) for r in c.fetchall()]

    # Extract all folders under base_path to build subfolders list
    if base_path == "/":
        c.execute("SELECT DISTINCT folder FROM files")
    else:
        c.execute("SELECT DISTINCT folder FROM files WHERE folder = ? OR folder LIKE ?", 
                  (base_path, base_path.rstrip("/") + "/%"))
    existing_folders = [r["folder"] for r in c.fetchall()]

    # Also folders table
    if base_path == "/":
        c.execute("SELECT path FROM folders")
    else:
        c.execute("SELECT path FROM folders WHERE path = ? OR path LIKE ?",
                  (base_path, base_path.rstrip("/") + "/%"))
    for r in c.fetchall():
        if r["path"] not in existing_folders:
            existing_folders.append(r["path"])

    # Compute immediate subfolders relative to target_folder
    subfolders = set()
    norm_target = target_folder.rstrip("/") + "/"
    for f in existing_folders:
        if f.startswith(norm_target) and f != target_folder:
            rel = f[len(norm_target):]
            first_part = rel.split("/")[0]
            if first_part:
                subfolders.add(norm_target + first_part)

    # Calculate folder stats
    if base_path == "/":
        c.execute("SELECT COUNT(*) as total_files, COALESCE(SUM(size), 0) as total_size FROM files")
    else:
        c.execute("SELECT COUNT(*) as total_files, COALESCE(SUM(size), 0) as total_size FROM files WHERE folder = ? OR folder LIKE ?",
                  (base_path, base_path.rstrip("/") + "/%"))
    stats = dict(c.fetchone())
    conn.close()

    sorted_subfolders = sorted(list(subfolders))
    subfolders_meta = []
    for sf in sorted_subfolders:
        subfolders_meta.append({
            "path": sf,
            "name": sf.split("/")[-1],
            "share_token": get_folder_share_token(sf)
        })

    folder_name = base_path.split("/")[-1] or "Root"
    return {
        "base_path": base_path,
        "folder_name": folder_name,
        "current_folder": target_folder,
        "files": files,
        "subfolders": sorted_subfolders,
        "subfolders_meta": subfolders_meta,
        "stats": stats,
        "folder_token": token
    }

@app.post("/api/folders")
async def create_folder(request: Request, x_auth: str = Header("")):
    verify_auth(x_auth)
    data = await request.json()
    path = data.get("path", "").strip()
    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/") or "/"
    
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS folders (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT OR IGNORE INTO folders (path) VALUES (?)", (path,))
    conn.commit()
    conn.close()
    return {"status": "ok", "path": path}

@app.delete("/api/folders")
async def delete_folder(path: str, x_auth: str = Header("")):
    verify_auth(x_auth)
    ok, msg, del_cnt = await perform_delete_folder(path)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "deleted_files": del_cnt}

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("/"),
    x_auth: str = Header("")
):
    verify_auth(x_auth)
    if not folder.startswith("/"):
        folder = "/" + folder
    folder = folder.rstrip("/") or "/"

    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    share_token = secrets.token_urlsafe(12)

    temp_dir = tempfile.mkdtemp(prefix="tg_up_")
    temp_path = os.path.join(temp_dir, file.filename)
    file_size = 0

    try:
        with open(temp_path, "wb") as buffer:
            while True:
                chunk = await file.read(4 * 1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)
                file_size += len(chunk)

        msg = await bot.send_document(
            chat_id=CHANNEL_ID,
            document=temp_path,
            file_name=file.filename,
            caption=f"Folder: `{folder}` | File: `{file.filename}`"
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO files (message_id, name, size, mime_type, folder, share_token) VALUES (?, ?, ?, ?, ?, ?)",
        (msg.id, file.filename, file_size, mime_type, folder, share_token)
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "message_id": msg.id, "name": file.filename, "share_token": share_token}

@app.post("/api/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk_size: int = Form(...),
    total_size: int = Form(...),
    file_name: str = Form(...),
    folder: str = Form("/"),
    chunk: UploadFile = File(...),
    x_auth: str = Header("")
):
    verify_auth(x_auth)

    clean_upload_id = re.sub(r'[^a-zA-Z0-9_\-]', '', upload_id)
    if not clean_upload_id:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    # If upload was already assembled and completed, return the cached result
    if clean_upload_id in completed_chunk_uploads:
        return completed_chunk_uploads[clean_upload_id]

    if not folder.startswith("/"):
        folder = "/" + folder
    folder = folder.rstrip("/") or "/"
    clean_name = os.path.basename(file_name)

    base_dir = get_chunk_base_dir()
    upload_dir = os.path.join(base_dir, clean_upload_id)
    os.makedirs(upload_dir, exist_ok=True)

    part_tmp = os.path.join(upload_dir, f"part_{chunk_index:06d}.tmp")
    part_done = os.path.join(upload_dir, f"part_{chunk_index:06d}.done")

    # Write chunk if not already done
    if not (os.path.exists(part_done) and os.path.getsize(part_done) > 0):
        with open(part_tmp, "wb") as f:
            while True:
                data = await chunk.read(1024 * 1024)
                if not data:
                    break
                f.write(data)
        os.replace(part_tmp, part_done)

    done_parts = [f for f in os.listdir(upload_dir) if f.startswith("part_") and f.endswith(".done")]
    if len(done_parts) < total_chunks:
        return {
            "status": "chunk_received",
            "chunk_index": chunk_index,
            "received_chunks": len(done_parts),
            "total_chunks": total_chunks
        }

    # Final chunk received: acquire lock to assemble and stream to Telegram
    async with get_chunk_lock(clean_upload_id):
        if clean_upload_id in completed_chunk_uploads:
            return completed_chunk_uploads[clean_upload_id]

        done_parts = [f for f in os.listdir(upload_dir) if f.startswith("part_") and f.endswith(".done")]
        if len(done_parts) < total_chunks:
            return {
                "status": "chunk_received",
                "chunk_index": chunk_index,
                "received_chunks": len(done_parts),
                "total_chunks": total_chunks
            }

        assembled_path = os.path.join(upload_dir, clean_name)
        with open(assembled_path, "wb") as outfile:
            for idx in range(total_chunks):
                p = os.path.join(upload_dir, f"part_{idx:06d}.done")
                if not os.path.exists(p):
                    raise HTTPException(status_code=400, detail=f"Missing chunk {idx}")
                with open(p, "rb") as infile:
                    shutil.copyfileobj(infile, outfile, length=4 * 1024 * 1024)
                try:
                    os.remove(p)
                except OSError:
                    pass

        actual_file_size = os.path.getsize(assembled_path)
        mime_type = mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
        share_token = secrets.token_urlsafe(12)

        try:
            msg = await bot.send_document(
                chat_id=CHANNEL_ID,
                document=assembled_path,
                file_name=clean_name,
                caption=f"Folder: `{folder}` | File: `{clean_name}`"
            )
        finally:
            shutil.rmtree(upload_dir, ignore_errors=True)

        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO files (message_id, name, size, mime_type, folder, share_token) VALUES (?, ?, ?, ?, ?, ?)",
            (msg.id, clean_name, actual_file_size, mime_type, folder, share_token)
        )
        conn.commit()
        conn.close()

        res = {
            "status": "ok",
            "message_id": msg.id,
            "name": clean_name,
            "share_token": share_token
        }
        completed_chunk_uploads[clean_upload_id] = res
        return res

@app.get("/api/upload/chunk/status")
async def get_chunk_status(upload_id: str, x_auth: str = Header("")):
    verify_auth(x_auth)
    clean_upload_id = re.sub(r'[^a-zA-Z0-9_\-]', '', upload_id)
    if clean_upload_id in completed_chunk_uploads:
        return completed_chunk_uploads[clean_upload_id]

    upload_dir = os.path.join(get_chunk_base_dir(), clean_upload_id)
    if not os.path.exists(upload_dir):
        return {"status": "not_found"}

    done_parts = [
        int(f[5:11]) for f in os.listdir(upload_dir)
        if f.startswith("part_") and f.endswith(".done") and f[5:11].isdigit()
    ]
    return {
        "status": "in_progress",
        "received_chunks": len(done_parts),
        "chunk_indices": done_parts
    }

@app.delete("/api/files/{file_id}")
async def delete_file(file_id: int, x_auth: str = Header("")):
    verify_auth(x_auth)
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("SELECT message_id FROM files WHERE id = ?", (file_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        await bot.delete_messages(CHANNEL_ID, row[0])
    except Exception:
        pass

    c.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}

@app.post("/api/files/batch-delete")
async def batch_delete_files(request: Request, x_auth: str = Header("")):
    verify_auth(x_auth)
    data = await request.json()
    file_ids = data.get("ids", [])
    if not file_ids:
        return {"status": "ok", "deleted": 0}

    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    deleted = 0
    for fid in file_ids:
        c.execute("SELECT message_id FROM files WHERE id = ?", (fid,))
        row = c.fetchone()
        if row:
            try:
                await bot.delete_messages(CHANNEL_ID, row[0])
            except Exception:
                pass
            c.execute("DELETE FROM files WHERE id = ?", (fid,))
            deleted += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "deleted": deleted}

@app.api_route("/dl/{message_id}", methods=["GET", "HEAD"], operation_id="dl_file_by_id")
@app.api_route("/dl/{message_id}/{filename:path}", methods=["GET", "HEAD"], operation_id="dl_file_by_id_name")
async def dl_file(message_id: int, request: Request, filename: str = "", token: str = "", key: str = ""):
    return await stream_file(message_id=message_id, request=request, filename=filename, token=token, key=key, dl=1)

@app.api_route("/stream/{message_id}", methods=["GET", "HEAD"], operation_id="stream_file_by_id")
@app.api_route("/stream/{message_id}/{filename:path}", methods=["GET", "HEAD"], operation_id="stream_file_by_id_name")
async def stream_file(message_id: int, request: Request, filename: str = "", token: str = "", key: str = "", dl: int = 0):
    if key != ADMIN_PASS:
        conn = sqlite3.connect("drive.db")
        c = conn.cursor()
        c.execute("SELECT share_token FROM files WHERE message_id = ?", (message_id,))
        row = c.fetchone()
        conn.close()
        if not row or not token or row[0] != token:
            raise HTTPException(status_code=401, detail="Unauthorized or invalid share token")

    msg = await bot.get_messages(CHANNEL_ID, message_id)
    if not msg or not msg.media:
        raise HTTPException(status_code=404, detail="Media not found on Telegram")

    media = getattr(msg, msg.media.value)
    file_size = media.file_size
    file_name = filename or getattr(media, "file_name", f"file_{message_id}")
    mime_type = getattr(media, "mime_type", None)

    guessed_type, _ = mimetypes.guess_type(file_name)
    if guessed_type:
        mime_type = guessed_type
    elif not mime_type or mime_type == "application/octet-stream":
        mime_type = "application/pdf" if file_name.lower().endswith(".pdf") else "application/octet-stream"

    range_header = request.headers.get("Range", "").strip()

    is_range = False
    start = 0
    end = file_size - 1

    if range_header and range_header.startswith("bytes="):
        is_range = True
        rng = range_header.replace("bytes=", "").strip()
        if "," in rng:
            rng = rng.split(",")[0].strip()
        parts = rng.split("-")
        p0 = parts[0].strip() if len(parts) > 0 else ""
        p1 = parts[1].strip() if len(parts) > 1 else ""

        if not p0 and not p1:
            is_range = False
        elif not p0:
            # Suffix range: bytes=-65536
            try:
                suffix = int(p1)
                if suffix <= 0:
                    return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
                start = max(0, file_size - suffix)
                end = file_size - 1
            except ValueError:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        elif not p1:
            # Prefix range: bytes=1048576-
            try:
                start = int(p0)
                end = file_size - 1
            except ValueError:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        else:
            # Specific range: bytes=100-200
            try:
                start = int(p0)
                end = int(p1)
            except ValueError:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        if start >= file_size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        end = min(end, file_size - 1)

    total_to_send = (end - start) + 1 if file_size > 0 else 0
    is_download = (dl == 1 or request.query_params.get("dl") == "1")
    disposition = "attachment" if is_download else "inline"

    safe_ascii_name = file_name.encode("ascii", "ignore").decode("ascii").replace('"', '').strip() or f"file_{message_id}"
    quoted_utf8_name = urllib.parse.quote(file_name)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(total_to_send),
        "Content-Disposition": f'{disposition}; filename="{safe_ascii_name}"; filename*=UTF-8\'\'{quoted_utf8_name}',
    }

    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    if request.method == "HEAD":
        return Response(status_code=206 if is_range else 200, headers=headers, media_type=mime_type)

    chunk_size = 1024 * 1024
    offset_chunks = start // chunk_size
    skip_bytes = start % chunk_size
    chunks_limit = ((end // chunk_size) - offset_chunks) + 1

    async def media_generator():
        sent = 0
        first = True
        try:
            async for chunk in bot.stream_media(msg, offset=offset_chunks, limit=chunks_limit):
                if first and skip_bytes:
                    chunk = chunk[skip_bytes:]
                    first = False
                if sent + len(chunk) > total_to_send:
                    chunk = chunk[:total_to_send - sent]
                yield chunk
                sent += len(chunk)
                if sent >= total_to_send:
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        media_generator(),
        status_code=206 if is_range else 200,
        media_type=mime_type,
        headers=headers
    )

HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cloud Drive</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-app: #f8fafc;
    --bg-surface: #ffffff;
    --bg-subtle: #f1f5f9;
    --bg-hover: #f8fafc;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --text-main: #0f172a;
    --text-secondary: #475569;
    --text-muted: #64748b;
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --primary-light: #eff6ff;
    --danger: #dc2626;
    --danger-light: #fef2f2;
    --shadow-sm: 0 1px 2px 0 rgba(15, 23, 42, 0.04);
    --shadow-md: 0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.05);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', -apple-system, sans-serif; -webkit-font-smoothing: antialiased; }
  body { background: var(--bg-app); color: var(--text-main); display: flex; height: 100vh; overflow: hidden; }

  svg { width: 18px; height: 18px; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; fill: none; flex-shrink: 0; }

  .sidebar { width: 260px; background: var(--bg-surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; justify-content: space-between; padding: 20px 16px; flex-shrink: 0; z-index: 50; transition: transform 0.25s ease; }
  .brand { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700; color: var(--text-main); padding: 4px 8px 20px; border-bottom: 1px solid var(--border); }
  .brand-icon { width: 32px; height: 32px; border-radius: 8px; background: var(--primary); color: #fff; display: flex; align-items: center; justify-content: center; }

  .nav-section { margin-top: 20px; flex: 1; overflow-y: auto; }
  .nav-header { display: flex; justify-content: space-between; align-items: center; padding: 0 8px; margin-bottom: 8px; }
  .nav-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }
  .btn-new-folder { display: inline-flex; align-items: center; gap: 4px; background: var(--primary-light); color: var(--primary); border: none; padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn-new-folder:hover { background: #dbeafe; }

  .folder-list { list-style: none; display: flex; flex-direction: column; gap: 2px; }
  .folder-item { padding: 9px 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 10px; font-size: 13.5px; font-weight: 500; color: var(--text-secondary); transition: all 0.15s; }
  .folder-item:hover { background: var(--bg-subtle); color: var(--text-main); }
  .folder-item.active { background: var(--primary-light); color: var(--primary); font-weight: 600; }

  .storage-card { background: var(--bg-subtle); border: 1px solid var(--border); padding: 14px; border-radius: 10px; }
  .storage-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text-secondary); }
  .badge { font-size: 10px; font-weight: 700; text-transform: uppercase; background: #dcfce7; color: #15803d; padding: 2px 7px; border-radius: 99px; }
  .storage-val { font-size: 14px; font-weight: 700; color: var(--text-main); }

  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
  .topbar { height: 64px; background: var(--bg-surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; padding: 0 24px; gap: 16px; flex-shrink: 0; }
  .topbar-left { display: flex; align-items: center; gap: 12px; flex: 1; max-width: 460px; }
  .menu-btn { display: none; background: none; border: 1px solid var(--border); border-radius: 8px; padding: 7px; color: var(--text-secondary); cursor: pointer; }

  .search-wrap { position: relative; flex: 1; }
  .search-wrap svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--text-muted); width: 16px; height: 16px; }
  .search-input { width: 100%; background: var(--bg-app); border: 1px solid var(--border); color: var(--text-main); padding: 8px 12px 8px 36px; border-radius: 8px; font-size: 13.5px; outline: none; }
  .search-input:focus { background: var(--bg-surface); border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }

  .topbar-right { display: flex; align-items: center; gap: 10px; }
  .auth-wrap { position: relative; display: flex; align-items: center; }
  .auth-wrap svg { position: absolute; left: 10px; color: var(--text-muted); width: 15px; height: 15px; }
  .pass-input { background: var(--bg-app); border: 1px solid var(--border); color: var(--text-main); padding: 8px 12px 8px 32px; border-radius: 8px; font-size: 13px; width: 165px; outline: none; }

  .content { flex: 1; padding: 24px; overflow-y: auto; }
  
  /* Upload / Folder Dropzone with Folder Picker */
  .upload-box { background: var(--bg-surface); border: 1.5px dashed var(--border-strong); border-radius: 12px; padding: 20px; margin-bottom: 24px; box-shadow: var(--shadow-sm); }
  .upload-controls { display: flex; gap: 10px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }
  .upload-controls input[type="text"] { flex: 1; background: var(--bg-app); border: 1px solid var(--border); padding: 8px 12px; border-radius: 8px; font-size: 13.5px; color: var(--text-main); outline: none; }
  
  .dropzone { border: 1.5px dashed var(--border-strong); background: var(--bg-app); border-radius: 10px; padding: 18px; text-align: center; cursor: pointer; transition: all 0.15s; }
  .dropzone:hover, .dropzone.dragover { border-color: var(--primary); background: var(--primary-light); }
  .dropzone h4 { font-size: 13.5px; font-weight: 600; color: var(--text-main); margin-bottom: 2px; }
  .dropzone p { font-size: 12px; color: var(--text-muted); }
  .progress-wrap { display: none; width: 100%; margin-top: 10px; background: var(--bg-subtle); height: 6px; border-radius: 99px; overflow: hidden; }
  .progress-bar { height: 100%; width: 0%; background: var(--primary); transition: width 0.2s; }

  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 12px; }
  .breadcrumb { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--text-main); }
  .breadcrumb svg { color: var(--primary); width: 18px; height: 18px; }
  .view-toggle { display: flex; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px; padding: 2px; }
  .view-btn { background: none; border: none; padding: 5px 8px; border-radius: 6px; color: var(--text-muted); cursor: pointer; display: flex; align-items: center; }
  .view-btn.active { background: var(--bg-subtle); color: var(--text-main); }

  /* Subfolders Section */
  .subfolder-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .subfolder-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; cursor: pointer; transition: all 0.15s; }
  .subfolder-card:hover { border-color: var(--border-strong); background: var(--bg-hover); }
  .subfolder-left { display: flex; align-items: center; gap: 10px; font-size: 13.5px; font-weight: 600; color: var(--text-main); overflow: hidden; }
  .subfolder-left svg { color: #f59e0b; width: 20px; height: 20px; }

  /* Files Grid / List */
  .file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(235px, 1fr)); gap: 16px; }
  .card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: var(--shadow-sm); }
  .card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
  .card-top { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; cursor: pointer; }
  .file-badge { width: 40px; height: 40px; border-radius: 9px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .badge-img { background: #eff6ff; color: #2563eb; }
  .badge-vid { background: #faf5ff; color: #9333ea; }
  .badge-aud { background: #fdf2f8; color: #db2777; }
  .badge-doc { background: #fff7ed; color: #ea580c; }
  .badge-gen { background: #f1f5f9; color: #475569; }
  
  .file-info { overflow: hidden; flex: 1; }
  .file-title { font-size: 13.5px; font-weight: 600; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px; }
  .file-meta { font-size: 12px; color: var(--text-muted); }

  .card-actions { display: flex; gap: 6px; padding-top: 10px; border-top: 1px solid var(--bg-subtle); }
  .btn-act { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 5px; background: var(--bg-app); border: 1px solid var(--border); color: var(--text-secondary); padding: 6px 8px; border-radius: 7px; font-size: 12px; font-weight: 500; cursor: pointer; text-decoration: none; }
  .btn-act:hover { background: var(--bg-subtle); color: var(--text-main); }
  .btn-icon-only { flex: 0 0 32px; padding: 6px; }
  .btn-del:hover { background: var(--danger-light); color: var(--danger); border-color: #fecaca; }

  .file-list { display: flex; flex-direction: column; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .list-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid var(--border); gap: 12px; }
  .list-row:last-child { border-bottom: none; }
  .list-row:hover { background: var(--bg-hover); }
  .list-left { display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1; cursor: pointer; }
  .list-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

  .empty-state { grid-column: 1 / -1; text-align: center; padding: 48px 20px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; color: var(--text-muted); }
  .empty-state svg { width: 36px; height: 36px; color: var(--border-strong); margin-bottom: 10px; }

  .modal { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.55); backdrop-filter: blur(4px); display: none; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
  .modal.open { display: flex; }
  .modal-box { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 14px; max-width: 860px; width: 100%; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(15, 23, 42, 0.15); }
  .modal-header { padding: 14px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .modal-close { background: var(--bg-subtle); border: none; width: 28px; height: 28px; border-radius: 6px; color: var(--text-secondary); display: flex; align-items: center; justify-content: center; cursor: pointer; }
  .modal-body { padding: 16px; display: flex; justify-content: center; align-items: center; max-height: 75vh; overflow: auto; background: #0f172a; }
  .modal-body video, .modal-body img, .modal-body iframe { max-width: 100%; max-height: 68vh; border-radius: 6px; }

  .backdrop { display: none; position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); z-index: 40; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: var(--text-main); color: #fff; padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 500; display: none; z-index: 200; }

  @media (max-width: 768px) {
    .sidebar { position: fixed; top: 0; bottom: 0; left: 0; transform: translateX(-100%); }
    .sidebar.open { transform: translateX(0); }
    .backdrop.open { display: block; }
    .menu-btn { display: flex; }
    .file-grid { grid-template-columns: repeat(auto-fill, minmax(165px, 1fr)); gap: 12px; }
    .btn-label { display: none; }
  }
</style>
</head>
<body>

  <div class="backdrop" id="backdrop" onclick="toggleSidebar()"></div>

  <aside class="sidebar" id="sidebar">
    <div>
      <div class="brand">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
        </div>
        <span>TG Cloud Drive</span>
      </div>
      <div class="nav-section">
        <div class="nav-header">
          <span class="nav-title">Directories</span>
          <button class="btn-new-folder" onclick="createNewFolder()">
            <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New
          </button>
        </div>
        <ul class="folder-list" id="folderList"></ul>
      </div>
    </div>

    <div class="storage-card">
      <div class="storage-top">
        <span>Total Stored</span>
        <span class="badge">Unlimited</span>
      </div>
      <div class="storage-val" id="totalStats">0 B • 0 files</div>
    </div>
  </aside>

  <main class="main">
    <header class="topbar">
      <div class="topbar-left">
        <button class="menu-btn" onclick="toggleSidebar()">
          <svg viewBox="0 0 24 24"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <div class="search-wrap">
          <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" id="searchInput" class="search-input" placeholder="Search files..." oninput="renderFiles()">
        </div>
      </div>
      <div class="topbar-right">
        <div class="auth-wrap">
          <svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <input type="password" id="pass" class="pass-input" placeholder="Admin Password" onchange="savePass()">
        </div>
      </div>
    </header>

    <section class="content">
      <!-- Upload & Folder Selection Box -->
      <div class="upload-box">
        <div class="upload-controls">
          <input type="text" id="targetFolderInput" value="/" placeholder="Target folder (e.g. /notes/physics)">
          <input type="file" id="folderInput" hidden webkitdirectory directory multiple onchange="handleFolderUpload(this.files)">
          <button class="btn-act" style="background:var(--primary); color:#fff; border:none; padding:8px 14px;" onclick="document.getElementById('folderInput').click()">
            📁 Upload Full Folder
          </button>
        </div>
        
        <div class="dropzone" id="dropzone" onclick="document.getElementById('fileInput').click()">
          <input type="file" id="fileInput" hidden multiple onchange="handleFiles(this.files)">
          <h4 id="dropTitle">Click to upload files or drag and drop into current folder</h4>
          <p>Supports individual files or complete directory uploads</p>
          <div class="progress-wrap" id="progressWrap">
            <div class="progress-bar" id="progressBar"></div>
          </div>
        </div>
      </div>

      <div class="toolbar">
        <div class="breadcrumb">
          <svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span id="currentFolderLabel">/</span>
        </div>
        <div class="view-toggle">
          <button class="view-btn active" id="btnGrid" onclick="setView('grid')">
            <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
          </button>
          <button class="view-btn" id="btnList" onclick="setView('list')">
            <svg viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          </button>
        </div>
      </div>

      <!-- Subfolders Grid -->
      <div class="subfolder-grid" id="subfolderGrid"></div>

      <!-- Files Container -->
      <div id="fileContainer" class="file-grid"></div>
    </section>
  </main>

  <div class="modal" id="previewModal">
    <div class="modal-box">
      <div class="modal-header">
        <h4 id="modalTitle">Preview</h4>
        <button class="modal-close" onclick="closeModal()">
          <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal-body" id="modalBody"></div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

<script>
  let currentFolder = '/';
  let allFiles = [];
  let subfoldersList = [];
  let viewMode = localStorage.getItem('tg_view') || 'grid';
  const passInput = document.getElementById('pass');
  passInput.value = localStorage.getItem('tg_pass') || '';
  document.getElementById('targetFolderInput').value = currentFolder;

  const ICONS = {
    folder: `<svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
    image: `<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`,
    video: `<svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg>`,
    audio: `<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
    doc: `<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
    file: `<svg viewBox="0 0 24 24"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`,
    eye: `<svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    download: `<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
    link: `<svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`,
    trash: `<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`
  };

  function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('backdrop').classList.toggle('open');
  }

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.innerText = msg;
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 3000);
  }

  function savePass() {
    localStorage.setItem('tg_pass', passInput.value);
    loadFiles();
  }

  function setView(mode) {
    viewMode = mode;
    localStorage.setItem('tg_view', mode);
    document.getElementById('btnGrid').classList.toggle('active', mode === 'grid');
    document.getElementById('btnList').classList.toggle('active', mode === 'list');
    document.getElementById('fileContainer').className = mode === 'grid' ? 'file-grid' : 'file-list';
    renderFiles();
  }

  function formatBytes(b) {
    if (!b || b === 0) return '0 B';
    const k = 1024, sizes = ['B', 'KB', 'MB', 'GB', 'TB'], i = Math.floor(Math.log(b) / Math.log(k));
    return parseFloat((b / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  function getFileMeta(mime) {
    if (mime.startsWith('image/')) return { icon: ICONS.image, cls: 'badge-img' };
    if (mime.startsWith('video/')) return { icon: ICONS.video, cls: 'badge-vid' };
    if (mime.startsWith('audio/')) return { icon: ICONS.audio, cls: 'badge-aud' };
    if (mime.includes('pdf') || mime.includes('text')) return { icon: ICONS.doc, cls: 'badge-doc' };
    return { icon: ICONS.file, cls: 'badge-gen' };
  }

  function switchFolder(folder) {
    currentFolder = folder;
    document.getElementById('currentFolderLabel').innerText = folder;
    document.getElementById('targetFolderInput').value = folder;
    if (window.innerWidth <= 768) toggleSidebar();
    loadFiles();
  }

  function createNewFolder() {
    let name = prompt('Enter new directory path (e.g. /notes/physics):');
    if (!name) return;
    if (!name.startsWith('/')) name = '/' + name;
    switchFolder(name);
  }

  async function loadFiles() {
    const res = await fetch(`/api/files?folder=${encodeURIComponent(currentFolder)}`, {
      headers: { 'x-auth': passInput.value }
    });
    if (!res.ok) {
      showToast('Authentication required: Enter Admin Password');
      return;
    }
    const data = await res.json();
    allFiles = data.files;
    subfoldersList = data.subfolders;

    document.getElementById('folderList').innerHTML = data.folders.map(f => `
      <li class="folder-item ${f === currentFolder ? 'active' : ''}" onclick="switchFolder('${f}')">
        ${ICONS.folder}
        <span>${f}</span>
      </li>
    `).join('');

    document.getElementById('totalStats').innerText = `${formatBytes(data.stats.total_size)} • ${data.stats.total_files} files`;
    renderSubfolders();
    setView(viewMode);
  }

  function renderSubfolders() {
    const grid = document.getElementById('subfolderGrid');
    if (subfoldersList.length === 0) {
      grid.innerHTML = '';
      return;
    }
    grid.innerHTML = subfoldersList.map(sf => {
      const folderName = sf.split('/').pop();
      return `
        <div class="subfolder-card" onclick="switchFolder('${sf}')">
          <div class="subfolder-left">
            ${ICONS.folder}
            <span>${folderName}</span>
          </div>
          <svg style="width:14px; height:14px; color:var(--text-muted);" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>
        </div>`;
    }).join('');
  }

  function renderFiles() {
    const q = document.getElementById('searchInput').value.toLowerCase();
    const filtered = allFiles.filter(f => f.name.toLowerCase().includes(q));
    const container = document.getElementById('fileContainer');

    if (filtered.length === 0 && subfoldersList.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          ${ICONS.folder}
          <h4>This folder is empty</h4>
          <p>Upload files or complete directories using the box above.</p>
        </div>`;
      return;
    } else if (filtered.length === 0) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = filtered.map(f => {
      const meta = getFileMeta(f.mime_type);
      const streamUrl = `/stream/${f.message_id}?token=${encodeURIComponent(f.share_token)}`;
      const dlUrl = `${streamUrl}&dl=1`;
      const safeName = f.name.replace(/'/g, "");
      const dateStr = f.created_at.split(' ')[0];

      if (viewMode === 'list') {
        return `
          <div class="list-row">
            <div class="list-left" onclick="openPreview('${safeName}', '${f.mime_type}', '${streamUrl}')">
              <div class="file-badge ${meta.cls}">${meta.icon}</div>
              <div class="file-info">
                <div class="file-title" title="${f.name}">${f.name}</div>
                <div class="file-meta">${formatBytes(f.size)} • ${dateStr}</div>
              </div>
            </div>
            <div class="list-right">
              <button class="btn-act" onclick="openPreview('${safeName}', '${f.mime_type}', '${streamUrl}')">${ICONS.eye} <span class="btn-label">View</span></button>
              <a class="btn-act" href="${dlUrl}">${ICONS.download} <span class="btn-label">Save</span></a>
              <button class="btn-act btn-icon-only" onclick="copyLink('${streamUrl}')" title="Copy Link">${ICONS.link}</button>
              <button class="btn-act btn-icon-only btn-del" onclick="delFile(${f.id})" title="Delete">${ICONS.trash}</button>
            </div>
          </div>`;
      }

      return `
        <div class="card">
          <div class="card-top" onclick="openPreview('${safeName}', '${f.mime_type}', '${streamUrl}')">
            <div class="file-badge ${meta.cls}">${meta.icon}</div>
            <div class="file-info">
              <div class="file-title" title="${f.name}">${f.name}</div>
              <div class="file-meta">${formatBytes(f.size)} • ${dateStr}</div>
            </div>
          </div>
          <div class="card-actions">
            <button class="btn-act" onclick="openPreview('${safeName}', '${f.mime_type}', '${streamUrl}')">${ICONS.eye} Preview</button>
            <a class="btn-act" href="${dlUrl}">${ICONS.download} Save</a>
            <button class="btn-act btn-icon-only" onclick="copyLink('${streamUrl}')" title="Copy Link">${ICONS.link}</button>
            <button class="btn-act btn-icon-only btn-del" onclick="delFile(${f.id})" title="Delete">${ICONS.trash}</button>
          </div>
        </div>`;
    }).join('');
  }

  function copyLink(relUrl) {
    const fullUrl = window.location.origin + relUrl;
    navigator.clipboard.writeText(fullUrl);
    showToast('Link copied to clipboard');
  }

  function openPreview(name, mime, url) {
    const modal = document.getElementById('previewModal');
    const body = document.getElementById('modalBody');
    document.getElementById('modalTitle').innerText = name;

    if (mime.startsWith('video/')) {
      body.innerHTML = `<video src="${url}" controls autoplay></video>`;
    } else if (mime.startsWith('image/')) {
      body.innerHTML = `<img src="${url}" alt="${name}">`;
    } else if (mime.startsWith('audio/')) {
      body.innerHTML = `<audio src="${url}" controls autoplay style="width:100%"></audio>`;
    } else if (mime.includes('pdf')) {
      body.innerHTML = `<iframe src="${url}" style="width:100%; height:65vh; border:none;"></iframe>`;
    } else {
      window.open(url, '_blank');
      return;
    }
    modal.classList.add('open');
  }

  function closeModal() {
    const modal = document.getElementById('previewModal');
    document.getElementById('modalBody').innerHTML = '';
    modal.classList.remove('open');
  }

  // Handle Full Directory Folder Upload
  async function handleFolderUpload(files) {
    if (!files.length) return;
    const baseTarget = document.getElementById('targetFolderInput').value.trim() || '/';
    const wrap = document.getElementById('progressWrap');
    const bar = document.getElementById('progressBar');
    const title = document.getElementById('dropTitle');

    wrap.style.display = 'block';

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      // webkitRelativePath gives structure like "my-folder/sub/file.png"
      const relPath = file.webkitRelativePath || file.name;
      const pathParts = relPath.split('/');
      pathParts.pop(); // remove file name
      
      let targetSub = baseTarget;
      if (pathParts.length > 0) {
        targetSub = baseTarget.endsWith('/') ? baseTarget + pathParts.join('/') : baseTarget + '/' + pathParts.join('/');
      }

      bar.style.width = `${Math.round(((i + 1) / files.length) * 100)}%`;
      title.innerText = `Uploading folder file (${i + 1}/${files.length}): ${file.name}`;

      await new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);
        formData.append('folder', targetSub);

        xhr.onload = () => resolve();
        xhr.open('POST', '/api/upload');
        xhr.setRequestHeader('x-auth', passInput.value);
        xhr.send(formData);
      });
    }

    title.innerText = 'Click to upload files or drag and drop into current folder';
    wrap.style.display = 'none';
    showToast('Complete folder uploaded successfully!');
    loadFiles();
  }

  const dropzone = document.getElementById('dropzone');
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  });

  async function handleFiles(files) {
    const targetSub = document.getElementById('targetFolderInput').value.trim() || currentFolder;
    const wrap = document.getElementById('progressWrap');
    const bar = document.getElementById('progressBar');
    const title = document.getElementById('dropTitle');

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      wrap.style.display = 'block';
      bar.style.width = '0%';
      title.innerText = `Uploading ${file.name} (${i + 1} of ${files.length})...`;

      await new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('file', file);
        formData.append('folder', targetSub);

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            bar.style.width = pct + '%';
            title.innerText = pct === 100 ? `Syncing to Telegram...` : `Uploading ${file.name}: ${pct}%`;
          }
        };

        xhr.onload = () => {
          if (xhr.status === 200) showToast(`Uploaded ${file.name}`);
          else showToast(`Failed: ${file.name}`);
          resolve();
        };

        xhr.open('POST', '/api/upload');
        xhr.setRequestHeader('x-auth', passInput.value);
        xhr.send(formData);
      });
    }

    title.innerText = 'Click to upload files or drag and drop into current folder';
    wrap.style.display = 'none';
    loadFiles();
  }

  async function delFile(id) {
    if (!confirm('Delete this file permanently?')) return;
    await fetch(`/api/files/${id}`, {
      method: 'DELETE',
      headers: { 'x-auth': passInput.value }
    });
    showToast('File deleted');
    loadFiles();
  }

  if (passInput.value) loadFiles();
</script>
</body>
</html>
"""

DIST_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "index.html")
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_ui():
    if os.path.exists(DIST_INDEX):
        with open(DIST_INDEX, "r", encoding="utf-8") as f:
            return f.read()
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return HTML_UI

@app.get("/api/f/{token}")
async def get_public_file_info(token: str):
    conn = sqlite3.connect("drive.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, message_id, name, size, mime_type, folder, share_token, created_at FROM files WHERE share_token = ?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="File not found or link has expired")
    file_data = dict(row)
    folder = file_data.get("folder", "/")
    folder_token = get_folder_share_token(folder)
    c.execute(
        "SELECT id, message_id, name, size, mime_type, share_token FROM files WHERE folder = ? ORDER BY id ASC",
        (folder,)
    )
    siblings = [dict(r) for r in c.fetchall()]
    conn.close()
    file_data["folder_token"] = folder_token
    file_data["siblings"] = siblings
    return file_data

@app.api_route("/share/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_share_page(token: str):
    return await serve_ui()

@app.api_route("/f/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/file/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/watch/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/v/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_file_share_page(token: str):
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("SELECT name, mime_type FROM files WHERE share_token = ?", (token,))
    row = c.fetchone()
    conn.close()

    html_content = await serve_ui()
    if row:
        file_name, mime_type = row
        meta_tags = (
            f'<meta property="og:title" content="{html.escape(file_name)}">\n'
            f'<meta property="og:type" content="video.other" />\n'
            f'<meta property="og:image" content="{BASE_URL}/thumb/f/{token}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{html.escape(file_name)}">\n'
            f'<meta name="twitter:image" content="{BASE_URL}/thumb/f/{token}">\n'
        )
        html_content = html_content.replace("<head>", f"<head>\n{meta_tags}", 1)
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
