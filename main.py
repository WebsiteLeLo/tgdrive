import os
import secrets
import shutil
import sqlite3
import tempfile
import mimetypes
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
PORT = int(os.getenv("PORT", "3005"))

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

def get_folder_share_token(path: str) -> str:
    path = path.rstrip("/") or "/"
    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("SELECT share_token FROM folders WHERE path = ?", (path,))
    row = c.fetchone()
    if row and row[0]:
        token = row[0]
    else:
        token = secrets.token_urlsafe(14)
        c.execute("INSERT INTO folders (path, share_token) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET share_token = ?", (path, token, token))
        conn.commit()
    conn.close()
    return token

bot = Client(
    "tg_drive_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    max_concurrent_transmissions=4
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.start()
    print("Telegram MTProto Connected (Subfolder Edition)")
    yield
    await bot.stop()

app = FastAPI(lifespan=lifespan)

def verify_auth(password: str):
    if password != ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid Admin Password")

@app.get("/api/files")
async def list_files(folder: str = "/", all_files: bool = False, x_auth: str = Header("")):
    verify_auth(x_auth)
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
        "folder_token": get_folder_share_token(folder)
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

@app.get("/api/share/{token}")
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
    path = path.rstrip("/") or "/"
    if path == "/":
        raise HTTPException(status_code=400, detail="Cannot delete root directory")

    conn = sqlite3.connect("drive.db")
    c = conn.cursor()
    c.execute("DELETE FROM folders WHERE path = ? OR path LIKE ?", (path, path + "/%"))
    
    c.execute("SELECT id, message_id FROM files WHERE folder = ? OR folder LIKE ?", (path, path + "/%"))
    files_to_del = c.fetchall()
    for fid, mid in files_to_del:
        try:
            await bot.delete_messages(CHANNEL_ID, mid)
        except Exception:
            pass
        c.execute("DELETE FROM files WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return {"status": "ok", "deleted_files": len(files_to_del)}

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

@app.api_route("/stream/{message_id}", methods=["GET", "HEAD"])
async def stream_file(message_id: int, request: Request, token: str = "", key: str = "", dl: int = 0):
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
    file_name = getattr(media, "file_name", f"file_{message_id}")
    mime_type = getattr(media, "mime_type", "application/octet-stream")

    range_header = request.headers.get("Range", "").strip()

    # If normal web browser top-level navigation, redirect to instant web preview page
    accept = request.headers.get("Accept", "")
    if dl != 1 and not range_header and "text/html" in accept and token:
        return RedirectResponse(url=f"/f/{token}", status_code=302)

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
    disposition = "attachment" if dl == 1 else "inline"

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(total_to_send),
        "Content-Disposition": f'{disposition}; filename="{file_name}"',
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

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
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
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="File not found or link has expired")
    return dict(row)

@app.get("/share/{token}", response_class=HTMLResponse)
async def serve_share_page(token: str):
    return await serve_ui()

@app.get("/f/{token}", response_class=HTMLResponse)
@app.get("/file/{token}", response_class=HTMLResponse)
async def serve_file_share_page(token: str):
    return await serve_ui()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
