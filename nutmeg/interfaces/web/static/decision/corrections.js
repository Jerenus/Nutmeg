// static/decision/corrections.js —— 纠正账（2026-10-30 产品形态第 10 阶段 Task 10.2，画布「纠正账」）。
// 数全来自 /api/corrections：rows（已按 id 折叠、新的在前）、summary（复发堆 / 草稿数，按全账算）、
// labels（类型 / 谁发现 / 回写到 / 状态的中文）。页面只做类型筛选（显示过滤）和两个按钮：
// 草稿 → 确认 / 不改·记一笔（POST /action/correction/{id}/status，回包后重新拉账）。
// ?obj=<前缀> 预选对象（期页「看纠正账」链接用）。文本一律 textContent / createElement，不用 innerHTML。
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
  function link(href, cls, text) { var a = el("a", cls, text); a.href = href; return a; }

  var root = document.getElementById("corrections");
  if (!root) return;
  var errBox = document.getElementById("errors");
  var params = new URLSearchParams(window.location.search);
  var state = { data: null, kind: "", obj: params.get("obj") || "", open: {}, busy: {}, rowErr: {} };
  var body = el("div", "cx-body");
  add(root, body);

  function showErrors(list) {
    clear(errBox);
    list.forEach(function (e) { add(errBox, el("span", null, e)); });
    errBox.hidden = list.length === 0;
  }
  function label(map, key) { return (state.data.labels[map] || {})[key] || key || "—"; }

  // ---- 类型筛选 ----
  function chips() {
    var box = el("div", "cx-chips");
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "按类型筛选");
    var kinds = [["", "全部"]].concat(Object.keys(state.data.labels.kinds).map(function (k) {
      return [k, state.data.labels.kinds[k]];
    }));
    var counts = state.data.summary.by_kind || {};
    kinds.forEach(function (pair) {
      var b = el("button", "cx-chip" + (state.kind === pair[0] ? " on" : ""));
      b.type = "button";
      b.setAttribute("aria-pressed", String(state.kind === pair[0]));
      b.dataset.focus = "chip-" + pair[0];
      add(b, document.createTextNode(pair[1]));
      if (pair[0] && counts[pair[0]]) add(b, el("small", "mono", " " + counts[pair[0]]));
      b.addEventListener("click", function () { state.kind = pair[0]; render(); });
      add(box, b);
    });
    return box;
  }

  // ---- 复发最多 ----
  function piles() {
    var list = state.data.summary.piles || [];
    var sec = el("section", "cx-section");
    add(sec, el("h2", null, "复发最多"));
    if (!list.length) return add(sec, el("p", "cx-wait", "还没有归堆的纠正。"));
    var grid = el("div", "cx-piles");
    list.forEach(function (p) {
      var dates = (p.dates || []).map(function (d) { return d.slice(5); }).join(" · ");
      add(grid, add(el("div", "cx-pile" + (p.open ? " cx-pile-open" : "")),
        add(el("div", "cx-pile-top"), el("span", "cx-pile-name", p.pile), el("span", "cx-pile-n mono", "×" + p.n)),
        el("span", "cx-pile-dates mono", dates),
        el("span", "cx-pile-state", p.open ? "未结 " + p.open : "全部结清")));
    });
    return add(sec, grid);
  }

  // ---- 行 ----
  function statusTag(r) {
    return el("span", "cx-status cx-st-" + r.status, label("statuses", r.status));
  }
  function setStatus(r, status) {
    state.busy[r.id] = true;
    delete state.rowErr[r.id];
    render();
    fetch("/action/correction/" + encodeURIComponent(r.id) + "/status", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: status, note: "" }),
    }).then(function (resp) {
      return resp.json().catch(function () { return { ok: false, error: "HTTP " + resp.status }; });
    }).then(function (out) {
      delete state.busy[r.id];
      if (!out.ok) { state.rowErr[r.id] = out.error || "改不了"; render(); return; }
      load();
    }).catch(function (e) {
      delete state.busy[r.id];
      state.rowErr[r.id] = "接口不可达：" + String(e && e.message || e);
      render();
    });
  }
  function actions(r) {
    var box = el("div", "cx-actions");
    if (r.status !== "draft") return add(box, statusTag(r));
    add(box, statusTag(r));
    [["confirmed", "确认", "cx-btn cx-btn-ok"], ["dismissed", "不改·记一笔", "cx-btn"]].forEach(function (a) {
      var b = el("button", a[2], a[1]);
      b.type = "button";
      b.disabled = !!state.busy[r.id];
      b.dataset.focus = "act-" + r.id + "-" + a[0];
      b.addEventListener("click", function () { setStatus(r, a[0]); });
      add(box, b);
    });
    if (state.rowErr[r.id]) add(box, el("span", "cx-row-err", state.rowErr[r.id]));
    return box;
  }
  function cellK(cls, key, content) {
    var c = el("div", cls);
    add(c, el("span", "cx-k", key));
    if (typeof content === "string") add(c, el("span", null, content)); else add(c, content);
    return c;
  }
  function row(r) {
    var open = !!state.open[r.id];
    var wrap = el("div", "cx-row-wrap" + (r.status === "draft" ? " cx-draft" : ""));
    var line = el("div", "cx-row");
    var change = el("button", "cx-change");
    change.type = "button";
    change.setAttribute("aria-expanded", String(open));
    change.dataset.focus = "chg-" + r.id;
    change.title = r.evidence ? "证据：" + r.evidence : "（没写证据）";
    add(change, el("s", "cx-old", r.old || "—"), el("span", "cx-arrow", " → "), el("span", "cx-new", r.new || "—"));
    change.addEventListener("click", function () { state.open[r.id] = !open; render(); });
    add(line,
      cellK("cx-c-date mono", "日期", String(r.at || "").slice(0, 10)),
      cellK("cx-c-obj", "对象", el("span", "cx-obj mono", r.obj)),
      cellK("cx-c-change", "旧→新", change),
      cellK("cx-c-kind", "类型", label("kinds", r.kind)),
      cellK("cx-c-who", "谁发现", label("found_by", r.found_by)),
      cellK("cx-c-dest", "回写到", label("dests", r.dest)),
      cellK("cx-c-status", "状态", actions(r)));
    add(wrap, line);
    if (open) {
      var more = el("div", "cx-more");
      add(more, add(el("p"), el("b", null, "证据 "), document.createTextNode(r.evidence || "（没写）")));
      if (r.pile) add(more, add(el("p"), el("b", null, "复发堆 "), document.createTextNode(r.pile)));
      if (r.note) add(more, add(el("p"), el("b", null, "备注 "), document.createTextNode(r.note)));
      add(more, el("p", "cx-meta mono", r.id + " · 来源 " + (r.source || "—")));
      (r.history || []).forEach(function (h) {
        add(more, el("p", "cx-meta", String(h.at || "").slice(0, 16).replace("T", " ") + " · " +
          label("statuses", h.status) + (h.by ? " · " + h.by : "") + (h.note ? " · " + h.note : "")));
      });
      add(wrap, more);
    }
    return wrap;
  }
  function table() {
    var sec = el("section", "cx-section");
    var rows = (state.data.rows || []).filter(function (r) { return !state.kind || r.kind === state.kind; });
    var head = add(el("div", "cx-table-head"), el("h2", null, "全部纠正"),
      el("span", "cx-count mono", rows.length + " 条"));
    add(sec, head);
    if (state.obj) {
      add(sec, add(el("p", "cx-filter"), document.createTextNode("只看对象 "),
        el("span", "mono", state.obj), document.createTextNode(" 及其下属 · "),
        link("/corrections", null, "看全部")));
    }
    if (!rows.length) return add(sec, el("p", "cx-wait", "这里还没有纠正。"));
    var grid = el("div", "cx-table");
    add(grid, add(el("div", "cx-row cx-row-head"),
      el("span", null, "日期"), el("span", null, "对象"), el("span", null, "旧 → 新"), el("span", null, "类型"),
      el("span", null, "谁发现"), el("span", null, "回写到"), el("span", null, "状态")));
    rows.forEach(function (r) { add(grid, row(r)); });
    return add(sec, grid);
  }

  function render() {
    if (!state.data) return;
    // 重画不丢焦点：按 data-focus 找回同一个按钮（确认后按钮没了就算了）
    var active = document.activeElement;
    var focus = active && active.dataset ? active.dataset.focus : null;
    clear(body);
    var drafts = state.data.summary.drafts || 0;
    // 导航角标是服务端渲染的；页上确认之后用同一份 summary.drafts 跟上，不用刷新整页
    document.querySelectorAll('.nm-badge[data-badge="corrections"]').forEach(function (badge) {   // 顶栏与手机底栏各一枚
      if (drafts) badge.textContent = String(drafts); else badge.remove();
    });
    add(body,
      add(el("div", "cx-bar"), chips(),
        el("span", "cx-drafts" + (drafts ? " on" : ""), drafts ? drafts + " 条草稿待你确认" : "没有待确认的草稿")),
      piles(), table());
    if (focus) {
      var again = body.querySelector('[data-focus="' + focus.replace(/"/g, "") + '"]');
      if (again) again.focus();
    }
  }

  function load() {
    var url = "/api/corrections" + (state.obj ? "?obj=" + encodeURIComponent(state.obj) : "");
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.ok ? r.json() : r.text().then(function (t) { throw new Error("HTTP " + r.status + " " + t.slice(0, 200)); });
      })
      .then(function (v) { state.data = v; showErrors((v.errors || []).slice()); render(); })
      .catch(function (e) { showErrors(["纠正账接口读取失败：" + String(e && e.message || e)]); });
  }
  load();
})();
