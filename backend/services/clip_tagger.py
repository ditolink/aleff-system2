"""
clip_tagger.py — Gerador de tags com OpenCLIP (visão computacional local)
Analisa imagens do Drive e sugere tags automaticamente, sem API externa.

Instalar: pip install open-clip-torch pillow requests
"""
import os, io, requests
from PIL import Image

DEFAULT_MODEL    = os.getenv('CLIP_MODEL',    'ViT-B-32')
DEFAULT_PRETRAIN = os.getenv('CLIP_PRETRAIN', 'laion400m_e32')
# false = site rápido (só texto/FTS). true = OpenCLIP local (precisa RAM ~2GB+)
CLIP_ENABLED = os.getenv('CLIP_ENABLED', 'true').lower().strip() in ('1', 'true', 'yes', 'on')

_model_cache = _preprocess_cache = _tokenizer_cache = None
_torch_cache = None
_torch_unavailable = False
_loading = False

# Vocabulário amplo PT ↔ EN (200+). TAG_PT[i] corresponde a TAG_EN[i].
TAG_PT = [
    # categorias principais
    "show", "casamento", "retrato", "infantil", "casal", "familia", "esporte", "editorial",
    "natureza", "urbano", "evento", "palco", "noturno", "externo", "estudio", "praia",
    "campo", "igreja", "jardim", "piscina", "estrada", "sorriso", "romantico", "grupo",
    "crianca", "artista", "noiva", "danca", "abraco", "beijo", "luz natural", "por do sol",
    "dramatico", "preto e branco", "cores", "bokeh", "alegria", "emocao", "amor",
    "adrenalina", "elegancia", "moto", "capacete", "flores", "velas", "bolo", "vestido",
    "multidao", "microfone", "guitarra", "bateria", "fogos", "festa",
    # pessoas / momentos
    "noivo", "padrinhos", "madrinha", "pai", "mae", "bebe", "adolescente", "idoso",
    "homem", "mulher", "amigos", "irmaos", "gemeos", "modelo", "cantor", "banda",
    "dj", "baterista", "guitarrista", "vocalista", "publico", "plateia",
    # casamento detalhado
    "alianca", "buque", "véu", "veu", "terno", "cerimonia", "altar", "entrada da noiva",
    "primeira danca", "brinde", "champagne", "mesa decorada", "convite", "alianças",
    "pre wedding", "trash the dress", "lua de mel", "casamento na praia", "casamento no campo",
    "casamento na igreja", "recepcao", "buffet", "pista de danca", "buquê",
    # shows / musica
    "luzes de palco", "smoke", "fumaca", "laser", "spotlight", "backstage", "camarim",
    "amplificador", "baixo", "teclado", "piano", "violao", "saxofone", "trompete",
    "show ao vivo", "festival", "rock", "sertanejo", "gospel", "rap", "hip hop",
    "eletronica", "samba", "pagode", "mpb", "coral", "orquestra",
    # retrato / luz
    "close", "meio corpo", "corpo inteiro", "perfil", "olhar", "olho", "cabelo",
    "maquiagem", "barba", "oculos", "chapeu", "bone", "joia", "brinco", "colar",
    "luz dourada", "hora magica", "contraluz", "sombra", "neon", "flash", "ring light",
    "janela", "reflexo", "espelho", "fumaca artistica", "chuva", "neblina",
    # lugares
    "cidade", "predio", "ponte", "rua", "calcada", "parque", "floresta", "montanha",
    "rio", "lago", "cachoeira", "mar", "onda", "areia", "pedra", "trilha",
    "fazenda", "sitio", "chacara", "quintal", "varanda", "sacada", "cobertura",
    "restaurante", "bar", "hotel", "sala", "quarto", "cozinha", "banheiro",
    "escola", "igreja antiga", "catedral", "capela", "cemiterio", "estadio",
    # esportes / acao
    "corrida", "futebol", "basquete", "natacao", "surf", "skate", "bike", "ciclismo",
    "motocross", "trilha de moto", "pista", "velocidade", "salto", "queda",
    "treino", "academia", "musculacao", "yoga", "meditacao",
    # infantil / familia
    "brinquedo", "balao", "festa infantil", "aniversario", "bolo infantil", "fantasia",
    "halloween", "natal", "pascoa", "cha de bebe", "cha revelacao", "gestante",
    "gravidez", "familia reunida", "retrato familiar", "geracoes",
    # estilo / mood
    "minimalista", "vintage", "retro", "moderno", "luxo", "casual", "street",
    "fashion", "moda", "comercial", "publicidade", "produto", "food", "comida",
    "cafe", "vinho", "doce", "bolo de casamento",
    # tecnico / cinema
    "cinematico", "filme", "making of", "bastidores", "ensaios", "sessao fotografica",
    "macro", "wide angle", "teleobjetiva", "profundidade de campo", "movimento",
    "congelado", "longa exposicao", "timelapse", "slow motion", "drone", "aereo",
    # emocao
    "risada", "choro", "lagrima", "surpresa", "ternura", "paixao", "carinho",
    "oracao", "fe", "celebracao", "vitoria", "concentracao", "serenidade",
]

TAG_EN = [
    "live concert", "wedding", "portrait", "children", "couple", "family", "sports", "editorial",
    "nature", "urban", "event", "stage lights", "night", "outdoor", "studio", "beach",
    "field", "church", "garden", "swimming pool", "road", "smiling", "romantic", "group",
    "child", "artist", "bride", "dance", "hug", "kiss", "golden light", "sunset",
    "dramatic", "black white", "colorful", "bokeh", "joy", "emotion", "love",
    "adrenaline", "elegance", "motorcycle", "helmet", "flowers", "candles", "cake", "dress",
    "crowd", "microphone", "guitar", "drums", "fireworks", "party",
    "groom", "groomsmen", "bridesmaid", "father", "mother", "baby", "teenager", "elderly",
    "man", "woman", "friends", "siblings", "twins", "model", "singer", "band",
    "dj", "drummer", "guitarist", "lead singer", "audience", "crowd watching",
    "wedding ring", "bridal bouquet", "wedding veil", "wedding veil", "suit", "ceremony", "altar", "bride entrance",
    "first dance", "toast", "champagne", "decorated table", "invitation", "wedding rings",
    "pre wedding", "trash the dress", "honeymoon", "beach wedding", "countryside wedding",
    "church wedding", "reception", "buffet", "dance floor", "bridal bouquet",
    "stage lighting", "smoke", "stage smoke", "laser lights", "spotlight", "backstage", "dressing room",
    "amplifier", "bass guitar", "keyboard", "piano", "acoustic guitar", "saxophone", "trumpet",
    "live show", "music festival", "rock concert", "country music", "gospel music", "rap performance", "hip hop",
    "electronic music", "samba", "pagode", "brazilian music", "choir", "orchestra",
    "close up", "half body portrait", "full body portrait", "profile", "gaze", "eye", "hair",
    "makeup", "beard", "glasses", "hat", "cap", "jewelry", "earring", "necklace",
    "golden hour", "magic hour", "backlight", "shadow", "neon lights", "camera flash", "ring light",
    "window light", "reflection", "mirror", "artistic smoke", "rain", "fog",
    "city", "building", "bridge", "street", "sidewalk", "park", "forest", "mountain",
    "river", "lake", "waterfall", "ocean", "wave", "sand", "rock", "hiking trail",
    "farm", "country house", "ranch", "backyard", "balcony", "terrace", "rooftop",
    "restaurant", "bar", "hotel", "living room", "bedroom", "kitchen", "bathroom",
    "school", "old church", "cathedral", "chapel", "cemetery", "stadium",
    "running", "soccer", "basketball", "swimming", "surfing", "skateboarding", "bicycle", "cycling",
    "motocross", "dirt bike trail", "race track", "speed", "jump", "fall",
    "training", "gym", "bodybuilding", "yoga", "meditation",
    "toy", "balloon", "kids party", "birthday", "kids cake", "costume",
    "halloween", "christmas", "easter", "baby shower", "gender reveal", "pregnant woman",
    "pregnancy", "family reunion", "family portrait", "generations",
    "minimalist", "vintage", "retro", "modern", "luxury", "casual", "street style",
    "fashion", "fashion editorial", "commercial", "advertising", "product photo", "food photography", "food",
    "coffee", "wine", "dessert", "wedding cake",
    "cinematic", "film still", "making of", "behind the scenes", "photo shoot", "photography session",
    "macro", "wide angle", "telephoto", "depth of field", "motion",
    "frozen action", "long exposure", "timelapse", "slow motion", "drone", "aerial view",
    "laughter", "crying", "tear", "surprise", "tenderness", "passion", "affection",
    "prayer", "faith", "celebration", "victory", "focus", "serenity",
]

assert len(TAG_PT) == len(TAG_EN), f"TAG mismatch: {len(TAG_PT)} vs {len(TAG_EN)}"


_requests_session = requests.Session()


def _get_torch():
    """Importa torch só quando necessário — evita derrubar o servidor se o Windows bloquear."""
    global _torch_cache, _torch_unavailable
    if _torch_unavailable:
        raise ImportError('PyTorch indisponível neste ambiente (bloqueio ou não instalado).')
    if _torch_cache is None:
        try:
            import torch
            _torch_cache = torch
        except Exception as e:
            _torch_unavailable = True
            raise ImportError(str(e)) from e
    return _torch_cache


def _torch_device_label():
    try:
        t = _get_torch()
        return 'cuda' if t.cuda.is_available() else 'cpu'
    except ImportError:
        return 'unavailable'


def is_enabled():
    return CLIP_ENABLED


def is_ready():
    return CLIP_ENABLED and _model_cache is not None


def _load_model():
    global _model_cache, _preprocess_cache, _tokenizer_cache, _loading
    if not CLIP_ENABLED:
        raise RuntimeError('OpenCLIP desativado (CLIP_ENABLED=false)')
    if _model_cache:
        return _model_cache, _preprocess_cache, _tokenizer_cache
    if _loading:
        raise RuntimeError('OpenCLIP ainda carregando')
    _loading = True
    try:
        torch = _get_torch()
        import open_clip
        print(f"[CLIP] Carregando {DEFAULT_MODEL}/{DEFAULT_PRETRAIN} — primeira vez demora ~2 min...")
        model, _, preprocess = open_clip.create_model_and_transforms(DEFAULT_MODEL, pretrained=DEFAULT_PRETRAIN)
        tokenizer = open_clip.get_tokenizer(DEFAULT_MODEL)
        model.eval()
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        model  = model.to(device)
        _model_cache = model; _preprocess_cache = preprocess; _tokenizer_cache = tokenizer
        print(f"[CLIP] Modelo pronto! Dispositivo: {device.upper()}")
        return model, preprocess, tokenizer
    finally:
        _loading = False

def _fetch_image(url):
    try:
        # Caminho local (upload fallback)
        if url and not str(url).lower().startswith(('http://', 'https://')):
            from pathlib import Path
            p = Path(url)
            if p.is_file():
                return Image.open(p).convert("RGB")
            return None

        # URL relativa do próprio servidor
        s = str(url or '')
        if s.startswith('/api/local/'):
            from backend.services.drive import resolve_local_path
            uid = s.rstrip('/').split('/')[-1]
            p = resolve_local_path(f'local:{uid}')
            if p and p.is_file():
                return Image.open(p).convert("RGB")
            return None

        if s.startswith('/api/media/') and s.rstrip('/').endswith('/thumb'):
            # Resolve via banco + Drive SA (mesmo pipeline do proxy)
            try:
                mid = int(s.split('/')[3])
                return _fetch_image_for_media_id(mid)
            except Exception:
                return None

        r = _requests_session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
            allow_redirects=True,
        )
        if r.status_code != 200 or not r.content:
            return None

        ctype = r.headers.get("Content-Type", "")
        # Drive às vezes devolve text/html de login; aceita magic bytes de imagem
        is_img = (
            "image" in ctype
            or r.content[:3] == b"\xff\xd8"
            or r.content[:8] == b"\x89PNG\r\n\x1a\n"
            or r.content[:4] == b"RIFF"
        )
        if not is_img:
            return None

        return Image.open(io.BytesIO(r.content)).convert("RGB")

    except Exception as e:
        print(f"[CLIP] Falha ao baixar imagem: {e}")
        return None


def _fetch_image_for_media_id(media_id):
    """Carrega imagem via Drive SA / arquivo local — não depende de thumb pública."""
    try:
        from backend.models.database import get_media
        from backend.services.drive import fetch_thumbnail_bytes, resolve_local_path, is_local_media_id
        item = get_media(int(media_id))
        if not item:
            return None
        did = item.get('drive_id') or ''
        if is_local_media_id(did):
            p = resolve_local_path(did)
            if p and p.is_file():
                return Image.open(p).convert('RGB')
            return None
        raw, _mime = fetch_thumbnail_bytes(did, size=512)
        return Image.open(io.BytesIO(raw)).convert('RGB')
    except Exception as e:
        print(f"[CLIP] Falha ao carregar mídia {media_id}: {e}")
        return None


def encode_image_embedding(image_url, media_id=None):
    """
    Gera o embedding (vetor CLIP) de uma imagem, pra salvar no banco
    (media_embeddings) e usar depois na busca semântica.
    Retorna bytes (float32) prontos pra sqlite BLOB, ou None se falhar.
    """
    try:
        import numpy as np
        torch = _get_torch()
        model, preprocess, tokenizer = _load_model()
        device = next(model.parameters()).device
        image = None
        if media_id is not None:
            image = _fetch_image_for_media_id(media_id)
        if image is None:
            image = _fetch_image(image_url)
        if image is None:
            return None
        img_in = preprocess(image).unsqueeze(0).to(device)
        with torch.no_grad():
            feat = model.encode_image(img_in)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat.cpu().numpy().astype('float32').tobytes()
    except Exception as e:
        print(f"[CLIP] Falha ao gerar embedding de imagem: {e}")
        return None


_text_emb_cache = {}
_TEXT_CACHE_MAX = 128


def encode_text_query(text):
    """
    Embedding CLIP do texto. Instantâneo se o modelo ainda não estiver pronto
    (retorna None → busca segue só com FTS). Com modelo quente, usa cache.
    """
    if not CLIP_ENABLED or _model_cache is None:
        return None
    key = (text or '').strip().lower()
    if not key:
        return None
    cached = _text_emb_cache.get(key)
    if cached is not None:
        return cached
    try:
        import numpy as np
        torch = _get_torch()
        model, preprocess, tokenizer = _model_cache, _preprocess_cache, _tokenizer_cache
        device = next(model.parameters()).device
        txt_in = tokenizer([text.strip()]).to(device)
        with torch.no_grad():
            feat = model.encode_text(txt_in)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        vec = feat.cpu().numpy().astype('float32')[0]
        if len(_text_emb_cache) >= _TEXT_CACHE_MAX:
            # descarta o mais antigo
            try:
                _text_emb_cache.pop(next(iter(_text_emb_cache)))
            except Exception:
                _text_emb_cache.clear()
        _text_emb_cache[key] = vec
        return vec
    except Exception as e:
        print(f"[CLIP] Falha ao gerar embedding de texto: {e}")
        return None


_backfill_running = False


def backfill_embeddings(batch_size=24, max_batches=0, pause_sec=0.05):
    """
    Indexa imagens antigas sem embedding. Roda em background após warmup.
    max_batches=0 → continua até acabar (ou falhar tudo).
    """
    global _backfill_running
    if not CLIP_ENABLED:
        return {'done': 0, 'failed': 0, 'skipped': True}
    if _backfill_running:
        return {'done': 0, 'failed': 0, 'skipped': True, 'reason': 'already_running'}
    _backfill_running = True
    done = failed = 0
    try:
        from backend.models.database import (
            get_media_missing_embeddings,
            save_media_embedding,
            embedding_stats,
        )
        import time
        batches = 0
        while True:
            missing = get_media_missing_embeddings(limit=batch_size)
            if not missing:
                break
            for item in missing:
                mid = item['id']
                try:
                    emb = encode_image_embedding(item.get('thumb_url'), media_id=mid)
                    if emb:
                        save_media_embedding(mid, emb)
                        done += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    print(f"[CLIP] Backfill item {mid} falhou: {e}")
                if pause_sec:
                    time.sleep(pause_sec)
            batches += 1
            stats = embedding_stats()
            print(f"[CLIP] Backfill: +{done} ok, {failed} falhas | índice {stats['embeddings']}/{stats['images']}")
            if max_batches and batches >= max_batches:
                break
            # evita loop infinito se todas as do lote falham
            if failed >= done + len(missing) and done == 0:
                print("[CLIP] Backfill parou — nenhuma imagem acessível neste lote.")
                break
        return {'done': done, 'failed': failed, 'stats': embedding_stats()}
    except Exception as e:
        print(f"[CLIP] Backfill abortado: {e}")
        return {'done': done, 'failed': failed, 'error': str(e)}
    finally:
        _backfill_running = False


def warmup(thumb_urls=None):
    """
    Pré-carrega o modelo CLIP na memória. Se thumb_urls for passado
    (lista de URLs de thumbnails), faz um encode de teste na primeira
    imagem disponível — garante que o pipeline completo já rodou.
    """
    if not CLIP_ENABLED:
        print("[CLIP] Desativado (CLIP_ENABLED=false) — busca só por texto.")
        return
    try:
        torch = _get_torch()
        model, preprocess, tokenizer = _load_model()

        if thumb_urls:
            for url in thumb_urls:
                image = _fetch_image(url)
                if image is None and str(url).startswith('/api/media/'):
                    try:
                        mid = int(str(url).split('/')[3])
                        image = _fetch_image_for_media_id(mid)
                    except Exception:
                        image = None
                if image is None:
                    continue
                device = next(model.parameters()).device
                img_in = preprocess(image).unsqueeze(0).to(device)
                with torch.no_grad():
                    model.encode_image(img_in)
                break

        return True

    except Exception as e:
        print(f"[CLIP] Warmup falhou: {e}")
        return False


def generate_tags(image_url, top_k=12, threshold=0.15):
    """
    Gera tags automáticas para uma imagem.
    Args:
        image_url: URL pública da thumbnail do Drive
        top_k:     máximo de tags a retornar
        threshold: similaridade mínima (0-1)
    Returns:
        dict com 'tags', 'scores', 'status', 'message', 'model'
    """
    if not CLIP_ENABLED:
        return {'tags':[],'scores':{},'status':'error','message':'OpenCLIP desativado.','model':DEFAULT_MODEL}
    try:
        torch = _get_torch()
        import open_clip
        model, preprocess, tokenizer = _load_model()
        device = next(model.parameters()).device
        image  = _fetch_image(image_url)
        if not image and str(image_url).startswith('/api/media/'):
            try:
                image = _fetch_image_for_media_id(int(str(image_url).split('/')[3]))
            except Exception:
                image = None
        if not image:
            return {'tags':[],'scores':{},'status':'error','message':'Não foi possível baixar a imagem.','model':f'{DEFAULT_MODEL}/{DEFAULT_PRETRAIN}'}
        img_in  = preprocess(image).unsqueeze(0).to(device)
        txt_in  = tokenizer(TAG_EN).to(device)
        with torch.no_grad():
            img_f = model.encode_image(img_in)
            txt_f = model.encode_text(txt_in)
            img_f /= img_f.norm(dim=-1, keepdim=True)
            txt_f /= txt_f.norm(dim=-1, keepdim=True)
            sims  = (100.0 * img_f @ txt_f.T).softmax(dim=-1)[0].cpu().numpy()
        indexed = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
        tags, scores = [], {}
        for idx, score in indexed:
            if len(tags) >= top_k: break
            if score < threshold:  break
            tag = TAG_PT[idx]
            if tag not in scores:
                tags.append(tag)
                scores[tag] = round(float(score), 4)
        return {'tags':tags,'scores':scores,'status':'ok',
                'message':f'{len(tags)} tags geradas com OpenCLIP',
                'model':f'{DEFAULT_MODEL}/{DEFAULT_PRETRAIN}'}
    except ImportError as e:
        return {'tags':[],'scores':{},'status':'error',
                'message': str(e) if 'PyTorch' in str(e) else 'OpenCLIP não instalado. Rode: pip install open-clip-torch',
                'model':DEFAULT_MODEL}
    except Exception as e:
        print(f"[CLIP] Erro: {e}")
        return {'tags':[],'scores':{},'status':'error','message':str(e),'model':DEFAULT_MODEL}

_info_cache = {'at': 0.0, 'result': None}
_INFO_TTL_SEC = 12.0

def get_model_info():
    import time
    now = time.monotonic()
    if _info_cache['result'] is not None and (now - _info_cache['at']) < _INFO_TTL_SEC:
        return _info_cache['result']

    installed = _check_installed()
    torch_ok = False
    try:
        _get_torch()
        torch_ok = True
    except ImportError:
        torch_ok = False
    info = {
        'model':     DEFAULT_MODEL,
        'pretrained':DEFAULT_PRETRAIN,
        'enabled':   CLIP_ENABLED,
        'loaded':    _model_cache is not None,
        'loading':   _loading,
        'device':    _torch_device_label() if torch_ok else 'unavailable',
        'vocab_size':len(TAG_PT),
        'installed': installed and torch_ok,
        'torch_available': torch_ok,
        'backfill_running': _backfill_running,
    }
    try:
        from backend.models.database import embedding_stats
        info['index'] = embedding_stats()
    except Exception:
        info['index'] = {'images': 0, 'embeddings': 0, 'missing': 0}
    _info_cache['result'] = info
    _info_cache['at'] = time.monotonic()
    return info

def _check_installed():
    try:
        import open_clip
        return True
    except ImportError:
        return False
