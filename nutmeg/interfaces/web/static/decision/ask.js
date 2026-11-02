// static/decision/ask.js —— 行内追问（2026-11-02 产品形态第 10 阶段 Task 10.4，画布 AskPhone）。
// 期页取证抽屉、竞彩板抽屉、账房逐期行上各有一个「问」按钮：点开底部面板，看这一行的问答线程、
// 用快捷问法或自己写一句提问（POST /action/ask），面板开着时每 4 秒拉一次 /api/ask?obj= 直到答上。
// 答案里的纠正草稿就地「确认纠正 / 不改，记一笔」（POST /action/correction/{id}/status，同纠正账页）；
// 待签提案只给去 /inbox 的链接。数全来自接口，文本一律 textContent，不用 innerHTML。
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
  function hhmm(iso) { return iso ? String(iso).slice(11, 16) : ""; }
  function when(iso) {
    var d = new Date();   // 本机日期（手机与 Mac 都在北京时间）
    var today = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    return iso && String(iso).slice(0, 10) !== today ? String(iso).slice(5, 10) + " " + hhmm(iso) : hhmm(iso);
  }
  function took(sec) {
    if (sec === null || sec === undefined) return "";
    sec = Math.round(sec);
    return sec >= 60 ? "用时 " + Math.floor(sec / 60) + " 分 " + (sec % 60) + " 秒" : "用时 " + sec + " 秒";
  }
  function json(resp) {
    return resp.json().catch(function () { return { ok: false, error: "HTTP " + resp.status }; });
  }

  var POLL_MS = 4000;
  var sheet = null;
  var s = { obj: "", label: "", data: null, timer: null, opener: null, sending: false, err: "", busy: {} };

  function build() {
    var back = el("div", "nm-ask-back");
    back.addEventListener("click", close);
    var box = el("div", "nm-ask");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    var head = el("div", "nm-ask-head");
    var title = el("strong", "nm-ask-title");
    var shut = el("button", "nm-ask-x", "关闭");
    shut.type = "button";
    shut.addEventListener("click", close);
    add(head, title, shut);
    var list = el("div", "nm-ask-list");
    list.setAttribute("aria-live", "polite");
    var quick = el("div", "nm-ask-quick");
    quick.setAttribute("role", "group");
    quick.setAttribute("aria-label", "快捷问法");
    var form = el("form", "nm-ask-form");
    var input = el("textarea", "nm-ask-input");
    input.rows = 2;
    input.placeholder = "问这一行";
    input.setAttribute("aria-label", "问这一行");
    var send = el("button", "nm-ask-send", "问");
    send.type = "submit";
    add(form, input, send);
    form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
    });
    var note = el("p", "nm-ask-note", "应答员只读文件、不改表；要改的数会变成纠正草稿或待签提案，等你确认。");
    add(box, head, list, quick, form, note);
    document.body.appendChild(back);
    document.body.appendChild(box);
    return { back: back, box: box, title: title, list: list, quick: quick, input: input, send: send };
  }

  function open(obj, label, opener) {
    sheet = sheet || build();
    s.obj = obj; s.label = label || obj; s.data = null; s.err = ""; s.opener = opener || null;
    sheet.title.textContent = "追问 · " + s.label;
    sheet.box.setAttribute("aria-label", "追问 · " + s.label);
    sheet.input.value = "";
    sheet.back.hidden = false; sheet.box.hidden = false;
    document.documentElement.classList.add("nm-ask-locked");
    render();
    load();
    sheet.input.focus();
  }

  function close() {
    if (!sheet) return;
    sheet.back.hidden = true; sheet.box.hidden = true;
    document.documentElement.classList.remove("nm-ask-locked");
    if (s.timer) { clearTimeout(s.timer); s.timer = null; }
    if (s.opener && s.opener.focus) s.opener.focus();
  }

  function waiting() {
    return !!(s.data && s.data.thread.some(function (q) { return !q.answer; }));
  }

  function load() {
    if (s.timer) { clearTimeout(s.timer); s.timer = null; }
    var obj = s.obj;
    fetch("/api/ask?obj=" + encodeURIComponent(obj), { headers: { Accept: "application/json" } })
      .then(json)
      .then(function (v) {
        if (obj !== s.obj || !sheet || sheet.box.hidden) return;
        if (v.ok === false) { s.err = v.error || "读取失败"; } else { s.data = v; s.err = ""; }
        render();
        if (waiting()) s.timer = setTimeout(load, POLL_MS);
      })
      .catch(function (e) { s.err = "追问接口读取失败：" + String(e && e.message || e); render(); });
  }

  function submit() {
    var text = sheet.input.value.trim();
    if (!text || s.sending) return;
    s.sending = true; s.err = ""; render();
    fetch("/action/ask", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ obj: s.obj, text: text }),
    }).then(json).then(function (out) {
      s.sending = false;
      if (!out.ok) { s.err = out.error || "没问出去"; render(); return; }
      sheet.input.value = "";
      load();
    }).catch(function (e) { s.sending = false; s.err = "没问出去：" + String(e && e.message || e); render(); });
  }

  function setCorrection(cid, status) {
    s.busy[cid] = true; render();
    fetch("/action/correction/" + encodeURIComponent(cid) + "/status", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: status, note: "追问面板" }),
    }).then(json).then(function (out) {
      delete s.busy[cid];
      if (!out.ok) s.err = out.error || "没改成";
      load();
    }).catch(function (e) { delete s.busy[cid]; s.err = String(e && e.message || e); render(); });
  }

  function draftCard(c) {
    var card = el("div", "nm-ask-draft");
    add(card, el("span", "nm-ask-tag", c.status === "draft" ? "这会改表 · 纠正草稿" : "纠正 · " + (c.status === "confirmed" ? "已确认，待回写" : c.status === "dismissed" ? "不改，已记一笔" : c.status)));
    add(card, el("p", "nm-ask-diff", (c.old || "—") + " → " + (c.new || "—")));
    if (c.status === "draft") {
      var row = el("div", "nm-ask-btns");
      var yes = el("button", "nm-ask-btn primary", "确认纠正");
      var no = el("button", "nm-ask-btn", "不改，记一笔");
      [yes, no].forEach(function (b) { b.type = "button"; b.disabled = !!s.busy[c.id]; });
      yes.addEventListener("click", function () { setCorrection(c.id, "confirmed"); });
      no.addEventListener("click", function () { setCorrection(c.id, "dismissed"); });
      add(card, add(row, yes, no));
    }
    return card;
  }

  function answerCard(q) {
    var a = q.answer;
    var card = el("div", "nm-ask-a");
    var key = q.date + "#" + q.seq;
    if (!a) {
      var reading = s.data.busy.indexOf(key) !== -1;
      var since = Math.max(0, Math.round((Date.now() - Date.parse(q.at)) / 1000));
      card.classList.add("wait");
      add(card, el("p", null, (reading ? "应答员在读文件…" : "排队中…") + " 已 " + (since >= 60 ? Math.floor(since / 60) + " 分 " : "") + (since % 60) + " 秒"));
      return card;
    }
    if (a.status === "failed") card.classList.add("failed");
    add(card, el("p", "nm-ask-text", a.text));
    if (a.sources && a.sources.length) {
      var det = el("details", "nm-ask-src");
      add(det, el("summary", null, "出处 " + a.sources.length));
      var ul = el("ul");
      a.sources.forEach(function (src) { add(ul, el("li", "mono", src)); });
      add(card, add(det, ul));
    }
    (a.correction_rows || []).forEach(function (c) { add(card, draftCard(c)); });
    if (a.proposals && a.proposals.length) {
      var p = el("a", "nm-ask-link", "待签提案 " + a.proposals.length + " 条 → 去待签");
      p.href = "/inbox";
      add(card, p);
    }
    add(card, el("p", "nm-ask-meta", ["应答员", when(a.at), took(a.duration_s)].filter(Boolean).join(" · ")));
    return card;
  }

  function render() {
    if (!sheet) return;
    clear(sheet.list);
    if (s.err) add(sheet.list, el("p", "nm-ask-err", s.err));
    if (!s.data) { add(sheet.list, el("p", "nm-ask-empty", "读取中…")); }
    else if (!s.data.thread.length) { add(sheet.list, el("p", "nm-ask-empty", "这一行还没人问过。")); }
    else {
      s.data.thread.forEach(function (q) {
        var item = el("div", "nm-ask-item");
        add(item, el("p", "nm-ask-q", q.text));
        var sub = "你 · " + when(q.at);
        if (q.obj !== s.obj) sub += " · 挂在 " + q.obj.slice(s.obj.length + 1);
        add(item, el("p", "nm-ask-meta", sub), answerCard(q));
        add(sheet.list, item);
      });
      sheet.list.scrollTop = sheet.list.scrollHeight;
    }
    clear(sheet.quick);
    ((s.data && s.data.quick) || []).forEach(function (text) {
      var b = el("button", "nm-ask-chip", text);
      b.type = "button";
      b.addEventListener("click", function () { sheet.input.value = text; sheet.input.focus(); });
      add(sheet.quick, b);
    });
    sheet.send.disabled = s.sending;
    sheet.send.textContent = s.sending ? "发送中" : "问";
  }

  // 给各页用：一个「问」按钮，点开这一行的追问面板
  function button(obj, label, cls) {
    var b = el("button", "nm-ask-trigger" + (cls ? " " + cls : ""), "问");
    b.type = "button";
    b.setAttribute("aria-label", "追问 · " + (label || obj));
    b.addEventListener("click", function (e) { e.stopPropagation(); open(obj, label, b); });
    return b;
  }

  window.NMAsk = { button: button, open: open };
})();
