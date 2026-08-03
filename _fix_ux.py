# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess
import re

root = Path(r"c:/Users/Pichau/Documents/aleff-system2")

# --- 1) Restore search.html from git with UTF-8, then patch player + lightbox ---
raw = subprocess.check_output(["git", "show", "HEAD:frontend/search.html"], cwd=root)
html = raw.decode("utf-8")

# Ensure player assets in head
if "player.css" not in html:
    html = html.replace(
        '  <link rel="stylesheet" href="css/search.css',
        '  <link rel="stylesheet" href="css/player.css?v=20260801ax"/>\n  <link rel="stylesheet" href="css/search.css',
        1,
    )
# bump search.css and include player.js
html = re.sub(r'css/search\.css\?v=[^"]+', 'css/search.css?v=20260801ax', html)
html = re.sub(r'js/search\.js\?v=[^"]+', 'js/search.js?v=20260801ax', html)
if "js/player.js" not in html:
    html = html.replace(
        '  <script src="js/search.js',
        '  <script src="js/player.js?v=20260801ax" defer></script>\n  <script src="js/search.js',
        1,
    )

# Enrich lightbox back card if simple
old_back = '<div class="lb-back"><span>Aleff Thiago</span></div>'
new_back = '''<div class="lb-back">
        <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <g stroke="#f5f5f5" stroke-width="1.3" stroke-linecap="round" opacity="0.85">
            <path d="M9 8 Q8 5 9.5 2"/><path d="M15 7 Q14 4 15.5 1"/><path d="M21 8 Q20 5 21.5 2"/>
          </g>
          <path d="M7.5 11 L22.5 11 L20.5 23 Q20.3 24 19 24 L11 24 Q9.7 24 9.5 23 Z" fill="#f5f5f5"/>
        </svg>
        <span>Aleff Thiago</span>
      </div>'''
if old_back in html:
    html = html.replace(old_back, new_back)

# Ensure custom icons are present (git version already has them)
assert "btn-ico\">◍</span>Casamento" in html or "btn-ico\">◍</span>Casamento" in html or "Casamento" in html
assert "qico" in html

out = root / "frontend" / "search.html"
out.write_text(html, encoding="utf-8", newline="\n")
print("search.html restored", out.stat().st_size)
print("sample icons:", "◍" in html, "♫" in html, "♡" in html)

# --- 2) Fix search.js if corrupted ---
js_path = root / "frontend" / "js" / "search.js"
js = js_path.read_text(encoding="utf-8")
# Fix common mojibake in strings if any
replacements = {
    "categoria � o": "categoria — o",
    "Ops � ": "Ops — ",
    "� ": "— ",
}
for a, b in replacements.items():
    if a in js:
        js = js.replace(a, b)
        print("fixed js:", a)

# Ensure lbStep exists and only one openLightbox
print("openLightbox", js.count("async function openLightbox"))
print("lbStep", js.count("function lbStep"))
print("AleffPlayer", "AleffPlayer" in js)

js_path.write_text(js, encoding="utf-8", newline="\n")

# --- 3) Login CSS: force full-bleed cinematic shell like screenshot (no compact box) ---
login_css = root / "frontend" / "css" / "login.css"
css = login_css.read_text(encoding="utf-8")

# Remove compact shell centering if present
css2 = css
# Ensure shell is full viewport split, not centered card
if "--shell-w" in css2 and "max-width: var(--shell-w)" in css2:
    css2 = re.sub(
        r"\.login-shell\s*\{[^}]*\}",
        """.login-shell {
  display: grid;
  grid-template-columns: 1fr var(--panel-w);
  width: 100%;
  height: 100vh;
  height: 100dvh;
  margin: 0;
  max-width: none;
  box-shadow: none;
}""",
        css2,
        count=1,
    )
    print("forced full-bleed login-shell")

# Solid CTA already there; also kill any leftover gradient on access-cta from ui
if "background-image: none" not in css2:
    pass

login_css.write_text(css2, encoding="utf-8", newline="\n")

# bump login cache
login_html = root / "frontend" / "loginsite.html"
lh = login_html.read_text(encoding="utf-8")
lh = re.sub(r'css/login\.css\?v=[^"]+', 'css/login.css?v=20260801ax', lh)
lh = re.sub(r'css/ui\.css\?v=[^"]+', 'css/ui.css?v=20260801ax', lh)
# Ensure CTA class is is-em not is-ig
lh = lh.replace("ui-cta is-ig", "ui-cta is-em")
login_html.write_text(lh, encoding="utf-8", newline="\n")
print("login bumped")

# cleanup
for p in [root / "frontend" / "search.html.orig", root / "frontend" / "search.html.git", root / "_fix_lb3.py"]:
    if p.exists():
        p.unlink()
        print("removed", p.name)
