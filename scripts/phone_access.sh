#!/usr/bin/env bash
# 手机访问决策页（2026-10-29 产品形态 Task 9.3）。
# Tailscale serve 把本机 127.0.0.1:8787 只发布到你自己的 tailnet（HTTPS，不上公网，服务仍只绑本机），
# 再把地址写进 .env 的 NUTMEG_DECISION_WEB_URL——播报与首发提醒的末行从此带期页链接。
#
# 前置（只做一次，需要你本人）：Mac 与 iPhone 各装 Tailscale、用同一个账号登录。
# 用法：scripts/phone_access.sh on | off | status
#   on     发布 :8787 → 写 .env → 自检；首次会提示去 Tailscale 后台开 HTTPS 证书，按提示点开再重跑
#   off    撤掉发布、删 .env 那一行（推送回到不带链接）
#   status 看当前发布与 .env
# 手机上：Safari 打开 on 打印的地址 → 分享 → 添加到主屏幕。
set -euo pipefail
cd "$(dirname "$0")/.."

TS=$(command -v tailscale || true)
[ -n "$TS" ] || TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
[ -x "$TS" ] || { echo "没找到 tailscale：先装 Tailscale（App Store 或 tailscale.com）并登录。" >&2; exit 1; }

KEY=NUTMEG_DECISION_WEB_URL

set_env() {  # set_env <url>；空串＝删掉这一行
  python3 - "$KEY" "$1" <<'EOF'
import pathlib, sys
key, url = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
lines = [l for l in (p.read_text().splitlines() if p.exists() else []) if not l.startswith(key + "=")]
if url:
    lines.append(f"{key}={url}")
p.write_text("\n".join(lines) + "\n")
EOF
}

case "${1:-status}" in
  on)
    curl -fsS -o /dev/null http://127.0.0.1:8787/manifest.webmanifest \
      || { echo "本机 :8787 没响应：launchctl kickstart -k gui/$(id -u)/com.nutmeg.decision.web" >&2; exit 1; }
    "$TS" serve --bg 8787
    host=$("$TS" status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
    url="https://$host"
    set_env "$url"
    echo "已写 .env：$KEY=$url"
    if curl -fsS -o /dev/null "$url/manifest.webmanifest"; then
      echo "自检通过。手机 Safari 打开 $url/day → 分享 → 添加到主屏幕。"
    else
      echo "⚠️ $url 暂时打不开（证书首签要几十秒）；稍后重跑 status 或直接在手机上试。" >&2
    fi
    ;;
  off)
    "$TS" serve --https=443 off || true
    set_env ""
    echo "已撤掉发布并删除 .env 的 $KEY；推送回到不带链接。"
    ;;
  status)
    "$TS" serve status || true
    grep "^$KEY=" .env 2>/dev/null || echo "（.env 未设 $KEY：推送不带链接）"
    ;;
  *)
    echo "用法：$0 on | off | status" >&2; exit 2 ;;
esac
