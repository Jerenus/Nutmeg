// static/decision/inbox.js —— 待签收件箱（2026-10-30 产品形态第 10 阶段 Task 10.3，画布手机板「待签」）。
// 数全来自 /api/inbox：rows（待签在前；已答按答复时刻新的在前）、summary（待签数）、labels（答复 / 状态的中文）、
// overdue（问过 ≥3 次或积压 ≥7 天，服务端判）。页面只做一件事：答复。四个按钮先选、再确认——
// 「改」必须写改成什么，其余原话可选；POST /action/inbox/{id}/answer，回包后重新拉账，卡片移到「已答」。
// 文本一律 textContent / createElement，不用 innerHTML。
(function () {
  "use strict";

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

  var root = document.getElementById("inbox");
  if (!root) return;
  var errBox = document.getElementById("errors");
  // pick: 卡片 id → 选中的答复（展开确认区）；draft: 卡片 id → 正在写的原话（重画不丢）
  var state = { data: null, pick: {}, draft: {}, busy: {}, rowErr: {}, answeredOpen: false };
  var body = el("div", "ib-body");
  add(root, body);

  function showErrors(list) {
    clear(errBox);
    list.forEach(function (e) { add(errBox, el("span", null, e)); });
    errBox.hidden = list.length === 0;
  }
  function label(map, key) { return (state.data.labels[map] || {})[key] || key || "—"; }
  function md(at) { return String(at || "").slice(5, 10); }
  function mdhm(at) { return String(at || "").slice(5, 16).replace("T", " "); }

  function syncBadge(n) {
    // 导航角标是服务端渲染的；答复之后用同一份 summary.pending 跟上，不用刷新整页
    var badge = document.querySelector('.nm-badge[data-badge="inbox"]');
    if (badge) { if (n) badge.textContent = String(n); else badge.remove(); return; }
    var nav = document.querySelector('.nm-nav a[href="/inbox"]');
    if (nav && n) {
      var b = el("span", "nm-badge", String(n));
      b.dataset.badge = "inbox";
      add(nav, document.createTextNode(" "), b);
    }
  }

  function submit(r) {
    var verdict = state.pick[r.id];
    var words = (state.draft[r.id] || "").trim();
    if (verdict === "modify" && !words) {
      state.rowErr[r.id] = "「改」要写改成什么";
      render();
      var ta = body.querySelector('[data-focus="words-' + r.id + '"]');
      if (ta) ta.focus();
      return;
    }
    state.busy[r.id] = true;
    delete state.rowErr[r.id];
    render();
    fetch("/action/inbox/" + encodeURIComponent(r.id) + "/answer", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ verdict: verdict, words: words }),
    }).then(function (resp) {
      return resp.json().catch(function () { return { ok: false, error: "HTTP " + resp.status }; });
    }).then(function (out) {
      delete state.busy[r.id];
      if (!out.ok) { state.rowErr[r.id] = out.error || "答不了"; render(); return; }
      delete state.pick[r.id];
      delete state.draft[r.id];
      load();
    }).catch(function (e) {
      delete state.busy[r.id];
      state.rowErr[r.id] = "接口不可达：" + String(e && e.message || e);
      render();
    });
  }

  function confirmBox(r) {
    var verdict = state.pick[r.id];
    var box = el("div", "ib-confirm");
    var need = verdict === "modify";
    var fid = "ib-words-" + r.id;
    var lab = el("label", "ib-words-label", need ? "改成什么（必填）" : "你的原话（可选）");
    lab.htmlFor = fid;
    var ta = el("textarea", "ib-words");
    ta.id = fid;
    ta.rows = need ? 3 : 2;
    ta.value = state.draft[r.id] || "";
    ta.placeholder = need ? "比如：改成只登记、不拨动" : "比如：可以";
    if (need) ta.required = true;
    ta.dataset.focus = "words-" + r.id;
    ta.addEventListener("input", function () { state.draft[r.id] = ta.value; });
    var go = el("button", "ib-btn ib-btn-go ib-v-" + verdict, "确认「" + label("verdicts", verdict) + "」");
    go.type = "button";
    go.disabled = !!state.busy[r.id];
    go.dataset.focus = "go-" + r.id;
    go.addEventListener("click", function () { submit(r); });
    var back = el("button", "ib-btn", "取消");
    back.type = "button";
    back.dataset.focus = "back-" + r.id;
    back.addEventListener("click", function () { delete state.pick[r.id]; delete state.rowErr[r.id]; render(); });
    add(box, lab, ta, add(el("div", "ib-confirm-row"), go, back));
    return box;
  }

  function buttons(r) {
    var row = el("div", "ib-actions");
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "答复");
    Object.keys(state.data.labels.verdicts).forEach(function (v) {
      var on = state.pick[r.id] === v;
      var b = el("button", "ib-btn ib-v-" + v + (on ? " on" : ""), label("verdicts", v));
      b.type = "button";
      b.setAttribute("aria-pressed", String(on));
      b.disabled = !!state.busy[r.id];
      b.dataset.focus = "pick-" + r.id + "-" + v;
      b.addEventListener("click", function () {
        state.pick[r.id] = on ? undefined : v;
        if (!state.pick[r.id]) delete state.pick[r.id];
        delete state.rowErr[r.id];
        render();
        var ta = body.querySelector('[data-focus="words-' + r.id + '"]');
        if (ta) ta.focus();
      });
      add(row, b);
    });
    return row;
  }

  function meta(r) {
    var bits = ["自 " + md(r.at), "问过 " + r.asked_count + " 次", "积压 " + r.age_days + " 天"];
    return el("p", "ib-age mono" + (r.overdue ? " ib-overdue" : ""), bits.join(" · "));
  }
  function src(r) {
    return el("p", "ib-src mono", [r.id, r.source, r.ref].filter(Boolean).join(" · "));
  }

  function pendingCard(r) {
    var card = el("article", "ib-card" + (r.overdue ? " ib-card-overdue" : ""));
    add(card, el("h3", "ib-title", r.title));
    if (r.body) add(card, el("p", "ib-text", r.body));
    if (r.blocks) add(card, add(el("p", "ib-blocks"), el("b", null, "拦住了什么 "), document.createTextNode(r.blocks)));
    if (r.deadline) add(card, add(el("p", "ib-deadline"), el("b", null, "截止 "), el("span", "mono", mdhm(r.deadline))));
    add(card, meta(r), buttons(r));
    if (state.pick[r.id]) add(card, confirmBox(r));
    if (state.rowErr[r.id]) add(card, el("p", "ib-row-err", state.rowErr[r.id]));
    add(card, src(r));
    return card;
  }

  function answeredCard(r) {
    var card = el("article", "ib-card ib-card-done");
    add(card, add(el("div", "ib-done-top"),
      el("span", "ib-tag ib-st-" + r.status, label("statuses", r.status)),
      el("h3", "ib-title", r.title)));
    var when = "答于 " + mdhm(r.answered_at) + (r.by && r.by !== "jun" ? " · " + r.by : "");
    if (r.batch_size > 1) when += " · 同批 " + r.batch_size + " 条";
    if (r.words) add(card, el("blockquote", "ib-quote", r.words));
    add(card, el("p", "ib-when mono", when));
    if (r.result) add(card, add(el("p", "ib-result"), el("b", null, "已执行 "), document.createTextNode(r.result),
      el("span", "mono ib-when", " · " + mdhm(r.done_at))));
    add(card, src(r));
    return card;
  }

  function render() {
    if (!state.data) return;
    var active = document.activeElement;
    var focus = active && active.dataset ? active.dataset.focus : null;
    clear(body);
    var rows = state.data.rows || [];
    var pending = rows.filter(function (r) { return r.status === "pending"; });
    var answered = rows.filter(function (r) { return r.status !== "pending"; });
    syncBadge(state.data.summary.pending || 0);

    var sec = el("section", "ib-section");
    var over = state.data.summary.overdue || 0;
    add(sec, add(el("div", "ib-sec-head"), el("h2", null, "待你签"),
      el("span", "ib-count mono", pending.length + " 条"),
      over ? el("span", "ib-count ib-overdue", over + " 条问过 ≥3 次或积压 ≥7 天") : null));
    if (!pending.length) add(sec, el("p", "ib-wait", "没有待签的提案。"));
    pending.forEach(function (r) { add(sec, pendingCard(r)); });
    add(body, sec);

    if (answered.length) {
      var det = el("details", "ib-answered");
      det.open = state.answeredOpen;
      det.addEventListener("toggle", function () { state.answeredOpen = det.open; });
      add(det, add(el("summary"), el("span", null, "已答 "), el("span", "mono", String(answered.length))));
      var list = el("div", "ib-list");
      answered.forEach(function (r) { add(list, answeredCard(r)); });
      add(body, add(det, list));
    }
    if (focus) {
      var again = body.querySelector('[data-focus="' + focus.replace(/"/g, "") + '"]');
      if (again) again.focus();
    }
  }

  function load() {
    fetch("/api/inbox", { headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.ok ? r.json() : r.text().then(function (t) { throw new Error("HTTP " + r.status + " " + t.slice(0, 200)); });
      })
      .then(function (v) { state.data = v; showErrors((v.errors || []).slice()); render(); })
      .catch(function (e) { showErrors(["收件箱接口读取失败：" + String(e && e.message || e)]); });
  }
  load();
})();
