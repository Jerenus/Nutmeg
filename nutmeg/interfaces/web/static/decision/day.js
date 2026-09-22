window.Day = (function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function hm(iso) { return iso ? String(iso).slice(11, 16) : "—"; }
  function body(id) { return document.querySelector("#" + id + " .day-body"); }

  function renderStatus(view) {
    var box = body("day-status"); box.innerHTML = "";
    (view.timeline || []).forEach(function (j) {
      var r = el("div", "day-row " + (j.exit === 0 ? "ok" : "alarm"));
      r.appendChild(el("span", null, "day " + j.job)); r.appendChild(el("span", null, hm(j.finished_at)));
      r.appendChild(el("span", null, "exit=" + j.exit)); r.appendChild(el("span", null, j.summary || ""));
      box.appendChild(r);
    });
    (view.launchd || []).forEach(function (a) {
      var r = el("div", "day-row " + (a.alarm ? "alarm" : "ok"));
      r.appendChild(el("span", null, a.label.replace("com.nutmeg.", "") + (a.loaded ? "" : "（未装载）")));
      r.appendChild(el("span", null, a.schedule)); r.appendChild(el("span", null, "exit=" + a.last_exit + " @" + (a.log_at ? hm(a.log_at) + " " + a.log_at.slice(5, 10) : "无时间证据")));
      r.appendChild(el("span", null, a.tail || "")); box.appendChild(r);
    });
    if (!box.children.length) box.appendChild(el("p", "obs-muted", "今日无作业记录"));
  }

  function renderDecisions(view) {
    var box = body("day-decisions"); box.innerHTML = "";
    var rows = (view.decisions || []).filter(function (d) { return d.status !== "done"; });
    if (!rows.length) box.appendChild(el("p", "obs-muted", "无待人决定"));
    rows.forEach(function (d) {
      var r = el("div", "day-decision " + d.status);
      r.appendChild(el("span", "due", d.deadline ? "截止 " + hm(d.deadline) : "无截止"));
      r.appendChild(el("span", null, "[" + d.kind + "] " + d.subject));
      r.appendChild(el("span", "obs-muted", "默认：" + d.default_action));
      box.appendChild(r);
    });
  }

  function card(m) {
    var c = el("article", "day-card");
    c.appendChild(el("h3", null, m.code + " " + (m.name || "") + " · " + hm(m.kickoff_bj)));
    var badges = el("div");
    [m.ladder, (m.labels || {}).judgment_tier, "研究 " + (m.research || {}).status,
     m.read ? (m.read.judge + "/" + m.read.status) : "无 Read"].forEach(function (t) { badges.appendChild(el("span", "day-badge", t)); });
    if (m.research && m.research.prospective === false) badges.appendChild(el("span", "day-badge alarm", "not_prospective"));
    c.appendChild(badges);
    var mk = m.market || {}, f = mk.fair || {};
    c.appendChild(el("p", null, "fair " + [f.home, f.draw, f.away].map(function (x) { return x == null ? "—" : Math.round(x * 100); }).join("/") +
      " · 位移 " + (mk.drift_pp == null ? "—" : mk.drift_pp + "pp") + " · 分歧 " + (mk.book_disagreement_pp == null ? "—" : mk.book_disagreement_pp + "pp") +
      " · 终盘 " + (mk.closing_books || "—") + " 书"));
    if (m.read) c.appendChild(el("p", null, "Read 拨动 " + m.read.moved_pp + "pp · conf " + (m.read.confidence == null ? "—" : m.read.confidence)));
    if (m.logic && m.logic.status === "ok") c.appendChild(el("p", "day-logic", m.logic.text));
    else if (m.logic) c.appendChild(el("p", "obs-muted", "逻辑层 " + m.logic.status + (m.logic.reason ? "：" + m.logic.reason : "")));
    if (m.audit && !m.audit.error) ["naked", "double", "full"].forEach(function (k) {
      var a = m.audit[k]; if (!a) return;
      badges.appendChild(el("span", "day-badge" + (a.blocking ? " alarm" : ""), k + " " + a.faces + (a.blocking ? " ✗" : " ✓")));
    });
    var d = el("details"); d.appendChild(el("summary", null, "标签 / 实力 / 研究摘要"));
    var pre = el("pre"); pre.textContent = JSON.stringify({ labels: m.labels, strength: m.strength, research: m.research }, null, 1);
    d.appendChild(pre); c.appendChild(d);
    return c;
  }

  function renderJczq(view) {
    var box = body("day-jczq"); box.innerHTML = "";
    var b = view.brief;
    if (!b) { box.appendChild(el("p", "obs-muted", "brief.json 缺席")); return; }
    (b.jczq.matches || []).forEach(function (m) { box.appendChild(card(m)); });
    if (!(b.jczq.matches || []).length) box.appendChild(el("p", "obs-muted", "今日无板面"));
  }

  function renderZucai(view) {
    var box = body("day-zucai"); box.innerHTML = "";
    var z = view.brief && view.brief.zucai;
    if (!z || !z.issue) { box.appendChild(el("p", "obs-muted", "无在售期")); return; }
    box.appendChild(el("p", null, "期 " + z.issue + " · 截止 " + (z.sale_deadline || "未知") + " · 备料槽 " + Object.keys(z.prep || {}).join(",")));
    if (z.tiers) box.appendChild(el("p", null, "风向 " + JSON.stringify(z.tiers.wind) + " · tiers " + z.tiers.tiers_hash));
    Object.keys(z.frontier || {}).forEach(function (ch) {
      var f = z.frontier[ch];
      box.appendChild(el("p", null, ch + " 前沿 " + f.points.length + " 点 · strict 地板 P=" + f.strict_max_p));
      f.points.forEach(function (p) { box.appendChild(el("div", "day-row ok", "k" + p.k + " P=" + p.p_all + " 注数 " + p.notes + " ¥" + p.stake_yuan + " 收窄 " + p.narrowings)); });
    });
    box.appendChild(el("p", "obs-muted", z.plan ? "已定案" : "未定案（plan choose → commit 是人的门）"));
  }

  function renderRsi(view) {
    var box = body("day-rsi"); box.innerHTML = "";
    var r = view.brief && view.brief.rsi;
    if (!r) { box.appendChild(el("p", "obs-muted", "今日闭环报告缺席")); return; }
    (r.human_actions || []).forEach(function (a) { box.appendChild(el("div", "day-row ok", a)); });
    (r.failed_steps || []).forEach(function (s) { box.appendChild(el("div", "day-row alarm", "闭环步骤失败 " + s)); });
    if (!box.children.length) box.appendChild(el("p", "obs-muted", "无待人决定；判决未到期"));
  }

  function renderSession(view) {
    var box = body("day-session"); box.innerHTML = "";
    var cmd = "uv run nutmeg day status --date " + view.date + " && sed -n 1,60p .nutmeg-data/daily/" + view.date + "/session.md";
    var pre = el("pre", "day-pre", cmd); box.appendChild(pre);
    var btn = el("button", null, "复制"); btn.onclick = function () { navigator.clipboard && navigator.clipboard.writeText(cmd); };
    box.appendChild(btn);
    box.appendChild(el("p", "obs-muted", "Claude Code 里输入 /today 即读同一份 session.md（P4）。"));
  }

  function renderTalk(view) {
    var box = body("day-talk"); box.innerHTML = "";
    (view.discussion || []).forEach(function (d) { box.appendChild(el("div", "day-row ok", hm(d.at) + " " + d.who + (d.obj ? " [" + d.obj + "]" : "") + "：" + d.text)); });
  }

  function renderRetro(view) { document.querySelector("#day-retro .day-body").textContent = view.retro || "昨日复盘草稿缺席（day settle 未跑）"; }

  function render(view) {
    renderStatus(view); renderDecisions(view); renderRetro(view); renderJczq(view);
    renderZucai(view); renderRsi(view); renderSession(view); renderTalk(view);
    var err = document.querySelector("#day-errors");
    if (view.errors && view.errors.length) { err.hidden = false; err.textContent = "部分数据缺席：" + view.errors.join("；"); }
  }

  function load(date) {
    return fetch("/api/day/" + date).then(function (r) { return r.json(); }).then(render);
  }

  function mount(selector) {
    var root = document.querySelector(selector), date = root.dataset.date;
    load(date);
    var send = function () {
      var text = document.querySelector("#day-talk-text").value.trim(); if (!text) return;
      fetch("/action/day-note", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: date, obj: document.querySelector("#day-talk-obj").value.trim(), text: text }) })
        .then(function () { document.querySelector("#day-talk-text").value = ""; load(date); });
    };
    document.querySelector("#day-talk-send").onclick = send;
    document.querySelector("#day-talk-text").addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
    setInterval(function () { load(date); }, 60000);
  }

  return { mount: mount, render: render };
})();
