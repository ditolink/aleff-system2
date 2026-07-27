"""security_audit.py — Testes básicos anti-ataque (rode local com o server up).

  python scripts/security_audit.py
  python scripts/security_audit.py http://127.0.0.1:3001
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3001").rstrip("/")
PASS = 0
FAIL = 0


def req(path, method="GET", data=None, headers=None, cookies=None):
    h = dict(headers or {})
    if cookies:
        h["Cookie"] = cookies
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=12) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} — {detail}")


def main():
    print(f"Security audit → {BASE}\n")

    # 1) secrets / source not exposed
    for p in ["/.env", "/backend/server.py", "/data/media.db", "/.git/config", "/wp-admin/", "/phpmyadmin"]:
        code, _, body = req(p)
        leaked = b"AUTH_USERS" in body or b"PRIVATE KEY" in body or b"SECRET_KEY" in body
        check(f"no leak {p}", code in (404, 400) and not leaked, f"status={code}")

    # 2) protected pages redirect
    for p in ["/dashboard.html", "/admin.html", "/code.html", "/upload.html"]:
        code, hdrs, _ = req(p)
        loc = hdrs.get("Location") or hdrs.get("location") or ""
        check(f"auth gate {p}", code in (302, 301, 404) and ("loginsite" in loc or code == 404), f"{code} {loc}")

    # 3) API lockdown
    code, _, body = req("/api/dashboard")
    check("dashboard API 401", code == 401, f"status={code}")

    code, _, _ = req("/api/dev/tree")
    check("dev tree blocked", code in (401, 403, 404), f"status={code}")

    # 4) login without CSRF fails
    code, _, body = req("/api/auth/login", method="POST", data={"username": "x", "password": "y"})
    check("login needs CSRF", code in (403, 401, 429), f"status={code} body={body[:80]!r}")

    # 5) security headers on home
    code, hdrs, _ = req("/")
    check("X-Frame-Options", (hdrs.get("X-Frame-Options") or "").upper() == "DENY")
    check("X-Content-Type-Options", (hdrs.get("X-Content-Type-Options") or "") == "nosniff")
    csp = hdrs.get("Content-Security-Policy") or ""
    check("CSP present", "default-src" in csp, csp[:60])

    # 6) public search still works
    code, _, body = req("/api/search?q=casal&per_page=1")
    check("public search OK", code == 200 and b"status" in body, f"status={code}")

    print(f"\nResultado: {PASS} ok, {FAIL} falhas")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
