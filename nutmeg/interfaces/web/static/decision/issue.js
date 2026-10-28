// static/decision/issue.js —— 期页：决策表即票（2026-10-27 产品形态第 1 阶段）。
// 推导一律在服务端：注数 / P / V 码 / 止损 / 刹车 / 死法清单来自 /api/precheck，
// 档 / 条件 k/n / 翻车面 / 默认 / 死门 / 首发来自分析包旁车（/api/issue）。这里只渲染。
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
  const state = { data: null, picks: {}, open: null, review: null, seq: 0, pending: false };

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

  // ---- 载入 ----------------------------------------------------------
  async function load() {
    try {
      const r = await fetch(`/api/issue/${encodeURIComponent(issue)}`);
      if (!r.ok) throw new Error(`/api/issue ${r.status}`);
      state.data = await r.json();
    } catch (exc) {
      showErrors([`期页数据读不出：${exc.message || exc}`]);
      return;
    }
    renderBrake();
    showErrors(state.data.errors || []);
    renderActions();
    render();
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
  function toggle(no, k) {
    const cur = new Set(state.picks[no] || "");
    if (cur.has(k)) cur.delete(k); else cur.add(k);
    const faces = FACES.filter((f) => cur.has(f)).join("");
    if (faces) state.picks[no] = faces; else delete state.picks[no];
    render();
    review();
  }

  function setPicks(faces) {
    state.picks = {};
    for (const [no, f] of Object.entries(faces || {})) if (f) state.picks[String(no)] = String(f);
    render();
    review();
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
      let body;
      try {
        const r = await fetch("/api/precheck", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ channel: "renjiu", issue, faces: state.picks }),
        });
        body = r.ok ? await r.json() : { ok: false, error: `审票接口 ${r.status}` };
      } catch (exc) {
        body = { ok: false, error: `审票接口不可达：${exc.message || exc}` };
      }
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
    if (gates.length) {
      const sec = el("div", "gates-wrap");
      sec.append(el("h3", null, "死法清单 · 先要过的门"));
      const ol = el("ol", "gates");
      gates.forEach((g, i) => {
        const li = el("li", "gate" + (g.p >= 0.3 ? " hot" : "") + (g.coin ? " coin" : ""));
        li.append(el("span", "label", `第 ${i + 1} 道门`),
          el("span", "what", `${g.no} 开 ${g.face}` + (g.coin ? " ·D档" : "")),
          el("span", "p mono", `${pct(g.p)}%`));
        ol.append(li);
      });
      sec.append(ol, el("span", "foot", "红框＝≥30% 的排除面；·D档＝硬币场"));
      rev.append(sec);
    }
    rev.append(el("span", "foot", "⛔ 只表示审票不同意；登记永远可以，否决会随票入账。"));
  }

  // ---- 按钮 ------------------------------------------------------------
  function renderActions() {
    const host = document.getElementById("actions");
    host.replaceChildren();
    host.className = "actions";
    const main = state.data.main_shape;
    const copy = button("btn primary", main ? `照抄主形 ${main.label || ""}`.trim() : "照抄主形（旁车无主形）",
      () => main && setPicks(main.faces));
    copy.disabled = !main || !main.faces;
    if (main) copy.setAttribute("aria-label", `照抄分析包 §2 主形 ${main.label || ""}`);
    const clear = button("btn", "清空", () => setPicks({}));
    clear.setAttribute("aria-label", "清空所有已选的格");
    host.append(copy, clear);
  }

  load();
})();
