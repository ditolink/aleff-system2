"""
search_engine.py — Motor de busca inteligente

Combina, num único ranqueamento:
  - correspondência textual (nome, descrição, tags, categoria, autor, pasta)
  - correspondência de nome/pasta (pessoa ou casal) com match parcial
  - filtros e boosts de data/ano/mês/horário extraídos da própria consulta
  - similaridade semântica via embeddings do OpenCLIP (quando disponíveis)

Não substitui o FTS5 (usado como um dos sinais de candidatos), só combina
tudo com uma pontuação final em Python, que é mais flexível pra esse tipo
de regra de negócio do que dá pra expressar direto em SQL.
"""
import re
import numpy as np
from datetime import datetime

from backend.models import database as db

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
    'ensaio': ['retrato', 'casal', 'externo', 'pre wedding'],
    'casal': ['casal', 'romantico', 'abraco', 'beijo', 'pre wedding'],
    'bebe': ['bebe', 'infantil', 'familia', 'ternura'],
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
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _text_terms(remaining_text):
    return [w for w in remaining_text.split() if len(w) >= 2]


def _name_match_score(pasta, terms, raw_query=''):
    """Match parcial de nome/pasta: cada termo que aparece na pasta soma pontos.
    'Amanda' bate parcialmente em 'Amanda Freitas'; 'Freitas' também bate."""
    if not pasta or not terms:
        return 0.0
    from difflib import SequenceMatcher
    pasta_norm = _strip_accents_lower(pasta)
    pasta_words = set(pasta_norm.split())
    score = 0.0
    for t in terms:
        t_norm = _strip_accents_lower(t)
        if t_norm in pasta_words:
            score += 1.0
        elif t_norm in pasta_norm:
            score += 0.5
        else:
            # tolerância pequena para nome digitado com erro
            for pw in pasta_words:
                if len(t_norm) >= 4 and len(pw) >= 4:
                    sim = SequenceMatcher(None, t_norm, pw).ratio()
                    if sim >= 0.78:
                        score += 0.7
                        break
    rq = _strip_accents_lower(raw_query.strip()) if raw_query else ''
    if rq and len(rq) >= 3 and rq in pasta_norm:
        score += 2.5
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
            bundle += ['show', 'shows', 'evento', 'guitarra', 'palco']
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


def intelligent_search(query='', extra_filters=None, page=1, per_page=24):
    """
    Busca inteligente combinando:
      texto (FTS: nome/descricao/tags/categoria/autor/pasta)
      + match de nome/pasta parcial
      + match de tags/categoria  ← prioridade alta
      + filtros/boost de data/ano/mês/hora extraídos da consulta
      + similaridade semântica via OpenCLIP (apoio, não sobrescreve tags)
    """
    extra_filters = dict(extra_filters or {})
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

    if not terms and not remaining_expanded.strip():
        total = db.count_media(hard_filters)
        start = (page - 1) * per_page
        window = db.get_candidates([], hard_filters, limit=start + per_page)
        page_items = window[start:start + per_page]
        return {
            'items': page_items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': max(1, (total + per_page - 1) // per_page) if total else 1,
            'parsed_filters': {**parsed_filters, **({'hora': target_hora} if target_hora else {})},
            'mode': 'browse',
        }

    by_id = {}

    if tag_mode:
        for item in db.get_by_tags(related_tags or exact_tags, hard_filters, limit=2500):
            by_id[item['id']] = item
        for tag in related_tags or exact_tags:
            for item in db.get_candidates([], {**hard_filters, 'categoria': tag}, limit=800):
                by_id.setdefault(item['id'], item)

    fts_terms = (terms_expanded or related_tags or terms) if tag_mode else (terms_expanded or terms)
    for item in db.get_candidates(fts_terms, hard_filters, limit=800):
        by_id.setdefault(item['id'], item)

    candidates = list(by_id.values())

    query_embedding = None
    clip_text = remaining_text.strip()
    if clip_text and not tag_mode:
        try:
            from backend.services.clip_tagger import encode_text_query
            query_embedding = encode_text_query(clip_text)
        except Exception:
            query_embedding = None
    elif clip_text and tag_mode and len(candidates) < 40:
        try:
            from backend.services.clip_tagger import encode_text_query
            query_embedding = encode_text_query(clip_text)
        except Exception:
            query_embedding = None

    if query_embedding is not None and len(candidates) < 80:
        broad = db.get_candidates([], hard_filters, limit=800)
        for item in broad:
            by_id.setdefault(item['id'], item)
        candidates = list(by_id.values())

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
        if tag_mode and not _item_matches_tag_query(item, exact_tags, related_tags):
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

        score += _name_match_score(item.get('pasta', ''), terms_expanded or terms, remaining_text) * 3.0
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

    scored.sort(key=lambda x: (x[0], x[1].get('created_at', '')), reverse=True)

    total = len(scored)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = [item for _, item in scored[start:end]]

    return {
        'items': page_items,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page) if total else 1,
        'parsed_filters': {**parsed_filters, **({'hora': target_hora} if target_hora else {})},
        'mode': 'tag' if tag_mode else 'smart',
        'matched_tags': exact_tags,
        'related_tags': related_tags[:12] if related_tags else [],
    }
