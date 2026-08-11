"""
search_engine.py — Motor de busca inteligente

Combina, num único ranqueamento:
  - correspondência textual (nome, descrição, tags, categoria, autor, pasta)
  - correspondência de nome/pasta (pessoa ou casal) com match parcial
  - filtros e boosts de data/ano/mês/horário extraídos da própria consulta

OpenCLIP NÃO roda no /api/search por padrão (SEARCH_USE_CLIP=0).
Face recognition NUNCA roda no search. Drive NUNCA no search.
"""
import os
import re
import time

from backend.models import database as db

# Cache de resultados — mais longo em produção (site no ar)
_RESULT_CACHE = {}
_RESULT_TTL = float(os.getenv('SEARCH_CACHE_TTL', '90' if os.getenv('FLASK_ENV') == 'production' else '20'))
_RESULT_MAX = int(os.getenv('SEARCH_CACHE_MAX', '128'))

# Pool home curado (evita recalcular pick_best a cada página)
_HOME_POOL_CACHE = {}
_HOME_POOL_TTL = float(os.getenv('HOME_POOL_CACHE_TTL', '120'))


def _result_cache_get(key):
    row = _RESULT_CACHE.get(key)
    if not row:
        return None
    if (time.time() - row['ts']) > _RESULT_TTL:
        _RESULT_CACHE.pop(key, None)
        return None
    return row['value']


def _result_cache_set(key, value):
    if len(_RESULT_CACHE) >= _RESULT_MAX:
        oldest = min(_RESULT_CACHE.items(), key=lambda kv: kv[1]['ts'])[0]
        _RESULT_CACHE.pop(oldest, None)
    _RESULT_CACHE[key] = {'ts': time.time(), 'value': value}
    return value


def clear_search_result_cache():
    _RESULT_CACHE.clear()
    _HOME_POOL_CACHE.clear()


def _home_pool_get(tipo):
    key = tipo or ''
    row = _HOME_POOL_CACHE.get(key)
    if not row:
        return None
    if (time.time() - row['ts']) > _HOME_POOL_TTL:
        _HOME_POOL_CACHE.pop(key, None)
        return None
    return row['pool']


def _home_pool_set(tipo, pool):
    _HOME_POOL_CACHE[tipo or ''] = {'ts': time.time(), 'pool': pool}
    return pool

MESES_PT = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9,
    'outubro': 10, 'novembro': 11, 'dezembro': 12,
}

TIPO_KEYWORDS = {
    'foto': 'image', 'fotos': 'image', 'imagem': 'image', 'imagens': 'image',
    'video': 'video', 'videos': 'video', 'reel': 'video', 'reels': 'video',
}

# Expansão de sinônimos PT → termos que batem em tags / CLIP
QUERY_EXPAND = {
    'noiva': ['noiva', 'casamento', 'vestido', 'véu', 'veu', 'buque'],
    'noivo': ['noivo', 'casamento', 'terno', 'alianca'],
    'casamento': ['casamento', 'noiva', 'noivo', 'cerimonia', 'igreja', 'festa'],
    'show': ['show', 'palco', 'banda', 'microfone', 'luzes de palco', 'publico'],
    'concerto': ['show', 'palco', 'orquestra', 'artista'],
    'retrato': ['retrato', 'close', 'olhar', 'estudio', 'luz natural'],
    'ensaio': ['ensaio', 'ensaios', 'externo', 'sessao', 'lifestyle'],
    'ensaios': ['ensaios', 'ensaio', 'externo', 'sessao'],
    'casal': ['casal', 'romantico', 'abraco', 'beijo', 'pre wedding'],
    'bebe': ['bebe', 'infantil', 'ternura'],
    'crianca': ['crianca', 'infantil', 'brinquedo', 'alegria'],
    'familia': ['familia', 'retrato familiar', 'grupo', 'geracoes'],
    'moto': ['moto', 'motocross', 'capacete', 'adrenalina', 'pista'],
    'motocross': ['motocross', 'moto', 'pista', 'poeira', 'acao'],
    'praia': ['praia', 'mar', 'areia', 'por do sol', 'externo'],
    'igreja': ['igreja', 'casamento', 'cerimonia', 'altar', 'fe'],
    'festa': ['festa', 'danca', 'alegria', 'multidao', 'celebracao'],
    'noite': ['noturno', 'neon', 'luzes de palco', 'dramatico'],
    'natureza': ['natureza', 'campo', 'floresta', 'rio', 'por do sol'],
    'urbano': ['urbano', 'cidade', 'rua', 'ponte', 'predio'],
    'estudio': ['estudio', 'retrato', 'ring light', 'fundo'],
    'danca': ['danca', 'festa', 'pista de danca', 'primeira danca'],
    'beijo': ['beijo', 'romantico', 'casal', 'amor'],
    'abraco': ['abraco', 'carinho', 'familia', 'casal'],
    'flores': ['flores', 'buque', 'jardim', 'natureza'],
    'lua': ['por do sol', 'noturno', 'romantico'],
    'dourado': ['luz dourada', 'por do sol', 'hora magica'],
    'bw': ['preto e branco', 'dramatico'],
    'pb': ['preto e branco', 'dramatico'],
}


def _strip_accents_lower(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def parse_query(query):
    """
    Extrai da consulta em linguagem natural:
      - ano (2023, 2024...)
      - data completa (15/03/2024, 15-03-2024)
      - mês/ano (03/2024) ou nome do mês (março, julho...)
      - horário (10:30, 18:42)
      - tipo de mídia (foto/vídeo/reel)
    Retorna (filters: dict, remaining_text: str) — remaining_text é o que
    sobra pra busca textual/semântica livre (nomes, tags, categoria etc).
    """
    filters = {}
    text = query

    # Data completa dd/mm/yyyy ou dd-mm-yyyy
    m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b', text)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        filters['dia'], filters['mes'], filters['ano'] = dia, mes, ano
        text = text.replace(m.group(0), ' ')

    # Mês/ano tipo 03/2024
    if 'mes' not in filters:
        m = re.search(r'\b(\d{1,2})[/\-](\d{4})\b', text)
        if m:
            filters['mes'], filters['ano'] = int(m.group(1)), int(m.group(2))
            text = text.replace(m.group(0), ' ')

    # Horário hh:mm
    m = re.search(r'\b([01]?\d|2[0-3]):([0-5]\d)\b', text)
    if m:
        filters['_hora'] = f"{int(m.group(1)):02d}:{m.group(2)}"
        text = text.replace(m.group(0), ' ')

    # Ano isolado (2015–2035, faixa razoável pra não confundir com outros números)
    if 'ano' not in filters:
        m = re.search(r'\b(20[1-3]\d)\b', text)
        if m:
            filters['ano'] = int(m.group(1))
            text = text.replace(m.group(0), ' ')

    # Nome do mês por extenso
    words = text.split()
    kept = []
    for w in words:
        w_norm = _strip_accents_lower(w.strip('.,!?'))
        if w_norm in MESES_PT and 'mes' not in filters:
            filters['mes'] = MESES_PT[w_norm]
            continue  # remove a palavra (não entra em 'kept')
        kept.append(w)
    text = ' '.join(kept)

    # Tipo de mídia (foto/vídeo/reel)
    words = text.split()
    kept = []
    for w in words:
        w_norm = _strip_accents_lower(w.strip('.,!?'))
        if w_norm in TIPO_KEYWORDS and 'tipo' not in filters:
            filters['tipo'] = TIPO_KEYWORDS[w_norm]
            continue
        kept.append(w)
    text = ' '.join(kept)

    remaining = re.sub(r'\s+', ' ', text).strip()
    # Expande sinônimos pra busca textual + semântica pegarem mais tags
    expanded = []
    for w in remaining.split():
        key = _strip_accents_lower(w.strip('.,!?'))
        expanded.append(w)
        for syn in QUERY_EXPAND.get(key, []):
            if syn not in expanded:
                expanded.append(syn)
    remaining_expanded = ' '.join(expanded) if expanded else remaining
    filters['_query_expanded'] = remaining_expanded
    return filters, remaining


def _cosine_sim(a, b):
    import numpy as np
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _text_terms(remaining_text):
    return [w for w in remaining_text.split() if len(w) >= 2]


def _name_match_score(pasta, terms, raw_query=''):
    """Match parcial de nome/pasta: cada termo que aparece na pasta soma pontos.
    'Amanda' bate parcialmente em 'Amanda Freitas'; 'Freitas' também bate."""
    if not pasta or not (terms or raw_query):
        return 0.0
    import html
    import re
    from difflib import SequenceMatcher

    pasta_clean = html.unescape(str(pasta or ''))
    pasta_norm = _strip_accents_lower(pasta_clean)
    pasta_norm = re.sub(r'[&/|+,]+', ' ', pasta_norm)
    pasta_norm = re.sub(r'\be\b', ' ', pasta_norm)
    pasta_norm = ' '.join(pasta_norm.split())
    pasta_words = set(pasta_norm.split())
    score = 0.0
    for t in terms or []:
        t_norm = _strip_accents_lower(t)
        if len(t_norm) < 2:
            continue
        if t_norm in pasta_words:
            score += 1.4
        elif any(pw.startswith(t_norm) for pw in pasta_words if len(t_norm) >= 3):
            score += 1.0
        elif t_norm in pasta_norm:
            score += 0.7
        else:
            for pw in pasta_words:
                if len(t_norm) >= 4 and len(pw) >= 4:
                    sim = SequenceMatcher(None, t_norm, pw).ratio()
                    if sim >= 0.78:
                        score += 0.8
                        break
    rq = _strip_accents_lower((raw_query or '').strip())
    if rq and len(rq) >= 2:
        if rq == pasta_norm:
            score += 5.0
        elif rq in pasta_norm:
            score += 3.2
        elif any(pw.startswith(rq) for pw in pasta_words if len(rq) >= 3):
            score += 2.2
    return score


def _tag_match_score(tags_str, terms, raw_query=''):
    """Pontua tags: frase exata da query > token exato > parcial."""
    if not tags_str:
        return 0.0
    tags = {
        _strip_accents_lower(t.strip())
        for t in str(tags_str).split(',')
        if t and t.strip()
    }
    if not tags:
        return 0.0

    score = 0.0
    rq = _strip_accents_lower((raw_query or '').strip())
    if rq and len(rq) >= 2 and rq in tags:
        score += 4.0

    for t in terms or []:
        tn = _strip_accents_lower(t)
        if len(tn) < 2:
            continue
        if tn in tags:
            score += 2.0
            continue
        # parcial só pra tags compostas ("por do sol") vs termo ("sol")
        for tag in tags:
            if len(tn) >= 3 and (tn in tag.split() or tn == tag):
                score += 1.0
                break
            if len(tn) >= 4 and (tn in tag or tag in tn):
                score += 0.7
                break
    return score


def _item_has_tag(tags_str, wanted):
    tags = {
        _strip_accents_lower(t.strip())
        for t in str(tags_str or '').split(',')
        if t and t.strip()
    }
    wanted_n = {_strip_accents_lower(t) for t in wanted if t}
    return bool(tags & wanted_n)


def _category_match_score(categoria, terms):
    if not categoria or not terms:
        return 0.0
    cat_norm = _strip_accents_lower(categoria)
    return sum(1.0 for t in terms if _strip_accents_lower(t) in cat_norm)


def _hora_match(item_hora, target_hora, tolerance_minutes=30):
    """Considera 'bateu' se o horário da mídia está dentro de +/- tolerância."""
    if not item_hora or not target_hora:
        return False
    try:
        h1, m1 = map(int, item_hora.split(':')[:2])
        h2, m2 = map(int, target_hora.split(':')[:2])
        diff = abs((h1 * 60 + m1) - (h2 * 60 + m2))
        return diff <= tolerance_minutes
    except Exception:
        return False


def _resolve_exact_tags(remaining_text, terms):
    """Se a consulta é (ou contém) tag(s) do catálogo, devolve-as normalizadas."""
    try:
        catalog = {
            _strip_accents_lower(t): t
            for t in (db.get_all_tags() or [])
            if t
        }
    except Exception:
        catalog = {}
    if not catalog:
        return []

    found = []
    rq = _strip_accents_lower((remaining_text or '').strip())
    if rq in catalog:
        found.append(rq)
    for t in terms or []:
        tn = _strip_accents_lower(t)
        if tn in catalog and tn not in found:
            found.append(tn)
    return found



def _expand_related_tags(exact_tags, terms):
    """Tag pedida + sinônimos (QUERY_EXPAND) pra achar mais itens etiquetados."""
    wanted = []
    seen = set()
    seeds = list(exact_tags or []) + list(terms or [])
    for t in seeds:
        tn = _strip_accents_lower(t)
        if not tn:
            continue
        bundle = [tn] + [_strip_accents_lower(s) for s in QUERY_EXPAND.get(tn, [])]
        if tn in ('casais', 'casal'):
            bundle += ['casal', 'casais', 'romantico', 'amor']
        if tn in ('shows', 'show'):
            bundle += ['show', 'shows', 'palco', 'banda', 'concerto']
        if tn in ('retratos', 'retrato'):
            bundle += ['retrato', 'retratos']
        if tn in ('familia',):
            bundle += ['familia', 'grupo']
        if tn in ('infantil', 'crianca', 'bebe'):
            bundle += ['infantil', 'crianca', 'bebe']
        if tn in ('motocross', 'moto', 'pista'):
            bundle += ['moto', 'motocross', 'pista']
        for s in bundle:
            if s and s not in seen:
                seen.add(s)
                wanted.append(s)
    return wanted


def _item_matches_tag_query(item, exact_tags, related_tags):
    """True se tags, categoria ou pasta/nome batem com a busca de tag."""
    if _item_has_tag(item.get('tags', ''), related_tags or exact_tags or []):
        return True
    cat = _strip_accents_lower(item.get('categoria', '') or '')
    pasta = _strip_accents_lower(item.get('pasta', '') or '')
    nome = _strip_accents_lower(item.get('nome', '') or '')
    for t in related_tags or exact_tags or []:
        if not t or len(t) < 2:
            continue
        if cat == t or t in cat:
            return True
        if len(t) >= 3 and (t in pasta or t in nome):
            return True
    return False


# Temas da grade Explorar → chaves FTS / qualidade
EXPLORE_THEME_KEYS = {
    'shows': ('show', 'shows', 'palco', 'banda', 'concerto', 'sonata'),
    'casamento': ('casamento', 'noiva', 'noivo', 'cerimonia', 'igreja', 'alianca', 'vestido'),
    'retratos': ('retrato', 'retratos', 'close', 'estudio', 'olhar'),
    'casais': ('casal', 'casais', 'romantico', 'amor', 'beijo', 'abraco'),
    'familia': ('familia', 'familiar', 'geracoes', 'batismo'),
    'infantil': ('infantil', 'crianca', 'bebe', 'aniversario'),
    'ensaios': ('ensaio', 'ensaios', 'externo', 'sessao', 'lifestyle'),
    'editorial': ('editorial', 'moda', 'fashion', 'conceito', 'artistico'),
    'show': ('show', 'shows', 'palco', 'banda'),
    'retrato': ('retrato', 'retratos', 'close', 'estudio'),
    'casal': ('casal', 'casais', 'romantico'),
    'noiva': ('noiva', 'casamento', 'vestido'),
    'ensaio': ('ensaio', 'ensaios', 'externo', 'sessao'),
    'pre wedding': ('casal', 'romantico', 'pre wedding'),
}


def _quality_boost(item):
    """Boost leve de qualidade (destaque/estrelas/face) — não sobrescreve relevância."""
    try:
        destaque = int(item.get('destaque') or 0)
        estrelas = int(item.get('estrelas') or 0)
    except (TypeError, ValueError):
        destaque, estrelas = 0, 0
    faces = 0
    try:
        faces = int(item.get('face_count') or 0)
    except (TypeError, ValueError):
        faces = 0
    return destaque * 8.0 + estrelas * 1.6 + min(faces, 3) * 0.4


def _sort_key_home(pair):
    score, item = pair
    return (score + _quality_boost(item), score, item.get('created_at', ''))


def _diversify_ranked(scored, start, per_page, max_per_pasta=3):
    """Mantém ordem de qualidade/relevância, mas limita fotos por pasta na página."""
    if not scored:
        return []
    need = start + per_page
    picked = []
    pasta_count = {}
    deferred = []
    for score, item in scored:
        pasta = (item.get('pasta') or '').strip().lower() or f"id:{item.get('id')}"
        if pasta_count.get(pasta, 0) >= max_per_pasta:
            deferred.append((score, item))
            continue
        pasta_count[pasta] = pasta_count.get(pasta, 0) + 1
        picked.append(item)
        if len(picked) >= need:
            break
    if len(picked) < need:
        for score, item in deferred:
            picked.append(item)
            if len(picked) >= need:
                break
    return picked[start:start + per_page]


def _resolve_theme_keys(terms, exact_tags, related_tags):
    bag = []
    for t in list(exact_tags or []) + list(related_tags or []) + list(terms or []):
        tn = _strip_accents_lower(t)
        # Preferir chaves da grade Explorar (sem poluir com sinônimos genéricos)
        if tn in EXPLORE_THEME_KEYS:
            return _expand_theme_key_list(EXPLORE_THEME_KEYS[tn])
        if tn in QUERY_EXPAND:
            return _expand_related_tags([tn], [tn])
        bag.append(tn)
    if len(bag) == 1:
        tn = bag[0]
        if tn in EXPLORE_THEME_KEYS:
            return _expand_theme_key_list(EXPLORE_THEME_KEYS[tn])
        if tn in QUERY_EXPAND:
            return _expand_related_tags([tn], [tn])
        return bag
    return None


def _expand_theme_key_list(keys):
    """Chaves da grade Explorar — sem QUERY_EXPAND (evita familia em infantil, etc.)."""
    out = []
    seen = set()
    for k in keys or ():
        kn = _strip_accents_lower(k)
        if not kn or len(kn) < 2 or kn in seen or ' ' in kn:
            continue
        seen.add(kn)
        out.append(kn)
    return out


def intelligent_search(query='', extra_filters=None, page=1, per_page=24, sort='home'):
    """
    Busca inteligente: SQLite/FTS + score em Python nos candidatos indexados.
    Nunca baixa Drive, nunca roda face, CLIP só se SEARCH_USE_CLIP=1.

    sort:
      - home   → browse ranqueado (destaque/estrelas/diversidade) — home da busca
      - recent → só created_at DESC
    """
    t_total0 = time.perf_counter()
    extra_filters = dict(extra_filters or {})
    sort_key = (sort or 'home').strip().lower()
    if sort_key not in ('home', 'recent', 'stars'):
        sort_key = 'home'
    cache_key = (
        (query or '').strip().lower(),
        tuple(sorted((k, str(v)) for k, v in extra_filters.items() if v)),
        int(page),
        int(per_page),
        sort_key,
    )
    cached = _result_cache_get(cache_key)
    if cached is not None:
        out = dict(cached)
        out['timing'] = {
            'db_ms': 0.0,
            'serialize_ms': 0.0,
            'total_ms': round((time.perf_counter() - t_total0) * 1000, 1),
            'cache': True,
        }
        return out

    parsed_filters, remaining_text = parse_query(query or '')

    target_hora = parsed_filters.pop('_hora', None)
    remaining_expanded = parsed_filters.pop('_query_expanded', remaining_text) or remaining_text

    hard_filters = {**parsed_filters, **{k: v for k, v in extra_filters.items() if v}}

    terms = _text_terms(remaining_text)
    terms_expanded = _text_terms(remaining_expanded)
    exact_tags = _resolve_exact_tags(remaining_text, terms)
    # Chaves do QUERY_EXPAND também viram “tag virtual” (ex.: show)
    if not exact_tags:
        for t in terms:
            tn = _strip_accents_lower(t)
            if tn in QUERY_EXPAND:
                exact_tags.append(tn)
    tag_mode = bool(exact_tags) and len(terms) <= 3
    related_tags = _expand_related_tags(exact_tags, terms) if tag_mode else []

    def _pack(page_items, total, mode, matched=None, related=None, db_ms=0.0, archive_total=None):
        t_ser0 = time.perf_counter()
        # Centro do rosto em lote (object-position no grid)
        try:
            need = [
                int(it['id']) for it in page_items
                if it.get('id') is not None and (
                    it.get('face_cx') is None or it.get('face_cy') is None
                )
            ]
            if need:
                foc = db.get_face_focus_many(need)
                for it in page_items:
                    try:
                        mid = int(it['id'])
                    except (TypeError, ValueError):
                        continue
                    f = foc.get(mid)
                    if f:
                        it['face_cx'] = f['cx']
                        it['face_cy'] = f['cy']
        except Exception:
            pass
        cards = [db.to_search_card(it, thumb_size=560) for it in page_items]
        serialize_ms = (time.perf_counter() - t_ser0) * 1000
        total_ms = (time.perf_counter() - t_total0) * 1000
        pages = max(1, (total + per_page - 1) // per_page) if total else 1
        # Evita página vazia se o cliente pedir além do pool
        safe_page = min(max(1, page), pages)
        payload = {
            'items': cards,
            'total': total,
            'page': safe_page,
            'per_page': per_page,
            'pages': pages,
            'archive_total': archive_total if archive_total is not None else total,
            'parsed_filters': {**parsed_filters, **({'hora': target_hora} if target_hora else {})},
            'mode': mode,
            'matched_tags': matched or [],
            'related_tags': (related or [])[:12],
            'timing': {
                'db_ms': round(db_ms, 1),
                'serialize_ms': round(serialize_ms, 1),
                'total_ms': round(total_ms, 1),
                'cache': False,
            },
        }
        return _result_cache_set(cache_key, payload)

    if not terms and not remaining_expanded.strip():
        t_db0 = time.perf_counter()
        archive_total = db.count_media(hard_filters)
        start = (page - 1) * per_page
        soft_only = not any(
            hard_filters.get(k) for k in ('categoria', 'autor', 'pasta', 'ano', 'mes', 'dia')
        )
        if sort_key == 'home' and soft_only:
            # Pool curado fixo — total/pages batem com o que existe de fato
            tipo_home = hard_filters.get('tipo') or 'image'
            pool = _home_pool_get(tipo_home)
            if pool is None:
                pool = _home_pool_set(
                    tipo_home,
                    db.pick_best_home_items(
                        limit=int(os.getenv('HOME_POOL_LIMIT', '360') or 360),
                        tipo=tipo_home,
                        max_per_pasta=int(os.getenv('HOME_POOL_MAX_PER_PASTA', '3') or 3),
                        diversify_faces=False,
                    ),
                )
            total = len(pool)
            pages = max(1, (total + per_page - 1) // per_page) if total else 1
            start = (min(max(1, page), pages) - 1) * per_page
            page_items = pool[start:start + per_page]
            mode = 'home'
            db_ms = (time.perf_counter() - t_db0) * 1000
            return _pack(
                page_items, total, mode, db_ms=db_ms, archive_total=archive_total
            )
        elif sort_key == 'home' and hard_filters.get('categoria'):
            cat = str(hard_filters.get('categoria') or '').strip().lower()
            keys = _expand_theme_key_list(EXPLORE_THEME_KEYS.get(cat, (cat,)))
            pool = db.pick_best_for_keys(
                keys,
                limit=max(start + per_page, int(os.getenv('THEME_POOL_LIMIT', '600') or 600)),
                tipo=hard_filters.get('tipo'),
                max_per_pasta=int(os.getenv('THEME_MAX_PER_PASTA', '24') or 24),
                diversify_faces=False,
            )
            total = len(pool)
            pages = max(1, (total + per_page - 1) // per_page) if total else 1
            start = (min(max(1, page), pages) - 1) * per_page
            page_items = pool[start:start + per_page]
            mode = 'home'
            db_ms = (time.perf_counter() - t_db0) * 1000
            return _pack(
                page_items, total, mode, db_ms=db_ms, archive_total=archive_total
            )
        else:
            page_items = db.get_candidates([], hard_filters, limit=per_page, offset=start)
            mode = 'browse'
            total = archive_total
        db_ms = (time.perf_counter() - t_db0) * 1000
        return _pack(page_items, total, mode, db_ms=db_ms, archive_total=archive_total)

    # Atalho: categoria/tema conhecido → melhores fotos do tema (sort=home)
    theme_keys = None
    if sort_key == 'home':
        theme_keys = _resolve_theme_keys(terms, exact_tags, related_tags)
    if theme_keys and sort_key == 'home' and not any(
        hard_filters.get(k) for k in ('autor', 'pasta', 'ano', 'mes', 'dia')
    ):
        t_db0 = time.perf_counter()
        start = (page - 1) * per_page
        pool = db.pick_best_for_keys(
            theme_keys,
            limit=max(start + per_page, int(os.getenv('THEME_POOL_LIMIT', '600') or 600)),
            tipo=hard_filters.get('tipo'),
            max_per_pasta=int(os.getenv('THEME_MAX_PER_PASTA', '24') or 24),
            diversify_faces=False,
        )
        db_ms = (time.perf_counter() - t_db0) * 1000
        if pool:
            total = len(pool)
            pages = max(1, (total + per_page - 1) // per_page)
            start = (min(max(1, page), pages) - 1) * per_page
            page_items = pool[start:start + per_page]
            return _pack(
                page_items,
                total,
                'home',
                matched=exact_tags or theme_keys[:3],
                related=related_tags or theme_keys,
                db_ms=db_ms,
            )

    by_id = {}
    t_db0 = time.perf_counter()

    # Prioridade: match direto no nome da pasta (pessoa/casal do Drive)
    pasta_items = db.get_by_pasta_query(
        terms or terms_expanded, remaining_text, hard_filters, limit=900
    )
    for item in pasta_items:
        by_id[item['id']] = item

    # Caminho rápido por NOME: pasta bateu → sem CLIP, sem varrer o acervo
    name_fast = (not tag_mode) and bool(pasta_items) and bool((remaining_text or '').strip())
    if name_fast:
        fts_terms = terms_expanded or terms
        if fts_terms:
            for item in db.get_candidates(fts_terms, hard_filters, limit=120):
                by_id.setdefault(item['id'], item)
        db_ms = (time.perf_counter() - t_db0) * 1000
        candidates = list(by_id.values())
        scored = []
        for item in candidates:
            name_score = _name_match_score(
                item.get('pasta', ''), terms_expanded or terms, remaining_text
            )
            score = name_score * (6.5 if name_score >= 1.0 else 3.5)
            for field in ('nome', 'descricao', 'autor', 'tags', 'categoria'):
                val = _strip_accents_lower(item.get(field, '') or '')
                for t in terms:
                    tt = _strip_accents_lower(t)
                    if len(tt) >= 3 and tt in val:
                        score += 0.5
            if score <= 0:
                continue
            scored.append((score, item))
        if sort_key == 'home':
            scored.sort(key=_sort_key_home, reverse=True)
            total = len(scored)
            start = (page - 1) * per_page
            page_items = _diversify_ranked(scored, start, per_page, max_per_pasta=3)
        else:
            scored.sort(key=lambda x: (x[0], x[1].get('created_at', '')), reverse=True)
            total = len(scored)
            start = (page - 1) * per_page
            end = start + per_page
            page_items = [item for _, item in scored[start:end]]
        return _pack(page_items, total, 'name', db_ms=db_ms)

    if tag_mode:
        for item in db.get_by_tags(related_tags or exact_tags, hard_filters, limit=900):
            by_id.setdefault(item['id'], item)
        for tag in (related_tags or exact_tags)[:6]:
            for item in db.get_candidates([], {**hard_filters, 'categoria': tag}, limit=400):
                by_id.setdefault(item['id'], item)
        # Tag com resultados: ranqueia rápido sem CLIP / sem varrer embeddings
        if by_id:
            db_ms = (time.perf_counter() - t_db0) * 1000
            candidates = list(by_id.values())
            scored = []
            for item in candidates:
                if not _item_matches_tag_query(item, exact_tags, related_tags):
                    name_score = _name_match_score(
                        item.get('pasta', ''), terms_expanded or terms, remaining_text
                    )
                    if name_score < 1.0:
                        continue
                tag_score = _tag_match_score(
                    item.get('tags', ''), terms_expanded or related_tags, remaining_text
                )
                if exact_tags and _item_has_tag(item.get('tags', ''), exact_tags):
                    tag_score += 6.0
                elif related_tags and _item_has_tag(item.get('tags', ''), related_tags):
                    tag_score += 3.5
                cat_norm = _strip_accents_lower(item.get('categoria', '') or '')
                if related_tags or exact_tags:
                    if cat_norm in (related_tags or exact_tags) or any(
                        cat_norm == t or (len(t) >= 3 and t in cat_norm)
                        for t in (related_tags or exact_tags)
                    ):
                        tag_score += 3.5
                score = tag_score * 3.5
                score += _name_match_score(
                    item.get('pasta', ''), terms_expanded or terms, remaining_text
                ) * 3.5
                if score <= 0:
                    continue
                scored.append((score, item))
            if sort_key == 'home':
                scored.sort(key=_sort_key_home, reverse=True)
                total = len(scored)
                start = (page - 1) * per_page
                page_items = _diversify_ranked(scored, start, per_page, max_per_pasta=3)
            else:
                scored.sort(key=lambda x: (x[0], x[1].get('created_at', '')), reverse=True)
                total = len(scored)
                start = (page - 1) * per_page
                end = start + per_page
                page_items = [item for _, item in scored[start:end]]
            return _pack(
                page_items, total, 'tag',
                matched=exact_tags, related=related_tags, db_ms=db_ms,
            )

    fts_terms = (terms_expanded or related_tags or terms) if tag_mode else (terms_expanded or terms)
    for item in db.get_candidates(fts_terms, hard_filters, limit=500):
        by_id.setdefault(item['id'], item)

    db_ms = (time.perf_counter() - t_db0) * 1000
    candidates = list(by_id.values())

    # CLIP NÃO entra no caminho crítico por padrão (CPU = resposta lenta).
    # Ative só com SEARCH_USE_CLIP=1 e modelo já aquecido (warmup).
    query_embedding = None
    clip_text = remaining_text.strip()
    pasta_hits = sum(
        1 for it in candidates
        if _name_match_score(it.get('pasta', ''), terms_expanded or terms, remaining_text) >= 1.0
    )
    use_clip = (
        os.getenv('SEARCH_USE_CLIP', '0').strip().lower() in ('1', 'true', 'yes', 'on')
        and bool(clip_text)
        and not tag_mode
        and pasta_hits < 1
        and len(candidates) < 40
    )
    if use_clip:
        try:
            from backend.services.clip_tagger import encode_text_query, get_model_info
            info = get_model_info()
            if info.get('loaded'):
                query_embedding = encode_text_query(clip_text)
        except Exception:
            query_embedding = None

    # Nunca amplia o funil com CLIP (isso + embeddings = lentidão)
    embeddings_cache = {}
    if query_embedding is not None:
        embeddings_cache = db.get_embeddings_for_ids([c['id'] for c in candidates])

    scored = []
    for item in candidates:
        score = 0.0
        has_exact_tag = bool(exact_tags) and _item_has_tag(item.get('tags', ''), exact_tags)
        has_related_tag = bool(related_tags) and _item_has_tag(item.get('tags', ''), related_tags)
        cat_norm = _strip_accents_lower(item.get('categoria', '') or '')
        has_cat = bool(related_tags or exact_tags) and (
            cat_norm in (related_tags or exact_tags)
            or any(cat_norm == t or (len(t) >= 3 and t in cat_norm) for t in (related_tags or exact_tags))
        )

        has_clip_only = False
        name_score = _name_match_score(item.get('pasta', ''), terms_expanded or terms, remaining_text)
        strong_name = name_score >= 1.0
        if tag_mode and not _item_matches_tag_query(item, exact_tags, related_tags) and not strong_name:
            if query_embedding is None:
                continue
            emb_blob = embeddings_cache.get(item['id']) if embeddings_cache else None
            if not emb_blob:
                continue
            has_clip_only = True

        tag_score = _tag_match_score(item.get('tags', ''), terms_expanded or related_tags, remaining_text)
        if has_exact_tag:
            tag_score += 6.0
        elif has_related_tag:
            tag_score += 3.5
        if has_cat:
            tag_score += 3.5
        score += tag_score * (3.5 if tag_mode else 2.4)

        # Nome da pasta (pessoa/casal) pesa mais que vibe/CLIP
        score += name_score * (6.5 if strong_name else 3.5)
        score += _category_match_score(item.get('categoria', ''), terms_expanded or related_tags) * 1.6

        for field in ('nome', 'descricao', 'autor'):
            val = _strip_accents_lower(item.get(field, '') or '')
            for t in (related_tags if tag_mode else terms):
                tt = _strip_accents_lower(t)
                if len(tt) >= 3 and tt in val:
                    score += 0.45

        if target_hora and _hora_match(item.get('hora_upload', ''), target_hora):
            score += 2.0

        if query_embedding is not None:
            import numpy as np
            emb_blob = embeddings_cache.get(item['id'])
            if emb_blob:
                img_vec = np.frombuffer(emb_blob, dtype='float32')
                sim = _cosine_sim(query_embedding, img_vec)
                if has_clip_only and sim < 0.22:
                    continue
                clip_w = 0.9 if tag_mode else 2.6
                if has_clip_only:
                    clip_w = 1.4
                score += max(sim, 0) * clip_w

        if not terms and not query_embedding:
            score += 1.0

        if score <= 0:
            continue
        scored.append((score, item))

    if sort_key == 'home':
        scored.sort(key=_sort_key_home, reverse=True)
        total = len(scored)
        start = (page - 1) * per_page
        page_items = _diversify_ranked(scored, start, per_page, max_per_pasta=3)
    else:
        scored.sort(key=lambda x: (x[0], x[1].get('created_at', '')), reverse=True)
        total = len(scored)
        start = (page - 1) * per_page
        end = start + per_page
        page_items = [item for _, item in scored[start:end]]

    return _pack(
        page_items, total, 'tag' if tag_mode else 'smart',
        matched=exact_tags, related=related_tags, db_ms=db_ms,
    )
