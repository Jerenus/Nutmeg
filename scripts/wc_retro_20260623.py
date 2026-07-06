#!/usr/bin/env python3
"""2026-06-22 世界杯四场 MD2 判读复盘——读 predictions.json + 抓 okooo 赛果, 逐场 grade,
手机PDF经 nutmeg Telegram bot 推送。launchd 在北京 6/23 14:30 触发。赛果未就绪时推兜底提示。"""
from __future__ import annotations
import os, json, socket
from pathlib import Path
from datetime import datetime
socket.setdefaulttimeout(30)

DATE = "2026-06-22"
BASE = Path(f".nutmeg-data/jczq/daily/{DATE}")
PRED = BASE / "predictions.json"

def fetch_results():
    from nutmeg.services.jczq_results import OkoooJczqResultProvider
    prov = OkoooJczqResultProvider()
    for d in [DATE, "2026-06-23"]:
        try:
            r = prov.fetch_results(d)
            if any((r.get(k, {}) or {}).get("score") for k in r):
                return r
        except Exception as e:
            print(f"fetch {d} failed: {e}")
    return {}

def parse_score(s):
    try:
        h, a = s.replace("：", ":").split(":"); return int(h), int(a)
    except Exception:
        return None, None

def grade():
    pred = json.load(open(PRED, encoding="utf-8"))
    res = fetch_results()
    rows = []
    have = 0
    for p in pred["picks"]:
        num = p["match_no"]; r = res.get(num, {}) or {}
        score = r.get("score", "")
        h, a = parse_score(score)
        line = {"num": num, "fixture": p["fixture"], "my_judge": p["judgment"],
                "my_score": p["score"], "score": score, "had": r.get("had", ""),
                "hhad": r.get("hhad", ""), "ttg": r.get("ttg", ""), "hits": []}
        if h is None:
            line["status"] = "赛果未就绪"; rows.append(line); continue
        have += 1
        total = h + a; margin = h - a
        # 方向(home/away/draw)
        actual_dir = "home" if margin > 0 else ("away" if margin < 0 else "draw")
        line["hits"].append(("判读方向", p["judgment"] == actual_dir))
        # 比分
        line["hits"].append(("精确比分", p["score"].replace("-", ":") == score.replace("-", ":")))
        # 总进球方向(我多偏大/小/2-3, 简化:记录实际total带)
        line["total"] = total
        rows.append(line)
    # opinion ticket: 044 受让平(阿尔净胜恰1)= hhad 让平
    ot = pred.get("opinion_ticket", {})
    otnum = ot.get("match_no", "")
    otr = res.get(otnum, {}) or {}
    ot_hit = None
    if otr.get("hhad"):
        ot_hit = (otr.get("hhad") == "让平")  # 约旦+1 让平 = 阿尔净胜1
    return pred, rows, have, ot, ot_hit, res

def build_pdf(pred, rows, have, ot, ot_hit):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    for fp in ["/System/Library/Fonts/Supplemental/Songti.ttc",
               "/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        if Path(fp).exists():
            pdfmetrics.registerFont(TTFont("CJK", fp, subfontIndex=0)); break
    NAVY = colors.HexColor("#10243f"); GREEN = colors.HexColor("#1d6b3a"); RED = colors.HexColor("#a01b1b")
    GREY = colors.HexColor("#444444"); LITE = colors.HexColor("#eef2f7"); WARM = colors.HexColor("#fdf3e3")
    def st(sz, c=colors.black, lead=None, sp=2, al=0):
        return ParagraphStyle(f"s{sz}{al}", fontName="CJK", fontSize=sz, textColor=c, leading=lead or sz*1.4, spaceAfter=sp, alignment=al)
    flow = []
    flow += [Paragraph("世界杯四场 MD2 · 判读复盘", st(13.5, NAVY, sp=2, al=1)),
             Paragraph(f"对账 2026-06-22 predictions.json · 评判员层(引擎空仓¥0另计)", st(8, GREY, sp=4, al=1))]
    def grid(data, widths, hc=NAVY):
        t = Table(data, colWidths=widths)
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), hc), ("FONTNAME", (0,0), (-1,-1), "CJK"),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTSIZE", (0,0), (-1,-1), 7.2),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LITE]), ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#c8d2de")),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 3), ("RIGHTPADDING", (0,0), (-1,-1), 3),
            ("TOPPADDING", (0,0), (-1,-1), 2.5), ("BOTTOMPADDING", (0,0), (-1,-1), 2.5)]))
        return t
    if have == 0:
        flow += [Spacer(1, 6), Table([[Paragraph("⏳ 赛果尚未就绪(okooo 未返回比分)。请稍后手动复盘, 或确认末场 044 已终场。", st(8.5, RED, lead=12))]],
                 colWidths=[96*mm], style=TableStyle([("BACKGROUND",(0,0),(-1,-1),WARM),("BOX",(0,0),(-1,-1),0.5,RED),
                 ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))]
    else:
        # 总表
        data = [["场次", "实际比分", "我判/比分", "方向", "比分"]]
        nhit = 0; ntot = 0
        for r in rows:
            if r.get("status") == "赛果未就绪":
                data.append([r["num"][-3:], "—", f"{r['my_judge']}/{r['my_score']}", "—", "—"]); continue
            dirhit = next((v for k, v in r["hits"] if k == "判读方向"), None)
            schit = next((v for k, v in r["hits"] if k == "精确比分"), None)
            ntot += 1; nhit += 1 if dirhit else 0
            data.append([r["num"][-3:], f"{r['score']}", f"{r['my_judge']}/{r['my_score']}",
                         "✓" if dirhit else "✗", "✓" if schit else "✗"])
        flow += [Spacer(1, 4), grid([[Paragraph(c, st(7.2, colors.white)) for c in data[0]]] +
                 [[Paragraph(str(c), st(7.1, NAVY if j == 0 else colors.black)) for j, c in enumerate(row)] for row in data[1:]],
                 [16*mm, 18*mm, 26*mm, 14*mm, 14*mm])]
        flow += [Spacer(1, 4), Paragraph(f"<b>方向命中: {nhit}/{ntot}</b>", st(9, NAVY, sp=3))]
        # 主题/opinion 校验
        checks = []
        rd = {r["num"]: r for r in rows}
        def tot(num):
            return rd.get(num, {}).get("total")
        if tot("周一042") is not None:
            checks.append(("042 打穿/总进球大(≥3)", tot("周一042") >= 3))
        if tot("周一043") is not None:
            r43 = rd["周一043"]; h, a = parse_score(r43["score"]); checks.append(("043 势均/总进球2-3", 2 <= (h+a) <= 3))
        if rd.get("周一044", {}).get("hhad"):
            checks.append(("044 fade打穿(阿尔未净胜2+)", rd["周一044"]["hhad"] != "让负"))
        if rd.get("周一041", {}).get("score"):
            h, a = parse_score(rd["周一041"]["score"]); checks.append(("041 奥地利进球(2-1型)", a is not None and a >= 1))
        for label, ok in checks:
            flow += [Paragraph(("✓ " if ok else "✗ ") + label, st(7.8, GREEN if ok else RED, lead=11))]
        if ot_hit is not None:
            flow += [Spacer(1, 3), Paragraph(("✓" if ot_hit else "✗") + f" <b>opinion单关 044受让平@{ot.get('odds')} (¥{ot.get('stake_yuan')})</b>: {'命中' if ot_hit else '未中'}",
                     st(8.2, GREEN if ot_hit else RED, lead=11.5))]
    flow += [Spacer(1, 5), Paragraph("纪律回顾: 让球(历史最准)/总进球为主, 比分半全场只当彩票; 整票0/94。教训沉淀进下次双峰判读与边际反推校准。", st(7.2, GREY, lead=10))]
    out = BASE / "wc-md2-RETRO-20260623.pdf"
    SimpleDocTemplate(str(out), pagesize=(112*mm, 230*mm), leftMargin=8*mm, rightMargin=8*mm, topMargin=8*mm, bottomMargin=7*mm,
                      title="WC2026 6/22 MD2 判读复盘").build(flow)
    return out

def push(out, have):
    from dotenv import load_dotenv
    load_dotenv()
    token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
    ids = [int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()]
    if not token or not ids:
        print("⚠️ Telegram env 缺失"); return False
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    client = TelegramBotClient(token=token)
    cap = ("📊 世界杯四场 MD2 判读复盘(对账 6/22 predictions)\n" +
           ("逐场核对:方向/比分/让球/总进球 + 双峰主线 + opinion单关044受让平。详见PDF。" if have else
            "⏳赛果未就绪,推送兜底提示,请稍后手动复盘。"))
    for cid in ids:
        client.send_document(chat_id=cid, document_path=out, caption=cap); print(f"sent to {cid}")
    return True

if __name__ == "__main__":
    # 轻量日期守门:只在 2026-06-23 当天跑(防 launchd 次年同日误触发)
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in ("2026-06-23", "2026-06-22"):
        print(f"今天{today}非复盘窗口,跳过"); raise SystemExit(0)
    pred, rows, have, ot, ot_hit, res = grade()
    out = build_pdf(pred, rows, have, ot, ot_hit)
    print(f"PDF: {out} (have={have})")
    ok = push(out, have)
    raise SystemExit(0 if ok else 1)
