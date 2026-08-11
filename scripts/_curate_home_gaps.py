#!/usr/bin/env python3
"""Deterministic home gap curation against media.db + local frontend/fotos."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.models.database import (  # noqa: E402
    _home_quality_score,
    _quality_score,
    to_search_card,
)

DB = ROOT / "data" / "media.db"
INDEX = ROOT / "frontend" / "index.html"
FOTOS = ROOT / "frontend" / "fotos"

# Home tiles (manual curation) — basename stems
USED_LOCAL = {
    "foto_casal_por_do_sol",
    "foto_thalles",
    "foto_detonautas",
    "foto_jotaquest",
    "foto_show_unico",
    "foto41",
    "foto40",
    "foto_guitarra",
    "foto_cerca",
    "foto94",
    "foto10",
    "foto_motocross",
    "foto_batismo",
    "foto_show_unico_marks",  # marks section
    "aleff-hero",
    "aleff-profile",
    "thumb_casamento21",
    "thumb_videoraps",
    "contato-sanmuel",
}

# Chapter gaps inferred from 4-col masonry packing:
# - Shows: 4×p-tall → complete
# - Ensaios: l-wide + 2×p-tall → complete
# - Casamentos: l-wide + 1×p-tall → missing 1×p-tall (span 1)
# - Cidade: l-wide + 1×p-tall → missing 1×p-tall
# - Família: 1×l-wide alone → missing companion (prefer p-tall for breath)

GAPS = [
    {
        "id": "casamentos_companion_tall",
        "chapter": "Casamentos",
        "after_idx": 6,
        "shape": "p-tall",
        "aspect": "portrait",  # ~3:4
        "hints": ("casamento", "casais", "ensaio", "wedding", "noiva", "casal"),
        "reject_hints": ("infantil", "anivers", "halloween", "motocross", "show", "palco"),
        "neighbor_stems": ("foto41", "foto40", "foto_casal_por_do_sol"),
        "prefer_local": (
            "foto_casal_reflexo.png",
            "foto_casal_passarela.jpg",
            "foto_casal_estrada.jpg",
            "foto_floral.png",
        ),
        # passarela/estrada are landscape — only reflexo is true tall among prefer_local
        "min_score": 0.55,
    },
    {
        "id": "cidade_companion_tall",
        "chapter": "Cidade & ação",
        "after_idx": 11,
        "shape": "p-tall",
        "aspect": "portrait",
        "hints": ("acao", "ação", "pista", "esporte", "motocross", "cidade", "rua", "lifestyle", "urbano"),
        "reject_hints": ("casamento", "batismo", "infantil", "show", "palco", "noiva"),
        "neighbor_stems": ("foto10", "foto_motocross"),
        "prefer_local": ("foto12.jpg", "foto_evento.jpg"),
        "min_score": 0.55,
    },
    {
        "id": "familia_companion",
        "chapter": "Família",
        "after_idx": 12,
        "shape": "p-tall",
        "aspect": "portrait",
        "hints": ("familia", "família", "batismo", "infantil", "crianca", "criança", "evento"),
        "reject_hints": ("show", "palco", "motocross", "nude"),
        "neighbor_stems": ("foto_batismo",),
        "prefer_local": ("foto_familia.png", "foto_superman.png", "foto_evento.jpg"),
        "min_score": 0.52,
    },
]


def stem(name: str) -> str:
    p = Path(name)
    s = p.stem.lower()
    s = re.sub(r"\s*-\s*copia(\s*\(\d+\))?$", "", s)
    return s


def aspect_of(w: int, h: int) -> str:
    if w <= 0 or h <= 0:
        return "unknown"
    r = w / h
    if r >= 1.7:
        return "wide"
    if r >= 1.15:
        return "landscape"
    if r <= 0.85:
        return "portrait"
    return "square"


def aspect_match(want: str, got: str) -> float:
    if want == got:
        return 1.0
    if want == "portrait" and got == "square":
        return 0.55
    if want == "landscape" and got in ("wide", "square"):
        return 0.7
    if want == "wide" and got == "landscape":
        return 0.75
    return 0.05


def blob_of(row) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in ("categoria", "pasta", "nome", "tags", "descricao", "ai_tags", "clip_tags")
    ).lower()


def hint_score(blob: str, hints, rejects) -> tuple[float, float]:
    hit = 0
    for h in hints:
        if h.lower() in blob:
            hit += 1
    rej = 0
    for h in rejects:
        if h.lower() in blob:
            rej += 1
    cat = min(1.0, hit / max(1, min(3, len(hints))))
    return cat, rej


def load_local_dims():
    out = {}
    try:
        from PIL import Image
    except ImportError:
        return out
    for p in FOTOS.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        st = stem(p.name)
        if st in USED_LOCAL or "copia" in p.name.lower():
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
            out[p.name] = {"path": f"fotos/{p.name}", "w": w, "h": h, "stem": st}
        except Exception:
            continue
    return out


def query_db_candidates(limit=400):
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(media)")}
    mime_clause = "1=1"
    if "mime_type" in cols:
        mime_clause = "(mime_type LIKE 'image%' OR mime_type IS NULL OR mime_type='')"
    if "tipo" in cols:
        mime_clause = f"({mime_clause} OR tipo='image')"
    sql = f"""
      SELECT * FROM media
      WHERE {mime_clause}
      ORDER BY destaque DESC, estrelas DESC, id ASC
      LIMIT ?
    """
    rows = [dict(r) for r in conn.execute(sql, (limit,))]
    conn.close()
    return rows


def local_candidate_score(gap, local, used_stems: set[str]):
    st = local["stem"]
    if st in used_stems:
        return None
    name = local["path"].lower()
    blob = name
    cat, rej = hint_score(blob, gap["hints"], gap["reject_hints"])
    if rej:
        return None
    asp = aspect_of(local["w"], local["h"])
    am = aspect_match(gap["aspect"], asp)
    if am < 0.5:
        return None
    prefer_boost = 0.12 if Path(local["path"]).name in gap.get("prefer_local", ()) else 0.0
    # local curated assets already chosen for site — strong prior
    score = (
        cat * 0.28
        + am * 0.30
        + 0.22  # available static asset
        + prefer_boost
        + 0.10  # diversity default
        + min(1.0, (local["w"] * local["h"]) / (2000 * 2000)) * 0.08
    )
    return {
        "source": "local",
        "path": local["path"],
        "stem": st,
        "w": local["w"],
        "h": local["h"],
        "aspect": asp,
        "categoria": "local",
        "score": round(score, 4),
        "parts": {"cat": cat, "aspect": am, "prefer": prefer_boost},
        "media_id": None,
        "nome": Path(local["path"]).name,
    }


def db_candidate_score(gap, row, used_ids: set[int], used_stems: set[str]):
    mid = int(row.get("id") or 0)
    if mid in used_ids:
        return None
    nome = str(row.get("nome") or "")
    st = stem(nome)
    if st in used_stems:
        return None
    blob = blob_of(row)
    # skip dump pastas lightly via name
    pasta = str(row.get("pasta") or "").lower()
    if any(x in pasta for x in ("sem edi", "originais", "separadas", "s.edit")):
        return None
    cat, rej = hint_score(blob, gap["hints"], gap["reject_hints"])
    if rej >= 2:
        return None
    w = int(row.get("width") or 0)
    h = int(row.get("height") or 0)
    asp = aspect_of(w, h)
    am = aspect_match(gap["aspect"], asp)
    if am < 0.5 and w and h:
        return None
    if w and h and am < 0.5:
        return None
    # if dims missing, soft-penalize but allow if strong category
    if not w or not h:
        am = 0.45
        if cat < 0.34:
            return None
    q = _home_quality_score(row) if callable(_home_quality_score) else _quality_score(row)
    # normalize quality roughly
    qn = min(1.0, max(0.0, q / 140.0))
    diversity = 0.08
    score = (
        cat * 0.30
        + am * 0.25
        + qn * 0.25
        + (0.0 if rej else 0.08)
        + diversity
        + min(1.0, (w * h) / (4000 * 3000)) * 0.04
    )
    if score < 0.35:
        return None
    return {
        "source": "db",
        "path": None,
        "stem": st,
        "w": w,
        "h": h,
        "aspect": asp,
        "categoria": row.get("categoria") or row.get("pasta") or "",
        "score": round(score, 4),
        "parts": {"cat": round(cat, 3), "aspect": round(am, 3), "quality": round(qn, 3)},
        "media_id": mid,
        "nome": nome,
        "thumb": None,
        "row": row,
    }


def main():
    used_stems = set(USED_LOCAL)
    used_ids: set[int] = set()

    locals_ = load_local_dims()
    db_rows = query_db_candidates(500)

    report = {
        "used_local": sorted(USED_LOCAL),
        "gaps_identified": len(GAPS),
        "local_pool": len(locals_),
        "db_pool": len(db_rows),
        "gaps": [],
        "additions": [],
    }

    for gap in GAPS:
        scored = []
        rejected = 0
        for loc in locals_.values():
            s = local_candidate_score(gap, loc, used_stems)
            if s:
                scored.append(s)
            else:
                rejected += 1
        for row in db_rows:
            s = db_candidate_score(gap, row, used_ids, used_stems)
            if s:
                # strip heavy row for top list later
                scored.append({k: v for k, v in s.items() if k != "row"})
            else:
                rejected += 1

        scored.sort(key=lambda x: (-x["score"], x.get("media_id") or 0, x["stem"]))
        top = scored[:8]
        chosen = None
        fillable = False
        reason_skip = ""
        if top and top[0]["score"] >= gap["min_score"]:
            # Prefer local static asset for home stability (no API dependency)
            local_ok = [c for c in top if c["source"] == "local" and c["score"] >= gap["min_score"]]
            if local_ok:
                chosen = local_ok[0]
                fillable = True
            elif top[0]["source"] == "db" and top[0]["score"] >= gap["min_score"] + 0.08:
                # Only accept DB if clearly strong AND we can materialize a stable local path later
                chosen = None
                fillable = False
                reason_skip = (
                    f"melhor candidato é DB id={top[0]['media_id']} score={top[0]['score']} "
                    "— home estática prefere asset local; sem export automático neste passo"
                )
            else:
                reason_skip = "nenhum candidato local acima do limiar"
        else:
            reason_skip = "score insuficiente / sem candidato compatível"

        gap_rep = {
            "id": gap["id"],
            "chapter": gap["chapter"],
            "shape_needed": gap["shape"],
            "aspect_needed": gap["aspect"],
            "candidates_scored": len(scored),
            "rejected_approx": rejected,
            "top": top,
            "fillable": fillable,
            "chosen": chosen,
            "skip_reason": reason_skip,
        }
        report["gaps"].append(gap_rep)

        if chosen and chosen["source"] == "local":
            used_stems.add(chosen["stem"])
            report["additions"].append(
                {
                    "gap": gap["id"],
                    "chapter": gap["chapter"],
                    "after_idx": gap["after_idx"],
                    "path": chosen["path"],
                    "shape": gap["shape"],
                    "aspect": chosen["aspect"],
                    "score": chosen["score"],
                    "why": (
                        f"completa bloco {gap['chapter']} (faltava {gap['shape']} "
                        f"{gap['aspect']}); score={chosen['score']}; "
                        f"aspect={chosen['aspect']} {chosen['w']}x{chosen['h']}"
                    ),
                }
            )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
