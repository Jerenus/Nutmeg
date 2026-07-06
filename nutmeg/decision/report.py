"""decision-report — 清洁版 PDF 日报(手机 112mm)+ Telegram 推送(M2 阶段一第三件)。

当日每场 Read(判读/偏移/CLV)+ 当日 Ticket + 双轴校准(Brier+CLV)要点 → reportlab PDF
字节 → 共享 TelegramBotClient.send_document 推送。

自立纪律:字体注册(NutmegCJK)+ _xml 转义**自包含**在本模块——不 import 阶段三待删的
jczq_final_plan_pdf/worldcup.report_pdf,新系统运营不依赖旧码。内容逻辑收敛在
``_report_blocks``(单一真源,可字符串断言),``render_report_pdf`` 只薄渲染成 PDF。
缺节标注、空库仍出报告(spec §7 报告必出)。
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- 字体注册(自包含,复制自 jczq_final_plan_pdf 的可复用逻辑;宿主属阶段三待删)-----
_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _register_cjk_font() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "NutmegCJK" in pdfmetrics.getRegisteredFontNames():
        return
    last_err: Exception | None = None
    for path in _CJK_FONT_CANDIDATES:
        try:
            pdfmetrics.registerFont(TTFont("NutmegCJK", path, subfontIndex=0))
            return
        except Exception as exc:  # noqa: BLE001 — 逐候选降级
            last_err = exc
            continue
    raise RuntimeError(
        f"No CJK font found from candidates: {_CJK_FONT_CANDIDATES}; last error: {last_err}"
    )


def _xml(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# 内容真源:当日报告 blocks(kind, text)。PDF 与测试共用,互不重复。
# ---------------------------------------------------------------------------

_OUTCOME_ZH = {"home": "主", "draw": "平", "away": "客"}


def _fmt_dist(d: dict[str, float]) -> str:
    if not d:
        return "—"
    return "/".join(f"{_OUTCOME_ZH.get(k, k)}{v:.0%}" for k, v in d.items())


def _tv_offset(belief: dict[str, float], prior: dict[str, float]) -> float:
    """判读相对市场基线的总变差偏移(0=完全跟市场)。"""
    keys = set(belief) | set(prior)
    return sum(abs(belief.get(k, 0.0) - prior.get(k, 0.0)) for k in keys) / 2


def _report_blocks(store, run_date: str) -> list[tuple[str, str]]:
    """组装当日报告内容为 (kind, text) 列表;kind ∈ {title,sub,h2,body,small}。

    单一内容真源——render_report_pdf 逐 block 渲成 Paragraph。当日归属靠
    canonical match_id 前缀 ``M-<run_date>-``(Read 直接带,Ticket 经 legs 带)。
    """
    from nutmeg.decision.ontology import Match, Read, Settlement, Ticket

    prefix = f"M-{run_date}-"
    matches = {m.match_id: m for m in store.load(Match)
               if m.match_id.startswith(prefix)}
    reads = [r for r in store.load(Read) if r.match_id.startswith(prefix)]
    settle = {s.ref_id: s for s in store.load(Settlement) if s.ref_type == "read"}
    tickets = [t for t in store.load(Ticket)
               if any(str(leg.get("match_id", "")).startswith(prefix) for leg in t.legs)]

    blocks: list[tuple[str, str]] = [
        ("title", f"决策日报 · {run_date}"),
        ("sub", "确定性产出 · 判读 vs 市场基线 · 双轴校准(Brier+CLV) · 空仓合法"),
    ]

    # 1) 今日场次判读(判读/偏移/CLV)
    blocks.append(("h2", "今日场次判读"))
    if not reads:
        blocks.append(("body", "(当日无判读/场次)"))
    for r in sorted(reads, key=lambda x: x.match_id):
        m = matches.get(r.match_id)
        label = f"{m.home} vs {m.away}" if m else r.match_id
        comp = f" · {m.competition}" if (m and m.competition) else ""
        kind = "市场基线" if r.shadow else "判读"
        offset = _tv_offset(r.belief, r.prior)
        blocks.append((
            "body",
            f"[{kind}] {label}{comp}｜{r.market} "
            f"{_fmt_dist(r.belief)}（市场 {_fmt_dist(r.prior)}，偏移 {offset:.0%}）"
            f" 信心{r.confidence}/5",
        ))
        if r.note:
            blocks.append(("small", "理由：" + r.note))
        s = settle.get(r.read_id)
        if s is not None:
            brier = f"{s.brier:.3f}" if s.brier is not None else "—"
            clv = f"{s.clv_pp * 100:+.1f}pp" if s.clv_pp is not None else "—"
            res = ("" if s.outcome_90 is None
                   else f" 结果 {_OUTCOME_ZH.get(s.outcome_90, s.outcome_90)}")
            blocks.append(("small", f"Brier {brier}｜CLV {clv}{res}"))

    # 2) 今日投注票(¥400 框架)
    blocks.append(("h2", "今日投注票(¥400 框架)"))
    if not tickets:
        blocks.append(("body", "(当日无票 — 空仓合法)"))
    total_stake = 0
    for t in sorted(tickets, key=lambda x: x.ticket_id):
        total_stake += int(t.stake_yuan)
        odds = _combined_odds(t.legs)
        odds_str = f" @{odds:.2f}" if odds is not None else ""
        blocks.append((
            "body",
            f"{t.ticket_id} [{t.tag or t.budget_bucket}] {t.structure} "
            f"¥{t.stake_yuan}{odds_str}",
        ))
        for leg in t.legs:
            line = (f"· {leg.get('match_id')}｜{leg.get('market')} "
                    f"{leg.get('selection')} @{leg.get('odds')}")
            if leg.get("line"):
                line += f"（让球 {leg['line']}）"
            blocks.append(("small", line))

    # 3) 双轴校准要点(Brier + CLV)
    blocks.append(("h2", "双轴校准要点(Brier + CLV)"))
    blocks.append(("body", _calibration_line(reads, settle, len(tickets), total_stake)))
    return blocks


def _combined_odds(legs: list[dict]) -> float | None:
    """票合并赔率 = 各腿赔率连乘(禁嘴算);任一腿无数值赔率 → None。"""
    out = 1.0
    seen = False
    for leg in legs:
        try:
            out *= float(leg["odds"])
            seen = True
        except (KeyError, TypeError, ValueError):
            return None
    return round(out, 2) if seen else None


def _calibration_line(reads, settle, n_tickets: int, total_stake: int) -> str:
    judged = [r for r in reads if not r.shadow]
    shadow = [r for r in reads if r.shadow]
    settled = [settle[r.read_id] for r in reads if r.read_id in settle]
    briers = [s.brier for s in settled if s.brier is not None]
    clvs = [s.clv_pp for s in settled if s.clv_pp is not None]

    def _mean(xs):
        return sum(xs) / len(xs) if xs else None

    mb = _mean(briers)
    mclv = _mean(clvs)
    clv_hit = (sum(1 for c in clvs if c > 0) / len(clvs)) if clvs else None
    mb_s = f"{mb:.3f}" if mb is not None else "—"
    mclv_s = f"{mclv * 100:+.1f}pp" if mclv is not None else "—"
    clv_hit_s = f"{clv_hit:.0%}" if clv_hit is not None else "—"
    return (
        f"判读 {len(judged)} 场 / 市场基线 {len(shadow)} 场 · 已结算 {len(settled)} · "
        f"平均 Brier {mb_s} · CLV 命中 {clv_hit_s}(平均 {mclv_s}) · "
        f"今日票 {n_tickets} 张 ¥{total_stake}"
    )


# ---------------------------------------------------------------------------
# 渲染 + 推送
# ---------------------------------------------------------------------------

def _styles():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    accent = colors.HexColor("#1a6b54")
    base = getSampleStyleSheet()
    body = ParagraphStyle("DBody", parent=base["BodyText"], fontName="NutmegCJK",
                          fontSize=8.5, leading=12)
    return {
        "title": ParagraphStyle("DTitle", parent=base["Title"], fontName="NutmegCJK",
                                 fontSize=15, leading=19, textColor=accent,
                                 alignment=TA_CENTER),
        "sub": ParagraphStyle("DSub", parent=body, fontSize=7, leading=10,
                              textColor=colors.grey, alignment=TA_CENTER),
        "h2": ParagraphStyle("DH2", parent=base["Heading2"], fontName="NutmegCJK",
                             fontSize=11, leading=14, textColor=accent,
                             spaceBefore=8, spaceAfter=3),
        "body": body,
        "small": ParagraphStyle("DSmall", parent=body, fontSize=7.5, leading=10.5,
                                textColor=colors.grey, leftIndent=3),
    }


def render_report_pdf(store, run_date: str) -> bytes:
    """当日报告 → reportlab PDF 字节(手机 112mm,NutmegCJK 中文)。不打网。"""
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    _register_cjk_font()
    st = _styles()
    story: list = []
    for i, (kind, text) in enumerate(_report_blocks(store, run_date)):
        story.append(Paragraph(_xml(text), st.get(kind, st["body"])))
        if kind == "title":
            story.append(HRFlowable(width="100%", thickness=1.0,
                                    color=st["title"].textColor,
                                    spaceBefore=3, spaceAfter=5))
        elif kind == "body" and i:
            story.append(Spacer(1, 2))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=(112 * mm, 240 * mm),
        leftMargin=7 * mm, rightMargin=7 * mm, topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"决策日报 {run_date}",
    )
    doc.build(story)
    return buffer.getvalue()


def dispatch(pdf_bytes: bytes, *, client=None, chat_ids=None, dry_run: bool = True,
             caption: str = "", pdf_path=None) -> dict:
    """推送 PDF。dry_run 不真推(不碰 client);--no-dry-run 走注入/真 client。

    ``send_document`` 按**文件路径**读,故先把 pdf_bytes 落盘(pdf_path 指定则写那里,
    否则临时文件),再逐 chat_id 推。缺 client/chat_ids → 跳过不崩。
    """
    chat_ids = list(chat_ids or [])
    if dry_run:
        return {"dispatched": False, "reason": "dry_run",
                "chat_ids": chat_ids, "bytes": len(pdf_bytes)}
    if client is None or not chat_ids:
        return {"dispatched": False, "reason": "missing client/chat_ids",
                "chat_ids": chat_ids, "bytes": len(pdf_bytes)}

    if pdf_path is not None:
        path = Path(pdf_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes)
    else:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()
        path = Path(tmp.name)

    sent: list[int] = []
    for chat_id in chat_ids:
        client.send_document(chat_id=chat_id, document_path=path, caption=caption)
        sent.append(chat_id)
    return {"dispatched": True, "chat_ids": sent, "bytes": len(pdf_bytes)}


def _resolve_telegram():
    """从 settings 装配真 client + chat_ids;缺凭据 → (None, [])。"""
    from nutmeg.config.settings import get_settings
    from nutmeg.interfaces.bot.telegram import TelegramBotClient

    s = get_settings()
    token = (s.telegram_bot_token or "").strip()
    raw = s.telegram_allowed_chat_ids or ""
    chat_ids = [int(p.strip()) for p in raw.split(",") if p.strip()]
    if not token or not chat_ids:
        return None, []
    return TelegramBotClient(token=token), chat_ids


def run_report(run_date: str, output_dir, *, dispatch_telegram: bool = False,
               dry_run: bool = True) -> str:
    """CLI 胶水:渲染当日 PDF → 落盘 → 可选 Telegram 推送 → 一行摘要。"""
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    pdf_bytes = render_report_pdf(store, run_date)
    pdf_path = Path(output_dir) / "daily" / run_date / f"decision-report-{run_date}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    msg = f"decision-report {run_date}: PDF {len(pdf_bytes)} bytes → {pdf_path}"
    if dispatch_telegram:
        client, chat_ids = (None, None) if dry_run else _resolve_telegram()
        res = dispatch(pdf_bytes, client=client, chat_ids=chat_ids, dry_run=dry_run,
                       caption=f"决策日报 {run_date}", pdf_path=pdf_path)
        msg += f" | telegram: {res}"
    return msg
