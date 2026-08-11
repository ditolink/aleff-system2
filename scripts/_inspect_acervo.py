import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "media.db"
MED = ROOT / "data" / "thumbs" / "medium"

c = sqlite3.connect(str(DB))
c.row_factory = sqlite3.Row
print("tables:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")])
for t in ("media", "media_embeddings", "media_faces"):
    print(t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print("images", c.execute("SELECT COUNT(*) FROM media WHERE tipo='image'").fetchone()[0])
print("media cols", [r[1] for r in c.execute("PRAGMA table_info(media)")])
print("faces cols", [r[1] for r in c.execute("PRAGMA table_info(media_faces)")])
print("emb cols", [r[1] for r in c.execute("PRAGMA table_info(media_embeddings)")])
# thumbs available
n_th = 0
for r in c.execute("SELECT id FROM media WHERE tipo='image'"):
    mid = r[0]
    if (MED / f"{mid}.webp").exists() or (MED / f"{mid}.jpg").exists():
        n_th += 1
print("medium thumbs", n_th)
# sample face stats
print(
    "faces with det>=0.8",
    c.execute("SELECT COUNT(*) FROM media_faces WHERE det_score>=0.8 AND face_count>=1").fetchone()[0],
)
