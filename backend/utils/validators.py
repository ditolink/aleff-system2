"""validators.py — Validação e sanitização"""
import re, os, html

MAX_FILE_SIZE = 500 * 1024 * 1024
ALLOWED_IMAGES = {'image/jpeg','image/jpg','image/png','image/webp','image/gif','image/heic','image/heif','image/bmp'}
ALLOWED_VIDEOS = {'video/mp4','video/quicktime','video/x-msvideo','video/webm','video/mpeg','video/3gpp'}
ALLOWED_MIMES  = ALLOWED_IMAGES | ALLOWED_VIDEOS
ALLOWED_EXT    = {'.jpg','.jpeg','.png','.webp','.gif','.heic','.heif','.bmp','.mp4','.mov','.avi','.webm','.mpeg','.mpg','.3gp'}


def safe_upload_basename(filename: str) -> str:
    """Só o nome do arquivo, sem path. Rejeita vazio."""
    name = os.path.basename((filename or '').replace('\\', '/').strip())
    name = name.lstrip('.')
    return name[:180]


def validate_file(filename, mime_type, size):
    if not filename:
        return False, "Nome inválido."
    raw = str(filename)
    if any(c in raw for c in ('\x00', '\n', '\r')):
        return False, "Nome inválido."
    # Path traversal / absolute paths no filename
    norm = raw.replace('\\', '/')
    if '/' in norm or norm.startswith('~'):
        if os.path.basename(norm) != norm.rstrip('/'):
            return False, "Nome de arquivo inválido."
    name = safe_upload_basename(raw)
    if not name or name in ('.', '..'):
        return False, "Nome inválido."
    ext = os.path.splitext(name.lower())[1]
    if ext not in ALLOWED_EXT:
        return False, f"Extensão '{ext}' não permitida."
    if mime_type not in ALLOWED_MIMES:
        return False, f"Tipo '{mime_type}' não permitido."
    if size > MAX_FILE_SIZE:
        return False, f"Arquivo muito grande ({size/(1024*1024):.1f} MB). Máx: 500 MB."
    if size == 0:
        return False, "Arquivo vazio."
    return True, ""


def sanitize_string(value, max_len=500):
    if not isinstance(value, str):
        value = str(value)
    value = html.escape(value.strip(), quote=True)
    value = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', value)
    return value[:max_len]


def sniff_mime_from_bytes(file_bytes, filename=''):
    """Detecta tipo real pelos magic bytes (não confia só no client)."""
    if not file_bytes:
        return 'application/octet-stream'
    head = file_bytes[:16]
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if head.startswith(b'RIFF') and file_bytes[8:12] == b'WEBP':
        return 'image/webp'
    if len(file_bytes) > 8 and file_bytes[4:8] == b'ftyp':
        return 'video/mp4'
    if head.startswith(b'\x1aE\xdf\xa3'):
        return 'video/webm'
    # fallback pela extensão
    ext = os.path.splitext((filename or '').lower())[1]
    return {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
        '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm',
        '.avi': 'video/x-msvideo', '.mpeg': 'video/mpeg', '.mpg': 'video/mpeg',
        '.3gp': 'video/3gpp',
    }.get(ext, 'application/octet-stream')


def sanitize_tags(tags_raw):
    if not tags_raw:
        return ''
    parts = [t.strip().lower() for t in re.split(r'[,;\s]+', tags_raw)]
    parts = [re.sub(r'[^\w\-áàâãéèêíïóôõöúüçñ]', '', t, flags=re.UNICODE) for t in parts]
    return ','.join(p for p in parts if p)[:2000]


def get_mime_category(mime_type):
    if mime_type in ALLOWED_IMAGES:
        return 'image'
    if mime_type in ALLOWED_VIDEOS:
        return 'video'
    return 'unknown'


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
