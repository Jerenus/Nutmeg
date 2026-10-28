// static/decision/issue.js —— 期页：决策表即票（2026-10-27 产品形态第 1 阶段）。
// 推导一律在服务端：注数 / P / V 码 / 止损 / 刹车 / 死法清单来自 /api/precheck，
// 档 / 条件 k/n / 翻车面 / 默认 / 死门 / 首发来自分析包旁车（/api/issue）。这里只渲染。
// §3 桥（第 3 阶段）：五条自检 / 差异格 / 理由读数来自 /api/bridge/{期}/preview，定稿走 /action/bridge。
// 研究文本是不可信输入：全部 textContent，不用 innerHTML。
(() => {
  "use strict";
  const root = document.getElementById("issue");
  if (!root) return;
  const issue = root.dataset.issue;
  const FACES = ["3", "1", "0"];
  const NAME = { 3: "胜", 1: "平", 0: "负" };
  const KEY = { 3: "home", 1: "draw", 0: "away" };
  const MARK = { veto: "⛔", warn: "⚠️", info: "ℹ️" };
  const COLS = ["场", "对阵", "档", "胜 · 平 · 负", "条件", "翻车面", "机器默认", "死门 P", "首发"];
  // cites：{场号: 矩阵行号 k | "out"}——抽屉「引用」写行号，桥上「矩阵外」写 "out"，定稿随桥记录落盘
  // mode：draft（默认）→ bridge（进桥时记 draft0；「回草案」退回 draft，再进桥另记 draft0）
  //       → walked（B1 已登记；/api/issue 带 bridge 时直接进）
  // signed：{场号: true}＝桥上签的博胆；只对票内的单有效——该场改成双 / 包 / 丢即自动撤签。
  // cites / outs / whys / signed / deviation / prediction 只在内存里，来回进出桥都不丢。
  const state = {
    data: null, picks: {}, open: null, review: null, seq: 0, pending: false, cites: {},
    mode: "draft", draft0: null, bview: null, bpending: false, bseq: 0, outs: {}, whys: {},
    signed: {}, deviation: "", prediction: "", record: null, registered: null, berror: "",
    submitting: false,
  };
  // 偏离理由封闭枚举 = betslip_diagnosis.DEVIATION_REASONS；空串也收（账上记「偏离初稿未登记理由」）
  const DEVIATIONS = [["fact_self_judged", "自判事实"], ["price_instinct", "价格直觉"],
    ["stake_allocation", "资金分配"], ["structure_preference", "结构偏好"], ["other", "其他"]];
  const WALKABLE = [9, 14];   // 任九 9 场 / 胜负彩 14 场——其余张数服务端也会报错，进桥前先挡

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };
  const button = (cls, text, onClick) => {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  };
  const pct = (x, digits = 0) => (x == null || Number.isNaN(Number(x)) ? "—" : (Number(x) * 100).toFixed(digits));
  const faceProb = (fair, k) => (fair ? (fair[KEY[k]] ?? fair[k]) : null);

  async function postJSON(url, payload, label) {
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
      });
      return r.ok ? await r.json() : { ok: false, error: `${label} ${r.status}` };
    } catch (exc) {
      return { ok: false, error: `${label}不可达：${exc.message || exc}` };
    }
  }

  // ---- 载入 ----------------------------------------------------------
  async function fetchIssue() {
    const r = await fetch(`/api/issue/${encodeURIComponent(issue)}`);
    if (!r.ok) throw new Error(`/api/issue ${r.status}`);
    return r.json();
  }

  async function load() {
    try {
      state.data = await fetchIssue();
    } catch (exc) {
      showErrors([`期页数据读不出：${exc.message || exc}`]);
      return;
    }
    renderBrake();
    showErrors(state.data.errors || []);
    renderActions();
    if (state.data.bridge) {              // 本期桥已走过：直接进 walked，表上摆 B1
      state.mode = "walked";
      state.record = state.data.bridge;
      setPicks(state.record.faces);
    } else {
      render();
    }
  }

  function showErrors(list) {
    const errs = document.getElementById("errors");
    errs.hidden = !list.length;
    errs.textContent = list.join("；");
  }

  function renderBrake() {
    const host = document.getElementById("brake");
    host.replaceChildren();
    const brake = state.data.brake || {};
    const line = brake.line || "";
    host.append(el("span", "brake-line" + (line.startsWith("⛔") ? " veto" : ""), line || "止损状态 —"));
    const ib = brake.issue;
    if (ib) host.append(el("span", "brake-chip veto",
      `刹车档 · ${ib.reason} · 复式 ≤¥${ib.slip_yuan} · 本期 ≤¥${ib.issue_yuan}`));
  }

  // ---- 选面 → 审票 -----------------------------------------------------
  const isSingle = (no) => (state.picks[no] || "").length === 1;
  const signedNos = () => Object.keys(state.signed).filter(isSingle).sort((a, b) => Number(a) - Number(b));
  function pruneSigned() {                 // 博胆只签单：改成双 / 包 / 丢就撤签
    for (const no of Object.keys(state.signed)) if (!isSingle(no)) delete state.signed[no];
  }

  function toggle(no, k) {
    const cur = new Set(state.picks[no] || "");
    if (cur.has(k)) cur.delete(k); else cur.add(k);
    const faces = FACES.filter((f) => cur.has(f)).join("");
    if (faces) state.picks[no] = faces; else delete state.picks[no];
    pruneSigned();
    render();
    review();
    bridgeRefresh();
  }

  function setPicks(faces) {
    state.picks = {};
    for (const [no, f] of Object.entries(faces || {})) if (f) state.picks[String(no)] = String(f);
    pruneSigned();
    render();
    review();
    bridgeRefresh();
  }

  let timer = null;
  function review() {
    clearTimeout(timer);
    const seq = ++state.seq;               // 任何新点格都让在途的旧回应作废
    if (!Object.keys(state.picks).length) {
      state.review = null; state.pending = false; renderSide();
      return;
    }
    state.pending = true; renderSide();
    timer = setTimeout(async () => {
      const body = await postJSON("/api/precheck", { channel: "renjiu", issue, faces: state.picks }, "审票接口");
      if (seq !== state.seq) return;       // 过期回应丢掉
      state.review = body; state.pending = false;
      renderSide();
    }, 150);
  }

  // ---- 决策表 ----------------------------------------------------------
  function headerRow() {
    const row = el("div", "row head");
    row.setAttribute("role", "row");
    for (const c of COLS) {
      const h = el("span", null, c);
      h.setAttribute("role", "columnheader");
      row.append(h);
    }
    return row;
  }

  function cell(cls, text) {
    const c = el("span", cls, text);
    c.setAttribute("role", "cell");
    return c;
  }

  function render() {
    const focusKey = document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.focus : null;
    const table = document.getElementById("table");
    table.setAttribute("aria-label", `${issue} 决策表`);
    table.replaceChildren(headerRow());
    for (const m of state.data.matches || []) {
      const p = m.packet || {};
      const tier = p.tier || "?";
      const open = state.open === m.no;
      const wrap = el("div", "match" + (open ? " open" : "") + (tier === "D" ? " coin" : ""));
      const row = el("div", "row");
      row.setAttribute("role", "row");

      row.append(cell("no mono", m.no));

      const nameCell = cell("name-cell");
      const name = button("name", m.name || `场 ${m.no}`, () => {
        state.open = open ? null : m.no; render();
      });
      name.setAttribute("aria-expanded", String(open));
      name.dataset.focus = `name-${m.no}`;
      nameCell.append(name);
      row.append(nameCell);

      const tierCell = cell("tier-cell");
      tierCell.append(el("span", "tier tier-" + tier.charAt(0).toUpperCase(), tier));
      row.append(tierCell);

      const cells = cell("cells");
      for (const k of FACES) {
        const on = (state.picks[m.no] || "").includes(k);
        const prob = faceProb(m.fair, k);
        const shown = prob == null ? "—" : pct(prob);
        const b = button("cell" + (on ? " on" : ""), null, () => toggle(m.no, k));
        b.setAttribute("aria-pressed", String(on));
        b.setAttribute("aria-label", `场 ${m.no} ${NAME[k]} ${shown}%`);
        b.dataset.focus = `cell-${m.no}-${k}`;
        b.append(el("small", null, k), el("b", "mono", shown));
        cells.append(b);
      }
      row.append(cells);

      row.append(
        cell("cond mono", p.k != null && p.n != null ? `${p.k}/${p.n}` : "—"),
        cell("flip", p.flip || ""),
        cell("dflt", p.default || ""),
        cell("dead mono", p.dead || ""),
      );
      const lineupCell = cell("lineup-cell");
      if (p.lineup_at) lineupCell.append(el("span", "lineup" + (p.lineup_before_close ? " pre" : ""), p.lineup_at));
      row.append(lineupCell);

      wrap.append(row);
      if (open && window.renderDrawer) wrap.append(window.renderDrawer(m, state));   // 第 2 阶段
      table.append(wrap);
    }
    if (focusKey) {
      const again = table.querySelector(`[data-focus="${focusKey}"]`);
      if (again) again.focus();
    }
    renderSide();
    renderBridge();
  }

  // ---- 侧栏：草案卡 / 审票卡 / 死法清单 ---------------------------------
  function stat(label, value, cls) {
    const box = el("div", "stat");
    box.append(el("span", "label", label), el("span", "value" + (cls ? " " + cls : ""), value));
    return box;
  }

  function verdictBox(level, tag, text) {
    const box = el("div", "v v-" + level);
    box.append(el("span", "tag", tag), el("span", "text", text));
    return box;
  }

  function lineLevel(line) {
    return line.startsWith("⛔") ? "veto" : line.startsWith("⚠️") ? "warn" : "info";
  }

  function renderSide() {
    const draft = document.getElementById("draft");
    const rev = document.getElementById("review");
    draft.replaceChildren(); rev.replaceChildren();
    draft.className = "card draft";
    rev.className = "card review";
    const r = state.review;
    const head = el("div", "card-head");
    head.append(el("span", "card-title", "我的草案"),
      el("span", "card-sub", state.pending ? "审票中…" : (r && r.ok ? r.mode : "")));
    draft.append(head);
    renderGo();

    if (!r) {
      const dflt = (state.data && state.data.default) || {};
      draft.append(el("p", "muted", state.pending ? "审票中…" : "点格出票，审票随点即算。"),
        el("p", "muted", "机器默认：" + (dflt.action || "—") + (dflt.reason ? `（${dflt.reason}）` : "")));
      rev.hidden = true;
      return;
    }
    if (!r.ok) {
      draft.append(el("p", "error", r.error || "审票失败"));
      rev.hidden = true;
      return;
    }
    const grid = el("div", "stats");
    grid.append(stat("形", r.shape || "—"), stat("金额", `¥${r.stake}`, "mono"),
      stat("P 全对", r.p != null ? `${pct(r.p, 2)}%` : "—", "mono"));
    draft.append(grid, el("code", "row500 mono", r.faces_row || "（还没选场）"),
      el("span", "foot", `${r.notes} 注 · 正式 P 与 V 码以 precheck（同 betslip preview）为准`));

    rev.hidden = false;
    const rhead = el("div", "card-head");
    rhead.append(el("span", "card-title", "审票 · 随点即算"), el("span", "card-sub", "precheck"));
    rev.append(rhead);
    for (const v of r.verdicts || []) {
      rev.append(verdictBox(v.level, `${MARK[v.level] || ""}${v.code}`, v.text));
    }
    for (const line of r.discipline || []) {
      rev.append(verdictBox(lineLevel(line), lineLevel(line) === "veto" ? "⛔纪律" : "纪律", line.replace(/^⛔/, "")));
    }
    if (r.brake_line) {
      const lvl = lineLevel(r.brake_line);
      rev.append(verdictBox(lvl, lvl === "veto" ? "⛔止损" : "止损", r.brake_line.replace(/^⛔/, "")));
    }

    const gates = r.gates || [];
    if (gates.length) rev.append(gatesSection(gates, "死法清单 · 先要过的门"));
    rev.append(el("span", "foot", "⛔ 只表示审票不同意；登记永远可以，否决会随票入账。"));
  }

  // 死法清单五门：侧栏审票卡与桥面板同一份排版（门本身来自服务端 death_list）
  function gatesSection(gates, title) {
    const sec = el("div", "gates-wrap");
    sec.append(el("h3", null, title));
    const ol = el("ol", "gates");
    gates.forEach((g, i) => {
      const li = el("li", "gate" + (g.p >= 0.3 ? " hot" : "") + (g.coin ? " coin" : ""));
      li.append(el("span", "label", `第 ${i + 1} 道门`),
        el("span", "what", `${g.no} 开 ${g.face}` + (g.coin ? " ·D档" : "")),
        el("span", "p mono", `${pct(g.p)}%`));
      ol.append(li);
    });
    sec.append(ol, el("span", "foot", "红框＝≥30% 的排除面；·D档＝硬币场"));
    return sec;
  }

  // ---- 取证抽屉（第 2 阶段）：§1c 反证矩阵 + 翻车面 + §1d 格 + 引用按钮 ------
  // 矩阵是 counter_matrix.issue_matrices 的原样输出，这里只排版；研究里的 URL 是不可信输入，
  // 只有 http(s) 才成链接，链接文字只写站点名。
  const SIGN = (v) => (v >= 2 ? "++" : v > 0 ? "+" : v <= -2 ? "−−" : v < 0 ? "−" : "·");
  const MX_COLS = ["行", "证据", "类", "来源", "价态", "H1", "H2", "引用"];

  function safeHref(u) {
    try {
      const x = new URL(String(u));
      return /^https?:$/.test(x.protocol) ? x : null;
    } catch {
      return null;
    }
  }

  function block(label, lines, cls) {
    const b = el("div", "blk" + (cls ? " " + cls : ""));
    b.append(el("small", null, label));
    for (const t of lines) if (t) b.append(el("span", null, t));
    return b;
  }

  function sourceCell(r) {
    const src = el("span", "mx-src");
    src.setAttribute("role", "cell");
    const url = r.source_url ? safeHref(r.source_url) : null;
    if (url) {
      const a = el("a", null, url.hostname);
      a.href = url.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = url.href;
      src.append(a);
    } else {
      src.textContent = r.source_text || "—";
    }
    return src;
  }

  function matrixTable(m, mx, st) {
    const table = el("div", "mx");
    table.setAttribute("role", "table");
    table.setAttribute("aria-label", `场 ${m.no} 反证矩阵`);
    const scroll = el("div", "mx-scroll");
    const head = el("div", "mx-row mx-head");
    head.setAttribute("role", "row");
    for (const t of MX_COLS) {
      const h = el("span", null, t);
      h.setAttribute("role", "columnheader");
      head.append(h);
    }
    scroll.append(head);
    if (!mx.rows.length) scroll.append(el("p", "mx-empty muted", "研究没有一条有区分力的证据"));
    mx.rows.forEach((r, i) => {
      const k = i + 1;
      const on = st.cites[m.no] === k;
      const row = el("div", "mx-row" + (on ? " cited" : ""));
      row.setAttribute("role", "row");
      const price = r.priced_in == null ? "—" : r.priced_in ? "价内" : "未价";
      const cite = button("cite" + (on ? " on" : ""), on ? "已引用" : "引用", () => {
        if (on) delete st.cites[m.no]; else st.cites[m.no] = k;
        render();
        bridgeRefresh();                   // 桥上：该格理由随引用即时重对照
      });
      cite.setAttribute("aria-pressed", String(on));
      cite.setAttribute("aria-label", `引用场 ${m.no} 矩阵行 ${k} 作为理由`);
      cite.dataset.focus = `cite-${m.no}-${k}`;
      const citeCell = cell("mx-cite");
      citeCell.append(cite);
      row.append(cell("mono muted", k), cell("mx-ev", r.evidence), cell("sub", r.kind), sourceCell(r),
        cell(r.priced_in === false ? "unpriced" : "sub", price),
        cell("mono sign", SIGN(r.h1)), cell("mono sign", SIGN(r.h2)), citeCell);
      scroll.append(row);
    });
    table.append(scroll);
    const inc = mx.inconsistent || {};
    table.append(el("p", "mx-foot",
      `不一致数 H1 ${inc.h1 ?? "—"} · H2 ${inc.h2 ?? "—"}（少者为 ACH 首选，只排序不推概率）`
      + (mx.loose ? ` · 区分力行 ${mx.rows.length} > 5：打分偏松` : "")
      + ` · 无区分力 ${mx.hidden ?? 0} 条不显示 · 引用＝把这一行写成该格的理由`));
    return table;
  }

  window.renderDrawer = (m, st) => {
    const mx = m.matrix || {};
    const p = m.packet || {};
    const hasMatrix = !mx.missing && Array.isArray(mx.rows);
    const box = el("div", "drawer");
    box.dataset.focus = `drawer-${m.no}`;   // 桥上「去取证」按它滚到抽屉
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", `取证 · 场 ${m.no}`);

    const head = el("div", "drawer-head");
    head.append(el("strong", null, `取证 · 场 ${m.no} ${m.name || ""}`.trim()));
    if (hasMatrix) {
      const hyp = el("span", "sub");
      hyp.append("H1 锚方面 ", el("b", "mono", mx.h1), " 对 H2 翻车面 ", el("b", "mono", mx.h2));
      const cov = mx.coverage && mx.coverage !== "—";
      head.append(hyp, el("span", "chip show", cov
        ? `研究收敛 ${mx.coverage}` + (mx.stop_reason && mx.stop_reason !== "coverage" ? `（${mx.stop_reason}）` : "")
        : "研究收敛 — · 引用制前落盘，只有来源名"));
    } else {
      head.append(el("span", "muted", "这场没有研究件（无反证矩阵）"));
    }
    box.append(head);

    const grid = el("div", "drawer-grid");
    if (hasMatrix) grid.append(matrixTable(m, mx, st));

    const side = el("div", "drawer-side");
    const lineup = p.lineup_at ? `首发 ${p.lineup_at}${p.lineup_before_close ? "（停售前可见）" : "（停售后）"}` : null;
    const researchUnk = hasMatrix && mx.unknowable_before_close && mx.unknowable_before_close !== "—"
      ? `研究：${mx.unknowable_before_close}` : null;
    side.append(block("停售前拿不到", [p.unknowable || lineup || (researchUnk ? null : "—"), researchUnk]));
    if (p.c1) {
      side.append(block("翻车面 · §1c", [p.c1.path, `固定招：${p.c1.move || "—"}`,
        `弱方能进球：${p.c1.q3a || "—"}`, `热门零封：${p.c1.fav || "—"}`,
        p.c1.weak_check && `标弱加查：${p.c1.weak_check}`], "c1"));
    } else {
      side.append(block("翻车面 · §1c", [p.tier === "D" ? "D 档硬币场：§1c 不列" : "旁车未给 §1c"]));
    }
    if (p.d1) {
      const d = p.d1;
      const diff = d.diff == null ? "—" : `${d.diff > 0 ? "+" : ""}${d.diff}pp`;
      side.append(block("历史同类格 · §1d · 只展示", [d.cell,
        `${d.layer || "—"} · n=${d.n ?? "—"} · 开 热/平/冷 ${d.open || "—"} · 热门开 ${d.hot_pct ?? "—"}%`
        + ` 对市场 ${d.p1 ?? "—"} · 差 ${diff}`], "show"));
    }
    if (hasMatrix) side.append(block("翻盘证据（研究自己写的）", [mx.falsifier || "（研究未写）"]));
    if (p.anchor || p.hole) side.append(block("锚方中轴 · 洞", [p.anchor, p.hole]));
    if (p.watch || p.consistency || p.crowd) {
      side.append(block("赛前看谁 · 一致性 · 人群", [p.watch && `看：${p.watch}`,
        p.consistency && `一致性：${p.consistency}`, p.crowd && `人群：${p.crowd}`]));
    }
    grid.append(side);
    box.append(grid);
    return box;
  };

  // ---- 按钮 ------------------------------------------------------------
  let goBtn = null;
  let goNote = null;
  function renderActions() {
    const host = document.getElementById("actions");
    host.replaceChildren();
    host.className = "actions";
    goBtn = button("btn primary", "带着这版走 §3 桥 →", enterBridge);
    goBtn.dataset.focus = "go-bridge";
    goNote = el("span", "foot");
    const main = state.data.main_shape;
    const copy = button("btn", main ? `照抄主形 ${main.label || ""}`.trim() : "照抄主形（旁车无主形）",
      () => main && setPicks(main.faces));
    copy.disabled = !main || !main.faces;
    if (main) copy.setAttribute("aria-label", `照抄分析包 §2 主形 ${main.label || ""}`);
    const clear = button("btn", "清空", () => setPicks({}));
    clear.setAttribute("aria-label", "清空所有已选的格");
    host.append(goBtn, goNote, copy, clear);
    renderGo();
  }

  const nPicks = () => Object.keys(state.picks).length;
  const walkable = () => WALKABLE.includes(nPicks());
  const hhmm = (at) => {
    const m = /T(\d\d:\d\d)/.exec(String(at || ""));
    return m ? m[1] : "时刻不明";
  };

  function renderGo() {
    if (!goBtn) return;
    if (state.mode === "draft") {
      goBtn.textContent = "带着这版走 §3 桥 →";
      goBtn.disabled = !walkable();
      goNote.textContent = walkable()
        ? "桥只走一次：对照一次、改一次、定稿。"
        : `选满 9 场（任九）或 14 场（胜负彩）才能走桥 · 已选 ${nPicks()} 场`;
    } else if (state.mode === "bridge") {
      goBtn.textContent = "桥上 · 见下方 §3 面板";
      goBtn.disabled = true;
      goNote.textContent = "改格、引用、写理由都在桥上即时对照；定稿按钮在面板底部。";
    } else {
      goBtn.textContent = `桥已走过 · ${hhmm((state.record || {}).at)}`;
      goBtn.disabled = true;
      goNote.textContent = "B1 已登记（试玩）。表仍可改；之后的实票由账房在 §5⑪ 和 B1 比。";
    }
  }

  // ---- §3 桥（第 3 阶段）：进桥 → 每改一格重对照 → 定稿登记 B1 ----------------
  function scrollToBridge() {
    const host = document.getElementById("bridge");
    if (host && typeof host.scrollIntoView === "function") host.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function enterBridge() {
    if (state.mode !== "draft" || !walkable()) return;
    state.mode = "bridge";
    state.draft0 = { ...state.picks };
    state.bview = null;
    state.berror = "";
    renderGo();
    renderBridge();
    bridgeRefresh();
    scrollToBridge();
  }

  const outsFor = () => {
    const out = {};
    for (const [no, t] of Object.entries(state.outs)) if (String(t).trim()) out[no] = String(t).trim();
    return out;
  };

  let btimer = null;
  function bridgeRefresh() {
    if (state.mode !== "bridge") return;
    clearTimeout(btimer);
    const seq = ++state.bseq;              // 新改动让在途的旧对照作废
    state.bpending = true;
    setBridgeStatus();
    btimer = setTimeout(async () => {
      const body = await postJSON(`/api/bridge/${encodeURIComponent(issue)}/preview`,
        { faces: { ...state.picks }, cites: { ...state.cites }, outs: outsFor(), signed_bold: signedNos() },
        "桥对照接口");
      if (seq !== state.bseq || state.mode !== "bridge") return;   // 过期回应丢掉
      state.bpending = false;
      if (body.ok) {
        state.bview = body;
        state.berror = "";
      } else {
        state.berror = body.error || "桥对照失败";   // 保留上一版对照，横幅说明
      }
      renderBridge();
    }, 150);
  }

  function backToDraft() {                // 回草案：什么都没写，服务端无可清；再进桥另记 draft0
    if (state.mode !== "bridge" || state.submitting) return;
    clearTimeout(btimer);
    state.bseq++;                          // 在途的对照一律丢掉
    state.bpending = false;
    state.mode = "draft";
    state.draft0 = null;
    state.bview = null;
    state.berror = "";
    renderBridge();
    if (goBtn) goBtn.focus({ preventScroll: true });
    const acts = document.getElementById("actions");
    if (acts && typeof acts.scrollIntoView === "function") acts.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function toggleSign(no) {
    if (state.signed[no]) delete state.signed[no];
    else if (isSingle(no)) state.signed[no] = true;
    renderBridge();
    bridgeRefresh();
  }

  let statusEl = null;
  function setBridgeStatus() {
    if (!statusEl) return;
    statusEl.textContent = state.submitting ? "登记中…" : state.bpending ? "对照中…" : state.bview ? "已对照" : "";
  }

  async function finalize() {
    if (state.mode !== "bridge" || state.submitting) return;
    clearTimeout(btimer);
    state.bseq++;                          // 定稿后到的对照一律丢掉
    state.bpending = false;
    state.submitting = true;
    state.berror = "";
    renderBridge();
    const v = state.bview || {};
    const failing = v.checks ? new Set(v.checks.filter((c) => !c.ok).map((c) => String(c.id))) : null;
    const whys = {};
    for (const [id, t] of Object.entries(state.whys)) {
      if (String(t).trim() && (!failing || failing.has(String(id)))) whys[id] = String(t).trim();
    }
    const payload = {
      issue, draft0: { ...(state.draft0 || {}) }, faces: { ...state.picks }, cites: { ...state.cites },
      outs: outsFor(), whys, signed_bold: signedNos(), deviation: state.deviation,
      prediction: state.prediction.trim(),
    };
    const body = await postJSON("/action/bridge", payload, "定稿接口");
    state.submitting = false;
    if (!body.ok) {
      state.berror = body.error || "定稿失败";
      renderBridge();
      return;
    }
    let record = null;
    try {
      record = (await fetchIssue()).bridge;   // 以落盘的桥记录为准
    } catch {
      record = null;
    }
    state.record = record || {
      at: body.at, slip_id: `${issue}-B1`, draft0: payload.draft0, faces: payload.faces,
      main_label: v.main_label, diffs: v.diffs || [], readout: body.readout,
      checks: (v.checks || []).map((c) => (whys[c.id] ? { ...c, why: whys[c.id] } : c)),
      signed_bold: payload.signed_bold.map((no) => ({ no, face: payload.faces[no] })),
      deviation: payload.deviation, prediction: payload.prediction,
    };
    state.registered = { summary: body.summary, lines: body.lines || [] };
    state.mode = "walked";
    renderGo();
    renderBridge();
  }

  function gotoEvidence(no) {
    state.open = String(no);
    render();
    const table = document.getElementById("table");
    const drawer = table.querySelector(`[data-focus="drawer-${no}"]`);
    const name = table.querySelector(`[data-focus="name-${no}"]`);
    if (name) name.focus({ preventScroll: true });
    if (drawer && typeof drawer.scrollIntoView === "function") drawer.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function toggleOut(no) {
    if (state.cites[no] === "out") delete state.cites[no]; else state.cites[no] = "out";
    render();                              // 抽屉里该场「已引用」随之熄灭
    bridgeRefresh();
  }

  const nameOf = (no) => ((state.data.matches || []).find((m) => m.no === String(no)) || {}).name || "";
  const faceText = (f) => f || "丢";
  const coverText = (face, x) => (face ? `${pct(x)}%` : "丢");

  function textInput(focusKey, value, label, placeholder, onInput) {
    const input = el("input", "b-input");
    input.type = "text";
    input.value = value || "";
    input.placeholder = placeholder;
    input.setAttribute("aria-label", label);
    input.dataset.focus = focusKey;
    input.addEventListener("input", (e) => onInput(e.target.value));
    return input;
  }

  function sectionTitle(text, sub) {
    const head = el("div", "b-sec-head");
    head.append(el("h3", null, text));
    if (sub) head.append(el("span", "muted", sub));
    return head;
  }

  function openingBox(lines) {
    const box = el("div", "b-opening");
    box.append(el("strong", null, "先复述：每条单靠什么成立、停售前拿不到什么"));
    for (const line of lines || []) {
      const row = el("div", "b-open-row");
      row.append(el("span", "b-open-label", line.label), el("span", "b-open-text", line.text));
      box.append(row);
    }
    return box;
  }

  function checksList(checks, editable) {
    const sec = el("div", "b-col");
    sec.append(sectionTitle("§3a 五条自检", editable ? "✗ 不拦定稿：写一句为什么仍然这样" : null));
    for (const c of checks || []) {
      const box = el("div", "b-check" + (c.ok ? " ok" : " fail"));
      const line = el("div", "b-check-line");
      const mark = el("span", "b-mark", c.ok ? "✓" : "✗");
      mark.setAttribute("aria-label", c.ok ? "通过" : "不通过");
      const body = el("div", "b-check-body");
      body.append(el("span", "b-check-title", `${c.id} · ${c.title}`), el("span", "b-check-detail", c.detail));
      line.append(mark, body);
      box.append(line);
      if (c.id === 2 && editable && (c.signable || []).length) box.append(signBox(c.signable));
      if (!c.ok && editable) {
        const why = el("label", "b-why");
        why.append(el("span", null, "我为什么仍然这样（停售前写，赛后对账）"),
          textInput(`b-why-${c.id}`, state.whys[c.id], `第 ${c.id} 条：我为什么仍然这样`, "一句话",
            (t) => { state.whys[c.id] = t; }));
        box.append(why);
      } else if (!c.ok) {
        box.append(el("span", "b-why-done" + (c.why ? "" : " blank"), c.why ? `我为什么仍然这样：${c.why}` : "没写为什么仍然这样"));
      }
      sec.append(box);
    }
    return sec;
  }

  // ② 里的「签为博胆」：服务端列的不许可单（signable）各一个开关；签 >1 条只警告不拦
  function signBox(signable) {
    const box = el("div", "b-signs");
    box.append(el("span", "b-signs-note", "C/D 档人群另一边买奖金的单可签为博胆；签了 ② 就算它有许可"));
    const row = el("div", "b-tools");
    for (const s of signable) {
      const no = String(s.no);
      const on = Boolean(state.signed[no]);
      const label = `${no}·${state.picks[no] || s.face}`;
      const tog = button("b-btn sign" + (on ? " on" : ""), on ? `${label} 已签博胆` : `${label} 签为博胆`,
        () => toggleSign(no));
      tog.dataset.focus = `b-sign-${no}`;
      tog.setAttribute("aria-pressed", String(on));
      tog.setAttribute("aria-label", `把场 ${label} 签为博胆`);
      row.append(tog);
    }
    box.append(row);
    const n = signedNos().length;
    if (n > 1) {
      const warn = el("p", "b-warn", `每票博胆 ≤1（§3a ③）：已签 ${n} 条`);
      warn.setAttribute("role", "status");
      box.append(warn);
    }
    return box;
  }

  function reasonNode(d) {
    const r = d.reason;
    if (r && r.kind === "matrix") {
      return el("span", "b-reason", `场 ${d.no}·矩阵行 ${r.row}：${r.evidence || "（该行已不在矩阵里）"}`);
    }
    if (r && r.kind === "out") return el("span", "b-reason", `矩阵外：${r.text}`);
    return el("span", "b-reason blank", "还没写理由");
  }

  function diffTable(diffs, editable) {
    const box = el("div", "b-diff");
    box.setAttribute("role", "table");
    box.setAttribute("aria-label", "差异格 · 和主形不同的格");
    const scroll = el("div", "b-diff-scroll");
    const head = el("div", "b-diff-row b-diff-head");
    head.setAttribute("role", "row");
    for (const t of ["格", "我的", "主形", "盖住 → / 排除 →", "理由"]) {
      const h = el("span", null, t);
      h.setAttribute("role", "columnheader");
      head.append(h);
    }
    scroll.append(head);
    if (!(diffs || []).length) scroll.append(el("p", "b-diff-empty muted", "和主形一格不差。"));
    for (const d of diffs || []) {
      const row = el("div", "b-diff-row");
      row.setAttribute("role", "row");
      const cover = cell("b-cover mono");
      cover.append(el("span", null, `盖住 ${coverText(d.main, d.cover_main)} → ${coverText(d.mine, d.cover_mine)}`),
        el("span", null, `排除 ${coverText(d.main, d.excl_main)} → ${coverText(d.mine, d.excl_mine)}`));
      const why = cell("b-why-cell");
      why.append(reasonNode(d));
      if (editable) {
        const out = state.cites[d.no] === "out";
        const tools = el("div", "b-tools");
        const ev = button("b-btn link", "去取证", () => gotoEvidence(d.no));
        ev.dataset.focus = `b-ev-${d.no}`;
        ev.setAttribute("aria-label", `打开场 ${d.no} 取证抽屉去引用矩阵行`);
        const tog = button("b-btn" + (out ? " on" : ""), "矩阵外", () => toggleOut(d.no));
        tog.dataset.focus = `b-out-${d.no}`;
        tog.setAttribute("aria-pressed", String(out));
        tog.setAttribute("aria-label", `场 ${d.no} 的理由在矩阵外`);
        tools.append(ev, tog);
        why.append(tools);
        if (out) {
          why.append(textInput(`b-outtext-${d.no}`, state.outs[d.no], `场 ${d.no} 矩阵外理由`, "矩阵外：一句话",
            (t) => { state.outs[d.no] = t; bridgeRefresh(); }));
        }
      }
      row.append(cell("b-cell-no", `${d.no} ${nameOf(d.no)}`.trim()), cell("mono strong", faceText(d.mine)),
        cell("mono sub", faceText(d.main)), cover, why);
      scroll.append(row);
    }
    box.append(scroll);
    return box;
  }

  function readoutLine(r) {
    const box = el("div", "b-readout");
    const x = r || {};
    box.append(el("span", "mono", `差异格 ${x.diffs ?? "—"} · 指到矩阵行 ${x.matrix ?? "—"} · 矩阵外 ${x.outside ?? "—"} · 未写 ${x.blank ?? "—"}`),
      el("span", "sub", "进 §5⑪ 计数"));
    return box;
  }

  function deviationBox() {
    const sec = el("div", "b-dev");
    sec.append(sectionTitle("偏离机器默认的理由", "五选一；不选也能登记，账上记「偏离初稿未登记理由」"));
    const chips = el("div", "b-chips");
    for (const [code, label] of DEVIATIONS) {
      const on = state.deviation === code;
      const chip = button("b-chip" + (on ? " on" : ""), label, () => {
        state.deviation = on ? "" : code;
        renderBridge();
      });
      chip.dataset.focus = `b-dev-${code}`;
      chip.setAttribute("aria-pressed", String(on));
      chips.append(chip);
    }
    const pred = el("label", "b-why");
    pred.append(el("span", null, "一句可证伪的预测"),
      textInput("b-pred", state.prediction, "一句可证伪的预测", "写一句赛后能判对错的话",
        (t) => { state.prediction = t; }));
    sec.append(chips, pred);
    return sec;
  }

  function errorBanner(host) {
    if (!state.berror) return;
    const banner = el("p", "b-error", state.berror);
    banner.setAttribute("role", "alert");
    host.append(banner);
  }

  function bridgePanel(host) {
    const v = state.bview;
    const main = (v && v.main_label) || (state.data.main_shape || {}).label || "—";
    const head = el("div", "b-head");
    const h = el("h2", null, "§3 桥 · 对照一次、改一次");
    h.id = "bridge-h";
    const changed = Object.keys({ ...state.picks, ...(state.draft0 || {}) })
      .filter((no) => (state.picks[no] || "") !== ((state.draft0 || {})[no] || "")).length;
    statusEl = el("span", "b-status");
    head.append(h, el("span", "muted",
      `对照对象：§2 主形 ${main}` + (v ? ` · 本版 ${v.shape || "—"} ¥${v.stake ?? "—"} · P ${v.p != null ? pct(v.p, 2) + "%" : "—"}` : "")
      + ` · 桥上已改 ${changed} 格`), statusEl);
    host.append(head);
    errorBanner(host);
    const known = new Set(state.data.errors || []);       // 页顶横幅已报的不重复
    const fresh = v ? (v.errors || []).filter((e) => !known.has(e)) : [];
    if (fresh.length) host.append(el("p", "foot", "旁车提示：" + fresh.join("；")));
    if (!v) {
      host.append(el("p", "muted", state.bpending ? "对照中…" : "还没有对照结果。"));
    } else {
      host.append(openingBox(v.opening));
      const cols = el("div", "b-cols");
      const right = el("div", "b-col");
      right.append(sectionTitle("§3b 差异格 · 和主形不同的格", "抽屉里点「引用」即写成该格理由"),
        diffTable(v.diffs, true), readoutLine(v.readout));
      cols.append(checksList(v.checks, true), right);
      host.append(cols);
      if ((v.gates || []).length) host.append(gatesSection(v.gates, "§3c 死法清单 · 先要过的门"));
    }
    host.append(deviationBox());

    const acts = el("div", "b-actions");
    const fails = v ? (v.checks || []).filter((c) => !c.ok).length : 0;
    const fin = button("btn primary", state.submitting ? "登记中…" : "定稿 · 登记桥后票 B1（试玩）", finalize);
    fin.dataset.focus = "b-final";
    fin.disabled = state.submitting;
    const mainShape = state.data.main_shape;
    const copy = button("btn", `再想改就照抄主形 ${main}`, () => mainShape && setPicks(mainShape.faces));
    copy.dataset.focus = "b-copy";
    copy.disabled = !mainShape || !mainShape.faces || state.submitting;
    const back = button("btn", "回草案（不登记）", backToDraft);
    back.dataset.focus = "b-back";
    back.disabled = state.submitting;
    back.setAttribute("aria-label", "回到草案继续改，不登记；已写的理由和签名都保留");
    const notes = [];
    if (fails) notes.push(`五条自检 ✗ ${fails} 条——不拦定稿，写的「为什么」随桥记录入账`);
    if (!state.deviation) notes.push("未选偏离理由：照样可登记，账上记「偏离初稿未登记理由」");
    notes.push("⛔ 只表示审票不同意；登记永远可以，否决会随票入账。桥只走一次。");
    acts.append(fin, copy, back, el("span", "foot", notes.join("；")));
    host.append(acts);
  }

  function walkedPanel(host) {
    const rec = state.record || {};
    const head = el("div", "b-head");
    const h = el("h2", null, "§3 桥 · 已走过（只走一次）");
    h.id = "bridge-h";
    statusEl = null;
    head.append(h, el("span", "muted", `对照对象：§2 主形 ${rec.main_label || "—"}`));
    host.append(head,
      el("p", "b-walked", `已走桥 · ${hhmm(rec.at)} · ${rec.slip_id || "B1"} 已登记（试玩）· 停售播报会报「未确认实购」`));
    errorBanner(host);
    if (state.registered) {
      host.append(el("p", "foot", state.registered.summary || ""));
      for (const line of state.registered.lines || []) host.append(el("p", "foot", line));
    }
    const cols = el("div", "b-cols");
    const right = el("div", "b-col");
    right.append(sectionTitle("§3b 差异格 · 和主形不同的格"), diffTable(rec.diffs, false), readoutLine(rec.readout));
    cols.append(checksList(rec.checks, false), right);
    host.append(cols);
    const bold = (rec.signed_bold || []).map((x) => `${x.no}·${x.face}`);
    if (bold.length) host.append(el("p", "b-dev-done", `签了博胆：${bold.join("、")}`));
    const dev = (DEVIATIONS.find(([code]) => code === rec.deviation) || [null, null])[1];
    host.append(el("p", "b-dev-done", `偏离理由：${dev || (rec.deviation || "未选")} · 预测：${rec.prediction || "没写"}`),
      el("p", "foot", "表仍可改；之后登记的实票由账房在 §5⑪ 和 B1 逐格比，页面不另记。"));
  }

  function renderBridge() {
    const host = document.getElementById("bridge");
    if (!host || !state.data) return;
    renderGo();
    const active = document.activeElement;
    const key = active && active.dataset ? active.dataset.focus : null;
    const sel = active && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
    host.replaceChildren();
    host.hidden = state.mode === "draft";
    if (state.mode === "draft") {
      statusEl = null;
      return;
    }
    if (state.mode === "walked") walkedPanel(host); else bridgePanel(host);
    setBridgeStatus();
    if (key && key.startsWith("b-")) {      // 重画不丢焦点与光标（输入框边打边对照）
      const again = host.querySelector(`[data-focus="${key}"]`);
      if (again) {
        again.focus();
        if (sel && typeof again.setSelectionRange === "function") again.setSelectionRange(sel[0], sel[1]);
      }
    }
  }

  load();
})();
