"""database.py — SQLite com FTS5 full-text search"""
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "media.db")

_READ_CACHE = {
    "stats": {"value": None, "ts": 0.0, "ttl": 12.0},
    "tags": {"value": None, "ts": 0.0, "ttl": 45.0},
    "pastas": {"value": None, "ts": 0.0, "ttl": 45.0},
}


def _cache_get(key):
    row = _READ_CACHE.get(key)
    if not row:
        return None
    if (time.time() - row["ts"]) <= row["ttl"]:
        return row["value"]
    return None


def _cache_set(key, value):
    row = _READ_CACHE.get(key)
    if row is None:
        return value
    row["value"] = value
    row["ts"] = time.time()
    return value


def invalidate_read_caches():
    for row in _READ_CACHE.values():
        row["value"] = None
        row["ts"] = 0.0

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-20000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def _add_missing_columns(conn):
    """Adiciona colunas novas em 'media' se ainda não existirem. Roda ANTES do FTS5,
    porque os triggers do FTS referenciam essas colunas (new.pasta etc)."""
    c = conn.cursor()
    new_columns = {
        'pasta':        "TEXT DEFAULT ''",   # nome da pessoa/casal, vindo da pasta do Drive
        'camera':       "TEXT DEFAULT ''",   # cameraMake + cameraModel (EXIF, quando disponível)
        'localizacao':  "TEXT DEFAULT ''",   # lat,lng (EXIF, quando disponível)
    }
    changed = False
    for col, decl in new_columns.items():
        if not _column_exists(conn, 'media', col):
            c.execute(f"ALTER TABLE media ADD COLUMN {col} {decl}")
            print(f"[DB] Migração: coluna '{col}' adicionada em media.")
            changed = True
    conn.commit()
    return changed


def _migrate_fts(conn):
    """Garante que o índice FTS inclui 'pasta'. Roda DEPOIS das colunas existirem."""
    c = conn.cursor()
    fts_cols = [r[1] for r in conn.execute("PRAGMA table_info(media_fts)").fetchall()]
    if 'pasta' not in fts_cols:
        c.executescript("""
            DROP TABLE IF EXISTS media_fts;
            DROP TRIGGER IF EXISTS media_ai;
            DROP TRIGGER IF EXISTS media_ad;
            DROP TRIGGER IF EXISTS media_au;
        """)
        conn.commit()
        _create_fts(conn)
        # Repopula o índice com os dados já existentes na tabela media
        c.execute("""
            INSERT INTO media_fts(rowid,nome,descricao,tags,categoria,autor,pasta)
            SELECT id,nome,descricao,tags,categoria,autor,pasta FROM media
        """)
        conn.commit()
        print("[DB] Migração: índice de busca (FTS) recriado incluindo 'pasta'.")


def _create_fts(conn):
    c = conn.cursor()
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
            nome, descricao, tags, categoria, autor, pasta,
            content='media', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    for trigger in [
        """CREATE TRIGGER IF NOT EXISTS media_ai AFTER INSERT ON media BEGIN
            INSERT INTO media_fts(rowid,nome,descricao,tags,categoria,autor,pasta)
            VALUES(new.id,new.nome,new.descricao,new.tags,new.categoria,new.autor,new.pasta);END""",
        """CREATE TRIGGER IF NOT EXISTS media_ad AFTER DELETE ON media BEGIN
            INSERT INTO media_fts(media_fts,rowid,nome,descricao,tags,categoria,autor,pasta)
            VALUES('delete',old.id,old.nome,old.descricao,old.tags,old.categoria,old.autor,old.pasta);END""",
        """CREATE TRIGGER IF NOT EXISTS media_au AFTER UPDATE ON media BEGIN
            INSERT INTO media_fts(media_fts,rowid,nome,descricao,tags,categoria,autor,pasta)
            VALUES('delete',old.id,old.nome,old.descricao,old.tags,old.categoria,old.autor,old.pasta);
            INSERT INTO media_fts(rowid,nome,descricao,tags,categoria,autor,pasta)
            VALUES(new.id,new.nome,new.descricao,new.tags,new.categoria,new.autor,new.pasta);END""",
    ]:
        c.execute(trigger)
    conn.commit()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id      TEXT UNIQUE NOT NULL,
            nome          TEXT NOT NULL,
            descricao     TEXT DEFAULT '',
            tags          TEXT DEFAULT '',
            tipo          TEXT NOT NULL,
            categoria     TEXT DEFAULT '',
            autor         TEXT DEFAULT '',
            data_upload   TEXT NOT NULL,
            hora_upload   TEXT NOT NULL,
            ano           INTEGER NOT NULL,
            mes           INTEGER NOT NULL,
            dia           INTEGER NOT NULL,
            tamanho       INTEGER DEFAULT 0,
            mime_type     TEXT DEFAULT '',
            thumb_url     TEXT DEFAULT '',
            drive_link    TEXT DEFAULT '',
            visualizacoes INTEGER DEFAULT 0,
            downloads     INTEGER DEFAULT 0,
            estrelas      INTEGER DEFAULT 0,
            destaque      INTEGER DEFAULT 0,
            cor           TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    _add_missing_columns(conn)
    _create_fts(conn)
    c.execute("""
        CREATE TABLE IF NOT EXISTS media_embeddings (
            media_id   INTEGER PRIMARY KEY,
            embedding  BLOB NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        )
    """)

    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_tipo      ON media(tipo)",
        "CREATE INDEX IF NOT EXISTS idx_categoria ON media(categoria)",
        "CREATE INDEX IF NOT EXISTS idx_ano       ON media(ano)",
        "CREATE INDEX IF NOT EXISTS idx_created   ON media(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_views     ON media(visualizacoes DESC)",
        "CREATE INDEX IF NOT EXISTS idx_destaque  ON media(destaque DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pasta     ON media(pasta)",
    ]:
        c.execute(idx)
    conn.commit()

    # Migração incremental do índice FTS — roda sempre, só aplica o que faltar
    _migrate_fts(conn)

    conn.close()
    print(f"[DB] Banco inicializado em {DB_PATH}")

def insert_media(data):
    now = datetime.now()
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        INSERT INTO media(drive_id,nome,descricao,tags,tipo,categoria,autor,
            data_upload,hora_upload,ano,mes,dia,tamanho,mime_type,thumb_url,drive_link,
            pasta,camera,localizacao)
        VALUES(:drive_id,:nome,:descricao,:tags,:tipo,:categoria,:autor,
            :data_upload,:hora_upload,:ano,:mes,:dia,:tamanho,:mime_type,:thumb_url,:drive_link,
            :pasta,:camera,:localizacao)
    """, {
        'drive_id':   data['drive_id'],
        'nome':       data.get('nome',''),
        'descricao':  data.get('descricao',''),
        'tags':       data.get('tags',''),
        'tipo':       data.get('tipo','image'),
        'categoria':  data.get('categoria',''),
        'autor':      data.get('autor',''),
        'data_upload':data.get('data_upload', now.strftime('%Y-%m-%d')),
        'hora_upload':data.get('hora_upload', now.strftime('%H:%M:%S')),
        'ano':        data.get('ano', now.year),
        'mes':        data.get('mes', now.month),
        'dia':        data.get('dia', now.day),
        'tamanho':    data.get('tamanho', 0),
        'mime_type':  data.get('mime_type',''),
        'thumb_url':  data.get('thumb_url',''),
        'drive_link': data.get('drive_link',''),
        'pasta':      data.get('pasta',''),
        'camera':     data.get('camera',''),
        'localizacao':data.get('localizacao',''),
    })
    new_id = c.lastrowid
    invalidate_read_caches()
    conn.commit(); conn.close()
    return new_id

def get_media(media_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_media(limit=None):
    conn = get_conn()
    sql = "SELECT * FROM media WHERE tipo='image' AND thumb_url!='' ORDER BY created_at DESC"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_media_embedding(media_id, embedding_blob):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO media_embeddings(media_id, embedding, updated_at) VALUES(?,?,datetime('now'))",
        (media_id, embedding_blob),
    )
    conn.commit(); conn.close()


def load_media_embedding(media_id):
    conn = get_conn()
    row = conn.execute("SELECT embedding FROM media_embeddings WHERE media_id=?", (media_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_all_embeddings():
    """Retorna {media_id: embedding_blob} pra todos os itens que já têm embedding salvo."""
    conn = get_conn()
    rows = conn.execute("SELECT media_id, embedding FROM media_embeddings").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def get_embeddings_for_ids(media_ids):
    """Carrega só os embeddings dos IDs pedidos — bem mais leve que get_all_embeddings."""
    ids = [int(i) for i in (media_ids or []) if i is not None]
    if not ids:
        return {}
    conn = get_conn()
    out = {}
    # SQLite limita variáveis — fatia em blocos
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        placeholders = ','.join('?' * len(chunk))
        rows = conn.execute(
            f"SELECT media_id, embedding FROM media_embeddings WHERE media_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for r in rows:
            out[r[0]] = r[1]
    conn.close()
    return out


def embedding_stats():
    conn = get_conn()
    total_img = conn.execute("SELECT COUNT(*) FROM media WHERE tipo='image'").fetchone()[0]
    with_emb = conn.execute("SELECT COUNT(*) FROM media_embeddings").fetchone()[0]
    conn.close()
    return {
        'images': total_img,
        'embeddings': with_emb,
        'missing': max(0, total_img - with_emb),
    }


def get_media_missing_embeddings(limit=40):
    """Imagens sem vetor CLIP — usadas no backfill em background."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT m.id, m.drive_id, m.thumb_url, m.nome, m.tipo
        FROM media m
        LEFT JOIN media_embeddings e ON e.media_id = m.id
        WHERE m.tipo='image' AND e.media_id IS NULL
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_pasta_by_drive_id(drive_id, pasta):
    """Atualiza pasta (e invalida cache) sem recriar a mídia."""
    pasta = (pasta or '').strip()
    if not drive_id:
        return False
    conn = get_conn()
    cur = conn.execute(
        "UPDATE media SET pasta=? WHERE drive_id=? AND (pasta IS NULL OR pasta='' OR pasta!=?)",
        (pasta, drive_id, pasta),
    )
    changed = cur.rowcount > 0
    if changed:
        invalidate_read_caches()
    conn.commit()
    conn.close()
    return changed


def annotate_storage(item: dict, thumb_size: int = 280) -> dict:
    out = dict(item)
    did = str(out.get('drive_id') or '')
    out['storage'] = 'local' if did.startswith('local:') else 'drive'
    mid = out.get('id')
    if mid and did.startswith('local:'):
        uid = did.split(':', 1)[1]
        out['thumb_url'] = f'/api/local/{uid}'
    elif mid:
        # Proxy com cache em disco — sz menor = grid mais rápido
        out['thumb_url'] = f'/api/media/{int(mid)}/thumb?sz={int(thumb_size) or 280}'
    return out


def update_media(media_id, data):
    allowed = {'nome','descricao','tags','categoria','autor','thumb_url','drive_link',
               'estrelas','destaque','cor','pasta','camera','localizacao'}
    fields = {k:v for k,v in data.items() if k in allowed}
    if not fields: return False
    set_clause = ', '.join(f"{k}=?" for k in fields)
    conn = get_conn()
    conn.execute(f"UPDATE media SET {set_clause} WHERE id=?", list(fields.values())+[media_id])
    invalidate_read_caches()
    conn.commit(); conn.close()
    return True

def delete_media(media_id):
    conn = get_conn()
    r = conn.execute("DELETE FROM media WHERE id=?", (media_id,))
    if r.rowcount > 0:
        invalidate_read_caches()
    conn.commit(); conn.close()
    return r.rowcount > 0

def increment_views(media_id):
    conn = get_conn()
    conn.execute("UPDATE media SET visualizacoes=visualizacoes+1 WHERE id=?", (media_id,))
    invalidate_read_caches()
    conn.commit(); conn.close()

def increment_downloads(media_id):
    conn = get_conn()
    conn.execute("UPDATE media SET downloads=downloads+1 WHERE id=?", (media_id,))
    invalidate_read_caches()
    conn.commit(); conn.close()

def search_media(query='', filters=None, page=1, per_page=24, sort='relevance'):
    """
    Busca básica (usada pela listagem do admin e como fallback).
    A busca inteligente de verdade (texto + tags + pasta + data/hora +
    OpenCLIP com ranqueamento) fica em backend/services/search_engine.py.
    """
    filters = filters or {}
    offset  = (page-1)*per_page
    conn    = get_conn()
    params  = []
    where   = []

    used_fts = False
    if query and query.strip():
        from backend.utils.security import build_fts_match
        terms = build_fts_match(query.strip().split())
        if terms:
            base_sql = "SELECT m.*, fts.rank AS _rank FROM media_fts fts JOIN media m ON m.id=fts.rowid WHERE media_fts MATCH ?"
            params.append(terms)
            used_fts = True
        else:
            base_sql = "SELECT m.*, 0 AS _rank FROM media m WHERE 1=1"
    else:
        base_sql = "SELECT m.*, 0 AS _rank FROM media m WHERE 1=1"

    for col in ('tipo','categoria','autor','pasta'):
        if filters.get(col):
            where.append(f"m.{col}=?"); params.append(filters[col])
    for col in ('ano','mes','dia'):
        if filters.get(col):
            where.append(f"m.{col}=?"); params.append(int(filters[col]))

    storage = (filters.get('storage') or '').strip().lower()
    if storage == 'local':
        where.append("m.drive_id LIKE 'local:%'")
    elif storage == 'drive':
        where.append("(m.drive_id IS NULL OR m.drive_id NOT LIKE 'local:%')")

    where_sql = ('AND '+' AND '.join(where)) if where else ''
    order_map = {
        'relevance':  'fts.rank' if used_fts else 'm.created_at DESC',
        'date_desc':  'm.created_at DESC',
        'date_asc':   'm.created_at ASC',
        'views':      'm.visualizacoes DESC',
        'downloads':  'm.downloads DESC',
        'name':       'm.nome ASC',
        'stars':      'm.estrelas DESC',
    }
    order_sql = order_map.get(sort, 'm.created_at DESC')
    full_sql  = f"{base_sql} {where_sql} ORDER BY {order_sql}"

    total = conn.execute(f"SELECT COUNT(*) FROM ({full_sql})", params).fetchone()[0]
    rows  = conn.execute(f"{full_sql} LIMIT ? OFFSET ?", params+[per_page, offset]).fetchall()
    conn.close()

    items = []
    for r in rows:
        item = dict(r)
        did = str(item.get('drive_id') or '')
        item['storage'] = 'local' if did.startswith('local:') else 'drive'
        items.append(item)

    return {
        'items':    items,
        'total':    total,
        'page':     page,
        'per_page': per_page,
        'pages':    max(1,(total+per_page-1)//per_page),
    }


def get_candidates(text_terms, hard_filters, limit=500):
    """Candidatos pra busca inteligente (texto + filtros)."""
    conn = get_conn()
    params = []
    where = []

    if text_terms:
        from backend.utils.security import build_fts_match
        match_expr = build_fts_match(text_terms)
        if not match_expr:
            base_sql = "SELECT m.* FROM media m WHERE 1=1"
        else:
            base_sql = "SELECT m.* FROM media_fts fts JOIN media m ON m.id=fts.rowid WHERE media_fts MATCH ?"
            params.append(match_expr)
    else:
        base_sql = "SELECT m.* FROM media m WHERE 1=1"

    for col in ('tipo','categoria','autor','pasta'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?"); params.append(hard_filters[col])
    for col in ('ano','mes','dia'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?"); params.append(int(hard_filters[col]))

    where_sql = ('AND '+' AND '.join(where)) if where else ''
    order_sql = "ORDER BY m.created_at DESC" if not text_terms else ""
    lim = int(limit) if limit else 500
    full_sql = f"{base_sql} {where_sql} {order_sql} LIMIT {lim}"

    rows = conn.execute(full_sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_media(hard_filters=None):
    hard_filters = hard_filters or {}
    conn = get_conn()
    params = []
    where = []
    for col in ('tipo','categoria','autor','pasta'):
        if hard_filters.get(col):
            where.append(f"{col}=?"); params.append(hard_filters[col])
    for col in ('ano','mes','dia'):
        if hard_filters.get(col):
            where.append(f"{col}=?"); params.append(int(hard_filters[col]))
    where_sql = ('WHERE '+' AND '.join(where)) if where else ''
    n = conn.execute(f"SELECT COUNT(*) FROM media {where_sql}", params).fetchone()[0]
    conn.close()
    return int(n)


def get_stats():
    cached = _cache_get("stats")
    if cached is not None:
        return cached
    conn = get_conn()
    s = {}
    s['total_imagens'] = conn.execute("SELECT COUNT(*) FROM media WHERE tipo='image'").fetchone()[0]
    s['total_videos']  = conn.execute("SELECT COUNT(*) FROM media WHERE tipo='video'").fetchone()[0]
    s['espaco_total']  = conn.execute("SELECT COALESCE(SUM(tamanho),0) FROM media").fetchone()[0]
    s['ultimos_uploads']  = [dict(r) for r in conn.execute("SELECT * FROM media ORDER BY created_at DESC LIMIT 8").fetchall()]
    s['mais_vistos']      = [dict(r) for r in conn.execute("SELECT * FROM media WHERE visualizacoes>0 ORDER BY visualizacoes DESC LIMIT 6").fetchall()]
    s['mais_baixados']    = [dict(r) for r in conn.execute("SELECT * FROM media WHERE downloads>0 ORDER BY downloads DESC LIMIT 6").fetchall()]
    s['por_categoria']    = [dict(r) for r in conn.execute("SELECT categoria, COUNT(*) as total FROM media GROUP BY categoria ORDER BY total DESC").fetchall()]
    s['destaques']        = [dict(r) for r in conn.execute("SELECT * FROM media WHERE destaque=1 ORDER BY created_at DESC LIMIT 6").fetchall()]
    conn.close()
    return _cache_set("stats", s)

def get_all_tags():
    cached = _cache_get("tags")
    if cached is not None:
        return cached
    conn = get_conn()
    rows = conn.execute("SELECT tags FROM media WHERE tags!=''").fetchall()
    conn.close()
    tags = set()
    for row in rows:
        for t in row[0].split(','):
            t = t.strip()
            if t: tags.add(t)
    return _cache_set("tags", sorted(tags))


def get_by_tags(tag_terms, hard_filters=None, limit=2000):
    """Itens cuja coluna tags contém pelo menos uma das tags (match de token).

    Aceita CSV com ou sem espaço após vírgula: "noiva,vestido" / "noiva, vestido".
    """
    hard_filters = hard_filters or {}
    tags = [str(t or '').strip().lower() for t in (tag_terms or []) if str(t or '').strip()]
    if not tags:
        return []

    conn = get_conn()
    params = []
    where = []
    tag_clauses = []
    # Normaliza espaços ao redor de vírgulas pra comparar tokens
    norm = (
        "TRIM(REPLACE(REPLACE(REPLACE(LOWER(COALESCE(m.tags,'')), ', ', ','), ' ,', ','), ',,', ','))"
    )
    for t in tags:
        tag_clauses.append(
            "("
            f"{norm} = ? OR "
            f"{norm} LIKE ? OR "
            f"{norm} LIKE ? OR "
            f"{norm} LIKE ?"
            ")"
        )
        params.extend([
            t,
            f"{t},%",
            f"%,{t}",
            f"%,{t},%",
        ])
    where.append('(' + ' OR '.join(tag_clauses) + ')')

    for col in ('tipo', 'categoria', 'autor', 'pasta'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?")
            params.append(hard_filters[col])
    for col in ('ano', 'mes', 'dia'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?")
            params.append(int(hard_filters[col]))

    storage = (hard_filters.get('storage') or '').strip().lower()
    if storage == 'local':
        where.append("m.drive_id LIKE 'local:%'")
    elif storage == 'drive':
        where.append("(m.drive_id IS NULL OR m.drive_id NOT LIKE 'local:%')")

    lim = max(1, min(int(limit or 2000), 5000))
    sql = f"SELECT m.* FROM media m WHERE {' AND '.join(where)} ORDER BY m.created_at DESC LIMIT {lim}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_pastas():
    """Lista de pastas (pessoas/casais) distintas já sincronizadas — usada em autocomplete."""
    cached = _cache_get("pastas")
    if cached is not None:
        return cached
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT pasta FROM media WHERE pasta!='' ORDER BY pasta").fetchall()
    conn.close()
    return _cache_set("pastas", [r[0] for r in rows])


def list_media(page=1, per_page=24, tipo=None, categoria=None, storage=None, sort='date_desc'):
    return search_media(
        query='',
        page=page,
        per_page=per_page,
        filters={'tipo': tipo, 'categoria': categoria, 'storage': storage},
        sort=sort or 'date_desc',
    )
