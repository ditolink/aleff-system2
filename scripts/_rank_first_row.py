"""Rank best-looking photos for Home first masonry row (after hero)."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "media.db"
MED = ROOT / "data" / "thumbs" / "medium"
OUT = ROOT / "scripts" / "_first_row_candidates.json"

DUMP = ("logo", "sem edi", "originais", "site", "captura", "mockup", "identidade")

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT m.id, m.nome, m.pasta, m.categoria, m.tags, m.destaque, m.estrelas,
           COALESCE(f.face_count,0) AS face_count,
           COALESCE(f.det_score,0) AS det_score,
           COALESCE(f.face_cx,0.5) AS face_cx,
           COALESCE(f.face_cy,0.5) AS face_cy
    FROM media m
    JOIN media_embeddings e ON e.media_id=m.id
    LEFT JOIN media_faces f ON f.media_id=m.id
    WHERE m.tipo='image'
    ORDER BY f.det_score DESC, m.destaque DESC, m.estrelas DESC
    LIMIT 400
    """
).fetchall()

cands = []
for r in rows:
    mid = int(r["id"])
    pasta = (r["pasta"] or "").lower()
    nome = (r["nome"] or "").lower()
    if any(d in pasta or d in nome for d in DUMP):
        continue
    th = None
    for ext in (".webp", ".jpg", ".png"):
        p = MED / f"{mid}{ext}"
        if p.exists():
            th = p
            break
    if not th:
        continue
    # dims
    w = h = 0
    meta = MED / f"{mid}.json"
    if meta.exists():
        try:
            j = json.loads(meta.read_text(encoding="utf-8"))
            w = int(j.get("w") or j.get("width") or 0)
            h = int(j.get("h") or j.get("height") or 0)
        except Exception:
            pass
    if not w or not h:
        try:
            from PIL import Image
            with Image.open(th) as im:
                w, h = im.size
        except Exception:
            continue
    ratio = w / h
    shape = "l-wide" if ratio >= 1.45 else "p-tall"
    # framing: prefer face not too edge
    cx, cy = float(r["face_cx"] or 0.5), float(r["face_cy"] or 0.5)
    frame = 1.0 - min(abs(cx - 0.5), 0.5) * 0.6 - min(abs(cy - 0.45), 0.5) * 0.4
    det = float(r["det_score"] or 0)
    fc = int(r["face_count"] or 0)
    # appearance score: face quality + framing + stars
    appear = (
        det * 55
        + frame * 18
        + min(fc, 2) * 4
        + float(r["destaque"] or 0) * 12
        + float(r["estrelas"] or 0) * 6
        + (8 if 0.7 <= ratio <= 0.85 or 1.4 <= ratio <= 1.8 else 0)
    )
    # prefer 1-2 faces for opening row portraits
    if fc == 1:
        appear += 10
    elif fc == 2:
        appear += 8
    elif fc >= 5:
        appear -= 8
    cands.append(
        {
            "id": mid,
            "nome": r["nome"],
            "pasta": r["pasta"],
            "categoria": r["categoria"],
            "shape": shape,
            "w": w,
            "h": h,
            "det": round(det, 3),
            "face_count": fc,
            "appear": round(appear, 2),
            "thumb": str(th.relative_to(ROOT)),
        }
    )

cands.sort(key=lambda x: -x["appear"])
# diversify pasta
picked = []
seen_pasta = {}
for c in cands:
    pk = (c["pasta"] or "").lower() or str(c["id"])
    if seen_pasta.get(pk, 0) >= 1:
        continue
    seen_pasta[pk] = seen_pasta.get(pk, 0) + 1
    picked.append(c)
    if len(picked) >= 24:
        break

OUT.write_text(json.dumps({"top": picked}, ensure_ascii=False, indent=2), encoding="utf-8")
print("TOP appearance (diverse pasta):")
for c in picked[:16]:
    print(f"{c['appear']:6.1f} {c['shape']:6} det={c['det']:.2f} fc={c['face_count']} id={c['id']} | {c['pasta']} | {c['nome'][:40]}")
