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
        r = _requests_session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
            timeout=20,
            allow_redirects=True
        )

        if "image" not in r.headers.get("Content-Type", ""):
            return None

        return Image.open(io.BytesIO(r.content)).convert("RGB")

    except Exception as e:
        print(f"[CLIP] Falha ao baixar imagem: {e}")
        return None

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

def get_model_info():
    installed = _check_installed()
    torch_ok = False
    try:
        _get_torch()
        torch_ok = True
    except ImportError:
        torch_ok = False
    return {
        'model':     DEFAULT_MODEL,
        'pretrained':DEFAULT_PRETRAIN,
        'enabled':   CLIP_ENABLED,
        'loaded':    _model_cache is not None,
        'loading':   _loading,
        'device':    _torch_device_label() if torch_ok else 'unavailable',
        'vocab_size':len(TAG_PT),
        'installed': installed and torch_ok,
        'torch_available': torch_ok,
    }

def _check_installed():
    try:
        import open_clip
        return True
    except ImportError:
        return False


def encode_image_embedding(image_url):
    """
    Gera o embedding (vetor CLIP) de uma imagem, pra salvar no banco
    (media_embeddings) e usar depois na busca semântica.
    Retorna bytes (float32) prontos pra sqlite BLOB, ou None se falhar
    (imagem inacessível, OpenCLIP não instalado etc — nunca levanta exceção).
    """
    try:
        import numpy as np
        torch = _get_torch()
        model, preprocess, tokenizer = _load_model()
        device = next(model.parameters()).device
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


def encode_text_query(text):
    """
    Gera o embedding (vetor CLIP) de um texto de busca.
    NÃO carrega o modelo sob demanda na busca — se ainda não estiver pronto,
    retorna None e a busca segue só com texto/FTS (sem atraso).
    """
    if not CLIP_ENABLED or _model_cache is None:
        return None
    try:
        import numpy as np
        torch = _get_torch()
        model, preprocess, tokenizer = _model_cache, _preprocess_cache, _tokenizer_cache
        device = next(model.parameters()).device
        txt_in = tokenizer([text]).to(device)
        with torch.no_grad():
            feat = model.encode_text(txt_in)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat.cpu().numpy().astype('float32')[0]
    except Exception as e:
        print(f"[CLIP] Falha ao gerar embedding de texto: {e}")
        return None

def warmup(thumb_urls=None):
    """
    Pré-carrega o modelo CLIP na memória. Se thumb_urls for passado
    (lista de URLs de thumbnails), faz um encode de teste na primeira
    imagem disponível — garante que o pipeline completo (download +
    preprocess + encode) já rodou uma vez antes do primeiro request
    real do usuário, evitando que a primeira busca fique lenta.
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
                if image is None:
                    continue
                device = next(model.parameters()).device
                img_in = preprocess(image).unsqueeze(0).to(device)
                with torch.no_grad():
                    model.encode_image(img_in)
                break  # uma imagem já é suficiente pra aquecer o pipeline

        return True

    except Exception as e:
        print(f"[CLIP] Warmup falhou: {e}")
        return False
