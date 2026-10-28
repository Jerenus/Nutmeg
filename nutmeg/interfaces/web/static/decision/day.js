// static/decision/day.js —— 今天页（2026-10-28 产品形态第 6 阶段 Task 6.2，画布 Today.dc.html）。
// 数全来自 /api/day/{日}：刹车 = shell.brake（precheck.month_brake + bankroll.status_line）、
// 刹车档 = shell.issue_brake、待你决定 = decisions（服务端现算，含 href / pass_target）、
// 期一眼 = glance（旁车）。页面只排版与排序，不推导判断。
// 空仓登记 → POST /action/pass {channel, target, reason}；400 原样显示服务端的 error。
// 研究 / 讨论文本是不可信输入：全部 textContent / createElement，不用 innerHTML。
window.Day = (function () {
  "use strict";

  var state = { date: null, view: null, passOpen: null, passReason: "", passError: "", busy: false };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]);
    return parent;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function body(id) { return document.querySelector("#" + id + " .day-body"); }
  function link(href, cls, text) { var a = el("a", cls, text); a.href = href; return a; }
  function button(cls, text, onclick) {
    var b = el("button", cls, text); b.type = "button"; b.onclick = onclick; return b;
  }

  // ---- 时间：服务端字符串都是北京时间（带或不带 +08:00、T 或空格），显示直接切字符串 ----
  var BJ_MS = 8 * 3600 * 1000;
  function parseBj(s) {
    var m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(:\d{2})?(.*)$/.exec(String(s || ""));
    if (!m) return null;
    var tz = m[4] && /[+-]\d{2}:?\d{2}|Z/.test(m[4]) ? m[4] : "+08:00";
    var t = Date.parse(m[1] + "T" + m[2] + (m[3] || ":00") + tz);
    return isNaN(t) ? null : t;
  }
  function bjIso(ms) { return new Date(ms + BJ_MS).toISOString(); }  // 「YYYY-MM-DDTHH:MM」北京时间
  function hm(s) { var t = parseBj(s); return t === null ? "—" : bjIso(t).slice(11, 16); }
  function when(ms, date) {  // 同日只写 HH:MM，跨日带 MM-DD
    var iso = bjIso(ms);
    return iso.slice(0, 10) === date ? iso.slice(11, 16) : iso.slice(5, 10) + " " + iso.slice(11, 16);
  }
  function countdown(ms) {
    var left = ms - Date.now();
    if (left <= 0) return "已过";
    var min = Math.floor(left / 60000);
    return "还有 " + Math.floor(min / 60) + ":" + String(min % 60).padStart(2, "0");
  }

  // ---- 数字排版：只做符号与千分位，数本身来自服务端 ----
  function grp(x) { return Math.round(Math.abs(x)).toLocaleString("en-US"); }
  function signed(x) { return (x < 0 ? "−" : x > 0 ? "+" : "") + grp(x); }
  function pct(p) { return p === null || p === undefined ? "—" : (p * 100).toFixed(2) + "%"; }

  function glanceFor(view, issue) {
    return (view.glance || []).filter(function (g) { return g.issue === issue; })[0] || null;
  }
  function passReasonFor(view, target) {
    var g = target && target.channel === "zucai" ? glanceFor(view, target.target) : null;
    return (g && g.default && g.default.reason) || "";
  }
  function sameTarget(a, b) { return !!a && !!b && a.channel === b.channel && a.target === b.target; }

  // ---- 空仓登记：理由输入 → 确认 → /action/pass → 重读 ----
  function openPass(target, where) {
    state.passOpen = { channel: target.channel, target: target.target, where: where };
    state.passReason = passReasonFor(state.view, target);
    state.passError = "";
    render(state.view);
    var input = document.getElementById("day-pass-reason");
    if (input) input.focus();
  }
  function closePass() { state.passOpen = null; state.passError = ""; render(state.view); }
  function submitPass() {
    var p = state.passOpen;
    if (!p || state.busy) return;
    state.busy = true;
    fetch("/action/pass", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: p.channel, target: p.target, reason: state.passReason.trim() }),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || !j.ok) throw new Error(j.error || ("登记失败（HTTP " + r.status + "）"));
        return j;
      });
    }).then(function () {
      state.busy = false; state.passOpen = null; state.passError = "";
      return load(state.date);
    }).catch(function (e) {
      state.busy = false; state.passError = e.message; render(state.view);
    });
  }
  function passForm(where) {
    var p = state.passOpen;
    if (!p || p.where !== where) return null;
    var box = el("div", "pass-form");
    var label = el("label", "label", (p.channel === "zucai" ? "期 " : "竞彩 ") + p.target + " 空仓理由");
    label.htmlFor = "day-pass-reason";
    var input = el("input", "input"); input.id = "day-pass-reason"; input.value = state.passReason;
    input.placeholder = "留空记「同意机器默认空仓」";
    input.oninput = function () { state.passReason = input.value; };
    input.onkeydown = function (e) { if (e.key === "Enter") submitPass(); if (e.key === "Escape") closePass(); };
    var row = add(el("div", "pass-actions"),
      button("btn primary", state.busy ? "登记中…" : "确认登记空仓", submitPass),
      button("btn", "取消", closePass));
    add(box, label, input, row);
    if (state.passError) add(box, el("p", "pass-error", state.passError));
    add(box, el("p", "foot", "写当日 passes.jsonl，不进 betslips；同日同目标只记第一次。"));
    return box;
  }

  // ---- 刹车带 ----
  function bigNum(title, value, cls) {
    return add(el("div", "brake-num" + (cls ? " " + cls : "")), el("span", "brake-label", title),
      el("span", "brake-big mono", value));
  }
  function activeIssue(view) {
    var issues = (view.shell && view.shell.issues) || [];
    return issues.length ? issues[0].issue : null;
  }
  function renderBrake(view) {
    var box = clear(document.getElementById("day-brake"));
    var shell = view.shell || {}, b = shell.brake;
    box.className = "brake" + (b && b.tripped ? " veto" : "");
    if (!b) {
      add(box, el("p", "brake-line", "月度刹车读不出：" + ((shell.errors || []).join("；") || "shell.brake 缺席")));
    } else {
      var nums = el("div", "brake-nums");
      add(nums, bigNum(b.tripped ? "刹车 · 本月已越止损线 · 实质" : "本月实质", signed(b.effective_net), "lead"),
        bigNum("止损线", "−" + grp(b.stop_loss)),
        b.room < 0 ? bigNum("越线", grp(b.room)) : bigNum("余", "¥" + grp(b.room)));
      var issue = activeIssue(view), ib = issue ? (shell.issue_brake || {})[issue] : undefined;
      if (issue) {
        nums.appendChild(ib
          ? add(el("div", "brake-num"), el("span", "brake-label", "刹车档 · " + issue),
            el("span", "brake-big mono", "单张 ≤¥" + grp(ib.slip_yuan) + " · 本期 ≤¥" + grp(ib.issue_yuan)),
            el("span", "brake-why", ib.reason || ""))
          : bigNum("刹车档 · " + issue, "无"));
      }
      add(box, nums, el("p", "brake-line", b.line));
    }
    var acts = el("div", "brake-actions");
    var targets = (view.decisions || []).filter(function (d) {
      return d.pass_target && d.pass_target.channel === "zucai";
    });
    targets.forEach(function (d) {
      var t = d.pass_target, open = sameTarget(state.passOpen, t) && state.passOpen.where === "brake";
      acts.appendChild(button("btn veto-fill", targets.length > 1 ? "登记 " + t.target + " 空仓" : "登记本期空仓",
        function () { if (open) closePass(); else openPass(t, "brake"); }));
    });
    acts.appendChild(link("/ledger", "btn veto-line", "看账房"));
    add(box, acts, passForm("brake"));
  }

  // ---- 今日时间轴：已跑作业 / 各截止 / 首场开球 / 现在，只排序 ----
  function renderTimeline(view) {
    var box = clear(body("day-status")), date = view.date, items = [];
    (view.timeline || []).forEach(function (j) {
      var t = parseBj(j.finished_at || j.started_at || j.planned_at);
      if (t === null) return;
      var bad = j.exit !== 0;
      items.push({ t: t, label: "day " + j.job + (bad ? " · exit=" + j.exit : ""), sub: j.summary || "",
        cls: bad ? "alarm" : "job" });
    });
    (view.decisions || []).forEach(function (d) {
      var t = parseBj(d.deadline);
      if (t === null) return;
      var label = d.kind === "register_zucai" ? "期 " + String(d.id || "").split(":").pop() + " 停售"
        : d.kind === "register_jczq" ? "竞彩登记截止" : "截止 · " + d.subject;
      items.push({ t: t, label: label, sub: d.status === "done" ? d.subject : "", cls: "deadline" });
    });
    var first = null;
    (((view.brief || {}).jczq || {}).matches || []).forEach(function (m) {
      var t = parseBj(m.kickoff_bj);
      if (t !== null && (first === null || t < first.t)) first = { t: t, m: m };
    });
    if (first) items.push({ t: first.t, label: "竞彩首场开球", sub: first.m.code + " " + (first.m.name || ""), cls: "kickoff" });
    var now = Date.now();
    if (bjIso(now).slice(0, 10) === date) items.push({ t: now, label: "现在", cls: "now" });
    items.sort(function (a, b) { return a.t - b.t; });
    if (!items.length) { box.appendChild(el("p", "muted", "今日无作业记录、无截止")); return; }
    var list = el("ol", "rail");
    items.forEach(function (it) {
      var past = it.cls !== "now" && it.t < now;
      var li = el("li", "ev " + it.cls + (past ? " past" : ""));
      add(li, el("span", "ev-t mono", when(it.t, date)), el("span", "ev-dot"),
        add(el("span", "ev-text"), el("span", "ev-label", it.label), it.sub ? el("span", "ev-sub", it.sub) : null));
      list.appendChild(li);
    });
    box.appendChild(list);
  }

  // ---- 待你决定 ----
  var ORDER = { open: 0, expired: 1, done: 2 };
  var OPEN_LABEL = { register_zucai: "打开决策表", register_jczq: "打开竞彩板" };
  function renderDecisions(view) {
    var box = clear(body("day-decisions"));
    var rows = (view.decisions || []).slice().sort(function (a, b) {
      var s = (ORDER[a.status] || 0) - (ORDER[b.status] || 0);
      if (s) return s;
      var ta = parseBj(a.deadline), tb = parseBj(b.deadline);
      return (ta === null ? Infinity : ta) - (tb === null ? Infinity : tb);
    });
    var open = rows.filter(function (d) { return d.status === "open"; }).length;
    document.getElementById("day-decisions-n").textContent = open + " 件待定 · 共 " + rows.length + " · 按截止排序";
    if (!rows.length) { box.appendChild(el("p", "muted", "无待人决定")); return; }
    rows.forEach(function (d) {
      var key = "card:" + d.id;
      var c = el("article", "decision " + d.status + (d.pass_target ? " register" : ""));
      var t = parseBj(d.deadline);
      var due = el("span", "due");
      if (t === null) due.textContent = "无截止";
      else add(due, el("span", null, (d.kind === "register_zucai" ? "停售 " : "截止 ") ),
        el("b", "mono", hm(d.deadline)), el("span", null, " · "),
        el("b", "mono", d.status === "done" ? "已登记" : countdown(t)));
      add(c, add(el("div", "decision-head"), el("span", "subject", d.subject), due));
      if (d.status !== "done") {
        add(c, add(el("p", "default"), el("span", "muted", "机器默认 "), el("b", null, d.default_action || "—")));
      }
      if (d.status === "expired") add(c, el("p", "muted small", "已过截止"));
      var acts = el("div", "decision-actions");
      if (d.href) acts.appendChild(link(d.href, d.status === "open" ? "btn primary" : "btn", OPEN_LABEL[d.kind] || "打开"));
      if (d.pass_target) {
        var isOpen = sameTarget(state.passOpen, d.pass_target) && state.passOpen.where === key;
        acts.appendChild(button("btn", "同意空仓并登记", function () {
          if (isOpen) closePass(); else openPass(d.pass_target, key);
        }));
      }
      if (acts.children.length) c.appendChild(acts);
      add(c, passForm(key));
      box.appendChild(c);
    });
  }

  // ---- 期一眼（旁车） ----
  var TIERS = ["A", "B", "b", "C", "D"];
  function segBar(k, n) {
    var bar = el("span", "segs");
    if (typeof n !== "number" || n <= 0) { bar.classList.add("none"); return bar; }
    bar.style.gridTemplateColumns = "repeat(" + n + ", minmax(0, 1fr))";
    for (var i = 0; i < n; i++) {
      bar.appendChild(el("span", "seg" + (i < (k || 0) ? " on" : "") + (n === 6 && i === 4 ? " seg-gate" : "")));
    }
    return bar;
  }
  function shapeRow(s, tag) {
    var row = el("div", "shape");
    add(row, add(el("div", "shape-main"),
      add(el("span", "shape-name"), tag ? el("span", "role", tag) : null, el("span", null, s.label || "—")),
      el("span", "shape-price mono", s.price === null || s.price === undefined ? "—" : "¥" + grp(s.price)),
      el("span", "shape-p mono", pct(s.p))));
    if (s.note) row.appendChild(el("p", "shape-note", s.note));
    return row;
  }
  function glanceCard(g) {
    var c = el("article", "glance");
    add(c, add(el("div", "block-head"), el("h2", null, g.issue + " 一眼"),
      el("span", "muted small", g.deadline ? "停售 " + hm(g.deadline) : "停售时刻不明")));
    if ((g.errors || []).length) c.appendChild(el("p", "errors", "旁车有问题：" + g.errors.join("；")));
    var chips = el("div", "tiers mono");
    TIERS.forEach(function (t) {
      var n = (g.tiers || {})[t] || 0;
      var cls = t === "C" ? "tier c" : t === "D" ? "tier d" : "tier lic" + (n ? " on" : "");
      chips.appendChild(el("span", cls, t + " " + n));
    });
    c.appendChild(chips);
    var lic = el("div", "lic");
    add(lic, add(el("div", "lic-head"), el("span", null, "A/B/b 六条件 k/n（≥5/6 才许可做胆）"), el("span", null, "只展示")));
    if (!(g.license_rows || []).length) lic.appendChild(el("p", "muted small", "无 A/B/b 行"));
    (g.license_rows || []).forEach(function (r) {
      add(lic, add(el("div", "lic-row"), el("span", "lic-name", r.no + " " + (r.name || "")), segBar(r.k, r.n),
        el("span", "lic-k mono", (r.k === null || r.k === undefined ? "—" : r.k) + "/" + (r.n === null || r.n === undefined ? "—" : r.n))));
    });
    c.appendChild(lic);
    var shapes = add(el("div", "shapes"), el("div", "shapes-head muted small", "主形与并排参考形（P＝全对概率）"));
    if (g.main_shape) shapes.appendChild(shapeRow(g.main_shape, "主形"));
    (g.alternatives || []).forEach(function (a) { shapes.appendChild(shapeRow(a, a.role || "替代")); });
    if (!g.main_shape && !(g.alternatives || []).length) shapes.appendChild(el("p", "muted small", "旁车没有票形"));
    c.appendChild(shapes);
    var d = g.default;
    var def = el("div", "default-box");
    if (d) add(def, add(el("p", "default"), el("span", "muted", "机器默认 "), el("b", null, d.action || "—")),
      d.reason ? el("p", "default-why", d.reason) : null);
    else def.appendChild(el("p", "muted", "旁车没有默认动作"));
    add(c, def, link("/issue/" + encodeURIComponent(g.issue), "more", "打开期页 " + g.issue + " →"));
    return c;
  }
  function renderGlance(view) {
    var box = clear(body("day-zucai"));
    var gs = view.glance || [];
    gs.forEach(function (g) { box.appendChild(glanceCard(g)); });
    if (!gs.length) {
      var z = view.brief && view.brief.zucai;
      add(box, el("h2", null, "期一眼"), el("p", "muted", z && z.issue
        ? "期 " + z.issue + " 不在售（截止 " + (z.sale_deadline || "未知") + "）" : "无在售期"));
    }
  }

  // ---- 竞彩一行 / 运维一行 ----
  function renderLines(view) {
    var j = clear(document.getElementById("day-jczq-line"));
    var b = view.brief, ms = (b && b.jczq && b.jczq.matches) || [];
    add(j, add(el("div", "line-head"), el("b", null, "竞彩"), el("span", "muted small", "机器不出票")),
      el("p", null, b ? "今日板面 " + ms.length + " 场" : "brief.json 缺席，场数未知"),
      link("/jczq/" + encodeURIComponent(view.date), "more", "竞彩当日板 →"));
    var o = clear(document.getElementById("day-ops-line"));
    var alarms = (view.launchd || []).filter(function (a) { return a.alarm; });
    var bad = (view.timeline || []).filter(function (t) { return t.exit !== 0; });
    var n = alarms.length + bad.length;
    o.className = "line-card ops" + (n ? " alarm" : "");
    var names = alarms.map(function (a) { return String(a.label || "").replace("com.nutmeg.", ""); })
      .concat(bad.map(function (t) { return "day " + t.job; }));
    add(o, add(el("div", "line-head"), add(el("span", "ops-title"), el("span", "dot"), el("b", null, "运维")),
      el("span", "mono", n ? n + " 处告警" : "无告警")),
      n ? el("p", "small", names.join("、")) : null,
      link("/runs/" + encodeURIComponent(view.date), "more", "作业进度 →"));
  }

  // ---- 折叠区：竞彩卡 / 昨日 / RSI / 会话入口 / 讨论（原样保留） ----
  function setCount(id, text) { var n = document.querySelector("#" + id + " summary .n"); if (n) n.textContent = text; }
  function card(m) {
    var c = el("article", "day-card");
    c.appendChild(el("h3", null, m.code + " " + (m.name || "") + " · " + hm(m.kickoff_bj)));
    var badges = el("div", "badges");
    [m.ladder, (m.labels || {}).judgment_tier, "研究 " + (m.research || {}).status,
     m.read ? (m.read.judge + "/" + m.read.status) : "无 Read"].forEach(function (t) {
      if (t !== undefined && t !== null) badges.appendChild(el("span", "day-badge", t));
    });
    if (m.research && m.research.prospective === false) badges.appendChild(el("span", "day-badge alarm", "not_prospective"));
    if (m.stance) badges.appendChild(el("span", "day-badge", "押 " + m.stance.face + " · " + m.stance.structure + "(" + m.stance.faces + ")"));
    c.appendChild(badges);
    var mk = m.market || {}, f = mk.fair || {};
    c.appendChild(el("p", "mono small", "fair " + [f.home, f.draw, f.away].map(function (x) { return x == null ? "—" : Math.round(x * 100); }).join("/") +
      " · 位移 " + (mk.drift_pp == null ? "—" : mk.drift_pp + "pp") + " · 分歧 " + (mk.book_disagreement_pp == null ? "—" : mk.book_disagreement_pp + "pp") +
      " · 终盘 " + (mk.closing_books || "—") + " 书"));
    if (m.read) c.appendChild(el("p", "small", "Read 拨动 " + m.read.moved_pp + "pp · conf " + (m.read.confidence == null ? "—" : m.read.confidence)));
    if (m.stance && m.stance.tilt_reason) c.appendChild(el("p", "muted small", "拨动：" + m.stance.tilt_reason));
    if (m.logic && m.logic.status === "ok") c.appendChild(el("p", "day-logic", m.logic.text));
    else if (m.logic) c.appendChild(el("p", "muted small", "逻辑层 " + m.logic.status + (m.logic.reason ? "：" + m.logic.reason : "")));
    var d = el("details"); d.appendChild(el("summary", null, "标签 / 实力 / 研究摘要"));
    d.appendChild(el("pre", null, JSON.stringify({ labels: m.labels, strength: m.strength, research: m.research }, null, 1)));
    c.appendChild(d);
    return c;
  }
  function renderJczq(view) {
    var box = clear(body("day-jczq")), b = view.brief;
    if (!b) { box.appendChild(el("p", "muted", "brief.json 缺席")); setCount("day-jczq", "· 缺席"); return; }
    var ms = (b.jczq && b.jczq.matches) || [];
    ms.forEach(function (m) { box.appendChild(card(m)); });
    if (!ms.length) box.appendChild(el("p", "muted", "今日无板面"));
    setCount("day-jczq", "· " + ms.length + " 场");
  }
  function renderRetro(view) {
    body("day-retro").textContent = view.retro || "昨日复盘草稿缺席（day settle 未跑）";
    setCount("day-retro", view.retro ? "" : "· 缺席");
  }
  function renderRsi(view) {
    var box = clear(body("day-rsi")), r = view.brief && view.brief.rsi;
    if (!r) { box.appendChild(el("p", "muted", "今日闭环报告缺席")); setCount("day-rsi", "· 缺席"); return; }
    (r.human_actions || []).forEach(function (a) { box.appendChild(el("div", "day-row ok", a)); });
    (r.failed_steps || []).forEach(function (s) { box.appendChild(el("div", "day-row alarm", "闭环步骤失败 " + s)); });
    var n = box.children.length;
    if (!n) box.appendChild(el("p", "muted", "无待人决定；判决未到期"));
    setCount("day-rsi", n ? "· " + n + " 条" : "");
  }
  function renderSession(view) {
    var box = clear(body("day-session"));
    var cmd = "sed -n 1,60p .nutmeg-data/daily/" + view.date + "/session.md";
    box.appendChild(el("pre", "day-pre", cmd));
    box.appendChild(button("btn", "复制", function () { if (navigator.clipboard) navigator.clipboard.writeText(cmd); }));
    box.appendChild(el("p", "muted small", "Claude Code 里输入 /today 即读同一份 session.md（P4）。"));
  }
  function renderTalk(view) {
    var box = clear(body("day-talk")), rows = view.discussion || [];
    rows.forEach(function (d) {
      box.appendChild(el("div", "day-row ok", hm(d.at) + " " + d.who + (d.obj ? " [" + d.obj + "]" : "") + "：" + d.text));
    });
    setCount("day-talk", rows.length ? "· " + rows.length + " 条" : "");
  }

  function renderErrors(view) {
    var err = document.getElementById("day-errors");
    var list = (view.errors || []).concat((view.shell && view.shell.errors) || []);
    err.hidden = !list.length;
    err.textContent = list.length ? "部分数据缺席：" + list.join("；") : "";
  }

  function render(view) {
    if (!view) return;
    state.view = view;
    if (!state.date) state.date = view.date;
    renderBrake(view); renderErrors(view); renderTimeline(view); renderDecisions(view);
    renderGlance(view); renderLines(view);
    renderJczq(view); renderRetro(view); renderRsi(view); renderSession(view); renderTalk(view);
  }

  function load(date) {
    return fetch("/api/day/" + encodeURIComponent(date)).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(render).catch(function (e) {
      var err = document.getElementById("day-errors");
      err.hidden = false; err.textContent = "读取 /api/day/" + date + " 失败：" + e.message;
    });
  }

  function mount(selector) {
    var root = document.querySelector(selector);
    state.date = root.dataset.date;
    load(state.date);
    var send = function () {
      var text = document.querySelector("#day-talk-text").value.trim(); if (!text) return;
      fetch("/action/day-note", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: state.date, obj: document.querySelector("#day-talk-obj").value.trim(), text: text }) })
        .then(function () { document.querySelector("#day-talk-text").value = ""; load(state.date); });
    };
    document.querySelector("#day-talk-send").onclick = send;
    document.querySelector("#day-talk-text").addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
    // 理由框开着时不刷新，免得把正在打的字冲掉
    setInterval(function () { if (!state.passOpen) load(state.date); }, 60000);
  }

  return { mount: mount, render: render };
})();
