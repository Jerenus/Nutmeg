"""决策页的密码门（2026-10-30 Jun 定：手机经学校 VPN 进校园网访问 Mac，服务对网络开放）。

校园网上谁都连得到这台 Mac，页面又能登记票、写账本，所以对外必须有密码。本机（127.0.0.1 / ::1）
直接打开不受影响；别的机器先过 /login，成功后发 180 天的 cookie（值是密码的 HMAC，改密码＝
旧 cookie 全部失效）。manifest 与图标不设门：iOS 取它们时不一定带 cookie，内容也不敏感。
连续输错 5 次锁 15 分钟（按来源 IP，进程内计数，重启清零）。
"""
from __future__ import annotations

import hashlib
import hmac
import html
import time
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "nm_auth"
MAX_AGE = 180 * 24 * 3600
LOCAL = {"127.0.0.1", "::1"}
PUBLIC_PREFIXES = ("/login", "/manifest.webmanifest", "/static/decision/icons/")
MAX_FAILS, LOCK_S = 5, 15 * 60


def auth_token(password: str) -> str:
    return hmac.new(password.encode(), b"nutmeg-decision-web-v1", hashlib.sha256).hexdigest()


def _safe_next(target: str) -> str:
    """只许站内相对路径，防 /login?next=//evil 跳出去。"""
    return target if target.startswith("/") and not target.startswith("//") else "/day"


def _page(next_path: str, error: str = "") -> HTMLResponse:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录 · Nutmeg</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/static/decision/icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Nutmeg">
<style>
:root{{--ink:#15181B;--paper:#FFFFFF;--line:#DADDD7;--muted:#565E66;--link:#2348C9;--veto:#B23A0E}}
@media (prefers-color-scheme:dark){{:root{{--ink:#E4E7E3;--paper:#1A1E22;--line:#2E343A;
  --muted:#9AA2AA;--link:#8EA6F5;--veto:#F08A63}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--paper);color:var(--ink);
  font-family:"PingFang SC","Hiragino Sans GB",system-ui,sans-serif}}
form{{width:min(320px,calc(100vw - 32px));display:grid;gap:12px}}
h1{{margin:0 0 4px;font-size:18px;letter-spacing:.08em}}
p{{margin:0;color:var(--muted);font-size:13px}} .err{{color:var(--veto)}}
input,button{{font:inherit;font-size:16px;min-height:44px;border-radius:6px;box-sizing:border-box}}
input{{padding:0 12px;border:1px solid var(--line);background:transparent;color:var(--ink)}}
button{{border:0;background:var(--link);color:#fff;font-weight:700}}
</style></head><body>
<form method="post" action="/login">
  <h1>NUTMEG</h1><p>决策页对校园网开放，先输密码。</p>{err}
  <input type="password" name="password" autocomplete="current-password" autofocus required>
  <input type="hidden" name="next" value="{html.escape(next_path)}">
  <button type="submit">进入</button>
</form></body></html>""")


def register_password_gate(app: FastAPI, password: str) -> None:
    token = auth_token(password)
    fails: dict[str, list[float]] = {}

    @app.middleware("http")
    async def password_gate(request: Request, call_next):
        client = request.client.host if request.client else ""
        path = request.url.path
        if client in LOCAL or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if hmac.compare_digest(request.cookies.get(COOKIE, ""), token):
            return await call_next(request)
        if request.method == "GET" and not path.startswith("/api/"):
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"/login?next={quote(path + query)}", status_code=303)
        return JSONResponse({"detail": "需要登录"}, status_code=401)

    @app.get("/login")
    def login_page(next: str = "/day") -> Response:  # noqa: A002
        return _page(_safe_next(next))

    @app.post("/login")
    async def login_submit(request: Request) -> Response:
        client = request.client.host if request.client else ""
        now = time.time()
        recent = [t for t in fails.get(client, []) if now - t < LOCK_S]
        fields = parse_qs((await request.body()).decode("utf-8", "replace"))
        target = _safe_next((fields.get("next") or ["/day"])[0])
        if len(recent) >= MAX_FAILS:
            return _page(target, "输错太多次，15 分钟后再试。")
        given = (fields.get("password") or [""])[0]
        if not hmac.compare_digest(auth_token(given), token):
            fails[client] = recent + [now]
            return _page(target, "密码不对。")
        fails.pop(client, None)
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax", path="/")
        return resp
