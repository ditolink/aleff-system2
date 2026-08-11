#!/usr/bin/env python3
"""Expand home Trabalhos chapters with deterministic DB+local picks; export static assets."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.models.database import _home_quality_score  # noqa: E402

DB = ROOT / "data" / "media.db"
FOTOS = ROOT / "frontend" / "fotos"
THUMBS_MED = ROOT / "data" / "thumbs" / "medium"
THUMBS_SMALL = ROOT / "data" / "thumbs" / "small"
OUT_JSON = ROOT / "scripts" / "_home_expand_selection.json"

USED_STEMS = {
    "foto_casal_por_do_sol",
    "foto41",
    "foto40",
    "foto_casal_reflexo",
    "foto_guitarra",
    "foto_cerca",
    "foto_barbara",
    "foto94",
    "foto10",
    "foto_motocross",
    "foto_batismo",
    "foto_familia",
    "foto_thalles",
    "foto_detonautas",
    "foto_jotaquest",
    "foto_show_unico",
    "foto_show_unico_marks",
    "aleff-hero",
    "aleff-profile",
    "thumb_casamento21",
    "thumb_videoraps",
    "contato-sanmuel",
}

# Target fill per chapter for 4-col masonry (W=2, T=1).
# Goal: each chapter ends with column sum % 4 == 0 and enough density.
CHAPTERS = {
    "casamentos": {
        "need_shapes": ["l-wide", "p-tall", "p-tall"],  # second row after existing W+T+T
        "hints": (
            "casament", "casal", "noiva", "noivo", "wedding", "pre-wedding",
            "cerimon", "alian", "buque", "buquê", "danca", "dança",
        ),
        "reject": ("motocross", "xadrez", "chess", "show", "palco", "bateria"),
        "local_prefer": {
            "l-wide": ["foto_casal_passarela.jpg", "foto_casal_estrada.jpg", "foto_evento.jpg"],
            "p-tall": ["foto_floral.png", "foto_gravata.png"],
        },
    },
    "ensaios": {
        # current W+T+T+T = 5 → add 3×T to complete second row of 4 talls under leftover
        "need_shapes": ["p-tall", "p-tall", "p-tall"],
        "hints": (
            "ensaio", "editorial", "retrato", "modelo", "lifestyle", "barbara",
            "fashion", "look", "studio", "estudio", "estúdio",
        ),
        "reject": ("casament", "batismo", "motocross", "show", "palco"),
        "local_prefer": {
            "p-tall": [
                "foto_floral.png",
                "foto_sorriso.png",
                "foto_cafe.png",
                "foto_gravata.png",
                "foto30.jpg",
                "foto55.jpg",
                "foto60.webp",
                "foto20.webp",
                "foto11i.jpg",
            ],
        },
    },
    "cidade": {
        "need_shapes": ["p-tall", "l-wide", "p-tall", "p-tall"],  # finish row + densify
        "hints": (
            "cidade", "rua", "urbano", "urban", "acao", "ação", "esporte",
            "moto", "pista", "movimento", "documental", "street", "skate",
            "bike", "corrida", "futebol", "basquete", "surf", "praia",
            "ponte", "sp", "sao paulo", "são paulo",
        ),
        "reject": ("casament", "noiva", "batismo", "xadrez", "chess", "familia", "família"),
        "local_prefer": {
            "p-tall": ["foto12.jpg"],  # will be rejected by visual/context if chess
            "l-wide": [],
        },
    },
    "familia": {
        "need_shapes": ["p-tall", "l-wide", "p-tall", "p-tall"],
        "hints": (
            "familia", "família", "infantil", "crianca", "criança", "batismo",
            "anivers", "bebe", "bebê", "kids", "filho", "filha", "mae", "mãe", "pai",
        ),
        "reject": ("motocross", "show", "palco", "xadrez", "chess"),
        "local_prefer": {
            "p-tall": ["foto_superman.png"],
            "l-wide": ["foto_evento.jpg"],
        },
    },
}


def stem(name: str) -> str:
    s = Path(name).stem.lower()
    return re.sub(r"\s*-\s*copia(\s*\(\d+\))?$", "", s)


def aspect_of(w: int, h: int) -> str:
    if w <= 0 or h <= 0:
        return "unknown"
    r = w / h
    if r >= 1.55:
        return "wide"
    if r >= 1.1:
        return "landscape"
    if r <= 0.9:
        return "portrait"
    return "square"


def shape_ok(shape: str, asp: str) -> float:
    if shape == "p-tall":
        return 1.0 if asp == "portrait" else (0.45 if asp == "square" else 0.0)
    if shape == "l-wide":
        return 1.0 if asp in ("wide", "landscape") else 0.0
    return 0.0


def blob(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("categoria", "pasta", "nome", "tags", "descricao", "localizacao")
    ).lower()


def hint_hits(text: str, hints) -> int:
    return sum(1 for h in hints if h.lower() in text)


def load_local():
    out = {}
    try:
        from PIL import Image
    except ImportError:
        Image = None
    for p in FOTOS.iterdir():
        if not p.is_file() or p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if "copia" in p.name.lower():
            continue
        st = stem(p.name)
        if st in USED_STEMS:
            continue
        w = h = 0
        if Image:
            try:
                with Image.open(p) as im:
                    w, h = im.size
            except Exception:
                continue
        out[p.name] = {"path": f"fotos/{p.name}", "w": w, "h": h, "stem": st, "source": "local"}
    return out


def load_db(limit=2000):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM media
            WHERE tipo='image'
            ORDER BY destaque DESC, estrelas DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
    ]
    conn.close()
    return rows


def score_local(shape, chapter, loc, used):
    if loc["stem"] in used:
        return None
    # hard reject chess for cidade
    if chapter == "cidade" and loc["stem"] in {"foto12"}:
        return None
    asp = aspect_of(loc["w"], loc["h"])
    am = shape_ok(shape, asp)
    if am < 0.5:
        return None
    cfg = CHAPTERS[chapter]
    text = loc["path"].lower()
    hits = hint_hits(text, cfg["hints"])
    rej = hint_hits(text, cfg["reject"])
    if rej:
        return None
    prefer = cfg["local_prefer"].get(shape, [])
    pref = 0.15 if Path(loc["path"]).name in prefer else 0.0
    cat = min(1.0, hits / 2.0) if hits else (0.55 if pref else 0.25)
    # local site assets already curated — strong prior when preferred
    sc = cat * 0.35 + am * 0.30 + 0.20 + pref + 0.05
    return {
        "source": "local",
        "path": loc["path"],
        "stem": loc["stem"],
        "media_id": None,
        "w": loc["w"],
        "h": loc["h"],
        "aspect": asp,
        "shape": shape,
        "score": round(sc, 4),
        "nome": Path(loc["path"]).name,
        "categoria": chapter,
        "pasta": "frontend/fotos",
    }


def score_db(shape, chapter, row, used_ids, used_stems):
    mid = int(row["id"])
    if mid in used_ids:
        return None
    nome = str(row.get("nome") or "")
    st = stem(nome)
    if st in used_stems or st in USED_STEMS:
        return None
    pasta = str(row.get("pasta") or "").lower()
    if any(x in pasta for x in ("sem edi", "originais", "separadas", "s.edit", "s edit")):
        return None
    text = blob(row)
    cfg = CHAPTERS[chapter]
    hits = hint_hits(text, cfg["hints"])
    rej = hint_hits(text, cfg["reject"])
    if rej:
        return None
    if hits < 1:
        return None
    w = int(row.get("width") or 0)
    h = int(row.get("height") or 0)
    # try thumb meta for dims
    if not w or not h:
        meta = THUMBS_MED / f"{mid}.json"
        if not meta.exists():
            meta = THUMBS_SMALL / f"{mid}.json"
        if meta.exists():
            try:
                meta_j = json.loads(meta.read_text(encoding="utf-8"))
                w = int(meta_j.get("w") or meta_j.get("width") or 0)
                h = int(meta_j.get("h") or meta_j.get("height") or 0)
            except Exception:
                pass
    asp = aspect_of(w, h)
    am = shape_ok(shape, asp)
    if am < 0.5:
        return None
    # must have exportable thumb
    thumb = None
    for tier in (THUMBS_MED, THUMBS_SMALL):
        for ext in (".webp", ".jpg", ".jpeg", ".png"):
            p = tier / f"{mid}{ext}"
            if p.exists():
                thumb = p
                break
        if thumb:
            break
    if not thumb:
        return None
    q = _home_quality_score(row)
    qn = min(1.0, max(0.0, q / 140.0))
    cat = min(1.0, hits / 3.0)
    sc = cat * 0.32 + am * 0.28 + qn * 0.25 + 0.08 + min(1.0, hits / 5.0) * 0.07
    if sc < 0.48:
        return None
    return {
        "source": "db",
        "path": None,
        "stem": st or f"media_{mid}",
        "media_id": mid,
        "w": w,
        "h": h,
        "aspect": asp,
        "shape": shape,
        "score": round(sc, 4),
        "nome": nome,
        "categoria": row.get("categoria") or "",
        "pasta": row.get("pasta") or "",
        "thumb": str(thumb),
        "q": round(q, 2),
    }


def export_pick(pick, chapter, slot_i):
    """Copy to frontend/fotos with stable name."""
    if pick["source"] == "local":
        return pick["path"], pick
    mid = pick["media_id"]
    src = Path(pick["thumb"])
    # stable deterministic filename
    safe_stem = re.sub(r"[^a-z0-9]+", "_", (pick["stem"] or f"id{mid}").lower()).strip("_")[:40]
    dest_name = f"home_{chapter}_{mid}_{safe_stem}{src.suffix.lower()}"
    dest = FOTOS / dest_name
    if not dest.exists():
        shutil.copy2(src, dest)
    # dims from image if missing
    if (not pick["w"] or not pick["h"]):
        try:
            from PIL import Image
            with Image.open(dest) as im:
                pick["w"], pick["h"] = im.size
                pick["aspect"] = aspect_of(pick["w"], pick["h"])
        except Exception:
            pass
    pick["path"] = f"fotos/{dest_name}"
    pick["exported"] = dest_name
    return pick["path"], pick


def main():
    locals_ = load_local()
    db_rows = load_db(2200)
    used_stems = set(USED_STEMS)
    used_ids: set[int] = set()

    report = {
        "previous_photos": 12,
        "chapters": {},
        "additions": [],
    }

    for chapter, cfg in CHAPTERS.items():
        ch_adds = []
        for shape in cfg["need_shapes"]:
            scored = []
            for loc in locals_.values():
                s = score_local(shape, chapter, loc, used_stems)
                if s:
                    scored.append(s)
            for row in db_rows:
                s = score_db(shape, chapter, row, used_ids, used_stems)
                if s:
                    scored.append(s)
            scored.sort(key=lambda x: (-x["score"], x.get("media_id") or 0, x["stem"]))
            top = scored[:20]
            chosen = None
            for cand in top:
                # prefer local when score close
                if cand["source"] == "local" and cand["score"] >= 0.55:
                    chosen = cand
                    break
            if not chosen and top and top[0]["score"] >= 0.55:
                chosen = top[0]
            if not chosen:
                ch_adds.append({
                    "shape": shape,
                    "status": "unfilled",
                    "top": [
                        {k: v for k, v in t.items() if k != "thumb"}
                        for t in top[:5]
                    ],
                })
                continue
            path, chosen = export_pick(chosen, chapter, len(ch_adds))
            used_stems.add(chosen["stem"])
            if chosen.get("media_id"):
                used_ids.add(int(chosen["media_id"]))
            # remove from local pool
            if chosen["source"] == "local":
                locals_.pop(Path(chosen["path"]).name, None)
            entry = {
                "chapter": chapter,
                "shape": shape,
                "path": path,
                "score": chosen["score"],
                "aspect": chosen["aspect"],
                "w": chosen["w"],
                "h": chosen["h"],
                "source": chosen["source"],
                "media_id": chosen.get("media_id"),
                "nome": chosen.get("nome"),
                "categoria": chosen.get("categoria"),
                "pasta": chosen.get("pasta"),
                "why": (
                    f"{chapter}/{shape}: score={chosen['score']} aspect={chosen['aspect']} "
                    f"src={chosen['source']} cat={chosen.get('categoria')} pasta={chosen.get('pasta')}"
                ),
            }
            ch_adds.append({"shape": shape, "status": "filled", **entry})
            report["additions"].append(entry)
        report["chapters"][chapter] = {
            "requested": len(cfg["need_shapes"]),
            "filled": sum(1 for x in ch_adds if x.get("status") == "filled"),
            "items": ch_adds,
        }

    report["final_photos"] = report["previous_photos"] + len(report["additions"])
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
