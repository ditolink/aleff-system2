#!/usr/bin/env python3
"""
Offline editorial Home curation from CLIP embeddings.

Does NOT run at page load. Produces:
  - scripts/editorial_home_selection.json
  - frontend/fotos/home_ed_*.webp (exports)
  - optionally rewrites Trabalhos in frontend/index.html (--apply)

Usage:
  python scripts/curate_editorial_home.py
  python scripts/curate_editorial_home.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "media.db"
MED = ROOT / "data" / "thumbs" / "medium"
SMALL = ROOT / "data" / "thumbs" / "small"
FOTOS = ROOT / "frontend" / "fotos"
OUT_JSON = ROOT / "scripts" / "editorial_home_selection.json"
INDEX = ROOT / "frontend" / "index.html"

# Manual locks
BARBARA_LOCAL = "fotos/foto_barbara.png"
BARBARA_MEDIA_ID = 2034
OPENER_LOCAL = "fotos/foto_casal_por_do_sol.jpg"

# Already featured in Pelo caminho — skip for Trabalhos
MARKS_STEMS = {
    "foto_thalles",
    "foto_detonautas",
    "foto_jotaquest",
    "foto_show_unico",
    "foto_show_unico_marks",
}
MARKS_NAME_HINTS = ("thalles", "detonautas", "jota quest", "jotaquest")

DUMP_PASTA = (
    "sem edi", "originais", "separadas", "s.edit", "s edit",
    "haloween s.edit", "fotos 13", "abril 2021",
    "logo", "logos", "marca", "marcas", "identidade", "branding",
    "design", "mockup", "vetor",
)

# Concept bank: keyword → candidate editorial titles (pick best by hit density)
CONCEPT_BANK = [
    {
        "id": "luz",
        "keys": ("por do sol", "contraluz", "silhueta", "luz dourada", "hora magica", "golden", "sunset", "backlight"),
        "titles": ("Quando a luz cai", "Antes que escureça", "Do outro lado da luz", "Luz baixa"),
    },
    {
        "id": "casal",
        "keys": ("casal", "casament", "noiva", "noivo", "romantico", "abraco", "beijo", "wedding", "pre wedding"),
        "titles": ("O tempo entre nós", "Só nós dois", "Promessas ao acaso", "De perto"),
    },
    {
        "id": "retrato",
        "keys": ("retrato", "editorial", "modelo", "close", "fashion", "ensaio", "olhar", "portrait"),
        "titles": ("Um lugar para ser", "Presença", "De frente", "Fora do enquadramento"),
    },
    {
        "id": "familia",
        "keys": ("familia", "infantil", "crianca", "bebe", "gestante", "aniversario", "batismo", "kids", "gravidez"),
        "titles": ("Laços", "Casa cheia", "Pequenos mundos", "Quem chega"),
    },
    {
        "id": "palco",
        "keys": ("show", "palco", "bateria", "microfone", "luzes de palco", "banda", "cantor", "concert", "stage"),
        "titles": ("Sob as luzes", "Quando a noite começa", "Entre luz e ruído", "Palco aberto"),
    },
    {
        "id": "cidade",
        "keys": ("cidade", "urbano", "rua", "ponte", "predio", "street", "moto", "esporte", "acao", "movimento"),
        "titles": ("Em movimento", "A cidade acontece", "Corpos em trânsito", "No caminho"),
    },
    {
        "id": "natureza",
        "keys": ("natureza", "praia", "campo", "jardim", "rio", "lago", "floresta", "externo"),
        "titles": ("Ar livre", "Onde o verde fica", "Fora de casa", "Horizonte perto"),
    },
    {
        "id": "noite",
        "keys": ("noturno", "neon", "noite", "night", "flash"),
        "titles": ("Depois do dia", "No escuro que ilumina", "Hora estranha"),
    },
    {
        "id": "gesto",
        "keys": ("danca", "movimento", "espontaneo", "risada", "alegria", "festa", "evento"),
        "titles": ("Depois do movimento", "Em passagem", "O que acontece no meio"),
    },
]


def stem(name: str) -> str:
    s = Path(name or "").stem.lower()
    return re.sub(r"\s*-\s*copia(\s*\(\d+\))?$", "", s)


def thumb_for(mid: int) -> Path | None:
    for tier in (MED, SMALL):
        for ext in (".webp", ".jpg", ".jpeg", ".png"):
            p = tier / f"{mid}{ext}"
            if p.exists():
                return p
    return None


def dims_for(mid: int, thumb: Path | None) -> tuple[int, int]:
    meta = MED / f"{mid}.json"
    if not meta.exists():
        meta = SMALL / f"{mid}.json"
    if meta.exists():
        try:
            j = json.loads(meta.read_text(encoding="utf-8"))
            w = int(j.get("w") or j.get("width") or j.get("ow") or 0)
            h = int(j.get("h") or j.get("height") or j.get("oh") or 0)
            if w and h:
                return w, h
        except Exception:
            pass
    if thumb:
        try:
            from PIL import Image
            with Image.open(thumb) as im:
                return im.size
        except Exception:
            pass
    return 0, 0


def aspect_label(w: int, h: int) -> str:
    if w <= 0 or h <= 0:
        return "unknown"
    r = w / h
    if r >= 1.45:
        return "wide"
    if r <= 0.9:
        return "portrait"
    return "square"


def shape_for(asp: str) -> str:
    return "l-wide" if asp in ("wide",) else "p-tall"


def load_candidates(limit: int = 900):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    # Prefer images that already have face + embedding; join thumbs availability later
    rows = conn.execute(
        """
        SELECT m.id, m.nome, m.pasta, m.categoria, m.tags, m.destaque, m.estrelas,
               m.visualizacoes, m.tamanho,
               COALESCE(f.face_count,0) AS face_count,
               COALESCE(f.det_score,0) AS det_score,
               e.embedding
        FROM media m
        JOIN media_embeddings e ON e.media_id = m.id
        LEFT JOIN media_faces f ON f.media_id = m.id
        WHERE m.tipo='image'
        ORDER BY m.destaque DESC, m.estrelas DESC, m.id ASC
        """
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        mid = int(r["id"])
        pasta = (r["pasta"] or "").lower()
        if any(d in pasta for d in DUMP_PASTA):
            continue
        nome = (r["nome"] or "").lower()
        if any(h in nome or h in pasta for h in MARKS_NAME_HINTS):
            continue
        if "captura de tela" in nome or "screenshot" in nome:
            continue
        if pasta.strip() in ("site (local)", "site"):
            continue
        if "logo" in pasta or "logo" in nome or "mockup" in pasta:
            continue
        if any(h in pasta for h in ("identidade", "branding", "marca", "design", "vetor")):
            continue
        th = thumb_for(mid)
        if not th:
            continue
        w, h = dims_for(mid, th)
        if not w or not h:
            continue
        blob = " ".join(
            str(r[k] or "") for k in ("categoria", "pasta", "nome", "tags")
        ).lower()
        vec = np.frombuffer(r["embedding"], dtype=np.float32).astype(np.float64)
        n = np.linalg.norm(vec)
        if n < 1e-8:
            continue
        vec = vec / n
        # quality prior
        q = (
            float(r["destaque"] or 0) * 20
            + float(r["estrelas"] or 0) * 8
            + min(float(r["det_score"] or 0), 1.0) * 10
            + min(int(r["face_count"] or 0), 3) * 1.5
            + min(int(r["visualizacoes"] or 0), 40) * 0.1
        )
        if (r["tags"] or "").strip():
            q += 6
        if (r["categoria"] or "").strip():
            q += 4
        out.append(
            {
                "id": mid,
                "nome": r["nome"],
                "pasta": r["pasta"] or "",
                "categoria": r["categoria"] or "",
                "tags": r["tags"] or "",
                "blob": blob,
                "vec": vec,
                "w": w,
                "h": h,
                "asp": aspect_label(w, h),
                "shape": shape_for(aspect_label(w, h)),
                "thumb": th,
                "q": q,
                "face_count": int(r["face_count"] or 0),
                "det_score": float(r["det_score"] or 0),
            }
        )
        if len(out) >= limit:
            break
    return out


def cluster_items(items: list[dict], n_clusters: int = 14):
    from sklearn.cluster import MiniBatchKMeans

    X = np.stack([it["vec"] for it in items], axis=0)
    # deterministic
    km = MiniBatchKMeans(
        n_clusters=n_clusters,
        random_state=42,
        batch_size=256,
        n_init=10,
        max_iter=200,
    )
    labels = km.fit_predict(X)
    centers = km.cluster_centers_
    # renormalize centers
    centers = centers / (np.linalg.norm(centers, axis=1, keepdims=True) + 1e-9)
    clusters: dict[int, list[dict]] = {}
    for it, lab in zip(items, labels):
        clusters.setdefault(int(lab), []).append(it)
    return clusters, centers


def pairwise_coherence(vecs: np.ndarray) -> float:
    if len(vecs) < 2:
        return 0.0
    sims = vecs @ vecs.T
    # upper triangle mean
    iu = np.triu_indices(len(vecs), k=1)
    return float(sims[iu].mean()) if iu[0].size else 0.0


def near_dup_filter(members: list[dict], thr: float = 0.93) -> list[dict]:
    kept = []
    for m in sorted(members, key=lambda x: -x["q"]):
        ok = True
        for k in kept:
            if float(m["vec"] @ k["vec"]) >= thr:
                ok = False
                break
        if ok:
            kept.append(m)
    return kept


def diversify(members: list[dict], limit: int) -> list[dict]:
    """Prefer quality but cap per pasta and balance wide/tall."""
    members = near_dup_filter(members)
    members = sorted(members, key=lambda x: -x["q"])
    picked = []
    pasta_count: dict[str, int] = {}
    wide_n = tall_n = 0
    for m in members:
        pk = (m["pasta"] or "").strip().lower() or f"id:{m['id']}"
        if pasta_count.get(pk, 0) >= 2:
            continue
        is_wide = m["shape"] == "l-wide"
        # soft balance: don't let one shape exceed the other by >3
        if is_wide and wide_n >= tall_n + 3 and tall_n + wide_n >= 2:
            continue
        if (not is_wide) and tall_n >= wide_n + 4 and tall_n + wide_n >= 2:
            continue
        picked.append(m)
        pasta_count[pk] = pasta_count.get(pk, 0) + 1
        if is_wide:
            wide_n += 1
        else:
            tall_n += 1
        if len(picked) >= limit:
            break
    return picked


def concept_for(members: list[dict]) -> dict:
    blob = " ".join(m["blob"] for m in members)
    best = None
    best_hits = -1
    for c in CONCEPT_BANK:
        hits = sum(1 for k in c["keys"] if k in blob)
        if hits > best_hits:
            best_hits = hits
            best = c
    return {"concept": best, "hits": best_hits}


def pick_title(used_titles: set[str], concept: dict | None, members: list[dict]) -> str:
    titles = []
    if concept and concept.get("titles"):
        titles.extend(concept["titles"])
    # fallbacks from atmosphere
    titles.extend(("Em passagem", "De perto", "Silêncio entre cenas", "Fora do centro"))
    for t in titles:
        if t not in used_titles:
            used_titles.add(t)
            return t
    # last resort
    t = f"Capítulo {len(used_titles) + 1}"
    used_titles.add(t)
    return t


def block_scores(members: list[dict], coherence: float) -> dict:
    if not members:
        return {"blockScore": 0}
    qs = [m["q"] for m in members]
    pastas = { (m["pasta"] or "").lower() for m in members }
    asps = {m["asp"] for m in members}
    quality = float(np.mean(qs)) / 40.0
    quality = min(1.0, max(0.0, quality))
    diversity = min(1.0, (len(pastas) / max(1, len(members))) * 0.7 + (len(asps) / 3) * 0.3)
    quantity = min(1.0, len(members) / 8.0)
    identity = coherence
    layout = 1.0 if len(members) >= 4 else len(members) / 4.0
    block = (
        coherence * 0.30
        + quality * 0.25
        + diversity * 0.15
        + identity * 0.15
        + quantity * 0.10
        + layout * 0.05
    )
    return {
        "coherenceScore": round(coherence, 4),
        "qualityScore": round(quality, 4),
        "diversityScore": round(diversity, 4),
        "visualIdentityScore": round(identity, 4),
        "quantityScore": round(quantity, 4),
        "layoutScore": round(layout, 4),
        "blockScore": round(block, 4),
    }


def order_for_story(members: list[dict]) -> list[dict]:
    """Opening (strong wide or best), then alternate, end with intimate/portrait."""
    if not members:
        return []
    wides = [m for m in members if m["shape"] == "l-wide"]
    talls = [m for m in members if m["shape"] != "l-wide"]
    wides.sort(key=lambda x: -x["q"])
    talls.sort(key=lambda x: -x["q"])
    ordered = []
    if wides:
        ordered.append(wides.pop(0))
    elif talls:
        ordered.append(talls.pop(0))
    # development: interleave
    while wides or talls:
        if talls:
            ordered.append(talls.pop(0))
        if wides:
            ordered.append(wides.pop(0))
    return ordered


def complete_masonry(
    ordered: list[dict],
    pool: list[dict],
    used_ids: set[int],
    *,
    fill: bool = False,
) -> list[dict]:
    """
    Optionally pad masonry spans. Default OFF (vitrine):
    never add a photo just to fill a hole — QUALIDADE > QUANTIDADE.
    """
    if not fill:
        return list(ordered)

    def span_sum(items):
        s = 0
        for it in items:
            s += 2 if it["shape"] == "l-wide" else 1
        return s

    out = list(ordered)
    leftovers = [m for m in pool if m["id"] not in used_ids and m["id"] not in {x["id"] for x in out}]
    leftovers = sorted(leftovers, key=lambda x: -x["q"])
    # try up to 3 additions
    for _ in range(4):
        rem = span_sum(out) % 4
        if rem == 0 and len(out) >= 4:
            break
        need = 4 - rem if rem else 0
        if need == 0 and len(out) < 4:
            need = 4 - span_sum(out)
        # prefer tall (1) to fill 1 or 3; wide for 2
        cand = None
        if need % 2 == 1 or need == 3 or need == 1:
            cand = next((m for m in leftovers if m["shape"] == "p-tall"), None)
        if cand is None and need >= 2:
            cand = next((m for m in leftovers if m["shape"] == "l-wide"), None)
        if cand is None:
            cand = leftovers[0] if leftovers else None
        if cand is None:
            break
        # quality gate — don't add mediocre fillers
        if cand["q"] < 8 and len(out) >= 4 and rem == 0:
            break
        if cand["q"] < 6:
            leftovers.remove(cand)
            continue
        out.append(cand)
        leftovers.remove(cand)
    return out


def export_item(item: dict) -> dict:
    mid = item["id"]
    src = item["thumb"]
    dest_name = f"home_ed_{mid}.webp"
    if src.suffix.lower() != ".webp":
        dest_name = f"home_ed_{mid}{src.suffix.lower()}"
    dest = FOTOS / dest_name
    if not dest.exists() or dest.stat().st_size == 0:
        shutil.copy2(src, dest)
    return {
        **{k: v for k, v in item.items() if k not in ("vec", "thumb", "blob")},
        "path": f"fotos/{dest_name}",
        "media_id": mid,
    }


def find_barbara_item(items: list[dict]) -> dict | None:
    for it in items:
        if it["id"] == BARBARA_MEDIA_ID:
            return it
    return None


def appearance_score(m: dict) -> float:
    """Face/appearance prior for opening masonry row (det_score + framing + 1–2 faces)."""
    det = float(m.get("det_score") or 0)
    fc = int(m.get("face_count") or 0)
    asp = float(m.get("w") or 1) / max(1, float(m.get("h") or 1))
    appear = (
        det * 55
        + min(fc, 2) * 4
        + float(m.get("destaque") or 0) * 12
        + float(m.get("estrelas") or 0) * 6
        + float(m.get("q") or 0) * 0.15
        + (8 if 0.7 <= asp <= 0.85 or 1.4 <= asp <= 1.8 else 0)
    )
    if fc == 1:
        appear += 10
    elif fc == 2:
        appear += 8
    elif fc >= 5:
        appear -= 8
    return appear


def inject_barbara(chapters: list[dict], items: list[dict], used: set[int]):
    """Force Barbara into retrato chapter (preferred) or best cosine match."""
    barb = find_barbara_item(items)
    local_entry = {
        "id": BARBARA_MEDIA_ID,
        "path": BARBARA_LOCAL,
        "shape": "p-tall",
        "asp": "portrait",
        "w": 682,
        "h": 1024,
        "nome": "Barbara",
        "categoria": "editorial",
        "pasta": "Barbara",
        "q": 99,
        "manualCurated": True,
        "media_id": BARBARA_MEDIA_ID,
        "source": "manual",
    }
    for c in chapters:
        c["photos"] = [p for p in c["photos"] if (p.get("media_id") or p.get("id")) != BARBARA_MEDIA_ID]
        c["hasBarbara"] = False

    target_i = next((i for i, ch in enumerate(chapters) if ch.get("conceptId") == "retrato"), None)
    if target_i is None and barb is not None:
        best_i, best_sim = 0, -1.0
        for i, ch in enumerate(chapters):
            ids = [p.get("media_id") or p.get("id") for p in ch["photos"]]
            vecs = [it["vec"] for it in items if it["id"] in ids]
            if not vecs:
                continue
            mean = np.mean(np.stack(vecs), axis=0)
            mean = mean / (np.linalg.norm(mean) + 1e-9)
            sim = float(barb["vec"] @ mean)
            if sim > best_sim:
                best_sim = sim
                best_i = i
        target_i = best_i
    if target_i is None:
        target_i = 0 if chapters else None
    if target_i is None:
        return
    ch = chapters[target_i]
    photos = ch["photos"]
    if photos and photos[0].get("shape") == "l-wide":
        photos.insert(1, local_entry)
    else:
        photos.insert(0, local_entry)
    # vitrine soft-cap — few strong photos
    ch["photos"] = photos[:4]
    ch["hasBarbara"] = True
    used.add(BARBARA_MEDIA_ID)


def promote_first_row_appearance(chapters: list[dict], items: list[dict], used: set[int]):
    """
    First masonry row after hero = best appearance (l-wide + Barbara + p-tall).
    Uses face det_score / face_count prior; Barbara stays locked as a tall.
    """
    if not chapters:
        return
    target_i = next((i for i, ch in enumerate(chapters) if ch.get("hasBarbara")), 0)
    ch = chapters[target_i]
    by_id = {it["id"]: it for it in items}

    def as_photo(it: dict) -> dict:
        mid = it["id"]
        if mid == BARBARA_MEDIA_ID:
            return {
                "id": BARBARA_MEDIA_ID,
                "path": BARBARA_LOCAL,
                "shape": "p-tall",
                "asp": "portrait",
                "w": 682,
                "h": 1024,
                "nome": "Barbara",
                "pasta": "Barbara",
                "q": 99,
                "manualCurated": True,
                "media_id": BARBARA_MEDIA_ID,
                "source": "manual",
                "det_score": it.get("det_score", 0),
                "face_count": it.get("face_count", 1),
            }
        return export_item(it)

    # Candidate pool: unused + current chapter (exclude Barbara for scoring picks)
    pool = []
    chapter_ids = {(p.get("media_id") or p.get("id")) for p in ch["photos"]}
    for it in items:
        mid = it["id"]
        if mid == BARBARA_MEDIA_ID:
            continue
        if mid in used and mid not in chapter_ids:
            continue
        pool.append(it)
    def row_rank(it: dict) -> float:
        # Opening row favors clear solo / couple faces over group candids
        s = appearance_score(it)
        fc = int(it.get("face_count") or 0)
        if fc == 1:
            s += 16
        elif fc == 2:
            s += 6
        return s

    pool.sort(key=row_rank, reverse=True)

    best_wide = next((it for it in pool if it.get("shape") == "l-wide"), None)
    best_tall = next(
        (
            it
            for it in pool
            if it.get("shape") == "p-tall"
            and (best_wide is None or it["id"] != best_wide["id"])
            and (it.get("pasta") or "").lower() != ((best_wide or {}).get("pasta") or "").lower()
        ),
        None,
    )
    if best_wide is None or best_tall is None:
        return

    if BARBARA_MEDIA_ID in by_id:
        barb_fallback = as_photo(by_id[BARBARA_MEDIA_ID])
    else:
        barb_fallback = {
            "id": BARBARA_MEDIA_ID,
            "path": BARBARA_LOCAL,
            "shape": "p-tall",
            "asp": "portrait",
            "w": 682,
            "h": 1024,
            "nome": "Barbara",
            "pasta": "Barbara",
            "q": 99,
            "manualCurated": True,
            "media_id": BARBARA_MEDIA_ID,
            "source": "manual",
        }
    barb_photo = next(
        (p for p in ch["photos"] if (p.get("media_id") or p.get("id")) == BARBARA_MEDIA_ID),
        barb_fallback,
    )

    first_ids = {best_wide["id"], BARBARA_MEDIA_ID, best_tall["id"]}
    rest = [
        p
        for p in ch["photos"]
        if (p.get("media_id") or p.get("id")) not in first_ids
    ]
    ch["photos"] = [as_photo(best_wide), barb_photo, as_photo(best_tall)] + rest
    ch["photos"] = ch["photos"][:4]
    used.add(best_wide["id"])
    used.add(best_tall["id"])
    # Drop these ids from later chapters to avoid dupes
    for other in chapters:
        if other is ch:
            continue
        other["photos"] = [
            p
            for p in other["photos"]
            if (p.get("media_id") or p.get("id")) not in first_ids
        ]


def render_html_chapters(opener_path: str, chapters: list[dict]) -> str:
    lines = []
    lines.append("    <!-- Abertura: âncora única -->")
    lines.append(
        f'    <div class="gi l-hero rv" data-idx="0" data-src="{opener_path}">'
    )
    lines.append(
        f'      <img src="{opener_path}" alt="Casal em silhueta no pôr do sol" width="1024" height="682" loading="eager" decoding="async" fetchpriority="high"/>'
    )
    lines.append("    </div>")
    lines.append("")
    idx = 1
    for ch in chapters:
        cat = ch.get("categoryKey") or ch.get("conceptId") or "editorial"
        title = ch["editorialTitle"]
        aria = f'{cat} — {title}'
        lines.append(
            f'    <div class="grid-break chapter-break" role="presentation" '
            f'data-category="{cat}" data-editorial-title="{title}" '
            f'aria-label="{aria}"><span>{title}</span></div>'
        )
        for p in ch["photos"]:
            shape = p.get("shape") or "p-tall"
            path = p["path"]
            w = p.get("w") or 720
            h = p.get("h") or 1080
            alt = (p.get("nome") or title).replace('"', "")
            manual = ' data-manual-curated="true"' if p.get("manualCurated") else ""
            mid = p.get("media_id") or p.get("id") or ""
            mid_attr = f' data-media-id="{mid}"' if mid != "" else ""
            lines.append(
                f'    <div class="gi {shape} rv" data-idx="{idx}"{manual}{mid_attr}>'
                f'<img src="{path}" alt="{alt}" width="{w}" height="{h}" loading="lazy" decoding="async"/></div>'
            )
            idx += 1
        lines.append("")
    return "\n".join(lines), idx


def apply_to_index(chapters_html: str, next_idx: int, media_paths: list[dict]):
    html = INDEX.read_text(encoding="utf-8")
    # replace gallery inner content between galeriaTrabalhos and closing
    m = re.search(
        r'(<div class="grid galeria-trabalhos" id="galeriaTrabalhos">)(.*?)(</div>\s*</section>)',
        html,
        flags=re.S,
    )
    if not m:
        raise RuntimeError("galeriaTrabalhos not found")
    new_inner = "\n" + chapters_html + "\n  "
    html = html[: m.start(2)] + new_inner + html[m.end(2) :]

    # fix video idxs (both tiles in #galeriaVideos)
    def _vid_idx(match, idxs=[next_idx]):
        i = idxs[0]
        idxs[0] = i + 1
        return f'{match.group(1)}{i}{match.group(3)}'

    html = re.sub(
        r'(id="galeriaVideos">[\s\S]*?</section>)',
        lambda m: re.sub(
            r'(<div class="gi v-wide rv" data-idx=")(\d+)(")',
            _vid_idx,
            m.group(0),
        ),
        html,
        count=1,
    )
    # cache bust
    html = re.sub(r"main\.js\?v=[^\"']+", "main.js?v=20260810edit2", html)
    html = re.sub(r"style\.css\?v=[^\"']+", "style.css?v=20260810edit2", html)
    INDEX.write_text(html, encoding="utf-8")

    # update mediaPool in main.js
    main = (ROOT / "frontend" / "js" / "main.js").read_text(encoding="utf-8")
    pool_entries = []
    for p in media_paths:
        title = (p.get("title") or p.get("nome") or "Trabalho").replace("'", "\\'")
        src = p["path"]
        pool_entries.append(f"    {{ type: 'img', src: '{src}', title: '{title}' }},")
    pool_entries.append("    { type: 'video', src: 'videos/video_casamento21.mp4', title: 'O Beijo' },")
    pool_entries.append("    { type: 'video', src: 'videos/VIDEORAPS.mp4', title: 'Sessão de Rap' },")
    new_pool = "  const mediaPool = [\n" + "\n".join(pool_entries) + "\n  ];"
    main2, n = re.subn(
        r"  const mediaPool = \[[\s\S]*?\n  \];",
        new_pool,
        main,
        count=1,
    )
    if n != 1:
        raise RuntimeError("mediaPool replace failed")
    (ROOT / "frontend" / "js" / "main.js").write_text(main2, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(
        description="Offline Home vitrine curator. QUALIDADE > QUANTIDADE — never fill holes."
    )
    ap.add_argument("--apply", action="store_true", help="Rewrite index.html + main.js")
    ap.add_argument("--clusters", type=int, default=14)
    ap.add_argument("--min-block", type=float, default=0.48, help="Strict block score gate")
    ap.add_argument("--max-chapters", type=int, default=3, help="Few strong chapters")
    ap.add_argument("--max-photos", type=int, default=14, help="Total photos excl. opener")
    ap.add_argument("--per-chapter", type=int, default=4, help="Max photos per chapter")
    ap.add_argument(
        "--fill-masonry",
        action="store_true",
        help="DEPRECATED for vitrine: pad spans with extra photos (off by default)",
    )
    args = ap.parse_args()

    print("Loading candidates with thumbs + embeddings…")
    items = load_candidates(limit=850)
    print(f"  candidates: {len(items)}")
    if len(items) < 20:
        raise SystemExit("Too few candidates with thumbs")

    clusters, centers = cluster_items(items, n_clusters=args.clusters)
    print(f"  raw clusters: {len(clusters)}")

    scored_blocks = []
    for lab, members in clusters.items():
        members = diversify(members, limit=12)
        # identity precisa de pelo menos 3 fortes — não forçar 4 para “completar”
        if len(members) < 3:
            continue
        vecs = np.stack([m["vec"] for m in members], axis=0)
        coh = pairwise_coherence(vecs)
        scores = block_scores(members, coh)
        if scores["blockScore"] < args.min_block:
            continue
        if coh < 0.26:
            continue
        info = concept_for(members)
        scored_blocks.append(
            {
                "label": lab,
                "members": members,
                "scores": scores,
                "concept": info["concept"],
                "conceptHits": info["hits"],
            }
        )

    scored_blocks.sort(key=lambda b: (-b["scores"]["blockScore"], -b["conceptHits"]))

    used_ids: set[int] = set()
    used_titles: set[str] = set()
    used_concepts: set[str] = set()
    chapters = []
    max_photos_total = args.max_photos
    photos_budget = 0
    min_chapter = 3

    for b in scored_blocks:
        if len(chapters) >= args.max_chapters:
            break
        if photos_budget >= max_photos_total:
            break
        concept = b["concept"]
        cid = concept["id"] if concept else f"misc-{b['label']}"
        # one chapter per visual concept (avoid Casal 1 / Casal 2)
        if cid in used_concepts and not cid.startswith("misc"):
            continue
        title = pick_title(used_titles, concept, b["members"])
        pool = [m for m in b["members"] if m["id"] not in used_ids]
        if len(pool) < min_chapter:
            continue
        per_chapter = min(args.per_chapter, max_photos_total - photos_budget)
        if per_chapter < min_chapter:
            break
        selected = diversify(pool, limit=per_chapter)
        ordered = order_for_story(selected)
        ordered = complete_masonry(ordered, pool, used_ids, fill=args.fill_masonry)
        ordered = ordered[:per_chapter]
        if len(ordered) < min_chapter:
            continue
        # drop weak tails — não manter mediana só para tamanho
        q_med = float(np.median([m["q"] for m in ordered]))
        ordered = [m for m in ordered if m["q"] >= max(6.0, q_med * 0.55)]
        if len(ordered) < min_chapter:
            continue
        photos = []
        for m in ordered:
            if m["id"] in used_ids:
                continue
            exp = export_item(m)
            photos.append(exp)
            used_ids.add(m["id"])
        if len(photos) < min_chapter:
            continue
        used_concepts.add(cid)
        photos_budget += len(photos)
        chapters.append(
            {
                "editorialTitle": title,
                "conceptId": cid,
                "categoryKey": cid,
                "scores": b["scores"],
                "photos": photos,
                "size": len(photos),
            }
        )

    # Barbara lock + first-row appearance (face quality)
    inject_barbara(chapters, items, used_ids)
    promote_first_row_appearance(chapters, items, used_ids)

    # Ensure opener exists (local)
    opener = OPENER_LOCAL
    if not (ROOT / "frontend" / opener).exists() and not (FOTOS / Path(opener).name).exists():
        opener = chapters[0]["photos"][0]["path"] if chapters else OPENER_LOCAL

    report = {
        "candidates": len(items),
        "chapters": len(chapters),
        "photoCount": sum(len(c["photos"]) for c in chapters) + 1,
        "opener": opener,
        "barbaraLocked": True,
        "barbaraPath": BARBARA_LOCAL,
        "chaptersDetail": [
            {
                "editorialTitle": c["editorialTitle"],
                "conceptId": c["conceptId"],
                "scores": c["scores"],
                "hasBarbara": c.get("hasBarbara", False),
                "photos": [
                    {
                        "path": p["path"],
                        "media_id": p.get("media_id") or p.get("id"),
                        "shape": p.get("shape"),
                        "manualCurated": p.get("manualCurated", False),
                        "pasta": p.get("pasta"),
                        "categoria": p.get("categoria"),
                    }
                    for p in c["photos"]
                ],
            }
            for c in chapters
        ],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("candidates", "chapters", "photoCount")}, indent=2))
    for c in chapters:
        print(f"  · {c['editorialTitle']} ({c['conceptId']}) n={len(c['photos'])} score={c['scores']['blockScore']}")

    if args.apply:
        html_block, next_idx = render_html_chapters(opener, chapters)
        media_paths = [{"path": opener, "title": "Silhueta Dourada", "nome": "Silhueta"}]
        for c in chapters:
            for p in c["photos"]:
                media_paths.append(
                    {
                        "path": p["path"],
                        "title": p.get("nome") or c["editorialTitle"],
                        "nome": p.get("nome"),
                    }
                )
        apply_to_index(html_block, next_idx, media_paths)
        print(f"Applied to {INDEX} (next video idx {next_idx})")
    else:
        print("Dry-run only. Re-run with --apply to write Home.")


if __name__ == "__main__":
    main()
