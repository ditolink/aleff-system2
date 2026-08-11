#!/usr/bin/env python3
import sqlite3
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
conn = sqlite3.connect(str(ROOT / "data" / "media.db"))
conn.row_factory = sqlite3.Row

print("=== categorias ===")
for r in conn.execute(
    "SELECT categoria, COUNT(*) n FROM media WHERE tipo='image' GROUP BY categoria ORDER BY n DESC LIMIT 40"
):
    print(f"{r['n']:>4} {r['categoria']}")

print("\n=== pastas (top) ===")
for r in conn.execute(
    "SELECT pasta, COUNT(*) n FROM media WHERE tipo='image' GROUP BY pasta ORDER BY n DESC LIMIT 50"
):
    print(f"{r['n']:>4} {r['pasta']}")

print("\n=== tag tokens containing action-ish ===")
c = Counter()
for (tags,) in conn.execute("SELECT tags FROM media WHERE tipo='image' AND tags IS NOT NULL AND tags!=''"):
    for t in (tags or "").lower().replace(";", ",").split(","):
        t = t.strip()
        if any(k in t for k in ("acao", "ação", "sport", "moto", "rua", "cidade", "urban", "skate", "bike", "pista", "show", "evento", "festa")):
            c[t] += 1
for t, n in c.most_common(40):
    print(n, t)
