export function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes <= 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

export function formatTime(seconds) {
  if (isNaN(seconds) || seconds <= 0) return '00:00';
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (hrs > 0) {
    return `${hrs}:${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
  }
  return `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

export function getFileExtension(filename = '') {
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

export function getFileTypeInfo(mime = '', filename = '') {
  const ext = getFileExtension(filename);
  const isVideo = mime.startsWith('video/') || ['mp4', 'mkv', 'webm', 'mov', 'avi', 'flv'].includes(ext);
  const isPdf = mime.includes('pdf') || ext === 'pdf';
  const isAudio = mime.startsWith('audio/') || ['mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a'].includes(ext);
  const isImage = mime.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'heic', 'bmp'].includes(ext);
  const isDoc = isPdf || ['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'csv', 'md'].includes(ext);

  return {
    isVideo,
    isPdf,
    isAudio,
    isImage,
    isDoc,
    ext: ext ? ext.toUpperCase() : (isVideo ? 'MP4' : isPdf ? 'PDF' : 'FILE')
  };
}

export function getAdminKey() {
  return localStorage.getItem('tg_admin_pass') || '';
}

export function setAdminKey(key) {
  if (key) {
    localStorage.setItem('tg_admin_pass', key);
  } else {
    localStorage.removeItem('tg_admin_pass');
  }
}
