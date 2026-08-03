import os, io, mimetypes
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, redirect

from backend.models.database import (
    insert_media,
    get_media,
    update_media,
    delete_media,
    list_media,
    search_media,
    get_stats,
    get_all_tags,
    increment_views,
    increment_downloads,
    annotate_storage,
)

from backend.services import drive as drive_svc
from googleapiclient.errors import HttpError

from backend.utils.validators import (
    validate_file,
    sanitize_string,
    sanitize_tags,
    get_mime_category,
    format_size,
    sniff_mime_from_bytes,
)
from backend.utils.security import (
    require_perm,
    ROLE_PERMS,
    safe_int,
    is_safe_thumb_url,
    is_safe_image_url,
    lockdown_before_request,
    verify_login,
    login_user,
    logout_user,
    is_logged_in,
    current_user,
    current_role,
    is_auth_configured,
    login_rate_limited,
    record_login_failure,
    clear_login_failures,
    issue_csrf_token,
    verify_csrf_token,
    touch_session,
    current_can,
)


api = Blueprint(
    'api',
    __name__,
    url_prefix='/api'
)

# Tranca a API inteira por padrão (API_LOCKDOWN=true no .env)
api.before_request(lockdown_before_request)


def ok(data=None, msg='ok', status=200):
    return jsonify({
        'status': 'ok',
        'message': msg,
        **(data or {})
    }), status


def err(msg, status=400):
    return jsonify({
        'status': 'error',
        'message': msg
    }), status


# ==================================================
# AUTH (login admin)
# ==================================================

@api.route('/auth/csrf', methods=['GET'])
def auth_csrf_ep():
    return ok({'csrf': issue_csrf_token()})


@api.route('/auth/login', methods=['POST'])
def auth_login_ep():
    import time

    if not is_auth_configured():
        return err('Auth não configurada no servidor (.env).', 503)

    blocked, wait = login_rate_limited()
    if blocked:
        return err(f'Muitas tentativas. Aguarde {wait}s.', 429)

    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or data.get('user') or '').strip()
    # str() evita bug se o JSON mandar número; strip só nas pontas
    password = str(data.get('password') if data.get('password') is not None else '')
    if password:
        password = password.strip()
    csrf = data.get('csrf') or request.headers.get('X-CSRF-Token') or ''

    if not verify_csrf_token(csrf):
        return err('Sessão inválida. Recarregue a página.', 403)

    if not username or not password:
        return err('Informe usuário e senha.', 400)
    if len(username) > 64 or len(password) > 128:
        return err('Credenciais inválidas.', 400)
    if any(c in username for c in ('\x00', '\n', '\r')):
        return err('Credenciais inválidas.', 400)

    # Delay constante dificulta timing attacks
    t0 = time.perf_counter()
    user_info = verify_login(username, password)
    elapsed = time.perf_counter() - t0
    time.sleep(max(0.0, 0.12 - elapsed))

    if not user_info:
        record_login_failure()
        return err('Usuário ou senha inválidos.', 401)

    clear_login_failures()
    login_user(user_info['user'], user_info['role'])
    role = user_info['role']
    return ok({
        'user': current_user(),
        'role': role,
        'perms': sorted(ROLE_PERMS.get(role, ())),
        'logged_in': True,
        'csrf': issue_csrf_token(),
    }, 'Login ok')


@api.route('/auth/logout', methods=['POST'])
def auth_logout_ep():
    logout_user()
    return ok({'logged_in': False}, 'Logout ok')


@api.route('/auth/me', methods=['GET'])
def auth_me_ep():
    if is_logged_in():
        touch_session()
    role = current_role()
    return ok({
        'logged_in': is_logged_in(),
        'user': current_user(),
        'role': role,
        'perms': sorted(ROLE_PERMS.get(role, ())) if role else [],
        'auth_configured': is_auth_configured(),
    })



# ==================================================
# MÍDIA
# ==================================================

@api.route('/media', methods=['GET'])
@require_perm('gallery')
def list_media_ep():

    page = safe_int(request.args.get('page', 1), default=1, min_v=1, max_v=10_000)
    per_page = safe_int(request.args.get('per_page', 24), default=24, min_v=1, max_v=100)
    storage = (request.args.get('storage') or '').strip().lower()
    if storage not in ('', 'local', 'drive'):
        storage = ''
    sort = (request.args.get('sort') or 'date_desc').strip()
    if sort not in ('date_desc', 'date_asc', 'views', 'downloads', 'name', 'stars'):
        sort = 'date_desc'

    result = list_media(
        page=page,
        per_page=per_page,
        tipo=request.args.get('tipo'),
        categoria=request.args.get('categoria'),
        storage=storage or None,
        sort=sort,
    )

    return ok(result)



@api.route('/media/<int:media_id>', methods=['GET'])
def get_media_ep(media_id):

    item = get_media(media_id)

    if not item:
        return err(
            'Mídia não encontrada.',
            404
        )

    increment_views(media_id)

    from backend.models.database import annotate_storage
    return ok({
        'item': annotate_storage(item)
    })



@api.route('/media', methods=['POST'])
@require_perm('upload')
def upload_ep():

    if 'file' not in request.files:
        return err(
            'Nenhum arquivo enviado.'
        )


    file = request.files['file']

    filename = file.filename or 'sem_nome'

    file_bytes = file.read()

    # Não confia no MIME do browser — detecta pelos magic bytes
    mime_type = sniff_mime_from_bytes(file_bytes, filename)


    valid, msg = validate_file(
        filename,
        mime_type,
        len(file_bytes)
    )


    if not valid:
        return err(msg)


    descricao = sanitize_string(
        request.form.get(
            'descricao',
            ''
        )
    )


    try:

        drive_result = drive_svc.upload_file(
            file_bytes,
            filename,
            mime_type,
            {
                'descricao': descricao
            }
        )

    except HttpError as e:
        status = getattr(e, 'resp', None) and e.resp.status
        msg = str(e)
        print(f'[Upload] Drive HttpError {status}: {msg}')
        if 'storage quota' in msg.lower() or 'do not have storage' in msg.lower():
            return err(
                'Google bloqueou escrita da service account no Meu Drive. '
                'Reinicie o start.bat — o sistema agora salva localmente.',
                502,
            )
        if status == 403:
            return err('Sem permissão para enviar ao Drive. Compartilhe a pasta com a service account.', 403)
        return err(f'Erro do Google Drive (HTTP {status or "?"}).', 502)

    except Exception as e:
        print(f'[Upload] {e}')
        return err(
            f'Erro no upload: {e}',
            500
        )


    now = datetime.now()

    pasta_val = sanitize_string(request.form.get('pasta', ''))
    if drive_result.get('storage') == 'local' and not pasta_val:
        pasta_val = 'Site (local)'

    media_id = insert_media({

        **{k: v for k, v in drive_result.items() if k != 'storage'},

        'nome':
            sanitize_string(
                request.form.get(
                    'nome',
                    filename
                )
            ),

        'descricao':
            descricao,

        'tags':
            sanitize_tags(
                request.form.get(
                    'tags',
                    ''
                )
            ),

        'categoria':
            sanitize_string(
                request.form.get(
                    'categoria',
                    ''
                )
            ),

        'autor':
            sanitize_string(
                request.form.get(
                    'autor',
                    ''
                )
            ),

        'pasta':
            pasta_val,

        'tipo':
            get_mime_category(
                mime_type
            ),

        'data_upload':
            now.strftime(
                '%Y-%m-%d'
            ),

        'hora_upload':
            now.strftime(
                '%H:%M:%S'
            ),

        'ano':
            now.year,

        'mes':
            now.month,

        'dia':
            now.day
    })

    # Gera o embedding CLIP em background (best-effort — nunca bloqueia
    # nem quebra o upload se o OpenCLIP não estiver instalado ou falhar).
    # É isso que alimenta a busca semântica em /api/search.
    if get_mime_category(mime_type) == 'image' and drive_result.get('thumb_url'):
        import threading

        clip_src = drive_result['thumb_url']
        if drive_result.get('storage') == 'local':
            local_path = drive_svc.resolve_local_path(drive_result['drive_id'])
            if local_path:
                clip_src = str(local_path)

        def _gen_embedding(mid, thumb_url):
            try:
                from backend.services.clip_tagger import encode_image_embedding
                emb = encode_image_embedding(thumb_url, media_id=mid)
                if emb:
                    from backend.models.database import save_media_embedding
                    save_media_embedding(mid, emb)
            except Exception as e:
                print(f"[CLIP] Embedding do upload {mid} falhou: {e}")

        threading.Thread(
            target=_gen_embedding,
            args=(media_id, clip_src),
            daemon=True
        ).start()

    return ok(
        {
            'item':
                get_media(media_id),
            'storage': drive_result.get('storage') or 'drive',
        },
        'Upload realizado!' if drive_result.get('storage') != 'local' else 'Upload salvo no servidor (Drive sem cota de escrita).',
        201
    )

# ==================================================
# UPDATE / DELETE / DOWNLOAD
# ==================================================

@api.route('/media/<int:media_id>', methods=['PUT'])
@require_perm('edit')
def update_media_ep(media_id):

    item = get_media(media_id)

    if not item:
        return err(
            'Mídia não encontrada.',
            404
        )


    data = request.get_json(force=True) or {}

    cleaned = {}


    if 'nome' in data:
        cleaned['nome'] = sanitize_string(data['nome'])

    if 'descricao' in data:
        cleaned['descricao'] = sanitize_string(data['descricao'])

    if 'tags' in data:
        cleaned['tags'] = sanitize_tags(data['tags'])

    if 'categoria' in data:
        cleaned['categoria'] = sanitize_string(data['categoria'])

    if 'autor' in data:
        cleaned['autor'] = sanitize_string(data['autor'])

    if 'pasta' in data:
        cleaned['pasta'] = sanitize_string(data['pasta'])

    if 'estrelas' in data:
        try:
            cleaned['estrelas'] = max(0, min(5, int(data['estrelas'])))
        except (TypeError, ValueError):
            pass

    if 'destaque' in data:
        cleaned['destaque'] = 1 if data['destaque'] else 0

    if 'cor' in data:
        cleaned['cor'] = sanitize_string(data['cor'], max_len=32)

    if 'thumb_url' in data:
        # Só aceita URLs https do Drive — evita javascript: / SSRF em src
        candidate = (data['thumb_url'] or '').strip()
        if is_safe_thumb_url(candidate):
            cleaned['thumb_url'] = candidate[:1000]


    update_media(
        media_id,
        cleaned
    )


    drive_svc.update_file_metadata(
        item['drive_id'],
        cleaned
    )


    return ok(
        {
            'item':
                get_media(media_id)
        },
        'Atualizado.'
    )



@api.route('/media/<int:media_id>', methods=['DELETE'])
@require_perm('delete')
def delete_media_ep(media_id):

    item = get_media(media_id)

    if not item:
        return err(
            'Mídia não encontrada.',
            404
        )


    drive_svc.delete_file(
        item['drive_id']
    )


    delete_media(media_id)


    return ok(
        msg='Mídia removida.'
    )



@api.route('/local/<uid>', methods=['GET'])
def local_media_ep(uid):
    """Serve arquivo local com Range (seek no player de vídeo)."""
    import re
    if not re.fullmatch(r'[a-f0-9]{16,64}', uid or ''):
        return err('Arquivo inválido.', 400)
    path = drive_svc.resolve_local_path(f'local:{uid}')
    if not path or not path.is_file():
        return err('Arquivo não encontrado.', 404)
    mime = mimetypes.guess_type(path.name)[0] or sniff_mime_from_bytes(path.read_bytes()[:32], path.name)
    # send_file no path real → conditional/etag/Range (não carrega tudo na RAM)
    return send_file(
        path,
        mimetype=mime,
        as_attachment=False,
        conditional=True,
        etag=True,
        last_modified=True,
        max_age=86400,
    )


@api.route('/media/<int:media_id>/download', methods=['GET'])
def download_ep(media_id):

    item = get_media(media_id)

    if not item:
        return err(
            'Mídia não encontrada.',
            404
        )


    try:

        file_bytes, mime = drive_svc.download_file(
            item['drive_id']
        )


        increment_downloads(
            media_id
        )

        # 'nome' é salvo sem extensão (upload.html remove antes de enviar);
        # reconstrói a extensão a partir do mime type para o arquivo baixado
        # abrir corretamente no sistema operacional.
        download_name = item['nome']

        if '.' not in os.path.basename(download_name):
            ext = (
                mimetypes.guess_extension(mime)
                or mimetypes.guess_extension(item.get('mime_type', ''))
                or ''
            )
            download_name += ext

        return send_file(
            io.BytesIO(file_bytes),
            mimetype=mime,
            as_attachment=True,
            download_name=download_name
        )


    except Exception as e:

        print(f'[Download] {e}')
        return err(
            'Erro no download.',
            500
        )


@api.route('/media/<int:media_id>/thumb', methods=['GET'])
def media_thumb_ep(media_id):
    """Thumbnail com cache em disco — 1ª vez baixa do Drive, depois é instantâneo."""
    item = get_media(media_id)
    if not item:
        return err('Mídia não encontrada.', 404)
    try:
        size = safe_int(request.args.get('sz', 280), default=280, min_v=120, max_v=1200)
        # ETag fraco pra browser/CDN
        raw, mime = drive_svc.fetch_thumbnail_bytes(item['drive_id'], size=size, use_cache=True)
        resp = send_file(
            io.BytesIO(raw),
            mimetype=mime or 'image/jpeg',
            as_attachment=False,
            download_name=f'thumb-{media_id}.jpg',
            max_age=604800,
        )
        resp.headers['Cache-Control'] = 'public, max-age=604800, immutable'
        resp.headers['X-Thumb-Cache'] = 'hit' if drive_svc.thumb_cache_path(item['drive_id'], size).is_file() else 'miss'
        return resp
    except Exception as e:
        print(f'[Thumb] media={media_id}: {e}')
        legacy = (item.get('thumb_url') or '').strip()
        if legacy.startswith('https://'):
            return redirect(legacy, code=302)
        return err('Thumbnail indisponível.', 404)


# ==================================================
# BUSCA
# ==================================================

@api.route('/search', methods=['GET'])
def search_ep():

    query = request.args.get(
        'q',
        ''
    ).strip()


    filters = {}


    for f in (
        'tipo',
        'categoria',
        'autor',
        'pasta',
        'ano',
        'mes',
        'dia'
    ):

        value = request.args.get(f)

        if value:
            filters[f] = value


    from backend.services.search_engine import intelligent_search
    from backend.models.database import annotate_storage

    result = intelligent_search(
        query=query,
        extra_filters=filters,
        page=safe_int(request.args.get('page', 1), default=1, min_v=1, max_v=10_000),
        per_page=safe_int(request.args.get('per_page', 24), default=24, min_v=1, max_v=100),
    )
    result['items'] = [annotate_storage(it, thumb_size=280) for it in (result.get('items') or [])]

    return ok(result)



@api.route('/search/autocomplete', methods=['GET'])
def autocomplete_ep():

    q = request.args.get(
        'q',
        ''
    ).lower().strip()


    if len(q) < 2:
        return ok({
            'suggestions': []
        })


    from backend.models.database import get_all_pastas

    pastas = [
        p for p in get_all_pastas()
        if q in p.lower()
    ][:5]

    tags = [
        t for t in get_all_tags()
        if q in t.lower()
    ][:8 - len(pastas)]


    return ok({
        'suggestions': [
            {
                'text': p,
                'type': 'pasta',
                'icon': 'pasta'
            }
            for p in pastas
        ] + [
            {
                'text': t,
                'type': 'tag',
                'icon': 'tag'
            }
            for t in tags
        ]
    })



# ==================================================
# DASHBOARD
# ==================================================

@api.route('/dashboard', methods=['GET'])
@require_perm('dashboard')
def dashboard_ep():

    stats = get_stats()

    stats['espaco_formatado'] = format_size(
        stats['espaco_total']
    )

    for key in ('ultimos_uploads', 'mais_vistos', 'mais_baixados', 'destaques'):
        stats[key] = [annotate_storage(dict(it), thumb_size=400) for it in (stats.get(key) or [])]

    return ok({
        'stats': stats
    })



@api.route('/search/stats', methods=['GET'])
def search_stats_ep():
    """Contagens para a grade Explorar (tags + categoria, não só coluna vazia)."""
    from backend.models.database import get_conn

    explore = {
        'shows': ('show', 'shows', 'palco', 'banda', 'concerto', 'artista'),
        'casamento': ('casamento', 'noiva', 'noivo', 'cerimonia', 'igreja', 'alianca', 'vestido'),
        'retratos': ('retrato', 'retratos', 'close', 'estudio', 'olhar'),
        'casais': ('casal', 'casais', 'romantico', 'amor', 'beijo', 'abraco'),
        'familia': ('familia', 'familiar', 'geracoes'),
        'infantil': ('infantil', 'crianca', 'bebe', 'aniversario'),
        'motocross': ('moto', 'motocross', 'pista', 'adrenalina'),
        'editorial': ('editorial', 'moda', 'fashion'),
    }
    conn = get_conn()
    rows = conn.execute("SELECT LOWER(COALESCE(tags,'')) AS t, LOWER(COALESCE(categoria,'')) AS c FROM media").fetchall()
    conn.close()
    out = []
    for cat, keys in explore.items():
        total = 0
        for t, c in rows:
            blob = f" {t.replace(',', ' ')} {c} "
            if any(f" {k} " in blob or k == c for k in keys):
                total += 1
        out.append({'categoria': cat, 'total': total})
    out.sort(key=lambda x: x['total'], reverse=True)
    return ok({'por_categoria': out})


@api.route('/tags', methods=['GET'])
def tags_ep():

    return ok({
        'tags': get_all_tags()
    })



# ==================================================
# DRIVE
# ==================================================

@api.route('/drive/status', methods=['GET'])
def drive_status_ep():
    """Público: só online/offline. Detalhes (SA, folder) só sync/system (dev)."""
    online, error_msg = drive_svc.drive_ping()
    payload = {
        'online': online,
        'error': None if online else (error_msg or 'Drive offline'),
    }
    if current_can('sync') or current_can('system'):
        email = drive_svc.get_service_account_email()
        folder = getattr(drive_svc, 'FOLDER_ID', None) or ''
        payload.update({
            'service_account': email,
            'folder_id': folder,
            'hint': (
                None if online else
                'Compartilhe a pasta do Drive com o e-mail da service account (permissão Editor).'
            ),
        })
    return ok(
        payload,
        'Drive online' if online else (error_msg or 'Drive offline'),
    )

# ==================================================
# DRIVE SYNC
# ==================================================

@api.route('/drive/sync', methods=['POST'])
@require_perm('sync')
def drive_sync_ep():

    from backend.models.database import get_conn
    from backend.services.drive import parse_image_metadata

    try:

        conn = get_conn()

        added = 0
        updated_pasta = 0
        pending_embeddings = []  # [(media_id, thumb_url), ...] pra processar depois


        while True:

            page_result = drive_svc.list_drive_files(None)


            for f in page_result['files']:

                exists = conn.execute(
                    "SELECT id, pasta FROM media WHERE drive_id=?",
                    (f['id'],)
                ).fetchone()


                if exists:
                    # Repara pasta vazia em itens já sincronizados
                    folder_name = sanitize_string(f.get('folder_name', ''), max_len=300)
                    if folder_name and not (exists['pasta'] or '').strip():
                        from backend.models.database import update_pasta_by_drive_id
                        if update_pasta_by_drive_id(f['id'], folder_name):
                            updated_pasta += 1
                    continue


                mime = f.get(
                    'mimeType',
                    ''
                )


                tipo = get_mime_category(
                    mime
                )


                if tipo == 'unknown':
                    continue



                now = datetime.now()


                ts = f.get(
                    'createdTime',
                    now.isoformat()
                )[:10]


                try:

                    date = datetime.fromisoformat(
                        ts
                    )

                except:

                    date = now


                thumb_url = drive_svc._thumb_url(f['id'])

                media_data = {

                    'drive_id':
                        f['id'],

                    'nome':
                        sanitize_string(
                            f.get('name', 'sem_nome'),
                            max_len=300
                        ),

                    'pasta':
                        sanitize_string(
                            f.get('folder_name', ''),
                            max_len=300
                        ),

                    'tamanho':
                        int(
                            f.get(
                                'size',
                                0
                            )
                        ),

                    'mime_type':
                        mime,

                    'tipo':
                        tipo,

                    'thumb_url':
                        thumb_url,

                    'drive_link':
                        drive_svc._view_url(
                            f['id']
                        ),

                    'data_upload':
                        date.strftime(
                            '%Y-%m-%d'
                        ),

                    'hora_upload':
                        date.strftime(
                            '%H:%M:%S'
                        ),

                    'ano':
                        date.year,

                    'mes':
                        date.month,

                    'dia':
                        date.day
                }

                # Sobrescreve data/hora/câmera/localização com EXIF real,
                # quando o Drive fornecer (mais preciso que createdTime).
                meta_extra = parse_image_metadata(f)
                for k, v in meta_extra.items():
                    if isinstance(v, str):
                        meta_extra[k] = sanitize_string(v, max_len=500)
                media_data.update(meta_extra)

                media_id = insert_media(media_data)

                if tipo == 'image':
                    pending_embeddings.append((media_id, thumb_url))

                added += 1



            token = page_result.get(
                'next_token'
            )


            if not token:
                break



        conn.close()

        # Gera embeddings CLIP das imagens novas em background — best-effort,
        # não atrasa a resposta do sync nem quebra se o OpenCLIP não estiver
        # instalado. Alimenta a busca semântica nas próximas buscas.
        if pending_embeddings:
            import threading

            def _gen_embeddings_batch(items):
                try:
                    from backend.services.clip_tagger import encode_image_embedding
                    from backend.models.database import save_media_embedding
                except Exception as e:
                    print(f"[CLIP] Embeddings do sync não geradas (OpenCLIP indisponível): {e}")
                    return
                for mid, url in items:
                    try:
                        emb = encode_image_embedding(url, media_id=mid)
                        if emb:
                            save_media_embedding(mid, emb)
                    except Exception as e:
                        print(f"[CLIP] Embedding do item {mid} falhou: {e}")

            threading.Thread(
                target=_gen_embeddings_batch,
                args=(pending_embeddings,),
                daemon=True
            ).start()


        msg = f'{added} arquivo(s) sincronizado(s).'
        if updated_pasta:
            msg += f' {updated_pasta} pasta(s) atualizada(s).'
        return ok(
            {
                'added': added,
                'updated_pasta': updated_pasta,
            },
            msg
        )


    except HttpError as e:

        status = getattr(e, 'status_code', None) or (e.resp.status if hasattr(e, 'resp') else None)

        if status == 403:
            msg = 'Sem permissão de acesso ao Drive. Verifique se a pasta foi compartilhada com a service account.'
        elif status == 404:
            msg = 'Pasta do Drive não encontrada. Verifique o DRIVE_FOLDER_ID no .env.'
        elif status == 401:
            msg = 'Credenciais inválidas ou expiradas. Gere uma nova chave da service account.'
        else:
            msg = f'Erro do Google Drive (HTTP {status}).'

        return err(msg, 502)

    except RuntimeError as e:

        print(f'[Drive sync] {e}')
        return err('Drive não configurado corretamente.', 503)

    except Exception as e:

        print(f'[Drive sync] {e}')
        return err(
            'Erro na sincronização.',
            500
        )



# ==================================================
# OPENCLIP
# ==================================================

@api.route('/ai/clip/status', methods=['GET'])
def clip_status_ep():
    """Público: ready/enabled. Modelo, device e índice só clip/system (dev)."""
    from backend.services.clip_tagger import get_model_info

    info = get_model_info()
    if current_can('clip') or current_can('system'):
        return ok({'clip': info})
    return ok({
        'clip': {
            'enabled': bool(info.get('enabled')),
            'ready': bool(info.get('installed') or info.get('loaded')),
            'loaded': bool(info.get('loaded')),
            'installed': bool(info.get('installed')),
        }
    })


@api.route('/ai/clip/backfill', methods=['POST'])
@require_perm('clip')
def clip_backfill_ep():
    """Dispara indexação CLIP das imagens que ainda não têm embedding."""
    import threading
    from backend.services.clip_tagger import backfill_embeddings, is_enabled
    from backend.models.database import embedding_stats

    if not is_enabled():
        return err('OpenCLIP desativado (CLIP_ENABLED=false).', 400)

    data = request.get_json(silent=True) or {}
    batch = safe_int(data.get('batch_size', 24), default=24, min_v=1, max_v=80)
    max_batches = safe_int(data.get('max_batches', 0), default=0, min_v=0, max_v=500)

    def _run():
        backfill_embeddings(batch_size=batch, max_batches=max_batches)

    threading.Thread(target=_run, daemon=True, name='clip-backfill').start()
    return ok(
        {'index': embedding_stats(), 'started': True},
        'Backfill CLIP iniciado em background.',
    )


@api.route('/ai/clip/tags', methods=['POST'])
@require_perm('clip')
def clip_tags_ep():

    from backend.services.clip_tagger import generate_tags


    data = request.get_json(
        force=True
    ) or {}


    media_id = data.get(
        'media_id'
    )

    image_url = data.get(
        'image_url'
    )



    if not image_url and media_id:

        try:
            mid = int(media_id)
        except (TypeError, ValueError):
            return err('media_id inválido.')

        item = get_media(mid)


        if not item:

            return err(
                'Mídia não encontrada.',
                404
            )


        image_url = item.get(
            'thumb_url',
            ''
        )



    if not image_url:

        return err(
            'Forneça image_url ou media_id.'
        )

    if not is_safe_image_url(image_url):
        return err(
            'URL de imagem não permitida.',
            400
        )



    try:

        result = generate_tags(
            image_url,
            top_k=20,
            threshold=0.08
        )


        if media_id and result.get('tags'):
            item = get_media(int(media_id))
            folder_name = ((item or {}).get('pasta') or '').strip()
            merged_tags = list(result['tags'])
            if folder_name:
                merged_tags.append(folder_name)
                for part in folder_name.replace('-', ' ').split():
                    if len(part) >= 3:
                        merged_tags.append(part)
            # preserva ordem e remove repetidos
            dedup = []
            seen = set()
            for tag in merged_tags:
                key = str(tag).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                dedup.append(str(tag).strip())
            result['tags'] = dedup
            result['subject_name'] = folder_name or None

            update_media(
                int(media_id),
                {
                    'tags':
                        ', '.join(
                            dedup
                        )
                }
            )



        return ok({
            'clip_result':
                result
        })


    except Exception as e:

        print(f'[OpenCLIP] {e}')
        return err(
            'Erro no OpenCLIP.',
            500
        )



@api.route('/ai/clip/warmup', methods=['POST'])
@require_perm('clip')
def clip_warmup_ep():

    from backend.services.clip_tagger import warmup

    import threading


    threading.Thread(
        target=warmup,
        daemon=True
    ).start()


    return ok(
        msg='Carregamento do modelo CLIP iniciado em background.'
    )


# ==================================================
# PORTFÓLIO SLOTS (admin + dev)
# ==================================================

@api.route('/portfolio/slots', methods=['GET'])
def portfolio_slots_list_ep():
    from backend.services import portfolio_slots as slots_svc
    return ok(slots_svc.load_slots())


@api.route('/portfolio/slots/<slot_id>', methods=['PUT'])
@require_perm('slots')
def portfolio_slots_update_ep(slot_id):
    from backend.services import portfolio_slots as slots_svc
    data = request.get_json(silent=True) or {}
    try:
        item = slots_svc.update_slot(slot_id, data)
    except ValueError as e:
        return err(str(e), 400)
    if not item:
        return err('Slot inválido.', 404)
    return ok({'slot': item}, 'Slot atualizado')


@api.route('/portfolio/slots/<slot_id>', methods=['DELETE'])
@require_perm('slots')
def portfolio_slots_clear_ep(slot_id):
    from backend.services import portfolio_slots as slots_svc
    item = slots_svc.clear_slot(slot_id)
    if not item:
        return err('Slot inválido.', 404)
    return ok({'slot': item}, 'Slot limpo')


@api.route('/portfolio/slots/<slot_id>/upload', methods=['POST'])
@require_perm('slots')
def portfolio_slots_upload_ep(slot_id):
    from backend.services import portfolio_slots as slots_svc

    if 'file' not in request.files:
        return err('Nenhum arquivo enviado.')
    f = request.files['file']
    raw = f.read()
    mime = sniff_mime_from_bytes(raw, f.filename or 'file')
    title = sanitize_string(request.form.get('title') or '', 80)
    cat = sanitize_string(request.form.get('cat') or request.form.get('categoria') or '', 80)
    try:
        item = slots_svc.save_upload(slot_id, raw, f.filename or 'upload', mime, title, cat)
    except ValueError as e:
        return err(str(e), 400)
    except OSError as e:
        return err(f'Falha ao salvar: {e}', 500)
    return ok({'slot': item}, 'Slot preenchido')


# ==================================================
# DEV SYSTEM (somente papel com perm system)
# ==================================================

def _env_flag(name: str, default: str = 'false') -> bool:
    return (os.getenv(name, default) or default).lower().strip() in ('1', 'true', 'yes', 'on')


@api.route('/dev/system', methods=['GET'])
@require_perm('system')
def dev_system_ep():
    """Resumo seguro do servidor — sem senhas, tokens ou caminhos secretos."""
    from backend.services.clip_tagger import get_model_info
    from backend.models.database import embedding_stats, count_media

    online, error_msg = drive_svc.drive_ping()
    clip = get_model_info()
    try:
        media_total = count_media()
    except Exception:
        media_total = None

    return ok({
        'role': current_role(),
        'user': current_user(),
        'flags': {
            'clip_enabled': _env_flag('CLIP_ENABLED', 'true'),
            'code_viewer_enabled': _env_flag('CODE_VIEWER_ENABLED', 'false'),
            'api_lockdown': _env_flag('API_LOCKDOWN', 'true'),
            'public_drive_files': _env_flag('PUBLIC_DRIVE_FILES', 'false'),
            'session_days': max(1, safe_int(os.getenv('SESSION_DAYS', '90'), default=90, min_v=1, max_v=3650)),
            'flask_env': (os.getenv('FLASK_ENV') or 'production').strip() or 'production',
        },
        'drive': {
            'online': online,
            'error': None if online else (error_msg or 'Drive offline'),
            'service_account': drive_svc.get_service_account_email(),
            'folder_id': getattr(drive_svc, 'FOLDER_ID', None) or '',
        },
        'clip': clip,
        'media_total': media_total,
        'index': clip.get('index') or embedding_stats(),
    })


# ==================================================
# CODE VIEWER (somente dev — e só se CODE_VIEWER_ENABLED=true)
# ==================================================

def _code_viewer_enabled() -> bool:
    return os.getenv('CODE_VIEWER_ENABLED', 'false').lower().strip() in ('1', 'true', 'yes', 'on')


@api.route('/dev/tree', methods=['GET'])
@require_perm('code')
def dev_tree_ep():
    if not _code_viewer_enabled():
        return err('Viewer de código desativado neste servidor.', 404)
    from backend.services import code_viewer as code_svc
    path = request.args.get('path') or ''
    try:
        return ok(code_svc.list_tree(path))
    except PermissionError as e:
        return err(str(e) or 'Acesso negado.', 403)
    except FileNotFoundError:
        return err('Pasta não encontrada.', 404)


@api.route('/dev/file', methods=['GET'])
@require_perm('code')
def dev_file_ep():
    if not _code_viewer_enabled():
        return err('Viewer de código desativado neste servidor.', 404)
    from backend.services import code_viewer as code_svc
    path = request.args.get('path') or ''
    if not path:
        return err('Informe path.')
    try:
        return ok(code_svc.read_file(path))
    except PermissionError as e:
        return err(str(e) or 'Arquivo bloqueado.', 403)
    except FileNotFoundError:
        return err('Arquivo não encontrado.', 404)
