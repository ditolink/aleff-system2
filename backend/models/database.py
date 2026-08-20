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
    try:
        from backend.services.search_engine import clear_search_result_cache
        clear_search_result_cache()
    except Exception:
        pass

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
        'pasta':          "TEXT DEFAULT ''",   # nome da pessoa/casal, vindo da pasta do Drive
        'camera':         "TEXT DEFAULT ''",   # cameraMake + cameraModel (EXIF, quando disponível)
        'localizacao':    "TEXT DEFAULT ''",   # lat,lng (EXIF, quando disponível)
        'drive_modified': "TEXT DEFAULT ''",   # modifiedTime do Drive — skip sync se igual
        'clip_status':    "TEXT DEFAULT 'pending'",  # pending|processing|completed|failed
        'face_status':    "TEXT DEFAULT 'pending'",
    }
    changed = False
    for col, decl in new_columns.items():
        if not _column_exists(conn, 'media', col):
            c.execute(f"ALTER TABLE media ADD COLUMN {col} {decl}")
            print(f"[DB] Migração: coluna '{col}' adicionada em media.")
            changed = True
    # Backfill status a partir dos índices já existentes (sem reprocessar AI)
    # (feito em init_db após criar media_embeddings / media_faces)
    conn.commit()
    return changed


def _backfill_ai_status(conn):
    """Marca completed onde já há embedding/rosto; vídeos não ficam pending."""
    if not _column_exists(conn, 'media', 'clip_status'):
        return
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE media SET clip_status='completed'
            WHERE id IN (SELECT media_id FROM media_embeddings)
              AND COALESCE(clip_status,'') IN ('', 'pending')
            """
        )
        c.execute(
            """
            UPDATE media SET face_status='completed'
            WHERE id IN (SELECT media_id FROM media_faces)
              AND COALESCE(face_status,'') IN ('', 'pending')
            """
        )
        c.execute(
            """
            UPDATE media SET clip_status='completed', face_status='completed'
            WHERE tipo!='image'
              AND COALESCE(clip_status,'pending')='pending'
            """
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] backfill ai_status: {e}")


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
    c.execute("""
        CREATE TABLE IF NOT EXISTS media_faces (
            media_id    INTEGER PRIMARY KEY,
            embedding   BLOB,
            cluster_id  INTEGER,
            face_count  INTEGER DEFAULT 0,
            det_score   REAL DEFAULT 0,
            face_cx     REAL,
            face_cy     REAL,
            updated_at  TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        )
    """)
    # Migração: centro do rosto (0–1) pra enquadramento de thumb/capa
    for col, decl in (('face_cx', 'REAL'), ('face_cy', 'REAL')):
        if not _column_exists(conn, 'media_faces', col):
            c.execute(f'ALTER TABLE media_faces ADD COLUMN {col} {decl}')
            print(f"[DB] Migração: coluna '{col}' adicionada em media_faces.")

    c.execute("""
        CREATE TABLE IF NOT EXISTS media_curation_scores (
            media_id INTEGER PRIMARY KEY,
            content_hash TEXT,
            aesthetic_score REAL DEFAULT 0,
            face_score REAL DEFAULT 0,
            composition_score REAL DEFAULT 0,
            lighting_score REAL DEFAULT 0,
            color_score REAL DEFAULT 0,
            technical_score REAL DEFAULT 0,
            moment_score REAL DEFAULT 0,
            wow_score REAL DEFAULT 0,
            context_score REAL DEFAULT 0,
            final_score REAL DEFAULT 0,
            portfolio_master REAL DEFAULT 0,
            symmetry_score REAL DEFAULT 0,
            meta_json TEXT DEFAULT '{}',
            analyzed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
        )
    """)
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_tipo      ON media(tipo)",
        "CREATE INDEX IF NOT EXISTS idx_curation_final ON media_curation_scores(final_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_curation_wow ON media_curation_scores(wow_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_curation_master ON media_curation_scores(portfolio_master DESC)",
        "CREATE INDEX IF NOT EXISTS idx_categoria ON media(categoria)",
        "CREATE INDEX IF NOT EXISTS idx_ano       ON media(ano)",
        "CREATE INDEX IF NOT EXISTS idx_created   ON media(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_views     ON media(visualizacoes DESC)",
        "CREATE INDEX IF NOT EXISTS idx_destaque  ON media(destaque DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pasta     ON media(pasta)",
        "CREATE INDEX IF NOT EXISTS idx_face_cluster ON media_faces(cluster_id)",
        "CREATE INDEX IF NOT EXISTS idx_face_count   ON media_faces(face_count)",
        # Compostos: filtram + ORDER BY sem TEMP B-TREE (EXPLAIN)
        "CREATE INDEX IF NOT EXISTS idx_pasta_created ON media(pasta, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_tipo_created  ON media(tipo, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_ano_mes       ON media(ano, mes)",
        "CREATE INDEX IF NOT EXISTS idx_clip_status   ON media(clip_status)",
        "CREATE INDEX IF NOT EXISTS idx_face_status   ON media(face_status)",
        "CREATE INDEX IF NOT EXISTS idx_drive_modified ON media(drive_id, drive_modified)",
        "CREATE INDEX IF NOT EXISTS idx_estrelas ON media(estrelas DESC)",
        "CREATE INDEX IF NOT EXISTS idx_autor ON media(autor)",
    ]:
        c.execute(idx)
    conn.commit()

    # Migração incremental do índice FTS — roda sempre, só aplica o que faltar
    _migrate_fts(conn)
    _backfill_ai_status(conn)

    conn.close()
    try:
        cleanup_pasta_html_entities()
    except Exception as e:
        print(f"[DB] cleanup pastas: {e}")
    print(f"[DB] Banco inicializado em {DB_PATH}")

def insert_media(data, *, invalidate_cache=True):
    now = datetime.now()
    conn = get_conn(); c = conn.cursor()
    clip_st = data.get('clip_status') or ('pending' if data.get('tipo', 'image') == 'image' else 'completed')
    face_st = data.get('face_status') or ('pending' if data.get('tipo', 'image') == 'image' else 'completed')
    c.execute("""
        INSERT INTO media(drive_id,nome,descricao,tags,tipo,categoria,autor,
            data_upload,hora_upload,ano,mes,dia,tamanho,mime_type,thumb_url,drive_link,
            pasta,camera,localizacao,drive_modified,clip_status,face_status)
        VALUES(:drive_id,:nome,:descricao,:tags,:tipo,:categoria,:autor,
            :data_upload,:hora_upload,:ano,:mes,:dia,:tamanho,:mime_type,:thumb_url,:drive_link,
            :pasta,:camera,:localizacao,:drive_modified,:clip_status,:face_status)
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
        'pasta':      normalize_pasta_name(data.get('pasta','')),
        'camera':     data.get('camera',''),
        'localizacao':data.get('localizacao',''),
        'drive_modified': data.get('drive_modified', '') or '',
        'clip_status': clip_st,
        'face_status': face_st,
    })
    new_id = c.lastrowid
    if invalidate_cache:
        invalidate_read_caches()
    conn.commit(); conn.close()
    return new_id

def get_media(media_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_media_many(ids) -> dict[int, dict]:
    """Batch lookup id → row. Uma query; ids inválidos ignorados."""
    id_list = []
    seen = set()
    for raw in ids or []:
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            continue
        if mid in seen:
            continue
        seen.add(mid)
        id_list.append(mid)
    if not id_list:
        return {}
    conn = get_conn()
    out: dict[int, dict] = {}
    # SQLite aceita no máx ~999 vars por default — fatia
    chunk = 400
    for i in range(0, len(id_list), chunk):
        part = id_list[i:i + chunk]
        placeholders = ','.join('?' * len(part))
        rows = conn.execute(
            f"SELECT * FROM media WHERE id IN ({placeholders})",
            part,
        ).fetchall()
        for row in rows:
            out[int(row['id'])] = dict(row)
    conn.close()
    return out


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
    conn.execute(
        "UPDATE media SET clip_status='completed' WHERE id=?",
        (int(media_id),),
    )
    conn.commit(); conn.close()


def set_media_ai_status(media_id, *, clip_status=None, face_status=None):
    """Atualiza status de processamento AI (pending|processing|completed|failed)."""
    sets = []
    params = []
    if clip_status:
        sets.append('clip_status=?')
        params.append(clip_status)
    if face_status:
        sets.append('face_status=?')
        params.append(face_status)
    if not sets:
        return
    params.append(int(media_id))
    conn = get_conn()
    conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()


def load_drive_sync_index():
    """Mapa drive_id → metadados leves — uma query no início do sync."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT drive_id, id, pasta, drive_modified, nome, tamanho
        FROM media
        WHERE drive_id IS NOT NULL AND drive_id != ''
        """
    ).fetchall()
    conn.close()
    return {r['drive_id']: dict(r) for r in rows}


def get_media_by_drive_id(drive_id, *, index=None):
    """Lookup por drive_id. Passe `index` (load_drive_sync_index) no sync em massa."""
    if not drive_id:
        return None
    if index is not None:
        return index.get(drive_id)
    conn = get_conn()
    row = conn.execute(
        "SELECT id, pasta, drive_modified, nome, tamanho FROM media WHERE drive_id=?",
        (drive_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def batch_update_drive_meta(updates, *, invalidate_cache=True):
    """
    Atualiza metadados de vários drive_ids numa única transação.
    updates: iterable de dicts com drive_id + campos opcionais
    (pasta, drive_modified, nome, tamanho).
    """
    if not updates:
        return 0
    conn = get_conn()
    changed = 0
    for u in updates:
        drive_id = u.get('drive_id')
        if not drive_id:
            continue
        sets = []
        params = []
        if 'pasta' in u and u['pasta'] is not None:
            sets.append('pasta=?')
            params.append(normalize_pasta_name(u['pasta']))
        if 'drive_modified' in u and u['drive_modified'] is not None:
            sets.append('drive_modified=?')
            params.append(u['drive_modified'] or '')
        if 'nome' in u and u['nome'] is not None:
            sets.append('nome=?')
            params.append(u['nome'])
        if 'tamanho' in u and u['tamanho'] is not None:
            sets.append('tamanho=?')
            params.append(int(u['tamanho'] or 0))
        if not sets:
            continue
        params.append(drive_id)
        cur = conn.execute(
            f"UPDATE media SET {', '.join(sets)} WHERE drive_id=?",
            params,
        )
        changed += cur.rowcount
    if changed:
        conn.commit()
        if invalidate_cache:
            invalidate_read_caches()
    conn.close()
    return changed


def update_drive_meta(drive_id, *, pasta=None, drive_modified=None, nome=None, tamanho=None, invalidate_cache=True):
    """Atualiza metadados leves sem recriar a mídia."""
    if not drive_id:
        return False
    payload = {'drive_id': drive_id}
    if pasta is not None:
        payload['pasta'] = pasta
    if drive_modified is not None:
        payload['drive_modified'] = drive_modified
    if nome is not None:
        payload['nome'] = nome
    if tamanho is not None:
        payload['tamanho'] = tamanho
    return batch_update_drive_meta([payload], invalidate_cache=invalidate_cache) > 0


def load_media_embedding(media_id):
    conn = get_conn()
    row = conn.execute("SELECT embedding FROM media_embeddings WHERE media_id=?", (media_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_all_embeddings():
    """
    DEPRECATED — carrega TODOS os embeddings na RAM.
    Use get_embeddings_for_ids(). Mantido só por compat; não chamar em request path.
    """
    raise RuntimeError('get_all_embeddings() desativado — use get_embeddings_for_ids()')


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


def save_media_face(
    media_id,
    embedding_blob,
    cluster_id,
    face_count=0,
    det_score=0.0,
    face_cx=None,
    face_cy=None,
):
    def _norm(v):
        if v is None:
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, x))

    cx = _norm(face_cx)
    cy = _norm(face_cy)
    conn = get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO media_faces(
            media_id, embedding, cluster_id, face_count, det_score,
            face_cx, face_cy, updated_at
        ) VALUES(?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            int(media_id),
            embedding_blob,
            int(cluster_id) if cluster_id is not None else None,
            int(face_count or 0),
            float(det_score or 0),
            cx,
            cy,
        ),
    )
    conn.execute(
        "UPDATE media SET face_status='completed' WHERE id=?",
        (int(media_id),),
    )
    conn.commit()
    conn.close()


def get_face_focus(media_id):
    """Centro do rosto principal (0–1) ou None."""
    if not media_id:
        return None
    conn = get_conn()
    row = conn.execute(
        """
        SELECT face_cx, face_cy, face_count FROM media_faces
        WHERE media_id=? AND COALESCE(face_count,0)>=1
          AND face_cx IS NOT NULL AND face_cy IS NOT NULL
        """,
        (int(media_id),),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return {'cx': float(row['face_cx']), 'cy': float(row['face_cy'])}
    except (TypeError, ValueError):
        return None


def update_face_focus(media_id, face_cx, face_cy):
    """Atualiza só o centro do rosto (não mexe no embedding)."""
    try:
        cx = max(0.0, min(1.0, float(face_cx)))
        cy = max(0.0, min(1.0, float(face_cy)))
    except (TypeError, ValueError):
        return False
    mid = int(media_id)
    conn = get_conn()
    cur = conn.execute(
        """
        UPDATE media_faces
        SET face_cx=?, face_cy=?, updated_at=datetime('now')
        WHERE media_id=?
        """,
        (cx, cy, mid),
    )
    if cur.rowcount <= 0:
        conn.execute(
            """
            INSERT INTO media_faces(
                media_id, embedding, cluster_id, face_count, det_score,
                face_cx, face_cy, updated_at
            ) VALUES(?, NULL, NULL, 1, 0.5, ?, ?, datetime('now'))
            """,
            (mid, cx, cy),
        )
    else:
        # Garante face_count >= 1 quando há centro
        conn.execute(
            """
            UPDATE media_faces SET face_count=CASE
                WHEN COALESCE(face_count,0)<1 THEN 1 ELSE face_count END
            WHERE media_id=?
            """,
            (mid,),
        )
    conn.commit()
    conn.close()
    return True


def get_face_focus_many(media_ids):
    """Map media_id → {cx, cy} (0–1)."""
    ids = []
    for mid in media_ids or []:
        try:
            ids.append(int(mid))
        except (TypeError, ValueError):
            pass
    if not ids:
        return {}
    out = {}
    conn = get_conn()
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        ph = ','.join('?' * len(chunk))
        rows = conn.execute(
            f"""
            SELECT media_id, face_cx, face_cy FROM media_faces
            WHERE media_id IN ({ph})
              AND COALESCE(face_count,0)>=1
              AND face_cx IS NOT NULL AND face_cy IS NOT NULL
            """,
            chunk,
        ).fetchall()
        for r in rows:
            try:
                out[int(r['media_id'])] = {
                    'cx': float(r['face_cx']),
                    'cy': float(r['face_cy']),
                }
            except (TypeError, ValueError):
                continue
    conn.close()
    return out


def face_stats():
    conn = get_conn()
    total_img = conn.execute("SELECT COUNT(*) FROM media WHERE tipo='image'").fetchone()[0]
    scanned = conn.execute("SELECT COUNT(*) FROM media_faces").fetchone()[0]
    with_face = conn.execute(
        "SELECT COUNT(*) FROM media_faces WHERE face_count>=1 AND cluster_id IS NOT NULL"
    ).fetchone()[0]
    clusters = conn.execute(
        "SELECT COUNT(DISTINCT cluster_id) FROM media_faces WHERE cluster_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    return {
        'images': total_img,
        'scanned': scanned,
        'with_face': with_face,
        'clusters': clusters,
        'missing': max(0, total_img - scanned),
    }


def get_media_missing_faces(limit=40):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT m.id, m.drive_id, m.thumb_url, m.nome, m.tipo
        FROM media m
        LEFT JOIN media_faces f ON f.media_id = m.id
        WHERE m.tipo='image' AND f.media_id IS NULL
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def next_face_cluster_id():
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(cluster_id), 0) + 1 FROM media_faces"
    ).fetchone()
    conn.close()
    return int(row[0] or 1)


def list_face_cluster_samples(limit_per_cluster=3):
    """
    {cluster_id: [np.float32 embeddings…]} — até N amostras por cluster
    para casar rostos novos sem carregar o acervo inteiro.
    """
    import numpy as np

    conn = get_conn()
    rows = conn.execute(
        """
        SELECT cluster_id, embedding, det_score
        FROM media_faces
        WHERE cluster_id IS NOT NULL AND embedding IS NOT NULL AND face_count>=1
        ORDER BY cluster_id ASC, det_score DESC
        """
    ).fetchall()
    conn.close()
    out = {}
    for r in rows:
        cid = int(r['cluster_id'])
        bucket = out.setdefault(cid, [])
        if len(bucket) >= int(limit_per_cluster):
            continue
        blob = r['embedding']
        if not blob:
            continue
        vec = np.frombuffer(blob, dtype=np.float32)
        if vec.size:
            bucket.append(vec)
    return out


def pick_contato_reel_items(limit=24):
    """
    Monta lista para o reel de Contato:
    1) no máximo 1 imagem por face_cluster
    2) completa com imagens sem rosto / sem índice (diversas por pasta)
    """
    lim = max(4, min(int(limit or 24), 48))
    conn = get_conn()
    faced = conn.execute(
        """
        SELECT m.*, f.cluster_id AS face_cluster, f.det_score
        FROM media m
        JOIN media_faces f ON f.media_id = m.id
        WHERE m.tipo='image'
          AND f.face_count >= 1
          AND f.cluster_id IS NOT NULL
        ORDER BY f.det_score DESC, m.estrelas DESC, m.created_at DESC
        """
    ).fetchall()

    seen_cluster = set()
    picked = []
    picked_ids = set()
    for r in faced:
        cid = int(r['face_cluster'])
        if cid in seen_cluster:
            continue
        seen_cluster.add(cid)
        item = dict(r)
        item['face_cluster'] = cid
        item['key'] = f'face:{cid}'
        picked.append(item)
        picked_ids.add(int(item['id']))
        if len(picked) >= lim:
            break

    if len(picked) < lim:
        extras = conn.execute(
            """
            SELECT m.*, f.cluster_id AS face_cluster
            FROM media m
            LEFT JOIN media_faces f ON f.media_id = m.id
            WHERE m.tipo='image'
            ORDER BY m.estrelas DESC, m.created_at DESC
            LIMIT 200
            """
        ).fetchall()
        pasta_seen = set()
        for r in extras:
            if len(picked) >= lim:
                break
            mid = int(r['id'])
            if mid in picked_ids:
                continue
            pasta = (r['pasta'] or '').strip().lower() or f'id:{mid}'
            if pasta in pasta_seen:
                continue
            pasta_seen.add(pasta)
            item = dict(r)
            cid = item.get('face_cluster')
            if cid is not None:
                item['face_cluster'] = int(cid)
                item['key'] = f'face:{int(cid)}'
            else:
                item['face_cluster'] = None
                item['key'] = f'pasta:{pasta}'
            picked.append(item)
            picked_ids.add(mid)

    conn.close()
    return picked


def _quality_score(row):
    """Score simples pra home/portfólio: destaque > estrelas > faces > views > frescor."""
    try:
        destaque = int(row.get('destaque') or 0)
    except (TypeError, ValueError):
        destaque = 0
    try:
        estrelas = int(row.get('estrelas') or 0)
    except (TypeError, ValueError):
        estrelas = 0
    try:
        faces = int(row.get('face_count') or 0)
    except (TypeError, ValueError):
        faces = 0
    try:
        det = float(row.get('det_score') or 0)
    except (TypeError, ValueError):
        det = 0.0
    try:
        views = int(row.get('visualizacoes') or 0)
    except (TypeError, ValueError):
        views = 0
    created = str(row.get('created_at') or '')
    # frescor leve: ISO date prefix ajuda a desempatar
    fresh = 0.0
    if len(created) >= 10:
        try:
            y, m, d = created[:10].split('-')
            fresh = int(y) * 372 + int(m) * 31 + int(d)
            fresh = fresh / 1_000_000.0
        except Exception:
            fresh = 0.0
    return (
        destaque * 100.0
        + estrelas * 12.0
        + min(faces, 4) * 2.5
        + min(det, 1.0) * 8.0
        + min(views, 50) * 0.15
        + fresh
    )


def _is_dump_pasta(pasta: str) -> bool:
    pl = (pasta or '').strip().lower()
    if not pl:
        return True
    if pl in _GENERIC_PASTA or pl.startswith('site'):
        return True
    if pl in ('2021', '2022', '2023', '2024', '2025', '2026'):
        return True
    # Arte gráfica / identidade — nunca entra em portfólio fotográfico
    if pl in ('logo', 'logos', 'marca', 'marcas', 'design', 'mockup', 'mockups'):
        return True
    if any(h in pl for h in ('logo', 'identidade', 'branding', 'mockup', 'vetor')):
        return True
    hints = (
        'sem edi', 'originais', 'separadas', 's.edit', 's edit',
        'fotos 13', 'abril 2021', 'belo horizonte', 'haloween s.edit',
        'sem edição', 'sem edicao',
    )
    return any(h in pl for h in hints)


def _framing_score(item, theme: str = '') -> float:
    """
    Prefere fotos com sujeito bem enquadrado: rosto claro, poucas faces,
    proporção útil (retrato/quadrado). Sem bbox salvo — usa face_count/det + dims.
    """
    theme = (theme or '').strip().lower()
    personish = theme in (
        'retratos', 'ensaios', 'editorial', 'casais', 'casamento',
        'familia', 'infantil',
    )
    score = 0.0
    try:
        fc = int(item.get('face_count') or 0)
    except (TypeError, ValueError):
        fc = 0
    try:
        det = float(item.get('det_score') or 0)
    except (TypeError, ValueError):
        det = 0.0

    if personish:
        if fc <= 0:
            score -= 22.0
        elif fc == 1:
            score += 18.0
        elif fc == 2:
            score += 14.0
        elif fc <= 4:
            score += 9.0
        else:
            score -= min(fc - 4, 10) * 1.8

        if det >= 0.85:
            score += 12.0
        elif det >= 0.7:
            score += 8.0
        elif det >= 0.5:
            score += 4.0
        elif fc >= 1 and det < 0.35:
            score -= 8.0

        if theme == 'retratos' and fc == 1:
            score += 10.0
        if theme in ('casais', 'casamento') and fc == 2:
            score += 8.0
        if theme == 'shows':
            pass
    else:
        # shows / geral: rosto ajuda mas não é obrigatório
        if 1 <= fc <= 6:
            score += 4.0
        if det >= 0.7:
            score += 3.0

    try:
        w = int(item.get('width') or 0)
        h = int(item.get('height') or 0)
    except (TypeError, ValueError):
        w = h = 0
    if w > 0 and h > 0:
        ar = w / float(h)
        if personish:
            if 0.55 <= ar <= 0.82:
                score += 10.0  # retrato clássico
            elif 0.82 < ar <= 1.15:
                score += 5.0
            elif ar > 1.55:
                score -= 10.0  # paisagem larga — costuma cortar mal na capa
            elif ar < 0.42:
                score -= 5.0
        elif 0.6 <= ar <= 1.4:
            score += 2.0
    return score


def _home_quality_score(row):
    """
    Ranking da busca home: com destaque/estrelas quase zerados no acervo,
    prioriza tags/categoria e pastas de cliente; pune dumps genéricos.
    """
    score = _quality_score(row)
    pasta = (row.get('pasta') or '').strip()
    pasta_l = pasta.lower()
    tags = (row.get('tags') or '').strip()
    cat = (row.get('categoria') or '').strip()
    tags_l = tags.lower()
    cat_l = cat.lower()

    if _is_dump_pasta(pasta_l):
        score -= 55.0
    elif pasta_l in _GENERIC_PASTA or pasta_l.startswith('site'):
        score -= 45.0

    # Tags/categoria reais (ignora lixo de teste curto)
    if tags and len(tags_l) >= 3 and tags_l not in ('dawd', 'fawdad', 'teste', 'test'):
        score += 28.0
        score += min(tags.count(','), 5) * 3.5
    if cat_l and cat_l not in ('geral', 'misc', 'teste'):
        score += 20.0

    if _is_couple_pasta(pasta) and not _is_show_pasta(pasta):
        score += 14.0
    if _is_show_pasta(pasta):
        score += 12.0
    if _is_kids_pasta(pasta):
        score += 10.0

    # Thumb utilizável
    thumb = (row.get('thumb_url') or '').strip()
    did = (row.get('drive_id') or '').strip()
    if thumb.startswith('https://') or thumb.startswith('/api/'):
        score += 4.0
    elif did:
        score += 2.0
    else:
        score -= 20.0

    # Preferir foto a vídeo no browse visual
    if (row.get('tipo') or '') == 'video':
        score -= 6.0

    return score


def _pasta_key(row):
    pasta = (row.get('pasta') or '').strip().lower()
    if pasta:
        return f'pasta:{pasta}'
    return f'id:{row.get("id")}'


_GENERIC_PASTA = (
    'site (local)', 'site', 'local', 'sem edicao', 'sem edição', 'originais',
    'geral', 'misc', 'upload', 'uploads', 'fotos', 'imagens',
)


def pick_best_home_items(limit=24, tipo=None, max_per_pasta=2, diversify_faces=False):
    """
    Melhores fotos/vídeos pro browse da busca (home).
    Ordena por qualidade editorial e diversifica por pasta.
    """
    lim = max(1, min(int(limit or 24), 720))
    per_pasta = max(1, min(int(max_per_pasta or 2), 12))
    conn = get_conn()
    tipo_sql = ''
    params = []
    if tipo in ('image', 'video'):
        tipo_sql = 'AND m.tipo=?'
        params.append(tipo)

    # Exige fonte de mídia utilizável (thumb OU drive_id)
    rows = conn.execute(
        f"""
        SELECT m.*,
               COALESCE(f.face_count, 0) AS face_count,
               f.cluster_id AS face_cluster,
               COALESCE(f.det_score, 0) AS det_score
        FROM media m
        LEFT JOIN media_faces f ON f.media_id = m.id
        WHERE (
            (m.thumb_url IS NOT NULL AND TRIM(m.thumb_url) != '')
            OR (m.drive_id IS NOT NULL AND TRIM(m.drive_id) != '')
          )
          {tipo_sql}
        ORDER BY
          CASE WHEN COALESCE(TRIM(m.tags),'') != '' THEN 0 ELSE 1 END,
          CASE WHEN COALESCE(TRIM(m.categoria),'') != '' THEN 0 ELSE 1 END,
          m.destaque DESC,
          m.estrelas DESC,
          m.created_at DESC
        LIMIT 2400
        """,
        params,
    ).fetchall()
    conn.close()

    scored = []
    for r in rows:
        item = dict(r)
        score = _home_quality_score(item)
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)

    picked = []
    picked_ids = set()
    pasta_count = {}
    face_seen = set()

    for score, item in scored:
        mid = int(item['id'])
        if mid in picked_ids:
            continue
        # Descarta dumps fortes no topo (ainda podem entrar no fim se faltar volume)
        pasta_l = (item.get('pasta') or '').strip().lower()
        pk = _pasta_key(item)
        cap = 1 if _is_dump_pasta(pasta_l) else per_pasta
        if pasta_count.get(pk, 0) >= cap:
            continue
        if diversify_faces:
            cid = item.get('face_cluster')
            if cid is not None:
                try:
                    cid = int(cid)
                except (TypeError, ValueError):
                    cid = None
                if cid is not None:
                    if cid in face_seen:
                        continue
                    face_seen.add(cid)
                    item['face_cluster'] = cid
        pasta_count[pk] = pasta_count.get(pk, 0) + 1
        item['_home_score'] = round(score, 3)
        picked.append(item)
        picked_ids.add(mid)
        if len(picked) >= lim:
            break

    # Se dumps engoliram o pool, segunda passagem sem dump
    if len(picked) < min(lim, 24):
        for score, item in scored:
            mid = int(item['id'])
            if mid in picked_ids:
                continue
            if _is_dump_pasta(item.get('pasta') or ''):
                continue
            pk = _pasta_key(item)
            if pasta_count.get(pk, 0) >= per_pasta:
                continue
            pasta_count[pk] = pasta_count.get(pk, 0) + 1
            item['_home_score'] = round(score, 3)
            picked.append(item)
            picked_ids.add(mid)
            if len(picked) >= lim:
                break

    return picked


def _is_couple_pasta(pasta: str) -> bool:
    p = (pasta or '').strip()
    if not p:
        return False
    # Banda "Sonata e Cristina" ≠ ensaio de casal
    if _is_show_pasta(p):
        return False
    if '&' in p:
        return True
    # "Nome e Nome" / "Nome E Nome"
    import re
    return bool(re.search(r'\b[eE]\b', p))


def _is_kids_pasta(pasta: str) -> bool:
    pl = (pasta or '').strip().lower()
    if not pl:
        return False
    if 'anos' in pl or 'anivers' in pl or 'bebe' in pl or 'bebê' in pl:
        return True
    if 'infantil' in pl or 'crianca' in pl or 'criança' in pl:
        return True
    return False


# Pastas que parecem nome próprio mas não são ensaio fotográfico
_ESSAY_BLOCKLIST = frozenset({
    'airsoft', 'logo', 'mariage', 'site (local)', 'unico', 'único',
    'thumbs', 'raw', 'jpg', 'png', 'selects',
})

# Força destino do ensaio (Halloween/Gameplays = ensaio, não show)
_ESSAY_BUCKET_FORCE = {
    'halloween': 'ensaios',
    'haloween': 'ensaios',
    'gameplay': 'ensaios',
    'barbara': 'editorial',
}


def _is_person_essay_pasta(pasta: str) -> bool:
    """
    Ensaio individual (nome próprio) — base de Ensaios / Retratos / Editorial.
    Exclui dumps, casais, kids, shows e pastas técnicas (Editadas, S.edit).
    """
    import re
    p = (pasta or '').strip()
    if not p:
        return False
    # Halloween / Gameplays: ensaio temático (não palco)
    pl = p.lower()
    if any(k in pl for k in ('halloween', 'haloween', 'gameplay')):
        return True
    if _is_dump_pasta(p) or _is_couple_pasta(p) or _is_kids_pasta(p) or _is_show_pasta(p):
        return False
    if pl in _GENERIC_PASTA or pl.startswith('site'):
        return False
    if pl in _ESSAY_BLOCKLIST:
        return False
    if any(b in pl for b in _ESSAY_BLOCKLIST):
        return False
    if re.fullmatch(r'\d{4}', pl):
        return False
    if re.search(r'\d{1,2}[/_-]\d{1,2}', pl):
        return False
    if 'editad' in pl or 's.edit' in pl or pl in ('editadas', 'originais', 'separadas'):
        return False
    # Precisa ter letra (nome)
    if not re.search(r'[a-zà-ü]', pl):
        return False
    return True


def _essay_bucket(pasta: str) -> str:
    """
    Destino do ensaio individual entre Retratos / Ensaios / Editorial.
    Regras semânticas primeiro; hash só pra espalhar o resto.
    """
    key = (pasta or '').strip().lower()
    if not key:
        return 'ensaios'
    for needle, bucket in _ESSAY_BUCKET_FORCE.items():
        if needle in key:
            return bucket
    if any(k in key for k in ('editorial', 'moda', 'fashion', 'conceito', 'beauty')):
        return 'editorial'
    if any(k in key for k in ('retrato', 'close', 'estudio', 'estúdio', 'studio')):
        return 'retratos'
    if any(k in key for k in ('ensaio', 'externo', 'lifestyle', 'sessao', 'sessão')):
        return 'ensaios'
    h = 0
    for ch in key:
        h = (h * 33 + ord(ch)) & 0xFFFFFFFF
    return ('retratos', 'ensaios', 'editorial')[h % 3]


def _belongs_to_theme(item: dict, theme: str) -> bool:
    """
    Filtro duro: item só entra na categoria se for do tema.
    Evita casal em Infantil / show em Casamento, etc.
    """
    if not theme:
        return True
    pasta = item.get('pasta') or ''
    pasta_l = pasta.strip().lower()
    cat = (item.get('categoria') or '').strip().lower()
    tags = (item.get('tags') or '').strip().lower()
    tags_l = tags.replace(',', ' ')

    if theme == 'infantil':
        if _is_dump_pasta(pasta):
            return False
        if cat == 'infantil' and _is_kids_pasta(pasta):
            return True
        if cat == 'infantil' and not _is_couple_pasta(pasta) and not _is_show_pasta(pasta):
            return True
        # Pastas de aniversário / criança — sinal forte
        if _is_kids_pasta(pasta):
            return True
        return False

    if theme == 'familia':
        # Confia na etiqueta explícita do acervo
        if cat in ('familia', 'familiar'):
            return True
        if any(k in pasta_l for k in ('familia', 'família', 'batismo', 'familiares')):
            return True
        return False

    if theme in ('casamento', 'casais'):
        if _is_kids_pasta(pasta) or _is_show_pasta(pasta):
            return False
        weddingish = any(
            k in pasta_l or k in tags_l or k in cat
            for k in ('casamento', 'noiva', 'noivo', 'wedding', 'cerimonia', 'cerimônia', 'igreja')
        )
        if theme == 'casamento':
            if cat == 'casamento' or weddingish:
                return True
            # Casal sem sinal de casamento também entra (acervo misto)
            if _is_couple_pasta(pasta):
                return True
            return False
        # casais: prioriza ensaio de casal; casamento puro ainda pode aparecer
        if cat in ('casais', 'casal'):
            return True
        if _is_couple_pasta(pasta):
            return True
        if any(k in tags_l for k in ('casal', 'casais', 'romantico', 'amor')):
            return not _is_dump_pasta(pasta_l)
        return False

    if theme == 'shows':
        # Só pasta/categoria de show — não puxa ensaio por tag solta
        if _is_person_essay_pasta(pasta) and not _is_show_pasta(pasta):
            return False
        if cat in ('shows', 'show') and not _is_person_essay_pasta(pasta):
            return True
        if _is_show_pasta(pasta):
            return True
        return False

    if theme == 'retratos':
        if cat in ('retrato', 'retratos'):
            return True
        if _is_couple_pasta(pasta) or _is_kids_pasta(pasta) or _is_show_pasta(pasta):
            return False
        if _is_dump_pasta(pasta_l):
            return False
        if any(k in tags_l for k in ('retrato', 'close', 'estudio', 'modelo')):
            return True
        # Só o bucket "retratos" — evita mesma grade que Ensaios/Editorial
        if _is_person_essay_pasta(pasta):
            return _essay_bucket(pasta) == 'retratos'
        return False

    if theme == 'ensaios':
        if cat in ('ensaios', 'ensaio'):
            return True
        if any(k in pasta_l for k in ('ensaio', 'ensaios')):
            return True
        if _is_couple_pasta(pasta) or _is_kids_pasta(pasta) or _is_show_pasta(pasta):
            return False
        if any(k in tags_l for k in ('ensaio', 'ensaios', 'sessao', 'sessão')):
            return True
        if _is_person_essay_pasta(pasta):
            return _essay_bucket(pasta) == 'ensaios'
        return False

    if theme == 'editorial':
        if _is_couple_pasta(pasta) or _is_kids_pasta(pasta) or _is_show_pasta(pasta):
            return any(k in pasta_l for k in ('editorial', 'moda', 'fashion'))
        if cat == 'editorial':
            return True
        if any(k in pasta_l for k in ('editorial', 'moda', 'fashion')):
            return True
        if any(k in tags_l for k in ('editorial', 'moda', 'fashion', 'conceito', 'artistico', 'artístico')):
            if ('edit' in pasta_l or 'editadas' in pasta_l) and 'editorial' not in pasta_l:
                return False
            return True
        if _is_person_essay_pasta(pasta):
            return _essay_bucket(pasta) == 'editorial'
        return False

    return True


def _is_show_pasta(pasta: str) -> bool:
    """Palco / banda / bastidor — NÃO inclui ensaio (Halloween, Gameplays, etc.)."""
    pl = (pasta or '').strip().lower()
    if not pl:
        return False
    # Retrato/ensaio temático que às vezes cai no acervo de “evento”
    if any(k in pl for k in ('gameplay', 'halloween', 'haloween', 'ensaio', 'editorial')):
        return False
    keys = (
        'show', 'palco', 'bastidor', 'sonata', 'thalles', 'jota', 'detonaut',
        'banda', 'concerto',
    )
    return any(k in pl for k in keys)


def _theme_from_keys(keys):
    """
    Tema mais específico primeiro (infantil antes de familia — QUERY_EXPAND
    de infantil inclui 'familia' e antes roubava o branch errado).
    """
    bag = ' '.join(str(k or '').lower() for k in (keys or []))
    if any(k in bag for k in ('casamento', 'noiva', 'noivo', 'wedding', 'cerimonia')):
        return 'casamento'
    if any(k in bag for k in ('casal', 'casais', 'romantico', 'pre wedding')):
        return 'casais'
    if any(k in bag for k in ('show', 'shows', 'palco', 'banda', 'concerto', 'sonata')):
        return 'shows'
    if any(k in bag for k in ('infantil', 'crianca', 'criança', 'bebe', 'bebê', 'aniversario', 'anos')):
        return 'infantil'
    if any(k in bag for k in ('familia', 'familiar', 'batismo')):
        return 'familia'
    if any(k in bag for k in ('ensaio', 'ensaios')):
        return 'ensaios'
    if any(k in bag for k in ('editorial', 'moda', 'fashion')):
        return 'editorial'
    if any(k in bag for k in ('retrato', 'retratos', 'modelo', 'close', 'estudio')):
        return 'retratos'
    if any(k in bag for k in ('evento', 'grupo')):
        return 'familia'
    return ''


def pick_best_for_keys(keys, limit=24, tipo=None, max_per_pasta=12, diversify_faces=False):
    """
    Melhores fotos para uma categoria/tema (casamento, shows, retratos…).

    O acervo costuma ter poucas tags — completa com heurísticas de NOME DA PASTA
    (casais com & / \"e\", shows, infantil \"X anos\", etc.).
    """
    lim = max(1, min(int(limit or 24), 720))
    # Categorias: mais fotos por pasta (casais/shows têm dezenas na mesma pasta)
    per_pasta = max(1, min(int(max_per_pasta or 24), 40))
    key_list = []
    seen_k = set()
    for k in keys or []:
        kk = str(k or '').strip().lower()
        if len(kk) < 2 or kk in seen_k or ' ' in kk:
            continue
        seen_k.add(kk)
        key_list.append(kk)
    theme = _theme_from_keys(key_list or keys)
    if not key_list and not theme:
        return pick_best_home_items(limit=lim, tipo=tipo, max_per_pasta=min(per_pasta, 4))

    hard = {}
    if tipo in ('image', 'video'):
        hard['tipo'] = tipo

    by_id = {}

    # 1) tags FTS
    try:
        for item in get_by_tags(key_list or [theme], hard, limit=800):
            by_id[int(item['id'])] = item
    except Exception:
        pass

    # 2) FTS geral por chave
    try:
        for item in get_candidates(key_list[:10] or ([theme] if theme else []), hard, limit=800):
            by_id.setdefault(int(item['id']), item)
    except Exception:
        pass

    conn = get_conn()
    tipo_sql = 'AND tipo=?' if hard.get('tipo') else ''
    params_extra = [hard['tipo']] if hard.get('tipo') else []

    # 3) categoria / tags / pasta LIKE textual
    for k in (key_list or ([theme] if theme else []))[:10]:
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM media
                WHERE (
                    LOWER(COALESCE(categoria,'')) = ?
                    OR LOWER(COALESCE(categoria,'')) LIKE ?
                    OR LOWER(COALESCE(tags,'')) LIKE ?
                    OR LOWER(COALESCE(pasta,'')) LIKE ?
                    OR LOWER(COALESCE(nome,'')) LIKE ?
                )
                  {tipo_sql}
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 300
                """,
                [k, f'%{k}%', f'%{k}%', f'%{k}%', f'%{k}%'] + params_extra,
            ).fetchall()
            for r in rows:
                by_id.setdefault(int(r['id']), dict(r))
        except Exception:
            pass

    # 4) Heurísticas de pasta (acervo pouco etiquetado)
    t = hard.get('tipo') or 'image'
    try:
        if theme in ('casamento', 'casais'):
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    pasta LIKE '%&%'
                    OR pasta LIKE '% e %'
                    OR pasta LIKE '% E %'
                    OR LOWER(pasta) LIKE '%casamento%'
                    OR LOWER(pasta) LIKE '%casal%'
                    OR LOWER(pasta) LIKE '%wedding%'
                    OR LOWER(COALESCE(categoria,'')) IN ('casamento','casais')
                    OR LOWER(COALESCE(tags,'')) LIKE '%casamento%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%casal%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%noiva%'
                  )
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%sonata%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%show%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%halloween%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%haloween%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%gameplay%'
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 1200
                """,
                (t,),
            ).fetchall()
        elif theme == 'shows':
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(pasta) LIKE '%show%'
                    OR LOWER(pasta) LIKE '%sonata%'
                    OR LOWER(pasta) LIKE '%bastidor%'
                    OR LOWER(pasta) LIKE '%palco%'
                    OR LOWER(pasta) LIKE '%thalles%'
                    OR LOWER(pasta) LIKE '%jota%'
                    OR LOWER(pasta) LIKE '%detonaut%'
                    OR LOWER(pasta) LIKE '%banda%'
                    OR LOWER(pasta) LIKE '%concerto%'
                    OR LOWER(COALESCE(categoria,'')) IN ('shows','show')
                  )
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%gameplay%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%halloween%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%haloween%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%ensaio%'
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 1200
                """,
                (t,),
            ).fetchall()
        elif theme == 'infantil':
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(pasta) LIKE '%anos%'
                    OR LOWER(pasta) LIKE '%anivers%'
                    OR LOWER(pasta) LIKE '%infantil%'
                    OR LOWER(pasta) LIKE '%bebe%'
                    OR LOWER(pasta) LIKE '%bebê%'
                    OR LOWER(pasta) LIKE '%crianca%'
                    OR LOWER(pasta) LIKE '%criança%'
                    OR LOWER(COALESCE(categoria,'')) = 'infantil'
                    OR LOWER(COALESCE(tags,'')) LIKE '%infantil%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%crianca%'
                  )
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 900
                """,
                (t,),
            ).fetchall()
        elif theme == 'familia':
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(pasta) LIKE '%familia%'
                    OR LOWER(pasta) LIKE '%família%'
                    OR LOWER(pasta) LIKE '%batismo%'
                    OR LOWER(pasta) LIKE '%familiares%'
                    OR LOWER(COALESCE(categoria,'')) IN ('familia','familiar')
                    OR LOWER(COALESCE(tags,'')) LIKE '%familia%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%batismo%'
                  )
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 700
                """,
                (t,),
            ).fetchall()
        elif theme == 'retratos':
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(COALESCE(categoria,'')) IN ('retrato','retratos')
                    OR LOWER(COALESCE(tags,'')) LIKE '%retrato%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%close%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%estudio%'
                    OR (
                      COALESCE(pasta,'') != ''
                      AND pasta NOT LIKE '%&%'
                      AND pasta NOT LIKE '% e %'
                      AND pasta NOT LIKE '% E %'
                      AND LOWER(pasta) NOT LIKE '%anos%'
                      AND LOWER(pasta) NOT LIKE '%show%'
                      AND LOWER(pasta) NOT LIKE '%sonata%'
                      AND LOWER(pasta) NOT LIKE '%halloween%'
                      AND LOWER(pasta) NOT LIKE '%haloween%'
                      AND LOWER(pasta) NOT LIKE '%gameplay%'
                      AND LOWER(pasta) NOT LIKE '%bastidor%'
                      AND LOWER(pasta) NOT LIKE '%banda%'
                      AND LOWER(pasta) NOT LIKE '%concerto%'
                      AND LOWER(pasta) NOT IN (
                        'sem edição','sem edicao','originais','site (local)',
                        'separadas','fotos 13_09_21','abril 2021','2022',
                        '2021','2023','2024','belo horizonte'
                      )
                    )
                  )
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 800
                """,
                (t,),
            ).fetchall()
        elif theme == 'ensaios':
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(COALESCE(categoria,'')) IN ('ensaios','ensaio')
                    OR LOWER(pasta) LIKE '%ensaio%'
                    OR LOWER(pasta) LIKE '%halloween%'
                    OR LOWER(pasta) LIKE '%haloween%'
                    OR LOWER(pasta) LIKE '%gameplay%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%ensaio%'
                    OR (
                      COALESCE(pasta,'') != ''
                      AND pasta NOT LIKE '%&%'
                      AND pasta NOT LIKE '% e %'
                      AND pasta NOT LIKE '% E %'
                      AND LOWER(pasta) NOT LIKE '%anos%'
                      AND LOWER(pasta) NOT LIKE '%anivers%'
                      AND LOWER(pasta) NOT LIKE '%show%'
                      AND LOWER(pasta) NOT LIKE '%sonata%'
                      AND LOWER(pasta) NOT LIKE '%bastidor%'
                      AND LOWER(pasta) NOT LIKE '%editad%'
                      AND LOWER(pasta) NOT LIKE '%s.edit%'
                      AND LOWER(pasta) NOT LIKE '%airsoft%'
                      AND LOWER(pasta) NOT IN (
                        'sem edição','sem edicao','originais','site (local)',
                        'separadas','fotos 13_09_21','abril 2021','2022',
                        '2021','2023','2024','belo horizonte','logo'
                      )
                    )
                  )
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 1200
                """,
                (t,),
            ).fetchall()
        elif theme == 'editorial':
            # Mesma base de ensaios individuais + moda/conceito (sem casal/show/kids)
            rows = conn.execute(
                """
                SELECT * FROM media
                WHERE tipo=?
                  AND (
                    LOWER(COALESCE(categoria,'')) LIKE '%editorial%'
                    OR LOWER(pasta) LIKE '%editorial%'
                    OR LOWER(pasta) LIKE '%moda%'
                    OR LOWER(pasta) LIKE '%fashion%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%editorial%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%moda%'
                    OR LOWER(COALESCE(tags,'')) LIKE '%conceito%'
                    OR (
                      LENGTH(TRIM(pasta)) BETWEEN 2 AND 40
                      AND LOWER(pasta) NOT LIKE '%&%'
                      AND LOWER(pasta) NOT LIKE '% e %'
                      AND LOWER(pasta) NOT LIKE '%show%'
                      AND LOWER(pasta) NOT LIKE '%sonata%'
                      AND LOWER(pasta) NOT LIKE '%halloween%'
                      AND LOWER(pasta) NOT LIKE '%haloween%'
                      AND LOWER(pasta) NOT LIKE '%gameplay%'
                      AND LOWER(pasta) NOT LIKE '%bastidor%'
                      AND LOWER(pasta) NOT LIKE '%anos%'
                      AND LOWER(pasta) NOT LIKE '%anivers%'
                      AND LOWER(pasta) NOT LIKE '%editad%'
                      AND LOWER(pasta) NOT LIKE '%s.edit%'
                      AND LOWER(pasta) NOT LIKE '%airsoft%'
                      AND LOWER(pasta) NOT IN (
                        'sem edição','sem edicao','originais','site (local)',
                        'separadas','fotos 13_09_21','abril 2021','2022',
                        '2021','2023','2024','belo horizonte','logo'
                      )
                    )
                  )
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%editad%'
                  AND LOWER(COALESCE(pasta,'')) NOT LIKE '%s.edit%'
                ORDER BY destaque DESC, estrelas DESC, created_at DESC
                LIMIT 1200
                """,
                (t,),
            ).fetchall()
        else:
            rows = []
        for r in rows:
            # Filtra dumps genéricos nas categorias
            if _is_dump_pasta(r['pasta'] if 'pasta' in r.keys() else ''):
                # Mantém se tiver tag/categoria forte
                cat = (r['categoria'] if 'categoria' in r.keys() else '') or ''
                tags = (r['tags'] if 'tags' in r.keys() else '') or ''
                if not cat and not tags:
                    continue
            by_id.setdefault(int(r['id']), dict(r))
    except Exception as e:
        print(f'[pick_best_for_keys] heur {theme}: {e}')

    conn.close()

    if not by_id:
        return []

    # Enriquecer face meta
    missing = [mid for mid, it in by_id.items() if 'face_count' not in it]
    if missing:
        conn = get_conn()
        for i in range(0, len(missing), 200):
            chunk = missing[i:i + 200]
            ph = ','.join('?' * len(chunk))
            rows = conn.execute(
                f"""
                SELECT m.id,
                       COALESCE(f.face_count, 0) AS face_count,
                       f.cluster_id AS face_cluster,
                       COALESCE(f.det_score, 0) AS det_score,
                       f.face_cx AS face_cx,
                       f.face_cy AS face_cy
                FROM media m
                LEFT JOIN media_faces f ON f.media_id = m.id
                WHERE m.id IN ({ph})
                """,
                chunk,
            ).fetchall()
            for r in rows:
                it = by_id.get(int(r['id']))
                if not it:
                    continue
                it['face_count'] = r['face_count']
                it['face_cluster'] = r['face_cluster']
                it['det_score'] = r['det_score']
                if r['face_cx'] is not None and r['face_cy'] is not None:
                    it['face_cx'] = r['face_cx']
                    it['face_cy'] = r['face_cy']
        conn.close()

    scored = []
    for item in by_id.values():
        if theme and not _belongs_to_theme(item, theme):
            continue
        score = _home_quality_score(item)
        pasta = item.get('pasta') or ''
        pasta_l = pasta.strip().lower()
        blob = ' '.join([
            str(item.get('categoria') or ''),
            pasta,
            str(item.get('nome') or ''),
            str(item.get('tags') or ''),
        ]).lower()
        if key_list and key_list[0] in blob:
            score += 18.0
        for k in key_list[1:8]:
            if k in blob:
                score += 3.0
        # boosts de heurística
        if theme in ('casamento', 'casais') and _is_couple_pasta(pasta) and not _is_show_pasta(pasta):
            score += 14.0
        if theme == 'shows' and _is_show_pasta(pasta):
            score += 14.0
        if theme == 'infantil' and _is_kids_pasta(pasta):
            score += 14.0
        if theme == 'ensaios' and _is_person_essay_pasta(pasta):
            score += 14.0
        if theme == 'editorial':
            if 'editorial' in pasta_l or 'moda' in pasta_l or (item.get('categoria') or '').lower() == 'editorial':
                score += 16.0
            elif _is_person_essay_pasta(pasta):
                score += 12.0
            try:
                if int(item.get('destaque') or 0):
                    score += 6.0
            except (TypeError, ValueError):
                pass
        if theme == 'retratos' and not _is_couple_pasta(pasta) and not _is_kids_pasta(pasta) and not _is_show_pasta(pasta):
            score += 8.0
        elif theme == 'retratos' and _is_show_pasta(pasta):
            score -= 20.0
        # Enquadramento: rosto claro + proporção (categorias de pessoa)
        score += _framing_score(item, theme)
        if _is_dump_pasta(pasta_l):
            score -= 30.0
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)

    picked = []
    picked_ids = set()
    pasta_count = {}
    face_seen = set()
    for score, item in scored:
        mid = int(item['id'])
        if mid in picked_ids:
            continue
        pk = _pasta_key(item)
        pasta_l = (item.get('pasta') or '').strip().lower()
        cap = 2 if (pasta_l in _GENERIC_PASTA or pasta_l.startswith('site')) else per_pasta
        if pasta_count.get(pk, 0) >= cap:
            continue
        if diversify_faces:
            cid = item.get('face_cluster')
            if cid is not None:
                try:
                    cid = int(cid)
                except (TypeError, ValueError):
                    cid = None
            if cid is not None:
                if cid in face_seen:
                    continue
                face_seen.add(cid)
                item['face_cluster'] = cid
        pasta_count[pk] = pasta_count.get(pk, 0) + 1
        item['_home_score'] = round(score, 3)
        picked.append(item)
        picked_ids.add(mid)
        if len(picked) >= lim:
            break

    # 2ª passagem: se ainda falta volume, relaxa cap por pasta (ainda só do tema)
    if len(picked) < lim:
        soft_cap = max(per_pasta * 2, 48)
        for score, item in scored:
            mid = int(item['id'])
            if mid in picked_ids:
                continue
            if theme and not _belongs_to_theme(item, theme):
                continue
            pasta_l = (item.get('pasta') or '').strip().lower()
            if _is_dump_pasta(pasta_l) and not (item.get('categoria') or item.get('tags')):
                continue
            pk = _pasta_key(item)
            if pasta_count.get(pk, 0) >= soft_cap:
                continue
            pasta_count[pk] = pasta_count.get(pk, 0) + 1
            item['_home_score'] = round(score, 3)
            picked.append(item)
            picked_ids.add(mid)
            if len(picked) >= lim:
                break

    return picked


_CAT_HINTS = {
    'casamento': ('casamento', 'noiva', 'noivo', 'cerimonia', 'alianca', 'vestido'),
    'casais': ('casal', 'casais', 'romantico', 'pre wedding', 'pre-wedding'),
    'retratos': ('retrato', 'retratos', 'editorial', 'modelo', 'close'),
    'shows': ('show', 'shows', 'palco', 'banda', 'concerto', 'sonata'),
    'familia': ('familia', 'batismo', 'evento', 'grupo'),
    'infantil': ('infantil', 'crianca', 'bebe', 'heroi', 'aniversario'),
    'lifestyle': ('lifestyle', 'praia', 'cafe', 'outdoor', 'guitarra'),
    'editorial': ('editorial', 'moda', 'artistico', 'conceito'),
}

_PORTFOLIO_LAYOUT = [
    ('l-wide', ('casais', 'casamento')),
    ('p-tall', ('retratos', 'editorial')),
    ('p-tall', ('retratos', 'shows')),
    ('l-wide', ('lifestyle', 'shows')),
    ('p-tall', ('retratos', 'lifestyle')),
    ('p-tall', ('editorial', 'retratos')),
    ('break', 'Casais & casamento'),
    ('l-wide', ('casamento', 'casais')),
    ('p-tall', ('casamento', 'casais')),
    ('p-tall', ('casais', 'casamento')),
    ('break', 'Retratos & modelo'),
    ('p-tall', ('retratos', 'editorial')),
    ('p-tall', ('retratos', 'lifestyle')),
    ('p-tall', ('editorial', 'retratos')),
    ('p-tall', ('retratos', 'shows')),
    ('break', 'Artístico & lifestyle'),
    ('p-tall', ('editorial', 'lifestyle')),
    ('p-tall', ('lifestyle', 'retratos')),
    ('p-tall', ('lifestyle', 'infantil')),
    ('p-tall', ('infantil', 'familia')),
    ('break', 'Família & eventos'),
    ('l-wide', ('familia', 'casamento')),
    ('l-wide', ('familia', 'shows')),
]


def _item_matches_hints(item, hints):
    blob = ' '.join([
        str(item.get('categoria') or ''),
        str(item.get('pasta') or ''),
        str(item.get('nome') or ''),
        str(item.get('tags') or ''),
    ]).lower()
    for hint in hints or ():
        keys = _CAT_HINTS.get(hint, (hint,))
        for k in keys:
            if k and k in blob:
                return True
    return False


def pick_portfolio_layout(limit=22):
    """
    Monta grade do index com shapes (l-wide / p-tall) equilibrados
    e fotos de qualidade diversificadas por pasta/categoria.
    """
    pool = pick_best_home_items(limit=min(120, max(40, int(limit) * 4)), tipo='image', max_per_pasta=2)
    if not pool:
        return {'items': [], 'total_pool': 0}

    used = set()
    out = []
    leftovers = list(pool)

    def take(prefer_hints, shape):
        nonlocal leftovers
        # 1) preferência por categoria
        for i, it in enumerate(leftovers):
            mid = int(it['id'])
            if mid in used:
                continue
            if prefer_hints and not _item_matches_hints(it, prefer_hints):
                continue
            used.add(mid)
            leftovers.pop(i)
            card = to_search_card(it, thumb_size=720)
            card['layout'] = shape
            card['title'] = (it.get('pasta') or it.get('nome') or 'Trabalho').strip()
            card['cat_label'] = (it.get('categoria') or it.get('pasta') or '').strip()
            return card
        # 2) qualquer restante
        for i, it in enumerate(leftovers):
            mid = int(it['id'])
            if mid in used:
                continue
            used.add(mid)
            leftovers.pop(i)
            card = to_search_card(it, thumb_size=720)
            card['layout'] = shape
            card['title'] = (it.get('pasta') or it.get('nome') or 'Trabalho').strip()
            card['cat_label'] = (it.get('categoria') or it.get('pasta') or '').strip()
            return card
        return None

    for kind, hints in _PORTFOLIO_LAYOUT:
        if kind == 'break':
            out.append({'type': 'break', 'label': hints})
            continue
        if len([x for x in out if x.get('type') != 'break']) >= limit:
            break
        card = take(hints, kind)
        if card:
            out.append({'type': 'photo', **card})

    return {
        'items': out,
        'total_pool': len(pool),
        'photos': sum(1 for x in out if x.get('type') == 'photo'),
    }


# Capas manuais da grade Explorar (media.id) — curadoria do portfólio
CATEGORY_COVER_OVERRIDES = {
    'shows': 1023,      # Sonata — bateria / palco
    'editorial': 2034,  # Barbara — ensaio branco / toboágua
}


def pick_category_covers(explore_map, thumb_size=420):
    """Uma capa (melhor foto do tema) por categoria da grade Explorar."""
    covers = {}
    used_ids = set()
    used_pastas = set()
    sibling = {'retratos', 'ensaios', 'editorial'}

    def _enrich_dims(it):
        if int(it.get('width') or 0) > 0 and int(it.get('height') or 0) > 0:
            return
        try:
            from backend.services.thumb_pipeline import dims_for_card
            w, h = dims_for_card(int(it['id']))
            if w and h:
                it['width'] = w
                it['height'] = h
        except Exception:
            pass

    def _cover_rank(it, theme):
        """Só ranking de qualidade — não troca capa por posição do rosto."""
        _enrich_dims(it)
        s = _framing_score(it, theme)
        try:
            s += float(it.get('_home_score') or 0) * 0.05
        except (TypeError, ValueError):
            pass
        return s

    def _commit_cover(cat, best, pool_len=0):
        if not best:
            return
        if best.get('face_cx') is None or best.get('face_cy') is None:
            foc = get_face_focus(best.get('id'))
            if foc:
                best['face_cx'] = foc['cx']
                best['face_cy'] = foc['cy']
        card = to_search_card(best, thumb_size=thumb_size)
        # Capa panorâmica com rosto no centro (botão largo/baixo)
        thumb = None
        try:
            from backend.services import thumb_pipeline as tp
            tp.ensure_cover_thumb(best)
            mid = int(best['id'])
            thumb = f'/api/media/{mid}/thumb-cover?v={tp.thumb_version(mid, tp.TIER_COVER)}'
        except Exception as e:
            print(f'[covers] cover thumb media={best.get("id")}: {e}')
            thumb = card.get('thumb_medium') or card.get('thumb_small') or card.get('thumb_url')
        covers[cat] = {
            'id': card.get('id'),
            'thumb_url': thumb,
            'thumb_cover': thumb,
            'pasta': card.get('pasta'),
            'estrelas': card.get('estrelas'),
            'destaque': card.get('destaque'),
            'total_pool': pool_len,
            'face_x': card.get('face_x'),
            'face_y': card.get('face_y'),
        }
        try:
            used_ids.add(int(best.get('id')))
        except (TypeError, ValueError):
            pass
        used_pastas.add(_pasta_key(best))

    for cat, keys in (explore_map or {}).items():
        theme = _theme_from_keys(keys) or str(cat or '').lower()
        best = None

        # Capa curada manualmente (ex.: Editorial = Barbara)
        override_id = CATEGORY_COVER_OVERRIDES.get(str(cat or '').lower())
        if override_id:
            try:
                forced = get_media(int(override_id))
            except Exception:
                forced = None
            if forced and int(forced.get('id') or 0) not in used_ids:
                _commit_cover(cat, forced, pool_len=0)
                continue

        try:
            pool = pick_best_for_keys(list(keys), limit=48, tipo='image', max_per_pasta=3)
        except Exception:
            pool = []
        candidates = []
        for it in pool:
            if not _belongs_to_theme(it, theme):
                continue
            try:
                mid = int(it.get('id'))
            except (TypeError, ValueError):
                continue
            pasta = it.get('pasta') or ''
            pk = _pasta_key(it)
            if mid in used_ids:
                continue
            if theme in sibling and pk in used_pastas:
                continue
            cat_i = (it.get('categoria') or '').strip().lower()
            strong = False
            if theme == 'infantil' and _is_kids_pasta(pasta):
                strong = True
            elif theme == 'shows' and _is_show_pasta(pasta):
                strong = True
            elif theme in ('casamento', 'casais') and _is_couple_pasta(pasta):
                strong = True
            elif theme == 'familia' and (
                cat_i in ('familia', 'familiar')
                or 'familia' in pasta.lower()
                or 'batismo' in pasta.lower()
            ):
                strong = True
            elif theme == 'ensaios' and _is_person_essay_pasta(pasta) and _essay_bucket(pasta) == 'ensaios':
                strong = True
            elif theme == 'editorial' and (
                cat_i == 'editorial'
                or 'editorial' in pasta.lower()
                or 'moda' in pasta.lower()
                or (_is_person_essay_pasta(pasta) and _essay_bucket(pasta) == 'editorial')
            ) and not _is_couple_pasta(pasta):
                strong = True
            elif theme == 'retratos' and _is_person_essay_pasta(pasta) and _essay_bucket(pasta) == 'retratos':
                strong = True
            if not strong:
                continue
            candidates.append(it)
        if candidates:
            # 1ª do ranking de qualidade (estável) — crop do rosto fica no thumb-cover
            best = max(candidates, key=lambda x: _cover_rank(x, theme))
        if not best and pool:
            fallbacks = []
            for cand in pool:
                if not _belongs_to_theme(cand, theme):
                    continue
                try:
                    mid = int(cand.get('id'))
                except (TypeError, ValueError):
                    continue
                pk = _pasta_key(cand)
                if mid in used_ids:
                    continue
                if theme in sibling and pk in used_pastas:
                    continue
                pasta0 = cand.get('pasta') or ''
                if theme == 'editorial' and _is_couple_pasta(pasta0):
                    continue
                if theme in ('ensaios', 'retratos', 'editorial') and not _is_person_essay_pasta(pasta0):
                    if theme != 'editorial' or not any(
                        k in pasta0.lower() for k in ('editorial', 'moda', 'fashion')
                    ):
                        continue
                if theme == 'infantil' and not _is_kids_pasta(pasta0):
                    continue
                if theme == 'shows' and not _is_show_pasta(pasta0):
                    continue
                fallbacks.append(cand)
            if fallbacks:
                best = max(fallbacks, key=lambda x: _cover_rank(x, theme))
        _commit_cover(cat, best, pool_len=len(pool))
    return covers


def update_pasta_by_drive_id(drive_id, pasta):
    """Atualiza pasta (e invalida cache) sem recriar a mídia."""
    pasta = normalize_pasta_name(pasta)
    if not drive_id:
        return False
    conn = get_conn()
    cur = conn.execute(
        "UPDATE media SET pasta=? WHERE drive_id=? AND (pasta IS NULL OR pasta='' OR pasta!=?)",
        (pasta, drive_id, pasta),
    )
    changed = cur.rowcount > 0
    if changed:
        conn.commit()
        invalidate_read_caches()
    conn.close()
    return changed


# Campos leves do card de busca (sem embedding, EXIF pesado)
CARD_FIELDS = (
    'id', 'nome', 'tipo', 'categoria', 'pasta', 'tags', 'autor',
    'data_upload', 'hora_upload', 'ano', 'mes', 'dia', 'created_at',
    'thumb_url', 'drive_id', 'drive_link', 'estrelas', 'destaque',
    'clip_status', 'face_status',
)

# Projeção interna de busca (inclui descricao só pra score — não vai no card)
CANDIDATE_FIELDS = CARD_FIELDS + ('descricao',)


def media_select_sql(alias='m', fields=None):
    """Projeção slim — evita SELECT * no caminho de busca."""
    cols_src = fields or CANDIDATE_FIELDS
    cols = ', '.join(f'{alias}.{c}' for c in cols_src)
    return f'SELECT {cols}'


def to_search_card(item: dict, thumb_size: int = 560) -> dict:
    """Payload mínimo pro grid de busca (sem blob/embedding/EXIF)."""
    if not item:
        return {}
    tags_raw = item.get('tags') or ''
    if isinstance(tags_raw, str) and tags_raw:
        top = [t.strip() for t in tags_raw.split(',') if t.strip()][:8]
        top_tags = ','.join(top)
    else:
        top_tags = ''
    out = {
        'id': item.get('id'),
        'nome': item.get('nome') or '',
        'tipo': item.get('tipo') or '',
        'categoria': item.get('categoria') or '',
        'pasta': item.get('pasta') or '',
        'people': (item.get('pasta') or '').strip(),
        'tags': top_tags,
        'autor': item.get('autor') or '',
        'data_upload': item.get('data_upload') or '',
        'hora_upload': item.get('hora_upload') or '',
        'ano': item.get('ano'),
        'mes': item.get('mes'),
        'dia': item.get('dia'),
        'created_at': item.get('created_at') or '',
        'thumb_url': item.get('thumb_url') or '',
        # Público: sem drive_id/link (enumeração + scrape HD)
        'estrelas': item.get('estrelas') or 0,
        'destaque': item.get('destaque') or 0,
        'clip_status': item.get('clip_status') or 'pending',
        'face_status': item.get('face_status') or 'pending',
    }
    # annotate_storage precisa do drive_id só pra classificar storage/local
    did = item.get('drive_id') or ''
    if did:
        out['_drive_id_internal'] = did
        out['drive_id'] = did  # removido após annotate
    # Centro do rosto em % (pra object-position / capas) — vem do item já enriquecido
    try:
        cx = item.get('face_cx')
        cy = item.get('face_cy')
        if cx is not None and cy is not None:
            out['face_x'] = round(float(cx) * 100.0, 1)
            out['face_y'] = round(float(cy) * 100.0, 1)
    except (TypeError, ValueError):
        pass
    card = annotate_storage(out, thumb_size=thumb_size)
    # Strip secrets / IDs Drive do JSON público
    card.pop('drive_id', None)
    card.pop('drive_link', None)
    card.pop('thumb_drive', None)
    card.pop('_drive_id_internal', None)
    mid = card.get('id')
    # Nunca expor /api/local/<uid> no JSON público
    for key in ('thumb_url', 'thumb_proxy', 'thumb_small', 'thumb_medium'):
        val = str(card.get(key) or '')
        if val.startswith('/api/local/'):
            if mid and (card.get('tipo') or '') == 'video':
                card[key] = (
                    f'/api/media/{int(mid)}/download?dl=0'
                    if key == 'thumb_proxy'
                    else f'/api/media/{int(mid)}/thumb-medium'
                )
            elif mid:
                card[key] = f'/api/media/{int(mid)}/thumb?sz={int(thumb_size) or 280}'
            else:
                card.pop(key, None)
    if card.get('storage') == 'local' and (card.get('tipo') or '') != 'video' and mid:
        card['thumb_proxy'] = f'/api/media/{int(mid)}/thumb?sz={int(thumb_size) or 280}'
        if not card.get('thumb_url') or str(card.get('thumb_url')).startswith('/api/local/'):
            card['thumb_url'] = card.get('thumb_small') or card['thumb_proxy']
    return card


def annotate_storage(item: dict, thumb_size: int = 280, *, light: bool = True) -> dict:
    """
    Normaliza storage + URLs de thumb pro grid.
    Pipeline: thumb_small (pré-cache) → thumb_medium (viewport) → proxy/Drive fallback.

    light=True (default na busca): só URLs estáveis, sem stat/json por card.
    light=False: inclui *_ready e dims do disco (admin/stats).
    """
    out = dict(item)
    did = str(out.get('drive_id') or '')
    out['storage'] = 'local' if did.startswith('local:') else 'drive'
    mid = out.get('id')
    sz = int(thumb_size) or 280
    if mid and did.startswith('local:'):
        uid = did.split(':', 1)[1]
        local_url = f'/api/local/{uid}'
        try:
            from backend.services import thumb_pipeline as tp
            mid_i = int(mid)
            out['thumb_small'] = f'/api/media/{mid_i}/thumb-small'
            out['thumb_medium'] = f'/api/media/{mid_i}/thumb-medium'
            if not light:
                urls = tp.urls_for_card(mid_i)
                out.update(urls)
                w, h = tp.dims_for_card(mid_i)
                if w and h:
                    out['width'] = w
                    out['height'] = h
            out['thumb_url'] = out.get('thumb_small') or local_url
            out['thumb_proxy'] = local_url
        except Exception:
            out['thumb_url'] = local_url
            out['thumb_proxy'] = local_url
            out['thumb_small'] = local_url
            out['thumb_medium'] = local_url
    elif mid:
        mid_i = int(mid)
        out['thumb_small'] = f'/api/media/{mid_i}/thumb-small'
        out['thumb_medium'] = f'/api/media/{mid_i}/thumb-medium'
        if not light:
            try:
                from backend.services import thumb_pipeline as tp
                urls = tp.urls_for_card(mid_i)
                out.update(urls)
                w, h = tp.dims_for_card(mid_i)
                if w and h:
                    out['width'] = w
                    out['height'] = h
            except Exception:
                pass
        out['thumb_url'] = out.get('thumb_small') or f'/api/media/{mid_i}/thumb?sz={sz}'
        out['thumb_proxy'] = f'/api/media/{mid_i}/thumb?sz={sz}'
        if did and not did.startswith('local:'):
            out['thumb_drive'] = f'https://drive.google.com/thumbnail?id={did}&sz=w{sz}'
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
    # Contador não deve invalidar cache de busca/stats (thrash em pageview)
    conn.commit(); conn.close()

def increment_downloads(media_id):
    conn = get_conn()
    conn.execute("UPDATE media SET downloads=downloads+1 WHERE id=?", (media_id,))
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


def get_candidates(text_terms, hard_filters, limit=500, offset=0):
    """Candidatos pra busca inteligente (texto + filtros). Projeção slim + LIMIT/OFFSET."""
    conn = get_conn()
    params = []
    where = []
    select = media_select_sql('m')

    if text_terms:
        from backend.utils.security import build_fts_match
        match_expr = build_fts_match(text_terms)
        if not match_expr:
            base_sql = f"{select} FROM media m WHERE 1=1"
        else:
            base_sql = (
                f"{select} FROM media_fts fts JOIN media m ON m.id=fts.rowid "
                "WHERE media_fts MATCH ?"
            )
            params.append(match_expr)
    else:
        base_sql = f"{select} FROM media m WHERE 1=1"

    for col in ('tipo','categoria','autor','pasta'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?"); params.append(hard_filters[col])
    for col in ('ano','mes','dia'):
        if hard_filters.get(col):
            where.append(f"m.{col}=?"); params.append(int(hard_filters[col]))

    where_sql = ('AND '+' AND '.join(where)) if where else ''
    order_sql = "ORDER BY m.created_at DESC" if not text_terms else ""
    lim = max(1, min(int(limit) if limit else 500, 5000))
    off = max(0, int(offset or 0))
    full_sql = f"{base_sql} {where_sql} {order_sql} LIMIT {lim} OFFSET {off}"

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
    """Itens com tags via FTS5 (coluna tags) — evita SCAN+LIKE no caminho de busca.

    Fallback LIKE só se FTS não retornar match expression válida.
    Aceita CSV com ou sem espaço após vírgula.
    """
    hard_filters = hard_filters or {}
    tags = [str(t or '').strip().lower() for t in (tag_terms or []) if str(t or '').strip()]
    if not tags:
        return []

    from backend.utils.security import escape_fts_term

    # FTS5 column filter: tags:"show" OR tags:"palco"
    fts_parts = []
    for t in tags[:24]:
        et = escape_fts_term(t)
        # Frases com espaço quebram o MATCH inteiro neste índice
        if ' ' in et:
            continue
        if len(et) >= 2:
            fts_parts.append(f'tags:"{et}"')
    lim = max(1, min(int(limit or 2000), 5000))
    select = media_select_sql('m')
    conn = get_conn()
    params = []
    where = []

    if fts_parts:
        base_sql = (
            f"{select} FROM media_fts fts JOIN media m ON m.id=fts.rowid "
            "WHERE media_fts MATCH ?"
        )
        params.append(' OR '.join(fts_parts))
    else:
        # Fallback raro
        base_sql = f"{select} FROM media m WHERE 1=1"
        norm = (
            "TRIM(REPLACE(REPLACE(REPLACE(LOWER(COALESCE(m.tags,'')), ', ', ','), ' ,', ','), ',,', ','))"
        )
        tag_clauses = []
        for t in tags:
            tag_clauses.append(
                f"({norm} = ? OR {norm} LIKE ? OR {norm} LIKE ? OR {norm} LIKE ?)"
            )
            params.extend([t, f"{t},%", f"%,{t}", f"%,{t},%"])
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

    where_sql = (' AND ' + ' AND '.join(where)) if where else ''
    sql = f"{base_sql}{where_sql} ORDER BY m.created_at DESC LIMIT {lim}"
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


def normalize_pasta_name(pasta: str) -> str:
    """Limpa nome de pasta do Drive (&amp; → &, espaços)."""
    import html
    import re

    s = html.unescape(str(pasta or '')).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def cleanup_pasta_html_entities():
    """One-shot: corrige pastas gravadas com &amp; etc."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT pasta FROM media WHERE pasta LIKE '%&%;%'"
    ).fetchall()
    changed = 0
    for r in rows:
        raw = r[0] or ''
        fixed = normalize_pasta_name(raw)
        if fixed and fixed != raw:
            conn.execute("UPDATE media SET pasta=? WHERE pasta=?", (fixed, raw))
            changed += conn.total_changes
    if changed:
        conn.commit()
        invalidate_read_caches()
        print(f"[DB] Pastas normalizadas: {changed} linha(s).")
    conn.close()
    return changed


def get_by_pasta_query(terms, raw_query='', hard_filters=None, limit=500):
    """
    Busca por nome da pasta (pessoa/casal), com match parcial e sem acento.
    Ex.: 'Amanda' → pasta 'Amanda Freitas'; 'Jose' → 'Karoline & José'.
    """
    import html
    import unicodedata

    hard_filters = hard_filters or {}

    def norm(s):
        s = html.unescape(str(s or '')).strip().lower()
        s = unicodedata.normalize('NFD', s)
        s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
        for sep in ('&', '/', '|', '+', ','):
            s = s.replace(sep, ' ')
        s = s.replace(' e ', ' ')
        return ' '.join(s.split())

    rq = norm(raw_query)
    term_list = [norm(t) for t in (terms or []) if norm(t) and len(norm(t)) >= 2]
    if not rq and not term_list:
        return []

    matched_pastas = []
    for pasta in get_all_pastas():
        pn = norm(pasta)
        if not pn:
            continue
        hit = False
        if rq and len(rq) >= 2 and (rq in pn or any(w.startswith(rq) for w in pn.split() if len(rq) >= 3)):
            hit = True
        if not hit:
            words = set(pn.split())
            for t in term_list:
                if t in words or t in pn or any(w.startswith(t) for w in words if len(t) >= 3):
                    hit = True
                    break
        if hit:
            matched_pastas.append(pasta)

    if not matched_pastas:
        return []

    conn = get_conn()
    params = []
    where = []
    # SQLite limite de variáveis — fatia
    out = []
    lim = max(1, min(int(limit or 500), 2000))
    for i in range(0, len(matched_pastas), 80):
        chunk = matched_pastas[i:i + 80]
        placeholders = ','.join('?' * len(chunk))
        params_chunk = list(chunk)
        where_extra = []
        for col in ('tipo', 'categoria', 'autor'):
            if hard_filters.get(col):
                where_extra.append(f"m.{col}=?")
                params_chunk.append(hard_filters[col])
        for col in ('ano', 'mes', 'dia'):
            if hard_filters.get(col) is not None and hard_filters.get(col) != '':
                where_extra.append(f"m.{col}=?")
                params_chunk.append(int(hard_filters[col]))
        extra_sql = (' AND ' + ' AND '.join(where_extra)) if where_extra else ''
        rows = conn.execute(
            f"""
            {media_select_sql('m')} FROM media m
            WHERE m.pasta IN ({placeholders}){extra_sql}
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            params_chunk + [lim],
        ).fetchall()
        for r in rows:
            out.append(dict(r))
            if len(out) >= lim:
                break
        if len(out) >= lim:
            break
    conn.close()
    return out[:lim]


def list_media(page=1, per_page=24, tipo=None, categoria=None, storage=None, sort='date_desc'):
    return search_media(
        query='',
        page=page,
        per_page=per_page,
        filters={'tipo': tipo, 'categoria': categoria, 'storage': storage},
        sort=sort or 'date_desc',
    )
