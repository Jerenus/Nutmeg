// static/decision/jczq.js —— 竞彩当日板（2026-10-28 产品形态第 5 阶段 Task 5.2，画布 Jczq.dc.html）。
// 推导一律在服务端：板面 / 每元回报 / 计数来自 /api/jczq/{日}；过关方式 / 注数 / 金额 / P / 中了拿回 /
// 期望回报率 / V 码 / 纪律 / 止损来自 /api/jczq/{日}/precheck（与 `betslip preview --channel jczq` 同一份）。
// 页面只送选择表 {编号: 面} 与倍数——赔率由服务端按体彩快照组腿，这里改不了它。
// 「我已在 500 下单 · 登记」→ /action/jczq/{日}/register（票号 <YYYYMMDD>-J<n> 服务端分配），每张一份回执。
// 研究文本是不可信输入：全部 textContent，不用 innerHTML。
(() => {
  "use strict";
  const root = document.getElementById("jczq");
  if (!root) return;
  const day = root.dataset.day;
  const h1 = root.querySelector(".jczq-head h1");
  if (h1 && window.NMAsk) h1.after(window.NMAsk.button(`jczq:${day}`, `竞彩 ${day} 整板`, "head-ask"));
  const FACES = ["3", "1", "0"];
  const NAME = { 3: "胜", 1: "平", 0: "负" };
  const MARK = { veto: "⛔", warn: "⚠️", info: "ℹ️" };
  const COLS = ["编号", "开球", "对阵", "胜 · 平 · 负", "让球", "表态 · 示", "旗 · 损耗", "关注度 · 示"];
  const HARD = ["STOP", "BRAKE", "DAYCAP"];   // 纪律否决码：一律 ⛔（同期页）
  const MULT_MIN = 1;
  const MULT_MAX = 99;
  // 偏离理由封闭枚举 = betslip_diagnosis.DEVIATION_REASONS；空串也收（账上记「偏离初稿未登记理由」）
  const DEVIATIONS = [["fact_self_judged", "自判事实"], ["price_instinct", "价格直觉"],
    ["stake_allocation", "资金分配"], ["structure_preference", "结构偏好"], ["other", "其他"]];

  // PM ≥$2万：服务端只给了关注度格的文本（crowd_polymarket.brief_cell：`PM$80k 73/16/11 主+3.1 …`），
  // 没有单独的成交额字段，所以这里从文本里解析 `PM$<n>k`。brief_cell 本身只给成交 ≥$20k 的场出格，
  // 解析只是防格式以后放宽时不误计。
  const pmVolumeK = (text) => {
    const m = /PM\$(\d+(?:\.\d+)?)k/.exec(String(text || ""));
    return m ? Number(m[1]) : 0;
  };
  // 大热 ≥70：用服务端的 fav 格（judgment_brief：终盘 sharp 或市场去水最大面 ≥70% 才有值），不在页面重算。
  const FILTERS = [
    ["all", "全部", () => true],
    ["open", "未开球", (r) => !r.kicked],
    ["single", "表态单", (r) => String(r.stance || "").startsWith("单")],
    ["flag", "有旗", (r) => Boolean(String(r.flags || "").trim())],
    ["fav", "大热 ≥70", (r) => Boolean(r.fav)],
    ["pm", "PM ≥$2万", (r) => pmVolumeK(r.attention) >= 20],
  ];

  const state = {
    data: null, filter: "all", open: null, picks: {}, mult: 1,
    review: null, seq: 0, pending: false, error: "",
    reg: { scheme: "", deviation: "", prediction: "", posting: false, error: "" },
    receipts: [], copied: {},
  };

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
  const num2 = (x) => (x == null || Number.isNaN(Number(x)) ? "—" : Number(x).toFixed(2));
  const yuan = (x) => (x == null || Number.isNaN(Number(x)) ? "—" : `¥${Number(x).toLocaleString("en-US")}`);
  const signed = (x) => (x == null || Number.isNaN(Number(x)) ? "—"
    : `${Number(x) < 0 ? "−" : "+"}${Math.abs(Number(x)).toLocaleString("en-US", { maximumFractionDigits: 0 })}`);

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

  // 重画不丢焦点与光标：按 data-focus 找回同一个控件
  function keepFocus(host, draw) {
    const active = document.activeElement;
    const key = active && active.dataset ? active.dataset.focus : null;
    const sel = active && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
    draw();
    if (!key) return;
    const again = host.querySelector(`[data-focus="${key}"]`);
    if (!again) return;
    again.focus();
    if (sel && typeof again.setSelectionRange === "function") again.setSelectionRange(sel[0], sel[1]);
  }

  // ---- 外壳：模板只给了 #brake / #errors / #table / #slip / #review / #actions，其余容器在这里挂上 ----
  const brakeEl = document.getElementById("brake");
  const tableEl = document.getElementById("table");
  const head = brakeEl.parentNode;
  const countsEl = el("div", "counts");
  countsEl.setAttribute("aria-label", "板面计数");
  const readingEl = el("p", "reading");
  head.append(countsEl, readingEl);
  const filtersEl = el("div", "filters");
  filtersEl.setAttribute("role", "group");
  filtersEl.setAttribute("aria-label", "筛选");
  tableEl.parentNode.insertBefore(filtersEl, tableEl);

  // ---- 载入 ----------------------------------------------------------
  async function load() {
    try {
      const r = await fetch(`/api/jczq/${encodeURIComponent(day)}`);
      if (!r.ok) throw new Error(`/api/jczq ${r.status}`);
      state.data = await r.json();
    } catch (exc) {
      showErrors([`竞彩板数据读不出：${exc.message || exc}`]);
      return;
    }
    showErrors(state.data.errors || []);
    renderBrake();
    renderHead();
    renderBoard();
    renderSide();
  }

  function showErrors(list) {
    const errs = document.getElementById("errors");
    errs.hidden = !list.length;
    errs.textContent = list.join("；");
    if (list.length) errs.setAttribute("role", "alert");
  }

  // 刹车带：服务端 status_line 原文 + 余量（不在页面算）
  function renderBrake() {
    brakeEl.replaceChildren();
    const b = state.data.brake || {};
    const line = String(b.line || "");
    const veto = Boolean(b.tripped) || line.startsWith("⛔");
    brakeEl.className = "brake" + (veto ? " veto" : "");
    const left = el("span", "brake-num");
    left.append(el("span", "brake-title", b.tripped ? "刹车 · 止损已触发" : `刹车 · 离止损线还有 ${yuan(b.room)}`),
      el("span", "brake-big mono", signed(b.effective_net)));
    brakeEl.append(left, el("span", "brake-line", line || "止损状态 —"));
  }

  function count(label, value, mono = true) {
    const box = el("div", "count");
    box.append(el("span", "label", label), el("span", "value" + (mono ? " mono" : ""), value));
    return box;
  }

  function renderHead() {
    const c = state.data.counts || {};
    countsEl.replaceChildren(
      count("板面", `${c.rows ?? 0} 场`),
      count("研究", `${c.researched ?? 0} / ${c.rows ?? 0}`),
      count("单关开", String(c.singles_open ?? 0)),
      count("机器", "不构票", false),
    );
    readingEl.replaceChildren();
    const part = (b, rest) => {
      const s = el("span");
      s.append(el("b", null, b), rest);
      return s;
    };
    readingEl.append(
      part("只展示", "：表态、旗、损耗、关注度都不拨动概率；每元回报＝市场去水 % × 体彩 SP（V1 用的就是它）。"),
      part("机器不构票", "：腿由你点，审票随点即算；⛔ 只表示审票不同意，登记永远可以。"),
    );
  }

  // ---- 选面 → 审票（150ms 防抖 + 过期回应丢掉） -------------------------
  function setFace(code, k) {
    const cur = new Set(state.picks[code] || "");
    if (cur.has(k)) cur.delete(k); else cur.add(k);
    const faces = FACES.filter((f) => cur.has(f)).join("");
    if (faces) state.picks[code] = faces; else delete state.picks[code];
    renderBoard();
    review();
  }

  function removeLeg(code) {
    delete state.picks[code];
    renderBoard();
    review();
  }

  function setMult(n) {
    const v = Math.min(MULT_MAX, Math.max(MULT_MIN, Math.round(Number(n) || MULT_MIN)));
    if (v === state.mult) return;
    state.mult = v;
    review();
  }

  let timer = null;
  function review() {
    clearTimeout(timer);
    const seq = ++state.seq;               // 任何新点格 / 新倍数都让在途的旧回应作废
    if (!Object.keys(state.picks).length) {
      state.review = null; state.pending = false; renderSide();
      return;
    }
    state.pending = true; renderSide();
    timer = setTimeout(async () => {
      const body = await postJSON(`/api/jczq/${encodeURIComponent(day)}/precheck`,
        { picks: { ...state.picks }, multiplier: state.mult }, "审票接口");
      if (seq !== state.seq) return;       // 过期回应丢掉
      state.review = body; state.pending = false;
      renderSide();
    }, 150);
  }

  // ---- 板面表 ----------------------------------------------------------
  function cell(cls, text) {
    const c = el("span", cls, text);
    c.setAttribute("role", "cell");
    return c;
  }

  function kickoffCell(r) {
    const c = cell("ko mono");
    const iso = String(r.kickoff || "");
    const date = iso.slice(0, 10);
    const hm = iso.slice(11, 16);
    if (date && date !== day) c.append(el("small", "ko-date", date.slice(5)));   // 次日凌晨场：带日期
    c.append(el("span", null, hm || "—"));
    if (r.kicked) c.append(el("small", "ko-state", "已开球"));
    else if (!r.selectable) c.append(el("small", "ko-state", "不可选"));
    return c;
  }

  const hhadText = (h) => {
    if (!h || h.line == null) return "—";
    const n = Number(h.line);
    return Number.isNaN(n) ? String(h.line) : (n > 0 ? `+${n}` : String(n));
  };

  function renderFilters() {
    const rows = state.data.rows || [];
    filtersEl.replaceChildren();
    for (const [key, label, test] of FILTERS) {
      const on = state.filter === key;
      const b = button("chip" + (on ? " on" : ""), null, () => { state.filter = key; renderBoard(); });
      b.append(label + " ", el("span", "n mono", rows.filter(test).length));
      b.setAttribute("aria-pressed", String(on));
      b.dataset.focus = `filter-${key}`;
      filtersEl.append(b);
    }
    filtersEl.append(el("span", "filters-note", "格内大字＝体彩 SP，小字＝市场去水 %；点格即入串"));
  }

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

  function spCells(r) {
    const box = cell("cells");
    for (const k of FACES) {
      const usable = r.selectable && r.sp && r.sp[k] != null;
      const on = (state.picks[r.code] || "").includes(k);
      const sp = r.sp && r.sp[k] != null ? num2(r.sp[k]) : "—";
      const fair = r.fair && r.fair[k] != null ? `${pct(r.fair[k])}%` : "—";
      const b = button("sp" + (on ? " on" : ""), null, () => { if (usable) setFace(r.code, k); });
      b.append(el("b", "mono", sp), el("small", null, `${NAME[k]} ${fair}`));
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-label", `${r.code} ${r.name} ${NAME[k]} SP ${sp} 市场 ${fair}`);
      if (!usable) {
        b.disabled = true;
        b.setAttribute("aria-disabled", "true");
      }
      b.dataset.focus = `sp-${r.code}-${k}`;
      box.append(b);
    }
    return box;
  }

  function drawer(r) {
    const box = el("div", "drawer");
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", `展开 · ${r.code} ${r.name}`);
    const left = el("div", "drawer-col");
    const blk = (label, text) => {
      const b = el("div", "blk");
      b.append(el("small", null, label), el("span", null, text || "—"));
      return b;
    };
    left.append(blk("研究一句话", r.note), blk("rubric", r.rubric),
      blk("判断种类", r.kind ? `${r.kind}${r.fav ? " · 大热 " + r.fav : ""}` : (r.fav ? "大热 " + r.fav : "")));
    const right = el("div", "drawer-col");
    right.append(el("small", "label", "每元回报 ＝ 市场 % × SP（≥0.90 加框；不等于有边）"));
    const tiles = el("div", "tiles");
    for (const k of FACES) {
      const v = r.ret ? r.ret[k] : null;
      const t = el("div", "tile" + (v != null && Number(v) >= 0.9 ? " hi" : ""));
      t.append(el("small", null, NAME[k]), el("b", "mono", num2(v)));
      tiles.append(t);
    }
    right.append(tiles);
    const h = r.hhad;
    right.append(el("span", "hh", h
      ? `让球 ${hhadText(h)}：胜 ${num2(h["3"])} · 平 ${num2(h["1"])} · 负 ${num2(h["0"])}`
      : "让球：未开售"));
    if (window.NMAsk) left.append(window.NMAsk.button(`jczq:${day}/${r.code}`, `${r.code} ${r.name || ""}`.trim()));
    box.append(left, right);
    return box;
  }

  function renderBoard() {
    if (!state.data) return;
    keepFocus(root, () => {
      renderFilters();
      const test = (FILTERS.find((f) => f[0] === state.filter) || FILTERS[0])[2];
      const rows = (state.data.rows || []).filter(test);
      tableEl.setAttribute("aria-label", `竞彩 ${day} 板面`);
      const body = el("div", "tbl");
      body.append(headerRow());
      if (!rows.length) body.append(el("p", "empty muted", (state.data.rows || []).length ? "这个筛选下没有场。" : "今天板面没有场。"));
      for (const r of rows) {
        const open = state.open === r.code;
        const wrap = el("div", "match" + (open ? " open" : "") + (r.selectable ? "" : " off"));
        const row = el("div", "row");
        row.setAttribute("role", "row");
        row.append(cell("code mono", r.code), kickoffCell(r));

        const nameCell = cell("name-cell");
        const name = button("name", null, () => { state.open = open ? null : r.code; renderBoard(); });
        name.append(r.name || r.code);
        if (r.league) name.append(" ", el("small", null, r.league));
        name.setAttribute("aria-expanded", String(open));
        name.dataset.focus = `name-${r.code}`;
        nameCell.append(name);
        row.append(nameCell, spCells(r), cell("hhad mono", hhadText(r.hhad)));

        const stanceCell = cell("stance-cell");
        stanceCell.append(el("span", "stance", r.stance || "—"));
        row.append(stanceCell);

        const fl = cell("flags-cell");
        const flagText = r.flags || (r.fav ? `大热 ${r.fav}` : "");
        if (flagText) fl.append(el("span", "flag", flagText));
        if (r.load) fl.append(el("span", "load", r.load));
        row.append(fl, cell("pm", r.attention || "—"));

        wrap.append(row);
        if (open) wrap.append(drawer(r));
        body.append(wrap);
      }
      tableEl.replaceChildren(body);
    });
    renderSide();
  }

  // ---- 侧栏：我的串 / 审票卡 / 理由 + 登记 + 回执 --------------------------
  function stat(label, value) {
    const box = el("div", "stat");
    box.append(el("span", "label", label), el("span", "value mono", value));
    return box;
  }

  function verdictBox(level, tag, text) {
    const box = el("div", "v v-" + level);
    box.append(el("span", "tag", tag), el("span", "text", text));
    return box;
  }

  const lineLevel = (line) => (line.startsWith("⛔") ? "veto" : line.startsWith("⚠️") ? "warn" : "info");

  function banner(text) {
    const p = el("p", "banner", text);
    p.setAttribute("role", "alert");
    return p;
  }

  function comboLabel() {
    const r = state.review;
    const n = Object.keys(state.picks).length;
    if (!n) return "未选";
    if (state.pending) return "审票中…";
    if (r && r.ok) return r.combo || "—";
    if (r && !r.ok && /单关未开/.test(String(r.error || ""))) return "单关未开";
    return "—";
  }

  function legsList() {
    const list = el("div", "legs");
    const codes = Object.keys(state.picks).sort();
    if (!codes.length) {
      list.append(el("span", "muted", "还没选腿。点板面里的 SP 格入串。"));
      return list;
    }
    const r = state.review;
    const fromServer = new Map(((r && r.ok && r.legs) || []).map((l) => [l.code, l]));
    const rowBy = new Map((state.data.rows || []).map((x) => [x.code, x]));
    for (const code of codes) {
      const faces = state.picks[code];
      const srv = fromServer.get(code);
      const row = rowBy.get(code) || {};
      // 赔率以审票回包为准（服务端按体彩快照组腿）；回包未到时先用板面 SP 展示
      const odds = srv && srv.faces === faces ? srv.odds : [...faces].map((k) => (row.sp ? row.sp[k] : null));
      const text = [...faces].map((k, i) => `${NAME[k]} @${num2(odds[i])}`).join(" / ");
      const leg = el("div", "leg");
      leg.append(el("span", "leg-code mono", code), el("span", "leg-name", (srv && srv.name) || row.name || ""),
        el("span", "leg-faces mono", text));
      const rm = button("rm", "−", () => removeLeg(code));
      rm.setAttribute("aria-label", `从串里去掉 ${code} ${row.name || ""}`.trim());
      rm.dataset.focus = `rm-${code}`;
      leg.append(rm);
      list.append(leg);
    }
    return list;
  }

  function multRow() {
    const box = el("div", "mult");
    box.append(el("span", "label", "倍数"));
    const down = button("step", "−", () => { setMult(state.mult - 1); });
    down.setAttribute("aria-label", "倍数减一");
    down.dataset.focus = "mult-down";
    down.disabled = state.mult <= MULT_MIN;
    const up = button("step", "+", () => { setMult(state.mult + 1); });
    up.setAttribute("aria-label", "倍数加一");
    up.dataset.focus = "mult-up";
    up.disabled = state.mult >= MULT_MAX;
    const v = el("span", "mult-v mono", state.mult);
    v.setAttribute("aria-live", "polite");
    box.append(down, v, up, el("span", "muted small", `${MULT_MIN}–${MULT_MAX}`));
    return box;
  }

  function renderSlip() {
    const host = document.getElementById("slip");
    host.className = "card slip";
    host.replaceChildren();
    const h = el("div", "card-head");
    h.append(el("span", "card-title", "我的串"), el("span", "card-sub", comboLabel()));
    host.append(h, legsList(), multRow());
    const r = state.review;
    if (r && !r.ok) host.append(banner(r.error || "审票失败"));
    const ok = r && r.ok && !state.pending;
    const grid = el("div", "stats");
    grid.append(stat("金额", ok ? yuan(r.stake) : "—"),
      stat("P 全中 · 市场口径", ok && r.p != null ? `${pct(r.p, 1)}%` : "—"),
      stat("中了拿回", ok ? yuan(r.max_payout) : "—"),
      stat("期望回报率 · V1", ok ? num2(r.ratio) : "—"));
    host.append(grid);
    if (ok) host.append(el("span", "foot", `${r.notes} 注 · ${r.multiplier ?? state.mult} 倍 · 全部来自 precheck（同 betslip preview --channel jczq）`));
  }

  function renderReview() {
    const host = document.getElementById("review");
    host.className = "card review";
    host.replaceChildren();
    const r = state.review;
    if (!r || !r.ok) { host.hidden = true; return; }
    host.hidden = false;
    const h = el("div", "card-head");
    h.append(el("span", "card-title", "审票 · 随点即算"), el("span", "card-sub", state.pending ? "重算中…" : "precheck"));
    host.append(h);
    for (const v of r.verdicts || []) host.append(verdictBox(v.level, `${MARK[v.level] || ""}${v.code}`, v.text));
    for (const line of r.discipline || []) {
      const lvl = lineLevel(String(line));
      host.append(verdictBox(lvl, lvl === "veto" ? "⛔纪律" : "纪律", String(line).replace(/^⛔/, "")));
    }
    if (r.brake_line) {
      const lvl = lineLevel(String(r.brake_line));
      host.append(verdictBox(lvl, lvl === "veto" ? "⛔止损" : "止损", String(r.brake_line).replace(/^⛔/, "")));
    }
    host.append(el("span", "foot", "⛔ 只表示审票不同意；登记永远可以，否决会随票入账。"));
  }

  function textInput(focusKey, value, label, placeholder, onInput) {
    const input = el("input", "input");
    input.type = "text";
    input.value = value || "";
    input.placeholder = placeholder;
    input.setAttribute("aria-label", label);
    input.dataset.focus = focusKey;
    input.addEventListener("input", (e) => onInput(e.target.value));
    return input;
  }

  function renderActions() {
    const host = document.getElementById("actions");
    host.className = "actions";
    host.replaceChildren();
    const card = el("div", "card");
    card.append(el("span", "card-title small-title", "理由 · 先于第一条腿开球"));
    const chips = el("div", "chips");
    for (const [code, label] of DEVIATIONS) {
      const on = state.reg.deviation === code;
      const chip = button("chip" + (on ? " on" : ""), label, () => {
        state.reg.deviation = on ? "" : code;
        renderActions();
      });
      chip.setAttribute("aria-pressed", String(on));
      chip.dataset.focus = `dev-${code}`;
      chips.append(chip);
    }
    const pred = el("label", "field");
    pred.append(el("span", "label", "一句可证伪的预测"),
      textInput("pred", state.reg.prediction, "一句可证伪的预测", "写一句赛后能判对错的话", (t) => { state.reg.prediction = t; }));
    const scheme = el("label", "field");
    scheme.append(el("span", "label", "500 方案号（选填）"),
      textInput("scheme", state.reg.scheme, "500 方案号（选填）", "方案号", (t) => { state.reg.scheme = t; }));
    card.append(chips, pred, scheme,
      el("span", "foot", "五选一；不选也能登记，账上记「偏离初稿未登记理由」。开球后才写的理由照记，不进理由净值。"));
    if (state.reg.error) card.append(banner(state.reg.error));
    const go = button("btn primary", state.reg.posting ? "登记中…" : "我已在 500 下单 · 登记", registerReal);
    go.dataset.focus = "register";
    go.disabled = state.reg.posting || !Object.keys(state.picks).length;
    card.append(go, el("span", "foot", "登记＝已经买了（没入账＝没打）——先在 500 付完款再按。可以接着登记下一张，每张一份回执。"));
    host.append(card);
    if (state.receipts.length) {
      const list = el("div", "receipts");
      const rh = el("div", "card-head");
      rh.append(el("span", "card-title small-title", "回执"), el("span", "card-sub", `${state.receipts.length} 张 · 新的在前`));
      list.append(rh);
      state.receipts.forEach((r, i) => list.append(receiptCard(r, i === 0)));
      host.append(list);
    }
  }

  function renderSide() {
    if (!state.data) return;
    keepFocus(root, () => {
      renderSlip();
      renderReview();
      renderActions();
    });
  }

  async function registerReal() {
    if (state.reg.posting) return;
    state.reg.posting = true;
    state.reg.error = "";
    renderSide();
    const payload = {
      picks: { ...state.picks }, multiplier: state.mult, scheme_no: state.reg.scheme.trim(),
      deviation: state.reg.deviation, prediction: state.reg.prediction.trim(),
    };
    const body = await postJSON(`/action/jczq/${encodeURIComponent(day)}/register`, payload, "登记接口");
    state.reg.posting = false;
    if (!body.ok) {
      state.reg.error = body.error || "登记失败";
    } else {
      state.receipts.unshift(body);
      state.reg.scheme = "";              // 方案号一张一个；理由与预测留着给下一张
    }
    renderSide();
  }

  // ⛔：纪律码一律；V 码看登记回来的审票行是不是 ⛔ 级（V1 也可能只是 ⚠️）——同期页
  function vetoCode(code, r) {
    if (HARD.includes(code)) return true;
    const lines = r.lines || [];
    if (lines.some((l) => String(l).startsWith(`⛔${code} `))) return true;
    if (lines.some((l) => new RegExp(`^\\S*${code} `).test(String(l)))) return false;
    return Boolean(r.vetoed) && /^V\d/.test(code);
  }

  function selectNode(node) {
    try {
      const range = document.createRange();
      range.selectNodeContents(node);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch {
      /* 选不中也只能让人自己拖选 */
    }
  }

  async function copySlip(r) {
    let ok = false;
    try {
      const clip = globalThis.navigator && globalThis.navigator.clipboard;
      if (clip && typeof clip.writeText === "function") {
        await clip.writeText(String(r.slip_text || ""));
        ok = true;
      }
    } catch {
      ok = false;
    }
    state.copied[r.slip_id] = ok ? "ok" : "fail";
    renderSide();
    if (!ok) {
      const node = document.getElementById("actions").querySelector(`[data-focus="slip-text-${r.slip_id}"]`);
      if (node) selectNode(node);
    }
  }

  function receiptCard(r, newest) {
    const box = el("article", "receipt" + (newest ? " newest" : ""));
    box.setAttribute("aria-label", `回执 ${r.slip_id}`);
    const h = el("div", "card-head");
    h.append(el("span", "card-title", `已登记 ${r.slip_id} · 实购`),
      el("span", "card-sub mono", r.stake != null ? `${r.notes} 注 × ${r.multiplier} 倍 · ${yuan(r.stake)}` : ""));
    box.append(h, el("p", "summary", r.summary || ""));
    const codes = r.codes || [];
    if (codes.length) {
      const chips = el("div", "codes");
      for (const c of codes) {
        const veto = vetoCode(c, r);
        chips.append(el("span", "code-chip mono" + (veto ? " veto" : ""), veto ? `⛔${c}` : c));
      }
      box.append(chips);
    }
    const notes = [];
    if (r.vetoed) notes.push(["veto", "审票不同意，已随票入账（登记不受限）"]);
    if (r.after_kickoff) notes.push(["warn", "理由写于开球后：照记，不进理由净值"]);
    for (const [cls, t] of notes) box.append(el("p", "note " + cls, t));

    box.append(el("small", "label", "500 投注单（照着逐条点）"));
    const sl = el("div", "slip-line");
    const pre = el("pre", "slip-text mono", r.slip_text || "");
    pre.dataset.focus = `slip-text-${r.slip_id}`;
    const done = state.copied[r.slip_id];
    const cp = button("btn copy", done === "ok" ? "已复制" : done === "fail" ? "手动选中" : "复制", () => copySlip(r));
    cp.setAttribute("aria-label", `复制 ${r.slip_id} 的 500 投注单`);
    cp.dataset.focus = `copy-${r.slip_id}`;
    sl.append(pre, cp);
    box.append(sl);
    if (done === "fail") {
      const n = el("span", "copy-fail", "剪贴板不可用：已选中投注单，手动复制（⌘C / 长按）");
      n.setAttribute("role", "status");
      box.append(n);
    }
    box.append(el("p", "note strong", "把 500 确认页截图发回 → 记实购（截图＝实购；SP 变了以确认页为准）"));
    if (r.brake_line) box.append(el("p", "note" + (String(r.brake_line).startsWith("⛔") ? " veto" : ""), r.brake_line));
    for (const line of r.lines || []) box.append(el("p", "foot", line));
    return box;
  }

  load();
})();
