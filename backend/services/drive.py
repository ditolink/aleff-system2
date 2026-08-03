"""drive.py — Google Drive API v3"""

import io
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

from google.oauth2 import service_account


FOLDER_ID = (os.getenv('DRIVE_FOLDER_ID') or '').strip()

SCOPES = [
    'https://www.googleapis.com/auth/drive'
]

_service_cache = None
_creds_cache = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_ssl_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    needles = (
        'ssl', 'record layer', 'tls', 'eof occurred', 'connection reset',
        'broken pipe', 'timed out', 'timeout', 'wrong version number',
        'remote end closed', 'protocol error',
    )
    return any(n in msg for n in needles) or 'ssl' in name


def _load_credentials():
    """Aceita caminho de arquivo OU JSON inline no .env."""
    global _creds_cache
    if _creds_cache is not None:
        return _creds_cache

    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not raw:
        candidate = _project_root() / "service-account.json"
        if candidate.is_file():
            raw = str(candidate)
        else:
            raise RuntimeError(
                "Drive não configurado: defina GOOGLE_APPLICATION_CREDENTIALS no .env"
            )

    # JSON inline no .env
    if raw.startswith("{"):
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS JSON inválido no .env"
            ) from e
        _creds_cache = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        return _creds_cache

    cred_path = raw
    if not os.path.isabs(cred_path):
        cred_path = str(_project_root() / cred_path)

    if not os.path.isfile(cred_path):
        raise RuntimeError(
            f"Arquivo de credenciais não encontrado: {cred_path}"
        )

    _creds_cache = service_account.Credentials.from_service_account_file(
        cred_path, scopes=SCOPES
    )
    return _creds_cache


def _build_service(creds):
    """
    Cliente Drive com transporte HTTP mais estável no Windows.
    Mitiga RECORD_LAYER_FAILURE / TLS flaky do httplib2 padrão.
    """
    try:
        import google_auth_httplib2
        import httplib2

        http = httplib2.Http(timeout=120)
        authorized = google_auth_httplib2.AuthorizedHttp(creds, http=http)
        return build(
            "drive",
            "v3",
            http=authorized,
            cache_discovery=False,
        )
    except Exception as first_err:
        try:
            return build(
                "drive",
                "v3",
                credentials=creds,
                cache_discovery=False,
            )
        except Exception:
            raise first_err


def _get_service(force_refresh: bool = False):
    global _service_cache

    if _service_cache and not force_refresh:
        return _service_cache

    try:
        creds = _load_credentials()
        _service_cache = _build_service(creds)
        print("[Drive] Autenticado via Service Account")
        return _service_cache
    except Exception as e:
        print("Erro Drive:", e)
        _service_cache = None
        raise RuntimeError(f"Falha ao autenticar no Drive: {e}") from e


def _drive_call(fn, retries: int = 3):
    """Executa chamada Drive com retry em erros SSL/rede e refresh do client."""
    global _service_cache
    last = None
    for attempt in range(retries):
        try:
            service = _get_service(force_refresh=(attempt > 0))
            return fn(service)
        except HttpError:
            raise
        except Exception as e:
            last = e
            if _is_ssl_error(e) and attempt < retries - 1:
                print(f"[Drive] SSL/rede instável — tentativa {attempt + 1}/{retries}: {e}")
                _service_cache = None
                time.sleep(0.45 * (attempt + 1))
                continue
            raise
    raise last


def _thumb_url(file_id, size=400):
    return (
        f"https://drive.google.com/thumbnail"
        f"?id={file_id}&sz=w{size}"
    )


def _view_url(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"


def _thumbs_dir() -> Path:
    d = _project_root() / 'data' / 'thumbs'
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_cache_path(drive_id: str, size: int = 400) -> Path:
    import hashlib
    key = hashlib.sha1(f'{drive_id}|{int(size)}'.encode('utf-8')).hexdigest()[:20]
    return _thumbs_dir() / f'{key}.jpg'


def _looks_like_image(content: bytes, ctype: str = '') -> bool:
    if content[:3] == b'\xff\xd8' or content[:8] == b'\x89PNG\r\n\x1a\n' or content[:4] == b'RIFF':
        return True
    return 'image' in (ctype or '')


def _try_public_thumb(drive_id: str, size: int) -> tuple[bytes, str] | None:
    """HTTP direto no thumbnail público do Drive — bem mais rápido que a API SA."""
    import requests as _req
    url = _thumb_url(drive_id, size=size)
    try:
        r = _req.get(
            url,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=6,
            allow_redirects=True,
        )
        if r.status_code == 200 and r.content and _looks_like_image(r.content, r.headers.get('Content-Type', '')):
            ctype = r.headers.get('Content-Type', 'image/jpeg')
            mime = ctype.split(';')[0].strip() if 'image' in ctype else 'image/jpeg'
            return r.content, mime
    except Exception:
        pass
    return None


def fetch_thumbnail_bytes(drive_id, size=400, use_cache=True):
    """
    Baixa bytes de thumbnail. Ordem:
      1) arquivo local
      2) cache em disco (data/thumbs)
      3) URL pública do Drive (rápido)
      4) API service account (confiável)
    """
    local = resolve_local_path(drive_id)
    if local and local.is_file():
        from backend.utils.validators import sniff_mime_from_bytes
        data = local.read_bytes()
        return data, sniff_mime_from_bytes(data, local.name)

    if not drive_id or is_local_media_id(drive_id):
        raise RuntimeError('Arquivo local não encontrado.')

    size = int(size) or 400
    cache = thumb_cache_path(drive_id, size)
    if use_cache and cache.is_file() and cache.stat().st_size > 200:
        return cache.read_bytes(), 'image/jpeg'

    # Atalho público — evita round-trip na API do Drive
    public = _try_public_thumb(drive_id, size)
    if public:
        raw, mime = public
        try:
            cache.write_bytes(raw)
        except OSError:
            pass
        return raw, mime

    import re
    import requests as _req

    def _do(service):
        meta = service.files().get(
            fileId=drive_id,
            fields='mimeType,thumbnailLink,name',
            supportsAllDrives=True,
        ).execute()
        link = (meta.get('thumbnailLink') or '').strip()
        mime = meta.get('mimeType') or 'image/jpeg'

        if link:
            link = re.sub(r'=s\d+$', f'=s{max(int(size), 220)}', link)
            headers = {}
            try:
                from google.auth.transport.requests import Request as GaRequest
                c = _load_credentials()
                if not c.valid:
                    c.refresh(GaRequest())
                headers['Authorization'] = f'Bearer {c.token}'
            except Exception:
                pass
            r = _req.get(link, headers=headers, timeout=12, allow_redirects=True)
            if r.status_code == 200 and r.content and _looks_like_image(r.content, r.headers.get('Content-Type', '')):
                ctype = r.headers.get('Content-Type', '')
                return r.content, (ctype.split(';')[0].strip() if 'image' in ctype else 'image/jpeg')

        if str(mime).startswith('image/'):
            request = service.files().get_media(fileId=drive_id, supportsAllDrives=True)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            raw = buffer.getvalue()
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(raw)).convert('RGB')
                img.thumbnail((max(int(size), 400), max(int(size), 400)))
                out = io.BytesIO()
                img.save(out, format='JPEG', quality=82)
                return out.getvalue(), 'image/jpeg'
            except Exception:
                return raw, mime

        raise RuntimeError('Thumbnail indisponível para este arquivo.')

    raw, mime = _drive_call(_do)
    try:
        if mime.startswith('image/') or _looks_like_image(raw):
            # normaliza cache como jpeg quando possível
            if not mime.endswith('jpeg') and not mime.endswith('jpg'):
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(raw)).convert('RGB')
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=82)
                    raw, mime = buf.getvalue(), 'image/jpeg'
                except Exception:
                    pass
            cache.write_bytes(raw)
    except OSError:
        pass
    return raw, mime


def prefetch_thumbnails(items, size=280, limit=48):
    """Aquece cache de thumbs recentes em background (não bloqueia)."""
    n = 0
    for item in (items or [])[:limit]:
        did = (item or {}).get('drive_id')
        if not did:
            continue
        try:
            fetch_thumbnail_bytes(did, size=size, use_cache=True)
            n += 1
        except Exception:
            continue
    return n



def _is_storage_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        'storage quota' in msg
        or 'service accounts do not have storage' in msg
        or 'shared drives' in msg and '403' in msg
    )


def _uploads_dir() -> Path:
    d = _project_root() / 'data' / 'uploads'
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_local_media_id(drive_id: str | None) -> bool:
    return bool(drive_id) and str(drive_id).startswith('local:')


def resolve_local_path(drive_id: str) -> Path | None:
    if not is_local_media_id(drive_id):
        return None
    uid = str(drive_id).split(':', 1)[1].strip()
    if not uid or '/' in uid or '\\' in uid or '..' in uid:
        return None
    matches = sorted(_uploads_dir().glob(f'{uid}_*'))
    return matches[0] if matches else None


def upload_local(file_bytes, filename, mime_type, metadata=None):
    """Salva no disco local quando o Drive SA não tem cota de escrita."""
    import re
    import uuid

    uid = uuid.uuid4().hex
    safe = re.sub(r'[^\w.\-]+', '_', filename or 'arquivo')[:120] or 'arquivo'
    path = _uploads_dir() / f'{uid}_{safe}'
    path.write_bytes(file_bytes)
    local_id = f'local:{uid}'
    return {
        'drive_id': local_id,
        'nome': Path(filename or safe).stem,
        'tamanho': len(file_bytes),
        'mime_type': mime_type,
        'thumb_url': f'/api/local/{uid}',
        'drive_link': f'/api/local/{uid}',
        'storage': 'local',
    }


def upload_file(file_bytes, filename, mime_type, metadata=None):
    metadata = metadata or {}

    if not FOLDER_ID:
        print('[Drive] DRIVE_FOLDER_ID vazio — salvando localmente')
        return upload_local(file_bytes, filename, mime_type, metadata)

    file_meta = {
        'name': filename,
        'parents': [FOLDER_ID],
        'description': metadata.get('descricao', '')
    }

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mime_type,
        resumable=True,
        chunksize=5 * 1024 * 1024
    )

    def _do(service):
        result = service.files().create(
            body=file_meta,
            media_body=media,
            fields='id,name,size,mimeType,createdTime',
            supportsAllDrives=True,
        ).execute()

        if os.getenv('PUBLIC_DRIVE_FILES', 'false').lower() in ('1', 'true', 'yes'):
            service.permissions().create(
                fileId=result['id'],
                body={
                    'role': 'reader',
                    'type': 'anyone'
                },
                supportsAllDrives=True,
            ).execute()
        return result

    try:
        result = _drive_call(_do)
    except HttpError as e:
        if _is_storage_quota_error(e):
            print(
                '[Drive] Service account sem cota no Meu Drive — '
                'salvando arquivo localmente em data/uploads/'
            )
            return upload_local(file_bytes, filename, mime_type, metadata)
        raise

    return {
        'drive_id': result['id'],
        'nome': result.get('name', filename),
        'tamanho': int(result.get('size', 0)),
        'mime_type': result.get('mimeType', mime_type),
        'thumb_url': _thumb_url(result['id']),
        'drive_link': _view_url(result['id']),
        'storage': 'drive',
    }


def download_file(drive_id):
    local = resolve_local_path(drive_id)
    if local and local.is_file():
        data = local.read_bytes()
        from backend.utils.validators import sniff_mime_from_bytes
        mime = sniff_mime_from_bytes(data, local.name)
        return data, mime

    def _do(service):
        meta = service.files().get(
            fileId=drive_id,
            fields='mimeType,name',
            supportsAllDrives=True,
        ).execute()

        request = service.files().get_media(fileId=drive_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        return (
            buffer.getvalue(),
            meta.get('mimeType', 'application/octet-stream')
        )

    return _drive_call(_do)


def delete_file(drive_id):
    local = resolve_local_path(drive_id)
    if local and local.is_file():
        try:
            local.unlink()
        except OSError as e:
            print(f"[Local] Erro ao deletar: {e}")
            return False
        return True

    try:
        def _do(service):
            service.files().update(
                fileId=drive_id,
                body={'trashed': True},
                supportsAllDrives=True,
            ).execute()
            return True

        return _drive_call(_do)
    except HttpError as e:
        print(f"[Drive] Erro ao deletar: {e}")
        return False


def update_file_metadata(drive_id, metadata):
    try:
        body = {}
        if 'nome' in metadata:
            body['name'] = metadata['nome']
        if 'descricao' in metadata:
            body['description'] = metadata['descricao']

        if not body:
            return True

        def _do(service):
            service.files().update(fileId=drive_id, body=body).execute()
            return True

        return _drive_call(_do)
    except HttpError as e:
        print(f"[Drive] Erro ao atualizar: {e}")
        return False


def get_file_metadata(drive_id):
    try:
        def _do(service):
            return service.files().get(
                fileId=drive_id,
                fields=(
                    'id,name,size,mimeType,createdTime,'
                    'modifiedTime,description,webViewLink'
                )
            ).execute()

        return _drive_call(_do)
    except HttpError:
        return None


def list_drive_files(page_token=None):
    """
    Varre recursivamente a pasta raiz do Drive. Cada arquivo retornado
    inclui 'folder_name' (nome da subpasta imediata onde ele está —
    pasta raiz não conta, fica '').

    Campos leves de propósito: pedir imageMediaMetadata em milhares de
    arquivos deixa o sync lento / timeout no browser.
    """
    if not FOLDER_ID:
        raise RuntimeError(
            "DRIVE_FOLDER_ID ausente no .env — defina o ID da pasta compartilhada."
        )

    files = []
    # Campos mínimos — sync rápido e estável
    FIELDS = "nextPageToken, files(id,name,size,mimeType,createdTime,parents)"

    def scan_folder(service, folder_id, folder_name):
        token = None
        while True:
            result = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields=FIELDS,
                pageSize=1000,
                pageToken=token or None,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for f in result.get('files', []):
                if f.get('mimeType') == 'application/vnd.google-apps.folder':
                    scan_folder(service, f['id'], f.get('name', ''))
                else:
                    f['folder_name'] = folder_name
                    files.append(f)

            token = result.get('nextPageToken')
            if not token:
                break

    def _do(service):
        t0 = time.time()
        scan_folder(service, FOLDER_ID, '')
        print(f"[Drive] listagem: {len(files)} arquivo(s) em {time.time() - t0:.1f}s")
        return {'files': files, 'next_token': None}

    return _drive_call(_do)


def parse_image_metadata(f):
    """
    Extrai data/hora real da foto e câmera/localização do imageMediaMetadata
    do Drive, quando disponível. Retorna dict pronto pra mesclar no insert_media.
    Se não houver EXIF, retorna {} (o chamador usa createdTime como fallback).
    """
    meta = f.get('imageMediaMetadata') or {}
    out = {}

    time_str = meta.get('time')
    if time_str:
        try:
            from datetime import datetime as _dt
            cleaned = time_str.replace('Z', '')
            dt = _dt.fromisoformat(cleaned)
            out['data_upload'] = dt.strftime('%Y-%m-%d')
            out['hora_upload'] = dt.strftime('%H:%M:%S')
            out['ano'] = dt.year
            out['mes'] = dt.month
            out['dia'] = dt.day
        except Exception:
            pass

    camera_make = meta.get('cameraMake', '')
    camera_model = meta.get('cameraModel', '')
    camera = f"{camera_make} {camera_model}".strip()
    if camera:
        out['camera'] = camera

    loc = meta.get('location') or {}
    lat, lng = loc.get('latitude'), loc.get('longitude')
    if lat is not None and lng is not None:
        out['localizacao'] = f"{lat},{lng}"

    return out


def get_service_account_email() -> str | None:
    """E-mail da service account (para compartilhar a pasta no Drive)."""
    raw = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
            return (data.get("client_email") or "").strip() or None

        if not raw:
            cand = _project_root() / "service-account.json"
            if cand.is_file():
                raw = str(cand)
            else:
                return None

        cred_path = raw
        if not os.path.isabs(cred_path):
            cred_path = str(_project_root() / cred_path)
        with open(cred_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("client_email") or "").strip() or None
    except Exception:
        return None


_ping_cache = {'at': 0.0, 'result': None}
_ping_lock = None
_PING_TTL_SEC = 12.0


def _get_ping_lock():
    global _ping_lock
    if _ping_lock is None:
        import threading
        _ping_lock = threading.Lock()
    return _ping_lock


def drive_ping():
    """
    Testa a conexão com o Google Drive.
    Retorna (online: bool, message: str|None).
    Cache ~12s + lock: várias abas/páginas compartilham um único ping.
    """
    import time

    now = time.monotonic()
    cached = _ping_cache.get('result')
    if cached is not None and (now - _ping_cache['at']) < _PING_TTL_SEC:
        return cached

    with _get_ping_lock():
        now = time.monotonic()
        cached = _ping_cache.get('result')
        if cached is not None and (now - _ping_cache['at']) < _PING_TTL_SEC:
            return cached

        try:
            def _do(service):
                if FOLDER_ID:
                    try:
                        service.files().get(
                            fileId=FOLDER_ID,
                            fields="id,name",
                            supportsAllDrives=True,
                        ).execute()
                    except HttpError as e:
                        status = getattr(e, "resp", None) and e.resp.status
                        if status == 404:
                            raise RuntimeError(
                                "Pasta não encontrada ou sem acesso. "
                                "Compartilhe a pasta do Drive com o e-mail da service account (editor)."
                            )
                        if status == 403:
                            raise RuntimeError(
                                "Sem permissão na pasta. "
                                "Compartilhe DRIVE_FOLDER_ID com a service account."
                            )
                        raise
                service.files().list(
                    pageSize=1,
                    fields="files(id)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                return True

            # 1 retry = resposta rápida pro status da barra/páginas
            _drive_call(_do, retries=1)
            result = (True, None)

        except HttpError as e:
            status = getattr(e, 'status_code', None) or (e.resp.status if hasattr(e, 'resp') else None)

            if status == 403:
                result = (False, 'Sem permissão de acesso ao Drive. Verifique se a pasta foi compartilhada com a service account.')
            elif status == 404:
                result = (False, 'Pasta do Drive não encontrada. Verifique o DRIVE_FOLDER_ID no .env.')
            elif status == 401:
                result = (False, 'Credenciais inválidas ou expiradas. Gere uma nova chave da service account.')
            else:
                result = (False, f'Erro do Google Drive (HTTP {status}).')

        except RuntimeError as e:
            result = (False, str(e))

        except Exception as e:
            if _is_ssl_error(e):
                result = (False, (
                    'Falha SSL ao falar com o Google Drive. '
                    'Reinicie o servidor e tente de novo; se persistir, verifique antivírus/proxy.'
                ))
            else:
                result = (False, f'Erro ao conectar ao Drive: {e}')

        _ping_cache['result'] = result
        _ping_cache['at'] = time.monotonic()
        return result
