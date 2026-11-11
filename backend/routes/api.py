import os, io, mimetypes
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, redirect, make_response

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
    from backend.models.database import annotate_storage
    result['items'] = [annotate_storage(it, thumb_size=800) for it in (result.get('items') or [])]

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

    from backend.models.database import annotate_storage, to_search_card
    from backend.utils.security import current_can

    # Público: card slim (sem drive_id/link). Staff: row anotada completa.
    if current_can('gallery'):
        return ok({'item': annotate_storage(item, light=False)})
    return ok({'item': to_search_card(item, thumb_size=800)})



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

    # CLIP + Faces em background via pipeline unificado
    if get_mime_category(mime_type) == 'image' and drive_result.get('thumb_url'):
        from backend.services.ai_pipeline import enqueue_media_ai

        clip_src = drive_result['thumb_url']
        if drive_result.get('storage') == 'local':
            local_path = drive_svc.resolve_local_path(drive_result['drive_id'])
            if local_path:
                clip_src = str(local_path)
        enqueue_media_ai(media_id, clip_src)

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
        from backend.models.database import normalize_pasta_name
        cleaned['pasta'] = normalize_pasta_name(sanitize_string(data['pasta']))

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
    """Serve arquivo local com Range (seek no player de vídeo).
    Imagens originais exigem gallery; vídeo pode ser público (player do site).
    """
    import re
    from backend.utils.security import current_can, public_originals_allowed

    if not re.fullmatch(r'[a-f0-9]{16,64}', uid or ''):
        return err('Arquivo inválido.', 400)
    path = drive_svc.resolve_local_path(f'local:{uid}')
    if not path or not path.is_file():
        return err('Arquivo não encontrado.', 404)
    mime = mimetypes.guess_type(path.name)[0] or sniff_mime_from_bytes(path.read_bytes()[:32], path.name)
    is_video = (mime or '').startswith('video/') or path.suffix.lower() in (
        '.mp4', '.webm', '.mov', '.m4v', '.mkv',
    )
    if not is_video and not (public_originals_allowed() or current_can('gallery')):
        return err('Arquivo original exige login.', 401)
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
    """Original HD. Público só com PUBLIC_MEDIA_ORIGINALS (+ confirm em prod).
    Sem auth: vídeos podem streamar; fotos redirecionam p/ thumb-medium (lightbox).
    """
    from backend.utils.security import current_can, public_originals_allowed

    item = get_media(media_id)

    if not item:
        return err(
            'Mídia não encontrada.',
            404
        )

    is_video = (item.get('tipo') or '') == 'video'
    can_original = public_originals_allowed() or current_can('gallery')
    as_attach = request.args.get('dl', '1') not in ('0', 'false', 'view')

    # Foto sem auth: não vaza HD — thumb medium (ou 401 se attachment)
    if not can_original and not is_video:
        if as_attach:
            return err('Download do original exige login.', 401)
        return redirect(f'/api/media/{media_id}/thumb-medium', code=302)

    try:
        # Stream do disco (cache) — não carrega o arquivo inteiro na RAM do Waitress
        path, mime = drive_svc.open_media_file(item['drive_id'])

        increment_downloads(media_id)

        download_name = item['nome']
        if '.' not in os.path.basename(download_name):
            ext = (
                mimetypes.guess_extension(mime)
                or mimetypes.guess_extension(item.get('mime_type', ''))
                or ''
            )
            download_name += ext

        resp = send_file(
            path,
            mimetype=mime,
            as_attachment=as_attach,
            download_name=download_name,
            conditional=True,
            etag=True,
            last_modified=True,
            max_age=86400,
        )
        resp.headers['Cache-Control'] = 'private, max-age=3600'
        return resp

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
        cache_path = drive_svc.thumb_cache_path(item['drive_id'], size)
        raw, mime = drive_svc.fetch_thumbnail_bytes(item['drive_id'], size=size, use_cache=True)
        # Preferir enviar do arquivo em disco (send_file + etag/condicional)
        if cache_path.is_file() and cache_path.stat().st_size > 200:
            resp = send_file(
                cache_path,
                mimetype=mime or 'image/jpeg',
                as_attachment=False,
                download_name=f'thumb-{media_id}.jpg',
                conditional=True,
                etag=True,
                last_modified=True,
                max_age=86400,
            )
        else:
            resp = send_file(
                io.BytesIO(raw),
                mimetype=mime or 'image/jpeg',
                as_attachment=False,
                download_name=f'thumb-{media_id}.jpg',
                max_age=86400,
            )
        resp.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
        resp.headers['X-Thumb-Cache'] = 'hit' if cache_path.is_file() else 'miss'
        return resp
    except Exception as e:
        print(f'[Thumb] media={media_id}: {e}')
        from backend.utils.security import is_safe_thumb_url
        legacy = (item.get('thumb_url') or '').strip()
        if is_safe_thumb_url(legacy):
            return redirect(legacy, code=302)
        return err('Thumbnail indisponível.', 404)


def _serve_tier_thumb(media_id: int, tier: str):
    """Serve WebP small/medium com cache longo + geração sob demanda."""
    from backend.services import thumb_pipeline as tp
    from flask import Response

    item = get_media(media_id)
    if not item:
        return err('Mídia não encontrada.', 404)
    if (item.get('tipo') or '') == 'video':
        # Vídeo: reusa proxy clássico
        return media_thumb_ep(media_id)

    prefer = 320 if tier == 'small' else 800

    # Hit WebP
    if tp.is_ready(media_id, tier):
        path = tp.thumb_path(media_id, tier)
        resp = send_file(
            path,
            mimetype='image/webp',
            as_attachment=False,
            download_name=f'thumb-{media_id}-{tier}.webp',
            conditional=True,
            etag=True,
            last_modified=True,
            max_age=31536000,
        )
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        resp.headers['X-Thumb-Tier'] = tier
        resp.headers['X-Thumb-Cache'] = 'hit'
        return resp

    # Gera WebP a partir de fonte local (JPEG legado / public)
    try:
        path = tp.ensure_thumb(item, tier=tier)
        resp = send_file(
            path,
            mimetype='image/webp',
            as_attachment=False,
            download_name=f'thumb-{media_id}-{tier}.webp',
            conditional=True,
            etag=True,
            last_modified=True,
            max_age=31536000,
        )
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        resp.headers['X-Thumb-Tier'] = tier
        resp.headers['X-Thumb-Cache'] = 'miss'
        return resp
    except Exception as e:
        print(f'[Thumb-{tier}] media={media_id}: {e}')

    # Fallback imediato: JPEG legado em disco (renderiza agora) + gera WebP em bg
    did = (item.get('drive_id') or '').strip()
    if did:
        try:
            raw = drive_svc.find_cached_thumb_bytes(did, prefer_w=prefer)
            if raw:
                def _bg_webp():
                    try:
                        tp.ensure_thumb(item, tier=tier)
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_bg_webp, daemon=True, name=f'thumb-bg-{media_id}').start()
                resp = Response(raw, mimetype='image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
                resp.headers['X-Thumb-Tier'] = tier
                resp.headers['X-Thumb-Cache'] = 'legacy-jpeg'
                return resp
        except Exception:
            pass

    # Último recurso: proxy clássico / Drive redirect
    try:
        return media_thumb_ep(media_id)
    except Exception:
        if did and not did.startswith('local:'):
            return redirect(drive_svc._thumb_url(did, size=prefer), code=302)
        return err('Thumbnail indisponível.', 404)


@api.route('/media/<int:media_id>/thumb-small', methods=['GET'])
def media_thumb_small_ep(media_id):
    """Pré-render leve (WebP ~320px) — grid / prefetch."""
    return _serve_tier_thumb(media_id, 'small')


@api.route('/media/<int:media_id>/thumb-medium', methods=['GET'])
def media_thumb_medium_ep(media_id):
    """Upgrade de qualidade na viewport (WebP ~800px)."""
    return _serve_tier_thumb(media_id, 'medium')


@api.route('/media/<int:media_id>/thumb-cover', methods=['GET'])
def media_thumb_cover_ep(media_id):
    """WebP panorâmico com rosto no centro — capas da grade Explorar."""
    from backend.services import thumb_pipeline as tp

    item = get_media(media_id)
    if not item:
        return err('Mídia não encontrada.', 404)
    if (item.get('tipo') or '') == 'video':
        return _serve_tier_thumb(media_id, 'medium')

    try:
        path = tp.ensure_cover_thumb(item)
        resp = send_file(
            path,
            mimetype='image/webp',
            as_attachment=False,
            download_name=f'thumb-{media_id}-cover.webp',
            conditional=True,
            etag=True,
            last_modified=True,
            max_age=31536000,
        )
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        resp.headers['X-Thumb-Tier'] = 'cover'
        resp.headers['X-Thumb-Cache'] = 'hit'
        return resp
    except Exception as e:
        print(f'[Thumb-cover] media={media_id}: {e}')
        return _serve_tier_thumb(media_id, 'medium')


@api.route('/thumbs/prefetch-plan', methods=['GET'])
def thumbs_prefetch_plan_ep():
    """
    IDs prioritários pra pré-cache (home + categorias).
    Retorna URLs medium estáveis — frontend aquece o browser cache de uma vez.
    """
    from backend.services import thumb_pipeline as tp

    limit = safe_int(request.args.get('limit', 240), default=240, min_v=8, max_v=400)
    ids = tp.get_prefetch_plan_cached(limit=limit)
    # ready_medium: conta rápida via listdir do tier (1× FS) em vez de N×stat
    ready_set = set()
    try:
        ready_set = {int(p.stem) for p in tp.tier_dir('medium').glob('*.webp') if p.stat().st_size > 80}
    except Exception:
        pass
    ready_medium = sum(1 for i in ids if i in ready_set)
    urls = [f'/api/media/{i}/thumb-medium' for i in ids]
    payload = {
        'ids': ids,
        'urls': urls,
        'total': len(ids),
        'ready_medium': ready_medium,
        'pending_medium': max(0, len(ids) - ready_medium),
    }
    resp = make_response(jsonify({'status': 'ok', 'message': 'ok', **payload}), 200)
    resp.headers['Cache-Control'] = 'public, max-age=30, stale-while-revalidate=60'
    return resp


@api.route('/thumbs/warm', methods=['GET', 'POST'])
@require_perm('gallery')
def thumbs_warm_ep():
    """
    Pré-geração em disco (home+categorias). Exige login — evita DoS anônimo.
    Boot do server já aquece sozinho; visitantes usam ensure_thumb sob demanda.
    """
    from backend.services import thumb_pipeline as tp

    limit = safe_int(request.args.get('limit', 240), default=240, min_v=8, max_v=400)
    workers = safe_int(request.args.get('workers', 4), default=4, min_v=1, max_v=8)
    started = tp.start_background_warm(limit=limit, workers=workers)
    return ok({
        'started': started,
        'limit': limit,
        'workers': workers,
    })


@api.route('/thumbs/stats', methods=['GET'])
@require_perm('system')
def thumbs_stats_ep():
    from backend.services import thumb_pipeline as tp
    return ok({'stats': tp.get_stats()})


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
    import time as _time

    t0 = _time.perf_counter()
    result = intelligent_search(
        query=query,
        extra_filters=filters,
        page=safe_int(request.args.get('page', 1), default=1, min_v=1, max_v=10_000),
        per_page=safe_int(request.args.get('per_page', 24), default=24, min_v=1, max_v=100),
        sort=(request.args.get('sort') or 'home').strip().lower(),
    )
    # Cards já vêm slim de intelligent_search (to_search_card)
    timing = result.get('timing') or {}
    http_ms = (_time.perf_counter() - t0) * 1000
    print(
        f"[SEARCH] q={query!r} mode={result.get('mode')} "
        f"total={result.get('total')} "
        f"db_ms={timing.get('db_ms')} ser_ms={timing.get('serialize_ms')} "
        f"eng_ms={timing.get('total_ms')} http_ms={http_ms:.1f}"
        f"{' cache' if timing.get('cache') else ''}"
    )

    payload = {
        'status': 'ok',
        'message': 'ok',
        **result,
    }
    resp = make_response(jsonify(payload), 200)
    mode = result.get('mode') or ''
    # Browse/home público: cache compartilhado (CDN/nginx/browser) — site no ar
    if mode in ('browse', 'home', 'tag', 'name') and not filters:
        if os.getenv('FLASK_ENV') == 'production':
            resp.headers['Cache-Control'] = (
                'public, max-age=60, s-maxage=120, stale-while-revalidate=300'
            )
        else:
            resp.headers['Cache-Control'] = 'private, max-age=20, stale-while-revalidate=60'
    else:
        resp.headers['Cache-Control'] = 'private, no-cache'
    return resp



@api.route('/search/autocomplete', methods=['GET'])
def autocomplete_ep():

    q = request.args.get(
        'q',
        ''
    ).strip()

    if len(q) < 2:
        return ok({
            'suggestions': []
        })

    import html
    import unicodedata
    from backend.models.database import get_all_pastas, normalize_pasta_name

    def norm(s):
        s = html.unescape(str(s or '')).strip().lower()
        s = unicodedata.normalize('NFD', s)
        return ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')

    qn = norm(q)
    scored_pastas = []
    for p in get_all_pastas():
        label = normalize_pasta_name(p)
        pn = norm(label)
        if not pn or len(pn) < 2:
            continue
        if qn == pn:
            scored_pastas.append((0, label))
        elif pn.startswith(qn) or any(w.startswith(qn) for w in pn.split()):
            scored_pastas.append((1, label))
        elif qn in pn:
            scored_pastas.append((2, label))
    scored_pastas.sort(key=lambda x: (x[0], x[1].lower()))
    # únicos
    seen = set()
    pastas = []
    for _, label in scored_pastas:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        pastas.append(label)
        if len(pastas) >= 6:
            break

    tags = [
        t for t in get_all_tags()
        if qn in norm(t)
    ][: max(0, 10 - len(pastas))]

    return ok({
        'suggestions': [
            {
                'text': p,
                'type': 'nome',
                'icon': 'nome'
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
    """Contagens + capas (melhores fotos) para a grade Explorar."""
    import time as _time
    from backend.models.database import pick_category_covers, pick_best_for_keys

    # Capas/contagens mudam pouco — TTL maior evita 8× pick_best por pageview
    cache_ttl = int(os.getenv('SEARCH_STATS_CACHE_SEC', '180') or 180)
    cache = getattr(search_stats_ep, '_cache', None)
    if cache and (_time.time() - cache['ts']) < max(45, cache_ttl):
        return ok(cache['data'])

    explore = {
        'shows': ('show', 'shows', 'palco', 'banda', 'concerto', 'sonata'),
        'casamento': ('casamento', 'noiva', 'noivo', 'cerimonia', 'igreja', 'alianca', 'vestido'),
        'retratos': ('retrato', 'retratos', 'close', 'estudio', 'olhar'),
        'casais': ('casal', 'casais', 'romantico', 'amor', 'beijo', 'abraco'),
        'familia': ('familia', 'familiar', 'geracoes'),
        'infantil': ('infantil', 'crianca', 'bebe', 'aniversario'),
        'ensaios': ('ensaio', 'ensaios', 'externo', 'sessao', 'lifestyle'),
        'editorial': ('editorial', 'moda', 'fashion', 'conceito', 'artistico'),
    }
    covers = {}
    try:
        covers = pick_category_covers(explore, thumb_size=560)
    except Exception as e:
        print(f'[search/stats] covers: {e}')

    out = []
    for cat, keys in explore.items():
        try:
            total = len(pick_best_for_keys(list(keys), limit=600, tipo='image', max_per_pasta=24))
        except Exception:
            total = int((covers.get(cat) or {}).get('total_pool') or 0)
        out.append({'categoria': cat, 'total': total})
    out.sort(key=lambda x: x['total'], reverse=True)
    payload = {'por_categoria': out, 'covers': covers}
    search_stats_ep._cache = {'ts': _time.time(), 'data': payload}
    return ok(payload)


@api.route('/portfolio/home', methods=['GET'])
def portfolio_home_ep():
    """Grade curada pro index: shapes equilibrados + melhores fotos diversificadas."""
    from backend.models.database import pick_portfolio_layout, count_media

    limit = safe_int(request.args.get('limit', 22), default=22, min_v=6, max_v=40)
    try:
        layout = pick_portfolio_layout(limit=limit)
    except Exception as e:
        print(f'[portfolio/home] {e}')
        return ok({'items': [], 'photos': 0, 'total_pool': 0, 'error': str(e)})
    return ok({
        **layout,
        'archive_total': count_media({'tipo': 'image'}),
    })


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

_sync_lock = __import__('threading').Lock()
_sync_running = False
_sync_last = None  # último resultado resumido


@api.route('/drive/sync/status', methods=['GET'])
@require_perm('sync')
def drive_sync_status_ep():
    """Indica se um sync está em andamento e o resultado do último."""
    global _sync_last
    return ok({
        'running': _sync_running,
        'last': _sync_last,
    })


@api.route('/drive/sync', methods=['POST'])
@require_perm('sync')
def drive_sync_ep():
    global _sync_running, _sync_last

    if not _sync_lock.acquire(blocking=False):
        return err('Sincronização já em andamento. Aguarde terminar.', 409)

    import time as _time
    from backend.models.database import (
        load_drive_sync_index,
        batch_update_drive_meta,
        insert_media,
        set_media_ai_status,
        invalidate_read_caches,
    )
    from backend.services.drive import parse_image_metadata, fetch_file_image_metadata
    from backend.services.ai_pipeline import enqueue_media_ai_batch

    fetch_exif = os.getenv('SYNC_FETCH_EXIF', '1').strip().lower() in ('1', 'true', 'yes', 'on')
    t0 = _time.perf_counter()
    _sync_running = True

    try:
        added = 0
        skipped = 0
        updated_pasta = 0
        exif_fetched = 0
        pending_ai = []
        meta_updates = []

        drive_index = load_drive_sync_index()
        page_result = drive_svc.list_drive_files(None)
        drive_files = page_result.get('files') or []

        for f in drive_files:
            drive_id = f['id']
            modified = (f.get('modifiedTime') or '').strip()
            exists = drive_index.get(drive_id)

            if exists:
                prev_mod = (exists.get('drive_modified') or '').strip()
                folder_name = sanitize_string(f.get('folder_name', ''), max_len=300)
                pasta_empty = not (exists.get('pasta') or '').strip()

                if prev_mod and modified and prev_mod == modified and not pasta_empty:
                    skipped += 1
                    continue

                upd = {'drive_id': drive_id}
                if folder_name:
                    upd['pasta'] = folder_name
                upd['drive_modified'] = modified or prev_mod
                nome = sanitize_string(f.get('name', ''), max_len=300)
                if nome:
                    upd['nome'] = nome
                if f.get('size') is not None:
                    upd['tamanho'] = int(f.get('size', 0) or 0)
                meta_updates.append(upd)

                if folder_name and pasta_empty:
                    updated_pasta += 1
                if modified and prev_mod and modified != prev_mod:
                    mid = exists['id']
                    mime = f.get('mimeType', '')
                    if get_mime_category(mime) == 'image':
                        thumb_url = drive_svc._thumb_url(drive_id)
                        set_media_ai_status(mid, clip_status='pending', face_status='pending')
                        pending_ai.append((mid, thumb_url))
                continue

            mime = f.get('mimeType', '')
            tipo = get_mime_category(mime)
            if tipo == 'unknown':
                continue

            now = datetime.now()
            ts = f.get('createdTime', now.isoformat())[:10]
            try:
                date = datetime.fromisoformat(ts)
            except Exception:
                date = now

            thumb_url = drive_svc._thumb_url(f['id'])
            media_data = {
                'drive_id': f['id'],
                'nome': sanitize_string(f.get('name', 'sem_nome'), max_len=300),
                'pasta': sanitize_string(f.get('folder_name', ''), max_len=300),
                'tamanho': int(f.get('size', 0) or 0),
                'mime_type': mime,
                'tipo': tipo,
                'thumb_url': thumb_url,
                'drive_link': drive_svc._view_url(f['id']),
                'drive_modified': modified,
                'data_upload': date.strftime('%Y-%m-%d'),
                'hora_upload': date.strftime('%H:%M:%S'),
                'ano': date.year,
                'mes': date.month,
                'dia': date.day,
                'clip_status': 'pending' if tipo == 'image' else 'completed',
                'face_status': 'pending' if tipo == 'image' else 'completed',
            }

            meta_extra = parse_image_metadata(f)
            if fetch_exif and tipo == 'image' and not meta_extra.get('data_upload'):
                meta_extra = fetch_file_image_metadata(drive_id) or meta_extra
                if meta_extra:
                    exif_fetched += 1
            for k, v in meta_extra.items():
                if isinstance(v, str):
                    meta_extra[k] = sanitize_string(v, max_len=500)
            media_data.update(meta_extra)

            media_id = insert_media(media_data, invalidate_cache=False)
            drive_index[drive_id] = {
                'drive_id': drive_id,
                'id': media_id,
                'pasta': media_data.get('pasta', ''),
                'drive_modified': modified,
                'nome': media_data.get('nome', ''),
                'tamanho': media_data.get('tamanho', 0),
            }
            if tipo == 'image':
                pending_ai.append((media_id, thumb_url))
            added += 1

        updated = batch_update_drive_meta(meta_updates, invalidate_cache=False)
        if added or updated or updated_pasta:
            invalidate_read_caches()

        elapsed_ms = round((_time.perf_counter() - t0) * 1000, 1)

        if pending_ai:
            enqueue_media_ai_batch(pending_ai, thread_prefix='sync')

        msg = f'{added} arquivo(s) sincronizado(s).'
        if updated:
            msg += f' {updated} metadado(s) atualizado(s).'
        if skipped:
            msg += f' {skipped} inalterado(s) ignorado(s).'
        if updated_pasta:
            msg += f' {updated_pasta} pasta(s) atualizada(s).'

        result = {
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'updated_pasta': updated_pasta,
            'exif_fetched': exif_fetched,
            'queued_ai': len(pending_ai),
            'drive_total': len(drive_files),
            'elapsed_ms': elapsed_ms,
        }
        _sync_last = {**result, 'ok': True, 'at': datetime.now().isoformat(timespec='seconds')}
        print(
            f"[Drive sync] +{added} ~{updated} skip={skipped} "
            f"exif={exif_fetched} ai_q={len(pending_ai)} {elapsed_ms}ms"
        )
        return ok(result, msg)

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
        _sync_last = {'ok': False, 'error': msg, 'at': datetime.now().isoformat(timespec='seconds')}
        return err(msg, 502)

    except RuntimeError as e:
        print(f'[Drive sync] {e}')
        _sync_last = {'ok': False, 'error': str(e), 'at': datetime.now().isoformat(timespec='seconds')}
        return err('Drive não configurado corretamente.', 503)

    except Exception as e:
        print(f'[Drive sync] {e}')
        _sync_last = {'ok': False, 'error': str(e), 'at': datetime.now().isoformat(timespec='seconds')}
        return err('Erro na sincronização.', 500)

    finally:
        _sync_running = False
        _sync_lock.release()



# ==================================================
# IA — OpenCLIP + InsightFace
# ==================================================

@api.route('/ai/status', methods=['GET'])
def ai_status_ep():
    """Status consolidado CLIP + Faces (público leve; detalhes só dev)."""
    from backend.services.ai_pipeline import get_public_ai_summary

    if current_can('clip') or current_can('system'):
        from backend.services.clip_tagger import get_model_info
        from backend.services.face_tagger import get_status
        return ok({
            'clip': get_model_info(),
            'face': get_status(),
        })
    return ok(get_public_ai_summary())


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
            'ready': bool(info.get('loaded')),
            'loaded': bool(info.get('loaded')),
            'installed': bool(info.get('installed')),
            'loading': bool(info.get('loading')),
        }
    })


# ==================================================
# FACES (InsightFace) — diversidade no reel Contato
# ==================================================

@api.route('/ai/face/status', methods=['GET'])
def face_status_ep():
    from backend.services.face_tagger import get_status

    info = get_status()
    if current_can('clip') or current_can('system'):
        return ok({'face': info})
    return ok({
        'face': {
            'enabled': bool(info.get('enabled')),
            'ready': bool(info.get('ready')),
            'installed': bool(info.get('installed')),
            'index': {
                'clusters': (info.get('index') or {}).get('clusters', 0),
                'with_face': (info.get('index') or {}).get('with_face', 0),
                'missing': (info.get('index') or {}).get('missing', 0),
            },
        }
    })


@api.route('/ai/face/backfill', methods=['POST'])
@require_perm('clip')
def face_backfill_ep():
    import threading
    from backend.services.face_tagger import backfill_faces, is_enabled, is_installed
    from backend.models.database import face_stats

    if not is_enabled():
        return err('Faces desativado (FACE_ENABLED=false).', 400)
    if not is_installed():
        return err('InsightFace não instalado. Rode: pip install -r requirements-face.txt', 400)

    data = request.get_json(silent=True) or {}
    batch = safe_int(data.get('batch_size', 16), default=16, min_v=1, max_v=60)
    max_batches = safe_int(data.get('max_batches', 0), default=0, min_v=0, max_v=500)

    def _run():
        backfill_faces(batch_size=batch, max_batches=max_batches)

    threading.Thread(target=_run, daemon=True, name='face-backfill').start()
    return ok(
        {'index': face_stats(), 'started': True},
        'Backfill de rostos iniciado em background.',
    )


@api.route('/ai/face/warmup', methods=['POST'])
@require_perm('clip')
def face_warmup_ep():
    import threading
    from backend.services.face_tagger import warmup, is_enabled, is_installed

    if not is_enabled():
        return err('Faces desativado (FACE_ENABLED=false).', 400)
    if not is_installed():
        return err('InsightFace não instalado. Rode: pip install -r requirements-face.txt', 400)

    threading.Thread(target=warmup, daemon=True, name='face-warmup-api').start()
    return ok(msg='Carregamento InsightFace iniciado em background.')


@api.route('/ai/warmup', methods=['POST'])
@require_perm('clip')
def ai_warmup_all_ep():
    """Aquece CLIP + Faces num único request (Dev)."""
    import threading
    from backend.services.clip_tagger import warmup as clip_warmup, is_enabled as clip_on
    from backend.services.face_tagger import warmup as face_warmup, is_enabled as face_on, is_installed

    started = []

    if clip_on():
        threading.Thread(target=clip_warmup, args=(None,), daemon=True, name='clip-warmup-api').start()
        started.append('clip')
    if face_on() and is_installed():
        threading.Thread(target=face_warmup, daemon=True, name='face-warmup-api').start()
        started.append('face')

    if not started:
        return err('CLIP e Faces desativados ou indisponíveis.', 400)
    return ok({'started': started}, f"Warmup iniciado: {', '.join(started)}.")


@api.route('/contato/reel', methods=['GET'])
def contato_reel_ep():
    """Fotos para o marquee de Contato — 1 por cluster de rosto quando indexado."""
    from backend.models.database import pick_contato_reel_items, face_stats
    from backend.services.face_tagger import is_enabled, is_installed, is_ready

    limit = safe_int(request.args.get('limit', 24), default=24, min_v=6, max_v=48)
    raw = pick_contato_reel_items(limit=limit)
    items = []
    for it in raw:
        ann = annotate_storage(dict(it), thumb_size=480)
        items.append({
            'id': ann.get('id'),
            'thumb_url': ann.get('thumb_url'),
            'pasta': ann.get('pasta') or '',
            'nome': ann.get('nome') or '',
            'tags': ann.get('tags') or '',
            'face_cluster': it.get('face_cluster'),
            'key': it.get('key') or (f"id:{ann.get('id')}" if ann.get('id') else ''),
            'tipo': 'image',
        })
    stats = face_stats()
    return ok({
        'items': items,
        'face': {
            'enabled': is_enabled(),
            'installed': is_installed(),
            'ready': is_ready(),
            'clusters': stats.get('clusters', 0),
            'with_face': stats.get('with_face', 0),
            'missing': stats.get('missing', 0),
        },
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
    from backend.services.ai_pipeline import get_public_ai_summary
    from backend.services.clip_tagger import get_model_info
    from backend.models.database import embedding_stats, count_media, face_stats

    online, error_msg = drive_svc.drive_ping()
    clip = get_model_info()
    face = {}
    try:
        from backend.services.face_tagger import get_status
        face = get_status()
    except Exception:
        face = {'enabled': False, 'ready': False}
    try:
        media_total = count_media()
    except Exception:
        media_total = None

    return ok({
        'role': current_role(),
        'user': current_user(),
        'ai': get_public_ai_summary(),
        'flags': {
            'clip_enabled': _env_flag('CLIP_ENABLED', 'false'),
            'face_enabled': _env_flag('FACE_ENABLED', 'false'),
            'search_use_clip': _env_flag('SEARCH_USE_CLIP', '0'),
            'sync_fetch_exif': _env_flag('SYNC_FETCH_EXIF', '1'),
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
        'sync': {
            'running': _sync_running,
            'last': _sync_last,
        },
        'clip': clip,
        'face': face,
        'media_total': media_total,
        'index': {
            'clip': clip.get('index') or embedding_stats(),
            'face': face_stats(),
        },
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
