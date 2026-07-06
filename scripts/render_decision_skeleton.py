# 渲染 docs/jczq-decision-skeleton.png —— Nutmeg JCZQ 每日决策骨架结构图。
# 长期文档生成器(配套 docs/jczq-decision-skeleton.md)。重渲染：uv run python scripts/render_decision_skeleton.py
# 依赖 matplotlib + 系统 CJK 字体(Songti/STHeiti/PingFang)。
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

for p in ["/System/Library/Fonts/Supplemental/Songti.ttc",
          "/System/Library/Fonts/STHeiti Medium.ttc","/System/Library/Fonts/PingFang.ttc"]:
    try: prop=font_manager.FontProperties(fname=p); break
    except Exception: prop=None
plt.rcParams["axes.unicode_minus"]=False

fig,ax=plt.subplots(figsize=(18,22)); ax.set_xlim(0,100); ax.set_ylim(0,100); ax.axis("off")
C=dict(entry="#dbe9f6",money="#f6dcd6",judge="#d8efdd",wc="#e6ddf2",disc="#fbf3d2",
       data="#e9e9ec",hdr="#1a6b54",white="#ffffff",conf="#fdeede",cbg="#fbf1ea")

def box(cx,cy,w,h,lines,fc,fs=13,ec="#4a4a4a",lw=1.4,bold0=False,tcol="#1a1a1a"):
    ax.add_patch(FancyBboxPatch((cx-w/2,cy-h/2),w,h,boxstyle="round,pad=0.35,rounding_size=0.7",
        fc=fc,ec=ec,lw=lw,zorder=2))
    if isinstance(lines,str): lines=[lines]
    n=len(lines); gap=h/(n+1)
    for i,ln in enumerate(lines):
        ax.text(cx,cy+h/2-gap*(i+1),ln,ha="center",va="center",fontproperties=prop,
            fontsize=(fs+1.5 if(bold0 and i==0) else fs),color=tcol,
            weight=("bold" if(bold0 and i==0) else "normal"),zorder=3)
def arrow(x1,y1,x2,y2,col="#333",lw=2.6):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=24,color=col,lw=lw,zorder=1))

ax.text(50,98,"Nutmeg JCZQ 每日决策骨架",ha="center",fontproperties=prop,fontsize=27,weight="bold",color=C["hdr"])
ax.text(50,95.3,"单一入口 · §A 定死 · 只动 §C · 钱/观点分账 · 双 agent 冲突处理",ha="center",fontproperties=prop,fontsize=14,color="#555")

# ===== ZONE 1 spine =====
sx=28
box(sx,91,48,4.2,["触发：『今天的方案 / today's bets』"],C["entry"],fs=14,bold0=True); arrow(sx,88.9,sx,87.2)
box(sx,84.5,48,4.8,["① 唯一入口  jczq-today  → today-packet.md"],C["entry"],fs=13.5,bold0=True); arrow(sx,82.1,sx,80.4)
box(sx,75.5,50,10,[""],C["white"],ec=C["hdr"],lw=2)
ax.text(sx,79.3,"② 读 today-packet.md ＝ 唯一决策来源",ha="center",fontproperties=prop,fontsize=14,weight="bold",color=C["hdr"])
cells=[("§A 引擎票面","勿改腿",C["money"]),("§B 盘面底座","Poisson",C["white"]),
       ("§C 裁量","唯一判断",C["judge"]),("§D 雷达","机会",C["white"]),("§E 世界杯","蒙特卡洛",C["wc"])]
cw=9.2; x0=sx-50/2+1.3+cw/2
for i,(a,b,fc) in enumerate(cells): box(x0+i*(cw+0.45),74.6,cw,6.2,[a,b],fc,fs=11.5,bold0=True)
arrow(sx-12,70.5,sx-12,68.4); arrow(sx+10,70.5,sx+10,68.4)
box(sx-13,65,22,5.8,["③a §A → 照单 / 空仓","勿改腿 · 空仓合法"],C["money"],fs=12,bold0=True)
box(sx+13,65,20,5.8,["③b §C → 逐条作答","信心1-5 + 理由"],C["judge"],fs=12,bold0=True)
arrow(sx,62.1,sx,60.4)
box(sx,57,50,5.6,["④ 窗口收尾（各 agent 各写）","answers + predictions → 推 PDF 日报"],C["wc"],fs=12.5,bold0=True)
arrow(sx,54.2,sx,52.6)

# ===== ZONE 1 right panels =====
rx=80
box(rx,90,36,7.5,["两大产品 · 永不合账","钱：引擎注金 ¥100 · 空仓合法","观点：评判员预测 · ¥15 记分"],C["white"],fs=12.5,bold0=True,ec=C["hdr"],lw=1.7)
box(rx,79.5,36,8,["档位定性 (§32)","A = 唯一可能结构 edge","   (§29 gap≥8pp / §28 R25)","B/D/E = 零 edge 方差娱乐"],C["disc"],fs=12,bold0=True)
box(rx,68,36,9.5,["纪律红线","· 空仓永远合法 · 禁嘴算","· 概率只来自 §B2 或引擎函数","· §A 定死,只动 §C","· §30：n<30 不改模型"],C["disc"],fs=12,bold0=True)

# ===== ZONE 2 conflict band =====
ax.add_patch(FancyBboxPatch((4,27),92,24.5,boxstyle="round,pad=0.35,rounding_size=0.9",
    fc=C["cbg"],ec="#c87a3a",lw=2.6,zorder=0))
ax.text(50,49.6,"⑤  GPT 与 Claude 方案冲突处理流程",ha="center",fontproperties=prop,fontsize=17,weight="bold",color="#a85a1f")
box(15,42,21,9,["各自独立跑同一 SOP","§A 完全相同 → 无分歧","分歧只在 §C + 评判员"],C["white"],fs=12,bold0=True)
arrow(26,42,31.5,42,col="#a85a1f")
box(40,42,15,7,["逐 q_id / 逐场","比对两家"],C["white"],fs=12.5,bold0=True)
for (by,txt,fc) in [(47.5,["① 一致 → 共识,照常执行"],C["judge"]),
                    (41,["② 判定分歧 → 标 divergent","钱:减注/剔除 · 观点:两份并存"],C["conf"]),
                    (34.5,["③ 事实冲突 → 带署名更正","不改对方判定(如 Partey 错)"],C["money"])]:
    arrow(47.5,42,57,by,col="#a85a1f",lw=2)
    box(76.5,by,37,(4.4 if len(txt)==1 else 6),txt,fc,fs=12,bold0=True)
box(50,30,88,3.8,["收敛：可经讨论趋同(今日加纳→双方都巴拿马客胜)   ⚠ ledger 暂只读 gpt 版,双评判员对账待接线"],
    C["white"],fs=11.5,ec="#c87a3a")

# ===== ZONE 3 data + footer =====
ax.text(50,23.6,"数据层（喂决策,非每日重选）",ha="center",fontproperties=prop,fontsize=15,weight="bold",color="#444")
dc=[("tiered 引擎","A/B/D/E 分层"),("世界杯 MC sim","Elo·锚定·校准"),
    ("赔率源","API-Football/500/体彩"),("judge-ledger","次日记分")]
dw=22; dx0=50-(4*dw+3*1.8)/2+dw/2
for i,(a,b) in enumerate(dc): box(dx0+i*(dw+1.8),18.5,dw,5.6,[a,b],C["data"],fs=12,bold0=True)
box(50,10.5,90,5,["历史根因：无钉死入口 → agent 即兴乱选 → 路径不一致。","对策 = 单一入口 + §A 定死 + 只动 §C + 钱/观点分账 + 冲突显式处理 + 次日记分。"],
    "#eef5f2",fs=12.5,ec=C["hdr"],lw=1.6)
ax.text(50,5.2,"今日(06-17)：引擎四档全空→¥0 空仓 ｜ 评判员逐场+哥伦比亚客胜¥15观点票 ｜ 加纳已双方收敛巴拿马",
    ha="center",fontproperties=prop,fontsize=11.5,color="#777",style="italic")

plt.tight_layout()
out="docs/jczq-decision-skeleton.png"
fig.savefig(out,dpi=150,bbox_inches="tight",facecolor="white"); print("saved",out)
