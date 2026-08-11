import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
c = sqlite3.connect(str(ROOT / "data" / "media.db"))
print("tables:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
print("embeddings", c.execute("SELECT COUNT(*) FROM media_embeddings").fetchone()[0])
print("images", c.execute("SELECT COUNT(*) FROM media WHERE tipo='image'").fetchone()[0])
print("faces", c.execute("SELECT COUNT(*) FROM media_faces WHERE face_count>=1").fetchone()[0])
row = c.execute("SELECT media_id, length(embedding) FROM media_embeddings LIMIT 3").fetchall()
print("sample lens", row)
med = ROOT / "data" / "thumbs" / "medium"
print("medium thumbs", len(list(med.glob("*.webp"))))
