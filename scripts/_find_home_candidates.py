#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "media.db"
MED = ROOT / "data" / "thumbs" / "medium"
SMALL = ROOT / "data" / "thumbs" / "small"

QUERIES = {
    "cidade": [
        "%moto%", "%esporte%", "%acao%", "%ação%", "%cidade%", "%rua%",
        "%urbano%", "%street%", "%skate%", "%bike%", "%pista%", "%corrida%",
        "%futebol%", "%basquete%", "%surf%", "%documental%", "%movimento%",
    ],
    "casamentos": [
        "%casament%", "%casal%", "%noiva%", "%noivo%", "%wedding%", "%alian%",
        "%buque%", "%buquê%", "%cerimon%",
    ],
    "ensaios": [
        "%ensaio%", "%editorial%", "%retrato%", "%modelo%", "%lifestyle%",
        "%fashion%", "%barbara%",
    ],
    "familia": [
        "%familia%", "%família%", "%infantil%", "%crianca%", "%criança%",
        "%batismo%", "%anivers%", "%bebe%", "%bebê%", "%kids%",
    ],
}


def has_thumb(mid: int) -> Path | None:
    for tier in (MED, SMALL):
        for ext in (".webp", ".jpg", ".jpeg", ".png"):
            p = tier / f"{mid}{ext}"
            if p.exists():
                return p
    return None


def dims(mid: int, thumb: Path | None):
    for tier in (MED, SMALL):
        meta = tier / f"{mid}.json"
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


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    print("thumbs medium", len(list(MED.glob("*.webp"))))
    print("thumbs small", len(list(SMALL.glob("*.webp"))))
    out = {}
    for theme, likes in QUERIES.items():
        clauses = []
        params = []
        for lk in likes:
            clauses.append(
                "lower(coalesce(tags,'')||' '||coalesce(pasta,'')||' '||coalesce(categoria,'')||' '||coalesce(nome,'')) LIKE ?"
            )
            params.append(lk)
        sql = f"""
        SELECT id, nome, pasta, categoria, tags, destaque, estrelas, tamanho
        FROM media
        WHERE tipo='image' AND ({' OR '.join(clauses)})
        ORDER BY destaque DESC, estrelas DESC, id ASC
        LIMIT 80
        """
        rows = []
        for r in conn.execute(sql, params):
            mid = int(r["id"])
            thumb = has_thumb(mid)
            if not thumb:
                continue
            w, h = dims(mid, thumb)
            if not w or not h:
                continue
            ratio = w / h
            orient = "portrait" if ratio < 0.95 else ("wide" if ratio >= 1.55 else "landscape")
            rows.append({
                "id": mid,
                "nome": r["nome"],
                "pasta": r["pasta"],
                "categoria": r["categoria"],
                "tags": (r["tags"] or "")[:80],
                "destaque": r["destaque"],
                "estrelas": r["estrelas"],
                "w": w,
                "h": h,
                "orient": orient,
                "thumb": str(thumb.relative_to(ROOT)),
            })
            if len(rows) >= 25:
                break
        out[theme] = rows
        print(f"\n=== {theme} ({len(rows)}) ===")
        for x in rows[:15]:
            print(
                f"{x['id']:>5} {x['orient']:9} {x['w']}x{x['h']} "
                f"d={x['destaque']} e={x['estrelas']} | {x['pasta']} | {x['categoria']} | {x['nome'][:45]}"
            )
    (ROOT / "scripts" / "_home_db_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conn.close()


if __name__ == "__main__":
    main()
