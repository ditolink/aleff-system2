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

        http = httplib2.Http(timeout=60)
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


def upload_file(file_bytes, filename, mime_type, metadata=None):
    metadata = metadata or {}

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
            fields='id,name,size,mimeType,createdTime'
        ).execute()

        if os.getenv('PUBLIC_DRIVE_FILES', 'false').lower() in ('1', 'true', 'yes'):
            service.permissions().create(
                fileId=result['id'],
                body={
                    'role': 'reader',
                    'type': 'anyone'
                }
            ).execute()
        return result

    result = _drive_call(_do)

    return {
        'drive_id': result['id'],
        'nome': result.get('name', filename),
        'tamanho': int(result.get('size', 0)),
        'mime_type': result.get('mimeType', mime_type),
        'thumb_url': _thumb_url(result['id']),
        'drive_link': _view_url(result['id'])
    }


def download_file(drive_id):
    def _do(service):
        meta = service.files().get(
            fileId=drive_id,
            fields='mimeType,name'
        ).execute()

        request = service.files().get_media(fileId=drive_id)
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
    try:
        def _do(service):
            service.files().update(
                fileId=drive_id,
                body={'trashed': True}
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
    pasta raiz não conta, fica '') e, quando disponível, metadados EXIF
    em 'imageMediaMetadata' (data real da foto, câmera, localização).
    """
    files = []

    FIELDS = (
        "nextPageToken, files(id,name,size,mimeType,createdTime,parents,"
        "imageMediaMetadata(time,cameraMake,cameraModel,location))"
    )

    def scan_folder(service, folder_id, folder_name):
        token = None
        while True:
            result = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields=FIELDS,
                pageSize=100,
                pageToken=token
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
        scan_folder(service, FOLDER_ID, '')
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


def drive_ping():
    """
    Testa a conexão com o Google Drive.
    Retorna (online: bool, message: str|None).
    """
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
            service.files().list(pageSize=1, fields="files(id)").execute()
            return True

        _drive_call(_do, retries=3)
        return True, None

    except HttpError as e:
        status = getattr(e, 'status_code', None) or (e.resp.status if hasattr(e, 'resp') else None)

        if status == 403:
            return False, 'Sem permissão de acesso ao Drive. Verifique se a pasta foi compartilhada com a service account.'
        if status == 404:
            return False, 'Pasta do Drive não encontrada. Verifique o DRIVE_FOLDER_ID no .env.'
        if status == 401:
            return False, 'Credenciais inválidas ou expiradas. Gere uma nova chave da service account.'

        return False, f'Erro do Google Drive (HTTP {status}).'

    except RuntimeError as e:
        return False, str(e)

    except Exception as e:
        if _is_ssl_error(e):
            return False, (
                'Falha SSL ao falar com o Google Drive. '
                'Reinicie o servidor e tente de novo; se persistir, verifique antivírus/proxy.'
            )
        return False, f'Erro ao conectar ao Drive: {e}'
