"""
photo_curator.py — Curadoria offline da Home (WOW / Portfolio Master).

Vasculha o acervo inteiro (embeddings CLIP + faces + OpenCV em thumbs),
grava cache em media_curation_scores e pode aplicar seleção estática na Home.

NÃO roda no page load. Sem APIs pagas.

Uso:
  python -m backend.services.photo_curator
  python -m backend.services.photo_curator --rebuild
  python -m backend.services.photo_curator --apply
  python -m backend.services.photo_curator --rebuild --apply --max-home 22
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "media.db"
MED = ROOT / "data" / "thumbs" / "medium"
SMALL = ROOT / "data" / "thumbs" / "small"
FOTOS = ROOT / "frontend" / "fotos"
INDEX = ROOT / "frontend" / "index.html"
MAIN_JS = ROOT / "frontend" / "js" / "main.js"
REPORT = ROOT / "scripts" / "home_curation_report.json"
TOP_JSON = ROOT / "scripts" / "home_curation_top200.json"

BARBARA_MEDIA_ID = 2034
BARBARA_LOCAL = "fotos/foto_barbara.png"
OPENER_LOCAL = "fotos/foto_casal_por_do_sol.jpg"

DUMP_HINTS = (
    "logo",
    "sem edi",
    "originais",
    "site",
    "captura",
    "mockup",
    "identidade",
    "marca",
    "design",
    "mageria",
)

# CLIP text banks (EN — alinhado ao modelo LAION)
PROMPT_BANKS = {
    "wow": [
        "an award winning cinematic photograph with stunning visual impact",
        "breathtaking professional photography portfolio hero image",
        "unforgettable iconic powerful photograph",
        "dramatic emotional masterpiece photography",
    ],
    "aesthetic": [
        "beautiful fine art photography",
        "magazine cover quality photograph",
        "elegant aesthetic professional photo",
    ],
    "composition": [
        "strong photographic composition with leading lines and depth",
        "perfectly framed portrait with beautiful bokeh",
        "balanced visual composition photography",
    ],
    "light": [
        "golden hour photography warm sunlight",
        "dramatic silhouette against sunset sky",
        "cinematic backlight photograph",
        "soft natural window light portrait",
        "dramatic stage concert lighting",
    ],
    "moment": [
        "candid decisive moment emotional photography",
        "intimate couple connection genuine emotion",
        "joyful authentic human expression portrait",
        "tender embrace between people photograph",
    ],
    "negative": [
        "blurry low quality phone snapshot",
        "boring ordinary forgettable photo",
        "logo graphic design mockup watermark",
        "screenshot of a website or document",
        "cluttered poorly framed group photo",
    ],
}

CONCEPT_TITLES = [
    {
        "id": "luz",
        "titles": ("Quando a luz cai", "Antes da noite", "Sob o dourado"),
        "prompts": [
            "golden hour photography",
            "sunset silhouette photograph",
            "warm cinematic light portrait",
        ],
    },
    {
        "id": "casal",
        "titles": ("Entre nós", "O tempo entre nós", "Depois do silêncio"),
        "prompts": [
            "romantic couple intimate photograph",
            "wedding couple emotional moment",
            "two people embracing with love",
        ],
    },
    {
        "id": "retrato",
        "titles": ("Um lugar para ser", "Presença", "Olhar que fica"),
        "prompts": [
            "striking portrait looking at camera",
            "editorial fashion portrait photography",
            "powerful facial expression portrait",
        ],
    },
    {
        "id": "movimento",
        "titles": ("Em movimento", "Corpos em passagem", "Fora do centro"),
        "prompts": [
            "dynamic action motion photography",
            "street photography urban energy",
            "concert stage performance photograph",
        ],
    },
    {
        "id": "mundo",
        "titles": ("Pequenos mundos", "Entre ruas", "Em passagem"),
        "prompts": [
            "atmospheric environmental storytelling photograph",
            "documentary lifestyle scene photography",
            "quiet everyday moment beautiful light",
        ],
    },
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def ensure_scores_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curation_final ON media_curation_scores(final_score DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curation_wow ON media_curation_scores(wow_score DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_curation_master ON media_curation_scores(portfolio_master DESC)"
    )
    conn.commit()


def _is_dump(pasta: str, nome: str) -> bool:
    blob = f"{pasta or ''} {nome or ''}".lower()
    return any(h in blob for h in DUMP_HINTS)


def _thumb_for(mid: int) -> Path | None:
    for base in (MED, SMALL):
        for ext in (".webp", ".jpg", ".png", ".jpeg"):
            p = base / f"{mid}{ext}"
            if p.exists() and p.stat().st_size > 0:
                return p
    return None


def _content_hash(mid: int, emb_updated: str | None, thumb: Path | None) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    h.update(str(mid).encode())
    h.update((emb_updated or "").encode())
    if thumb and thumb.exists():
        h.update(str(thumb.stat().st_mtime_ns).encode())
        h.update(str(thumb.stat().st_size).encode())
    return h.hexdigest()[:24]


def _l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-8:
        return v
    return v / n


def _encode_prompt_banks() -> dict[str, np.ndarray]:
    """Warm CLIP and encode all prompt banks → mean unit vector per bank."""
    from backend.services.clip_tagger import _load_model, encode_text_query, CLIP_ENABLED

    if not CLIP_ENABLED:
        raise SystemExit("CLIP_ENABLED=false — ative para curadoria WOW.")
    print("[curator] Warming OpenCLIP…")
    model, preprocess, tokenizer = _load_model()
    if model is None:
        raise SystemExit("Falha ao carregar OpenCLIP.")
    # force encode via warm path
    out = {}
    for bank, prompts in PROMPT_BANKS.items():
        vecs = []
        for p in prompts:
            v = encode_text_query(p)
            if v is None:
                # model just loaded — encode_text_query needs cache; retry after ensure
                from backend.services import clip_tagger as ct

                ct._model_cache = model
                ct._preprocess_cache = preprocess
                ct._tokenizer_cache = tokenizer
                v = encode_text_query(p)
            if v is not None:
                vecs.append(np.asarray(v, dtype=np.float32))
        if not vecs:
            raise SystemExit(f"Sem embeddings de texto para bank={bank}")
        m = _l2(np.mean(np.stack(vecs, axis=0), axis=0).astype(np.float32))
        out[bank] = m
        print(f"  bank {bank}: {len(vecs)} prompts")
    # concept centroids
    for concept in CONCEPT_TITLES:
        vecs = []
        for p in concept["prompts"]:
            v = encode_text_query(p)
            if v is not None:
                vecs.append(np.asarray(v, dtype=np.float32))
        concept["vec"] = _l2(np.mean(np.stack(vecs), axis=0).astype(np.float32)) if vecs else None
    return out


def _opencv_metrics(path: Path) -> dict:
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return {}
    h, w = img.shape[:2]
    if h < 8 or w < 8:
        return {}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # sharpness
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharp = min(1.0, lap / 550.0)
    # contrast / exposure
    contrast = float(gray.std()) / 80.0
    contrast = float(np.clip(contrast, 0, 1))
    mean = float(gray.mean()) / 255.0
    exposure = 1.0 - abs(mean - 0.48) * 1.6
    exposure = float(np.clip(exposure, 0, 1))
    # colorfulness (Hasler-like)
    b, g, r = cv2.split(img.astype(np.float32))
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    color_score = float(np.clip(colorfulness / 55.0, 0, 1))
    # edge energy / depth proxy
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float(edges.mean()) / 255.0
    # left-right symmetry (feature only)
    left = gray[:, : w // 2]
    right = cv2.flip(gray[:, w - w // 2 :], 1)
    mh = min(left.shape[0], right.shape[0])
    mw = min(left.shape[1], right.shape[1])
    if mh > 4 and mw > 4:
        a = left[:mh, :mw].astype(np.float32)
        b2 = right[:mh, :mw].astype(np.float32)
        corr = float(np.corrcoef(a.ravel(), b2.ravel())[0, 1])
        if np.isnan(corr):
            corr = 0.0
        symmetry = (corr + 1.0) / 2.0
    else:
        symmetry = 0.5
    # warm/cool
    warmth = float(np.clip((r.mean() - b.mean()) / 40.0 + 0.5, 0, 1))
    aspect = w / max(h, 1)
    return {
        "w": w,
        "h": h,
        "aspect": aspect,
        "sharp": sharp,
        "contrast": contrast,
        "exposure": exposure,
        "color": color_score,
        "edge": float(np.clip(edge_density * 4.0, 0, 1)),
        "symmetry": float(np.clip(symmetry, 0, 1)),
        "warmth": warmth,
        "technical": float(np.clip(0.45 * sharp + 0.3 * contrast + 0.25 * exposure, 0, 1)),
    }


def _face_score(det: float, fc: int, cx: float | None, cy: float | None) -> tuple[float, float]:
    det = float(det or 0)
    fc = int(fc or 0)
    face = det * 0.75
    if fc == 1:
        face += 0.18
    elif fc == 2:
        face += 0.14
    elif fc >= 5:
        face -= 0.12
    face = float(np.clip(face, 0, 1))
    # framing / thirds — not always center-best
    if cx is None or cy is None:
        comp_face = 0.5
    else:
        # distance to nearest third line
        thirds = (1 / 3, 2 / 3)
        dx = min(abs(float(cx) - t) for t in thirds + (0.5,))
        dy = min(abs(float(cy) - t) for t in thirds + (0.42,))
        comp_face = float(np.clip(1.0 - dx * 1.2 - dy * 0.9, 0, 1))
    return face, comp_face


def _clip01(x: float) -> float:
    return float(np.clip(x, 0, 1))


def _percentile_ranks(values: np.ndarray) -> np.ndarray:
    """Rank → [0,1] within corpus (average ranks for ties)."""
    order = values.argsort()
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.linspace(0.0, 1.0, len(values), endpoint=True)
    return ranks


def analyze_all(*, rebuild: bool = False) -> dict:
    """
    Two-pass scoring:
      1) raw CLIP sims + OpenCV + faces for every embedding
      2) percentile-normalize within corpus → WOW / final / portfolio_master
    """
    conn = _conn()
    ensure_scores_table(conn)
    banks = _encode_prompt_banks()

    rows = conn.execute(
        """
        SELECT m.id, m.nome, m.pasta, m.categoria, m.tags, m.destaque, m.estrelas,
               m.visualizacoes, e.embedding, e.updated_at AS emb_updated,
               COALESCE(f.face_count,0) AS face_count,
               COALESCE(f.det_score,0) AS det_score,
               f.face_cx, f.face_cy
        FROM media m
        JOIN media_embeddings e ON e.media_id = m.id
        LEFT JOIN media_faces f ON f.media_id = m.id
        WHERE m.tipo = 'image'
        ORDER BY m.id
        """
    ).fetchall()

    cached = {}
    if not rebuild:
        for r in conn.execute(
            "SELECT media_id, content_hash FROM media_curation_scores"
        ):
            cached[int(r["media_id"])] = r["content_hash"]

    print(f"[curator] candidates with embeddings: {len(rows)}")
    t0 = time.time()
    skipped = 0
    with_cv = 0
    raw_rows: list[dict] = []

    for r in rows:
        mid = int(r["id"])
        thumb = _thumb_for(mid)
        chash = _content_hash(mid, r["emb_updated"], thumb)
        if not rebuild and cached.get(mid) == chash:
            skipped += 1
            continue

        emb = _l2(np.frombuffer(r["embedding"], dtype=np.float32).astype(np.float64))
        wow = float(emb @ banks["wow"])
        aesthetic = float(emb @ banks["aesthetic"])
        composition_c = float(emb @ banks["composition"])
        light = float(emb @ banks["light"])
        moment = float(emb @ banks["moment"])
        neg = float(emb @ banks["negative"])
        # impact margin vs forgettable
        wow_margin = wow - neg

        face_s, face_comp = _face_score(r["det_score"], r["face_count"], r["face_cx"], r["face_cy"])
        cv = {}
        if thumb is not None:
            try:
                cv = _opencv_metrics(thumb)
                if cv:
                    with_cv += 1
            except Exception:
                cv = {}

        technical = float(cv.get("technical", 0.45))
        color_s = float(cv.get("color", 0.45))
        symmetry = float(cv.get("symmetry", 0.5))
        edge = float(cv.get("edge", 0.4))
        warmth = float(cv.get("warmth", 0.5))
        contrast = float(cv.get("contrast", 0.5))

        context = 0.25
        context += min(0.25, float(r["destaque"] or 0) * 0.12)
        context += min(0.2, float(r["estrelas"] or 0) * 0.05)
        if (r["tags"] or "").strip():
            context += 0.08
        if (r["categoria"] or "").strip():
            context += 0.06
        if _is_dump(r["pasta"] or "", r["nome"] or ""):
            context -= 0.55
        context = _clip01(context)

        raw_rows.append(
            {
                "mid": mid,
                "chash": chash,
                "wow": wow,
                "aesthetic": aesthetic,
                "composition_c": composition_c,
                "light": light,
                "moment": moment,
                "neg": neg,
                "wow_margin": wow_margin,
                "face_s": face_s,
                "face_comp": face_comp,
                "technical": technical,
                "color": color_s,
                "symmetry": symmetry,
                "edge": edge,
                "warmth": warmth,
                "contrast": contrast,
                "context": context,
                "pasta": r["pasta"],
                "nome": r["nome"],
                "face_count": int(r["face_count"] or 0),
                "det_score": float(r["det_score"] or 0),
                "has_cv": bool(cv),
                "aspect": cv.get("aspect"),
            }
        )
        if len(raw_rows) % 400 == 0:
            print(f"  … collected {len(raw_rows)} raw (+{skipped} cached)")

    if not raw_rows and skipped:
        print("[curator] all cached — nothing to recompute")
        conn.close()
        return {"analyzed": 0, "cached_skip": skipped, "with_opencv": 0, "total_with_embeddings": len(rows), "seconds": round(time.time() - t0, 1)}

    n = len(raw_rows)
    print(f"[curator] percentile-normalizing {n} rows…")
    keys = ["wow", "aesthetic", "composition_c", "light", "moment", "wow_margin", "face_s", "technical", "color", "edge", "warmth", "contrast"]
    pct = {k: _percentile_ranks(np.array([x[k] for x in raw_rows], dtype=np.float64)) for k in keys}
    # lower is better for neg
    pct["neg_inv"] = 1.0 - _percentile_ranks(np.array([x["neg"] for x in raw_rows], dtype=np.float64))

    batch: list[tuple] = []
    for i, x in enumerate(raw_rows):
        aes_p = float(pct["aesthetic"][i])
        wow_p = float(pct["wow"][i])
        margin_p = float(pct["wow_margin"][i])
        light_p = float(pct["light"][i])
        moment_p = float(pct["moment"][i])
        comp_p = float(pct["composition_c"][i])
        face_p = float(pct["face_s"][i])
        tech_p = float(pct["technical"][i])
        color_p = float(pct["color"][i])
        edge_p = float(pct["edge"][i])
        neg_p = float(pct["neg_inv"][i])  # high = less forgettable

        composition = _clip01(0.5 * comp_p + 0.25 * x["face_comp"] + 0.25 * edge_p)
        lighting = _clip01(0.7 * light_p + 0.15 * float(pct["warmth"][i]) + 0.15 * float(pct["contrast"][i]))

        wow_score = _clip01(
            0.34 * wow_p
            + 0.22 * margin_p
            + 0.16 * aes_p
            + 0.14 * lighting
            + 0.10 * moment_p
            + 0.08 * neg_p
        )
        final = _clip01(
            0.30 * wow_score
            + 0.14 * aes_p
            + 0.12 * composition
            + 0.12 * lighting
            + 0.10 * moment_p
            + 0.08 * face_p
            + 0.07 * tech_p
            + 0.04 * color_p
            + 0.03 * x["context"]
        )
        portfolio_master = _clip01(
            0.42 * wow_score
            + 0.18 * aes_p
            + 0.14 * lighting
            + 0.12 * moment_p
            + 0.08 * composition
            + 0.06 * face_p
        )

        shape = None
        if x["aspect"] is not None:
            shape = "l-wide" if x["aspect"] >= 1.45 else ("p-tall" if x["aspect"] <= 0.9 else "square")
        meta = {
            "wow_raw": round(x["wow"], 4),
            "neg_raw": round(x["neg"], 4),
            "wow_pct": round(wow_p, 4),
            "light_pct": round(light_p, 4),
            "moment_pct": round(moment_p, 4),
            "face_count": x["face_count"],
            "det_score": round(x["det_score"], 4),
            "pasta": x["pasta"],
            "nome": x["nome"],
            "has_cv": x["has_cv"],
            "aspect": x["aspect"],
            "shape": shape,
        }
        batch.append(
            (
                x["mid"],
                x["chash"],
                round(aes_p, 4),
                round(x["face_s"], 4),
                round(composition, 4),
                round(lighting, 4),
                round(color_p, 4),
                round(tech_p, 4),
                round(moment_p, 4),
                round(wow_score, 4),
                round(x["context"], 4),
                round(final, 4),
                round(portfolio_master, 4),
                round(x["symmetry"], 4),
                json.dumps(meta, ensure_ascii=False),
            )
        )
        if len(batch) >= 250:
            _flush_scores(conn, batch)
            batch.clear()
    if batch:
        _flush_scores(conn, batch)

    elapsed = time.time() - t0
    stats = {
        "analyzed": n,
        "cached_skip": skipped,
        "with_opencv": with_cv,
        "total_with_embeddings": len(rows),
        "seconds": round(elapsed, 1),
    }
    print(f"[curator] done: {stats}")
    conn.close()
    return stats


def _flush_scores(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO media_curation_scores(
            media_id, content_hash, aesthetic_score, face_score, composition_score,
            lighting_score, color_score, technical_score, moment_score, wow_score,
            context_score, final_score, portfolio_master, symmetry_score, meta_json, analyzed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(media_id) DO UPDATE SET
            content_hash=excluded.content_hash,
            aesthetic_score=excluded.aesthetic_score,
            face_score=excluded.face_score,
            composition_score=excluded.composition_score,
            lighting_score=excluded.lighting_score,
            color_score=excluded.color_score,
            technical_score=excluded.technical_score,
            moment_score=excluded.moment_score,
            wow_score=excluded.wow_score,
            context_score=excluded.context_score,
            final_score=excluded.final_score,
            portfolio_master=excluded.portfolio_master,
            symmetry_score=excluded.symmetry_score,
            meta_json=excluded.meta_json,
            analyzed_at=datetime('now')
        """,
        batch,
    )
    conn.commit()


def load_ranked(limit: int = 200) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT s.*, m.nome, m.pasta, m.categoria, m.tags, m.destaque, m.estrelas,
               e.embedding,
               COALESCE(f.face_count,0) AS face_count,
               COALESCE(f.det_score,0) AS det_score
        FROM media_curation_scores s
        JOIN media m ON m.id = s.media_id
        JOIN media_embeddings e ON e.media_id = m.id
        LEFT JOIN media_faces f ON f.media_id = m.id
        WHERE m.tipo='image'
        ORDER BY s.portfolio_master DESC, s.wow_score DESC, s.final_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        if _is_dump(r["pasta"] or "", r["nome"] or ""):
            continue
        emb = _l2(np.frombuffer(r["embedding"], dtype=np.float32).astype(np.float64))
        meta = {}
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except Exception:
            meta = {}
        thumb = _thumb_for(int(r["media_id"]))
        # dims
        w = h = 0
        if thumb:
            try:
                from PIL import Image

                with Image.open(thumb) as im:
                    w, h = im.size
            except Exception:
                pass
        if not w and meta.get("aspect"):
            w, h = (720, 480) if meta["aspect"] >= 1.2 else (720, 1080)
        if not w:
            w, h = 720, 960
        ratio = w / max(h, 1)
        shape = "l-wide" if ratio >= 1.45 else "p-tall"
        out.append(
            {
                "id": int(r["media_id"]),
                "nome": r["nome"],
                "pasta": r["pasta"] or "",
                "categoria": r["categoria"] or "",
                "wow": float(r["wow_score"]),
                "aesthetic": float(r["aesthetic_score"]),
                "composition": float(r["composition_score"]),
                "light": float(r["lighting_score"]),
                "moment": float(r["moment_score"]),
                "technical": float(r["technical_score"]),
                "final": float(r["final_score"]),
                "master": float(r["portfolio_master"]),
                "face_score": float(r["face_score"]),
                "face_count": int(r["face_count"] or 0),
                "det_score": float(r["det_score"] or 0),
                "vec": emb,
                "w": w,
                "h": h,
                "shape": shape,
                "thumb": thumb,
                "reason": _reason(r, meta),
            }
        )
    conn.close()
    return out


def _reason(r, meta: dict) -> str:
    bits = []
    if float(r["wow_score"]) >= 0.72:
        bits.append("impacto visual alto")
    if float(r["lighting_score"]) >= 0.65:
        bits.append("luz marcante")
    if float(r["moment_score"]) >= 0.6:
        bits.append("momento/emoção")
    if float(r["composition_score"]) >= 0.6:
        bits.append("composição forte")
    if float(r["face_score"]) >= 0.7:
        bits.append("retrato/enquadramento")
    if float(r["aesthetic_score"]) >= 0.65:
        bits.append("estética de portfólio")
    if not bits:
        bits.append("score composto sólido")
    return " + ".join(bits)


def diversify(
    ranked: list[dict],
    limit: int,
    near_thr: float = 0.92,
    *,
    max_per_pasta: int = 1,
) -> list[dict]:
    picked = []
    pasta_n: dict[str, int] = {}
    for it in ranked:
        pk = (it["pasta"] or "").strip().lower() or f"id:{it['id']}"
        if pasta_n.get(pk, 0) >= max_per_pasta:
            continue
        dup = False
        for k in picked:
            if it.get("vec") is None or k.get("vec") is None:
                continue
            if float(it["vec"] @ k["vec"]) >= near_thr:
                dup = True
                break
        if dup:
            continue
        picked.append(it)
        pasta_n[pk] = pasta_n.get(pk, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def _best_concept(item: dict) -> dict:
    best = CONCEPT_TITLES[0]
    best_s = -1.0
    for c in CONCEPT_TITLES:
        v = c.get("vec")
        if v is None:
            continue
        s = float(item["vec"] @ v)
        if s > best_s:
            best_s = s
            best = c
    return best


def curate_home(max_home: int = 22) -> dict:
    """Pick impactful chapters from full ranking. Barbara locked."""
    # ensure concept vecs
    need = any(c.get("vec") is None for c in CONCEPT_TITLES)
    if need:
        _encode_prompt_banks()

    ranked = load_ranked(400)
    top200 = ranked[:200]
    TOP_JSON.write_text(json.dumps(
        [
            {
                "id": x["id"],
                "master": x["master"],
                "wow": x["wow"],
                "final": x["final"],
                "pasta": x["pasta"],
                "nome": x["nome"],
                "reason": x["reason"],
            }
            for x in top200
        ],
        ensure_ascii=False,
        indent=2,
    ), encoding="utf-8")

    # thresholds after percentile calibration (top ~20% / ~8%)
    masters = [x for x in ranked if x["master"] >= 0.78]
    strong = [x for x in ranked if x["wow"] >= 0.70 or x["final"] >= 0.72]
    # prefer items with exportable thumb (or already exported)
    def has_visual(it: dict) -> bool:
        if it.get("thumb") and Path(it["thumb"]).exists():
            return True
        return (FOTOS / f"home_ed_{it['id']}.webp").exists()

    base = masters or strong or ranked
    base = [x for x in base if has_visual(x)] or base
    pool = diversify(base, limit=max(90, max_home * 5), max_per_pasta=1, near_thr=0.90)

    # opener: prefer silhouette/sunset among masters, else keep local cinematic opener if strong
    opener = {
        "id": 0,
        "path": OPENER_LOCAL,
        "shape": "l-hero",
        "w": 1024,
        "h": 682,
        "nome": "Silhueta",
        "manual": True,
        "reason": "abertura cinematográfica local — impacto imediato",
    }
    # if a DB photo beats local opener on light+wow silhouette-like, use it as first chapter lead instead
    # (keep local hero file — brand anchor)

    # group by concept
    buckets: dict[str, list[dict]] = {}
    for it in pool:
        c = _best_concept(it)
        buckets.setdefault(c["id"], []).append(it)

    # sort concepts by mean master of top members
    scored_concepts = []
    used_titles: set[str] = set()
    for c in CONCEPT_TITLES:
        members = buckets.get(c["id"], [])
        if len(members) < 3:
            continue
        members = sorted(members, key=lambda x: (-x["master"], -x["wow"]))
        members = diversify(members, limit=10, near_thr=0.90, max_per_pasta=1)
        if len(members) < 3:
            continue
        mean_m = float(np.mean([m["master"] for m in members[:5]]))
        title = next((t for t in c["titles"] if t not in used_titles), c["titles"][0])
        used_titles.add(title)
        scored_concepts.append((mean_m, c["id"], title, members))

    # narrative order when scores are close: luz → casal → retrato → resto
    preferred = {"luz": 0, "casal": 1, "retrato": 2, "movimento": 3, "mundo": 4}
    scored_concepts.sort(key=lambda x: (preferred.get(x[1], 9), -x[0]))
    # few strong chapters — QUALIDADE > QUANTIDADE
    chapters = []
    used_ids: set[int] = set()
    budget = max_home
    for mean_m, cid, title, members in scored_concepts:
        if len(chapters) >= 4:
            break
        take_n = 4 if cid in ("casal", "retrato") else 3
        take_n = min(take_n, budget)
        if take_n < 3:
            break
        photos = []
        for m in members:
            if m["id"] in used_ids:
                continue
            photos.append(m)
            used_ids.add(m["id"])
            if len(photos) >= take_n:
                break
        if len(photos) < 3:
            continue
        # rhythm: best wide first when available, then by master
        ordered = []
        wides = sorted([p for p in photos if p["shape"] == "l-wide"], key=lambda x: -x["master"])
        if wides:
            ordered.append(wides[0])
        for p in sorted(photos, key=lambda x: -x["master"]):
            if p not in ordered:
                ordered.append(p)
        ordered = ordered[:take_n]
        chapters.append(
            {
                "conceptId": cid,
                "editorialTitle": title,
                "meanMaster": round(mean_m, 4),
                "photos": ordered,
            }
        )
        budget -= len(ordered)

    # Barbara lock into retrato chapter
    inject_barbara(chapters, used_ids)

    # stats from DB
    conn = _conn()
    ensure_scores_table(conn)
    total = conn.execute("SELECT COUNT(*) FROM media_curation_scores").fetchone()[0]
    tech_ok = conn.execute(
        "SELECT COUNT(*) FROM media_curation_scores WHERE technical_score>=0.45"
    ).fetchone()[0]
    strong_n = conn.execute(
        "SELECT COUNT(*) FROM media_curation_scores WHERE wow_score>=0.70"
    ).fetchone()[0]
    master_n = conn.execute(
        "SELECT COUNT(*) FROM media_curation_scores WHERE portfolio_master>=0.78"
    ).fetchone()[0]
    conn.close()

    selected = []
    for ch in chapters:
        selected.extend(ch["photos"])

    report = {
        "total_analyzed": total,
        "technically_good": tech_ok,
        "visually_strong": strong_n,
        "portfolio_master": master_n,
        "candidates_final": len(pool),
        "selected_home": len(selected) + 1,
        "opener": opener,
        "chapters": [
            {
                "title": ch["editorialTitle"],
                "conceptId": ch["conceptId"],
                "meanMaster": ch["meanMaster"],
                "photos": [
                    {
                        "id": p["id"],
                        "path": _export_photo(p),
                        "shape": p["shape"],
                        "w": p["w"],
                        "h": p["h"],
                        "wow": p["wow"],
                        "aesthetic": p["aesthetic"],
                        "composition": p["composition"],
                        "moment": p["moment"],
                        "light": p["light"],
                        "master": p["master"],
                        "final": p["final"],
                        "pasta": p["pasta"],
                        "nome": p["nome"],
                        "reason": p["reason"],
                        "manualCurated": p.get("manualCurated", False),
                    }
                    for p in ch["photos"]
                ],
            }
            for ch in chapters
        ],
        "top10": [
            {
                "id": x["id"],
                "wow": x["wow"],
                "aesthetic": x["aesthetic"],
                "composition": x["composition"],
                "moment": x["moment"],
                "master": x["master"],
                "pasta": x["pasta"],
                "nome": x["nome"],
                "reason": x["reason"],
            }
            for x in top200[:10]
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report)
    return report


def inject_barbara(chapters: list[dict], used_ids: set[int]) -> None:
    barb = {
        "id": BARBARA_MEDIA_ID,
        "nome": "Barbara",
        "pasta": "Barbara",
        "shape": "p-tall",
        "w": 682,
        "h": 1024,
        "wow": 0.9,
        "aesthetic": 0.9,
        "composition": 0.88,
        "moment": 0.7,
        "light": 0.75,
        "master": 0.95,
        "final": 0.92,
        "thumb": FOTOS / "foto_barbara.png",
        "vec": None,
        "reason": "manualCurated — lock Barbara",
        "manualCurated": True,
    }
    # remove if present elsewhere
    for ch in chapters:
        ch["photos"] = [p for p in ch["photos"] if p["id"] != BARBARA_MEDIA_ID]
    target = next((ch for ch in chapters if ch["conceptId"] == "retrato"), None)
    if target is None and chapters:
        target = chapters[-1]
    if target is None:
        chapters.append(
            {
                "conceptId": "retrato",
                "editorialTitle": "Um lugar para ser",
                "meanMaster": 0.9,
                "photos": [barb],
            }
        )
        used_ids.add(BARBARA_MEDIA_ID)
        return
    # insert after wide opener of chapter
    photos = target["photos"]
    if photos and photos[0].get("shape") == "l-wide":
        photos.insert(1, barb)
    else:
        photos.insert(0, barb)
    # keep chapter lean
    target["photos"] = photos[:5]
    used_ids.add(BARBARA_MEDIA_ID)


def _export_photo(p: dict) -> str:
    mid = p["id"]
    if mid == BARBARA_MEDIA_ID or p.get("manualCurated"):
        return BARBARA_LOCAL
    dest = FOTOS / f"home_ed_{mid}.webp"
    if dest.exists() and dest.stat().st_size > 0:
        return f"fotos/{dest.name}"
    src = p.get("thumb") or _thumb_for(mid)
    if src is None:
        try:
            from backend.services.thumb_pipeline import ensure_thumb, TIER_MEDIUM
            from backend.models.database import get_media

            item = get_media(mid)
            if item:
                ensure_thumb(dict(item), TIER_MEDIUM)
            src = _thumb_for(mid)
        except Exception as e:
            print(f"[curator] thumb gen fail id={mid}: {e}")
    if src and src.exists():
        try:
            from PIL import Image

            with Image.open(src) as im:
                im = im.convert("RGB")
                im.save(dest, "WEBP", quality=84, method=4)
            return f"fotos/{dest.name}"
        except Exception:
            shutil.copy2(src, dest)
            return f"fotos/{dest.name}"
    return f"fotos/home_ed_{mid}.webp"


def print_report(report: dict) -> None:
    print("\n" + "=" * 37)
    print("HOME CURATION REPORT")
    print("=" * 37)
    print(f"\nTotal analisado: {report['total_analyzed']}")
    print(f"Fotos tecnicamente boas: {report['technically_good']}")
    print(f"Fotos visualmente fortes: {report['visually_strong']}")
    print(f"Portfolio Master: {report['portfolio_master']}")
    print(f"Candidatas finais: {report['candidates_final']}")
    print(f"Selecionadas para Home: {report['selected_home']}")
    print("\nTOP FOTOGRAFIAS\n")
    for i, x in enumerate(report.get("top10") or [], 1):
        print(f"#{i} id={x['id']} | {x.get('pasta')} | {x.get('nome')}")
        print(
            f"WOW: {x['wow']:.2f}  Aesthetic: {x['aesthetic']:.2f}  "
            f"Composition: {x['composition']:.2f}  Moment: {x['moment']:.2f}  Master: {x['master']:.2f}"
        )
        print(f"Motivo: {x['reason']}\n")
    print("CAPÍTULOS\n")
    for ch in report["chapters"]:
        print(f"· {ch['title']} ({ch['conceptId']}) n={len(ch['photos'])} meanMaster={ch['meanMaster']}")
        for p in ch["photos"]:
            print(f"   - {p['id']} {p['shape']} master={p['master']:.2f} · {p['reason']}")
    print("=" * 37)


def apply_home(report: dict) -> None:
    lines = []
    lines.append("    <!-- Abertura: impacto -->")
    lines.append(
        f'    <div class="gi l-hero rv" data-idx="0" data-src="{OPENER_LOCAL}">'
    )
    lines.append(
        f'      <img src="{OPENER_LOCAL}" alt="Casal em silhueta no pôr do sol" width="1024" height="682" loading="eager" decoding="async" fetchpriority="high"/>'
    )
    lines.append("    </div>")
    lines.append("")
    idx = 1
    media_paths = [{"path": OPENER_LOCAL, "title": "Silhueta"}]
    for ch in report["chapters"]:
        title = ch["title"]
        cid = ch["conceptId"]
        lines.append(
            f'    <div class="grid-break chapter-break" role="presentation" '
            f'data-category="{cid}" data-editorial-title="{title}" '
            f'aria-label="{title}"><span>{title}</span></div>'
        )
        for p in ch["photos"]:
            path = p["path"]
            shape = p.get("shape") or "p-tall"
            w = p.get("w") or 720
            h = p.get("h") or 1080
            manual = ' data-manual-curated="true"' if p.get("manualCurated") else ""
            mid = p["id"]
            alt = "Barbara" if p.get("manualCurated") else ""
            eager = "eager" if idx <= 2 else "lazy"
            prio = ' fetchpriority="low"' if idx <= 2 else ""
            if mid and mid != BARBARA_MEDIA_ID:
                srcset = (
                    f'/api/media/{mid}/thumb-small 320w, '
                    f'/api/media/{mid}/thumb-medium 800w, '
                    f'{path} 1200w'
                )
            elif mid == BARBARA_MEDIA_ID:
                srcset = f'/api/media/{mid}/thumb-medium 800w, {path} 1200w'
            else:
                srcset = ""
            sizes = (
                "(max-width:768px) 100vw, 48vw"
                if shape in ("l-wide", "l-hero")
                else "(max-width:768px) 48vw, 22vw"
            )
            srcset_attr = f' srcset="{srcset}" sizes="{sizes}"' if srcset else ""
            lines.append(
                f'    <div class="gi {shape} rv" data-idx="{idx}"{manual} data-media-id="{mid}">'
                f'<img src="{path}"{srcset_attr} alt="{alt}" width="{w}" height="{h}" '
                f'loading="{eager}" decoding="async"{prio}/></div>'
            )
            media_paths.append({"path": path, "title": title, "media_id": mid, "id": mid})
            idx += 1
        lines.append("")

    html = INDEX.read_text(encoding="utf-8")
    m = re.search(
        r'(<div class="grid galeria-trabalhos" id="galeriaTrabalhos">)(.*?)(</div>\s*</section>)',
        html,
        flags=re.S,
    )
    if not m:
        raise RuntimeError("galeriaTrabalhos not found")
    html = html[: m.start(2)] + "\n" + "\n".join(lines) + "\n  " + html[m.end(2) :]

    # video idxs
    def _vid(match, counter=[idx]):
        s = match.group(0)
        s2 = re.sub(r'data-idx="\d+"', f'data-idx="{counter[0]}"', s, count=1)
        counter[0] += 1
        return s2

    html = re.sub(
        r'<div class="gi v-wide rv" data-idx="\d+"[\s\S]*?</div>\s*(?=<div class="gi v-wide|<)',
        _vid,
        html,
        count=2,
    )
    # cache bust
    html = re.sub(r"main\.js\?v=[^\"']+", "main.js?v=20260810wow", html)
    html = re.sub(r"style\.css\?v=[^\"']+", "style.css?v=20260810wow", html)
    INDEX.write_text(html, encoding="utf-8")

    main = MAIN_JS.read_text(encoding="utf-8")
    pool = ["  /* Lightbox: medium thumbs (~800px) — nunca originais HD */", "  const mediaPool = ["]
    for p in media_paths:
        title = (p.get("title") or "Trabalho").replace("'", "\\'")
        path = p["path"]
        mid = p.get("media_id") or p.get("id")
        if mid and str(mid).isdigit() and int(mid) > 0:
            src = f"/api/media/{int(mid)}/thumb-medium"
            pool.append(
                f"    {{ type: 'img', src: '{src}', title: '{title}', mediaId: {int(mid)} }},"
            )
        else:
            pool.append(f"    {{ type: 'img', src: '{path}', title: '{title}' }},")
    pool.append(
        "    { type: 'video', src: 'videos/video_casamento21.mp4', title: 'O Beijo', poster: 'fotos/thumb_casamento21.jpg' },"
    )
    pool.append(
        "    { type: 'video', src: 'videos/VIDEORAPS.mp4', title: 'Sessão de Rap', poster: 'fotos/thumb_videoraps.jpg' },"
    )
    pool.append("  ];")
    main2, n = re.subn(
        r"  const mediaPool = \[[\s\S]*?\n  \];",
        "\n".join(pool),
        main,
        count=1,
    )
    if n != 1:
        raise RuntimeError("mediaPool replace failed")
    MAIN_JS.write_text(main2, encoding="utf-8")
    print(f"[curator] Applied Home -> {INDEX} (next video idx {idx})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline WOW Home curator — full archive")
    ap.add_argument("--rebuild", action="store_true", help="Recompute all scores")
    ap.add_argument("--apply", action="store_true", help="Write index.html + mediaPool")
    ap.add_argument("--max-home", type=int, default=22)
    ap.add_argument("--skip-analyze", action="store_true", help="Use existing score cache only")
    args = ap.parse_args(argv)

    if not args.skip_analyze:
        analyze_all(rebuild=args.rebuild)
    report = curate_home(max_home=args.max_home)
    if args.apply:
        apply_home(report)
    else:
        print("[curator] Dry-run. Re-run with --apply to write Home.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
