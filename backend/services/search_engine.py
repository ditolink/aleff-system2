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


def _tag_match_score(tags_str, terms):
    if not tags_str or not terms:
        return 0.0
    tags = set(_strip_accents_lower(t.strip()) for t in tags_str.split(','))
    score = 0.0
    for t in terms:
        if _strip_accents_lower(t) in tags:
            score += 1.0
    return score


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


def intelligent_search(query='', extra_filters=None, page=1, per_page=24):
    """
    Busca inteligente combinando:
      texto (FTS: nome/descricao/tags/categoria/autor/pasta)
      + match de nome/pasta parcial
      + match de tags/categoria
      + filtros/boost de data/ano/mês/hora extraídos da consulta
      + similaridade semântica via OpenCLIP (se houver embeddings salvos)

    extra_filters: filtros vindos da UI (tipo, categoria, autor, ano, mes, dia)
    que se somam ao que for extraído da própria query.
    """
    extra_filters = dict(extra_filters or {})
    parsed_filters, remaining_text = parse_query(query or '')

    target_hora = parsed_filters.pop('_hora', None)
    remaining_expanded = parsed_filters.pop('_query_expanded', remaining_text) or remaining_text

    # Filtros da UI têm prioridade se o usuário escolheu explicitamente
    hard_filters = {**parsed_filters, **{k: v for k, v in extra_filters.items() if v}}

    terms = _text_terms(remaining_text)
    terms_expanded = _text_terms(remaining_expanded)

    candidates = db.get_candidates(terms_expanded or terms, hard_filters)

    # Se não sobrou nada (nem termo nem candidato via filtro), pega os mais recentes
    if not terms and not hard_filters:
        candidates = db.get_candidates([], {})

    # Embedding da consulta pra busca semântica (best-effort — se OpenCLIP
    # não estiver instalado ou não houver texto livre, isso é pulado)
    query_embedding = None
    clip_text = remaining_expanded.strip() or remaining_text.strip()
    if clip_text:
        try:
            from backend.services.clip_tagger import encode_text_query
            query_embedding = encode_text_query(clip_text)
        except Exception:
            query_embedding = None

    # Se a parte textual vier fraca, abre mais o funil para a semântica do CLIP ranquear.
    if query_embedding is not None and len(candidates) < 80:
        broad = db.get_candidates([], hard_filters)
        by_id = {item['id']: item for item in candidates}
        for item in broad:
            by_id[item['id']] = item
        candidates = list(by_id.values())

    embeddings_cache = db.get_all_embeddings() if query_embedding is not None else {}

    scored = []
    for item in candidates:
        score = 0.0

        # 1) match de nome/pasta (pessoa ou casal) — o sinal mais importante
        score += _name_match_score(item.get('pasta', ''), terms, remaining_text) * 3.4

        # 2) match de tags (com sinônimos expandidos)
        score += _tag_match_score(item.get('tags', ''), terms_expanded) * 2.0

        # 3) match de categoria
        score += _category_match_score(item.get('categoria', ''), terms_expanded) * 1.5

        # 4) match textual geral (nome do arquivo, descrição, autor)
        for field in ('nome', 'descricao', 'autor'):
            val = _strip_accents_lower(item.get(field, '') or '')
            for t in terms:
                if _strip_accents_lower(t) in val:
                    score += 0.5

        # 5) boost de horário aproximado
        if target_hora and _hora_match(item.get('hora_upload', ''), target_hora):
            score += 2.0

        # 6) similaridade semântica via OpenCLIP
        if query_embedding is not None:
            emb_blob = embeddings_cache.get(item['id'])
            if emb_blob:
                img_vec = np.frombuffer(emb_blob, dtype='float32')
                sim = _cosine_sim(query_embedding, img_vec)
                score += max(sim, 0) * 4.0  # semântica pesa bastante quando disponível

        # Se não há nenhum termo de texto (busca só por data/tipo/ano), todo
        # candidato que passou pelos filtros rígidos já é relevante
        if not terms and not query_embedding:
            score += 1.0

        scored.append((score, item))

    # Ordena por score desc, e em empate por mais recente
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
        'pages': max(1, (total + per_page - 1) // per_page),
        'parsed_filters': {**parsed_filters, **({'hora': target_hora} if target_hora else {})},
    }
