// static/decision/ledger.js —— 账房页（2026-10-28 产品形态第 7 阶段 Task 7.2，画布 Ledger.dc.html）。
// 数全来自 /api/ledger/{月}（Task 7.1）：月报 report、返奖 payout、曲线 curve、逐期 issues、
// 竞彩出票日 jczq_days、选择账 choices、桥后改动账 bridges；初稿账（gym 回放）懒加载
// /api/ledger/{月}/draft（含反事实曲线 curve，到了就叠在净值图上，Task 7.3）。页面不累计、不推导金额：只画 / 印服务端给的数（千分位、正负号、
// 回收率＝返奖/投入 只是排版）。文本一律 textContent / createElement，不用 innerHTML。
(function () {
  "use strict";

  var SVG = "http://www.w3.org/2000/svg";
  // 偏离理由封闭枚举 = betslip_diagnosis.DEVIATION_REASONS（同 issue.js / jczq.js）
  var REASONS = { fact_self_judged: "自判事实", price_instinct: "价格直觉",
    stake_allocation: "资金分配", structure_preference: "结构偏好", other: "其他" };

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
  function put(parent, child) { parent.appendChild(child); return child; }   // 返回子节点
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function link(href, cls, text) { var a = el("a", cls, text); a.href = href; return a; }
  function svg(tag, attrs, text) {
    var n = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function isNum(x) { return typeof x === "number" && isFinite(x); }

  // ---- 数字排版：只做符号与千分位，数本身来自服务端 ----
  function grp(x) { return Math.round(Math.abs(x)).toLocaleString("en-US"); }
  function signed(x) {
    if (!isNum(x)) return "—";
    var r = Math.round(x);
    return (r < 0 ? "−" : r > 0 ? "+" : "") + grp(x);
  }
  function yuan(x) { return isNum(x) ? "¥" + grp(x) : "—"; }
  function plain(x) { return isNum(x) ? grp(x) : "—"; }
  function pct(p, digits) { return isNum(p) ? (p * 100).toFixed(digits === undefined ? 1 : digits) + "%" : "—"; }
  function negLine(x) { return isNum(x) ? "−" + grp(x) : "—"; }   // 止损线是正数，画 / 写在 −line
  function tone(x) { return !isNum(x) || Math.round(x) === 0 ? "" : x < 0 ? "lg-neg" : "lg-pos"; }
  function mmdd(day) { return String(day || "").slice(5, 10); }
  function money(cls, x) { return el("span", ["mono", tone(x), cls].filter(Boolean).join(" "), signed(x)); }

  // ---- 外壳 ----
  var root = document.getElementById("ledger");
  if (!root) return;
  var month = root.getAttribute("data-month");
  var errBox = document.getElementById("errors");
  var errors = [];
  var view = null;

  function showErrors() {
    clear(errBox);
    errors.forEach(function (e) { add(errBox, el("span", null, e)); });
    errBox.hidden = errors.length === 0;
  }

  function card(title, note) {
    var sec = el("section", "lg-card");
    var head = add(el("div", "lg-card-head"), el("h2", null, title));
    if (note) add(head, el("span", "lg-note", note));
    return add(sec, head);
  }
  function scrollTable(cls, headers) {
    var wrap = el("div", "lg-scroll");
    var table = put(wrap, el("table", "lg-table" + (cls ? " " + cls : "")));
    var tr = put(put(table, el("thead")), el("tr"));
    headers.forEach(function (h) { add(tr, el("th", h[1] || null, h[0])); });
    var tbody = put(table, el("tbody"));
    return { wrap: wrap, tbody: tbody };
  }
  function td(cls, content) {
    var c = el("td", cls || null);
    if (content instanceof Node) c.appendChild(content);
    else if (content !== undefined && content !== null) c.textContent = content;
    return c;
  }

  // ---- 月份切换 ----
  function renderMonths(months) {
    var head = root.querySelector(".ledger-head");
    var old = head.querySelector(".lg-months");
    if (old) old.remove();
    var list = (months || []).slice();
    if (list.indexOf(month) < 0) list.push(month);
    list.sort().reverse();
    var nav = el("nav", "lg-months");
    nav.setAttribute("aria-label", "月份");
    list.forEach(function (m) {
      var a = link("/ledger/" + m, "lg-month mono", m);
      if (m === month) a.setAttribute("aria-current", "page");
      add(nav, a);
    });
    add(head, nav);
  }

  // ---- 四块数字 + 实质余量 ----
  function kpi(label, big, bigCls, sub) {
    var box = el("div", "lg-kpi");
    add(box, el("span", "lg-kpi-label", label), el("span", "lg-kpi-big" + (bigCls ? " " + bigCls : ""), big));
    if (sub) add(box, el("span", "lg-kpi-sub", sub));
    return box;
  }

  function renderKpis(v) {
    var r = v.report;
    var wrap = el("section", "lg-kpis");
    wrap.setAttribute("aria-label", "本月数字");
    if (!r) {
      add(wrap, kpi("净值", "—", "", "月报读不出（见上方错误）"));
      return [wrap];
    }
    add(wrap, kpi("净值 vs 空仓", signed(r.net), tone(r.net),
      "空仓 ＝ 0 · " + plain(r.entries) + " 条入账" + (r.tripped ? " · 实质已越止损线 " + negLine(r.stop_loss) : "")));

    var pay = v.payout;
    var paySub;
    if (!pay) paySub = "返奖读不出";
    else if (pay.missing && pay.missing.length) {
      paySub = "返奖 " + plain(pay.payout) + " · " + pay.missing.length + " 条缺投入/返奖（" +
        pay.missing.join("、") + "），不出回收率";
    } else {
      paySub = "返奖 " + plain(pay.payout) + " · 回收 " + (r.stake ? pct(pay.payout / r.stake) : "—");
    }
    add(wrap, kpi("投入 / 返奖", plain(r.stake), "", paySub));

    var ch = r.by_channel || {};
    var issues = v.issues || [];
    var won = issues.filter(function (it) { return isNum(it.payout) && it.payout > 0; });
    var wonSub = won.length
      ? "中奖 " + won.length + " 期（" + won.map(function (it) { return it.issue + " " + signed(it.net); }).join("、") + "）"
      : "无中奖期";
    add(wrap, kpi("足彩 " + issues.length + " 期", signed(ch.zucai), tone(ch.zucai), wonSub));
    add(wrap, kpi("竞彩 " + (v.jczq_days || []).length + " 个出票日", signed(ch.jczq), tone(ch.jczq),
      "只列有投入的日子"));

    var room = el("p", "lg-room" + (r.tripped ? " veto" : ""));
    var pend = r.pending || { n: 0, stake: 0, slips: [] };
    var line = " · 现行止损线 " + negLine(r.stop_loss);
    var tail = isNum(r.room)
      ? (r.room < 0 ? "越线 ¥" + grp(r.room) : "余 ¥" + grp(r.room)) : "";
    if (pend._error) {
      room.textContent = "实质余量：登记簿读不出，待结票未知——" + pend._error;
      room.className = "lg-room veto";
    } else if (pend.n) {
      var ids = (pend.slips || []).map(function (s) { return s.slip_id; });
      add(room, el("span", null, "实质余量：待结 " + pend.n + " 张 " + yuan(pend.stake) + " 按全损计（" +
        ids.slice(0, 6).join("、") + (ids.length > 6 ? " 等" : "") + "）→ 实质 "),
        el("b", null, signed(r.effective_net)), el("span", null, " · " + tail + line));
    } else {
      add(room, el("span", null, "实质余量：无待结票，同净值 "), el("b", null, signed(r.effective_net)),
        el("span", null, " · " + tail + line));
    }
    var out = [wrap, room];
    if (r.unknown && r.unknown.length) {
      out.push(el("p", "lg-note", r.unknown.length + " 条无法归月、未计入：" + r.unknown.slice(0, 8).join("、")));
    }
    return out;
  }

  // ---- 曲线：阶梯净值、0 线、止损线（含换线标注）、实质点；初稿账到了再叠反事实虚线 ----
  var chartBox = null, chartWidth = 0, legendBox = null, draftCurve = null;
  var DRAFT_KEY = "足彩换成机器初稿（竞彩照实际·不套止损）";

  function daysIn(m) { return new Date(Number(m.slice(0, 4)), Number(m.slice(5, 7)), 0).getDate(); }
  function niceStep(span) {
    var steps = [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000];
    for (var i = 0; i < steps.length; i++) if (span / steps[i] <= 6) return steps[i];
    return 100000;
  }
  function tickLabel(v) {
    if (v === 0) return "0";
    var k = Math.abs(v) / 1000;
    var s = (k >= 1 ? (Number.isInteger(k) ? String(k) : k.toFixed(1)) + "k" : String(Math.abs(v)));
    return (v < 0 ? "−" : "+") + s;
  }
  function netOn(points, day) {   // 当日（或之前最近一日）的服务端累计净值点；没有 → null
    var hit = null;
    (points || []).forEach(function (p) { if (p.day <= day) hit = p; });
    return hit;
  }

  function drawChart(curve) {
    if (!chartBox) return;
    clear(chartBox);
    var W = Math.max(320, Math.min(1000, Math.round(chartBox.clientWidth || 1000)));
    chartWidth = W;
    var narrow = W < 560;
    var H = narrow ? 260 : 340;
    var padL = narrow ? 40 : 52, padR = narrow ? 14 : 24, padT = 16, padB = 30;
    var points = curve.points || [], moves = curve.moves || [], eff = curve.effective;
    var nDays = daysIn(month);
    var first = month + "-01", last = month + "-" + String(nDays).padStart(2, "0");

    // 止损线拐点：points[].line ∪ moves（换线日 → to），起点取首个换线的 from 或首点的 line
    var knots = points.map(function (p) { return { day: p.day, line: p.line }; })
      .concat(moves.map(function (mv) { return { day: mv.day, line: mv.to }; }))
      .filter(function (k) { return isNum(k.line); })
      .sort(function (a, b) { return a.day < b.day ? -1 : a.day > b.day ? 1 : 0; });
    var startLine = null;
    if (moves.length && (!points.length || moves[0].day <= points[0].day)) startLine = moves[0].from;
    else if (knots.length) startLine = knots[0].line;

    var vals = [0];
    points.forEach(function (p) { vals.push(p.net); if (isNum(p.line)) vals.push(-p.line); });
    moves.forEach(function (mv) { vals.push(-mv.from, -mv.to); });
    if (eff && isNum(eff.net)) vals.push(eff.net);
    (draftCurve || []).forEach(function (p) { vals.push(p.net); });   // 反事实线出界 → 放大值域，不裁
    vals = vals.filter(isNum);
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var step = niceStep(Math.max(hi - lo, 1));
    var yLo = Math.floor(lo / step) * step, yHi = Math.ceil(hi / step) * step;
    if (yHi === yLo) yHi = yLo + step;

    function x(day) {
      var d = Number(String(day).slice(8, 10)) || 1;
      return padL + (d - 1) / Math.max(nDays - 1, 1) * (W - padL - padR);
    }
    function y(v) { return padT + (yHi - v) / (yHi - yLo) * (H - padT - padB); }
    function f(n) { return Math.round(n * 10) / 10; }

    var cfLast = draftCurve && draftCurve.length ? draftCurve[draftCurve.length - 1] : null;
    var label = "本月累计净值阶梯线" + (points.length ? "，末点 " + signed(points[points.length - 1].net) : "，无入账") +
      (moves.length ? "；止损线换档 " + moves.map(function (mv) {
        return mmdd(mv.day) + " " + negLine(mv.from) + "→" + negLine(mv.to);
      }).join("、") : "") + (eff ? "；实质 " + signed(eff.net) + "（" + mmdd(eff.day) + "，含待结票全损）" : "") +
      (cfLast ? "；" + DRAFT_KEY + " 末点 " + signed(cfLast.net) : "");
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": label });

    // 网格 + y 轴
    for (var v = yLo; v <= yHi + 1e-9; v += step) {
      if (v === 0) continue;
      add(s, svg("line", { x1: padL, x2: W - padR, y1: f(y(v)), y2: f(y(v)), "class": "c-grid" }));
      add(s, svg("text", { x: padL - 6, y: f(y(v) + 4), "text-anchor": "end" }, tickLabel(v)));
    }
    add(s, svg("line", { x1: padL, x2: W - padR, y1: f(y(0)), y2: f(y(0)), "class": "c-zero" }));
    add(s, svg("text", { x: padL - 6, y: f(y(0) + 4), "text-anchor": "end" }, "0"));

    // x 轴：月初、月末、换线日、末点、实质点；挤在一起的后来者让位
    var placed = [];
    var xTicks = [[first, "start"], [last, "end"]];
    moves.forEach(function (mv) { xTicks.push([mv.day, "middle"]); });
    if (points.length) xTicks.push([points[points.length - 1].day, "middle"]);
    if (eff) xTicks.push([eff.day, "middle"]);
    xTicks.forEach(function (t) {
      var px = x(t[0]);
      if (placed.some(function (q) { return Math.abs(q - px) < (narrow ? 34 : 42); })) return;
      placed.push(px);
      add(s, svg("text", { x: f(px), y: H - 8, "text-anchor": t[1] }, mmdd(t[0])));
    });

    // 止损线（阶梯，虚线）
    if (isNum(startLine)) {
      var d = "M" + f(x(first)) + "," + f(y(-startLine));
      var cur = startLine;
      knots.forEach(function (k) {
        if (k.line === cur) return;
        d += " H" + f(x(k.day)) + " V" + f(y(-k.line));
        cur = k.line;
      });
      d += " H" + f(x(last));
      add(s, svg("path", { d: d, "class": "c-line" }));
      add(s, svg("text", { x: f(x(first) + 4), y: f(y(-startLine) - 5), "class": "c-veto" }, "线 " + negLine(startLine)));
    }

    // 反事实线（阶梯，虚线；画在实际线下面）：服务端逐日累计点，末点标数，与实际线同延到实质日
    var lastPt = points.length ? points[points.length - 1] : null;
    if (cfLast) {
      var dc = "M" + f(x(first)) + "," + f(y(0));
      draftCurve.forEach(function (p) { dc += " H" + f(x(p.day)) + " V" + f(y(p.net)); });
      if (eff && eff.day > cfLast.day) dc += " H" + f(x(eff.day));
      add(s, svg("path", { d: dc, "class": "c-draft" }));
      var cx = x(cfLast.day), cy = y(cfLast.net);
      add(s, svg("circle", { cx: f(cx), cy: f(cy), r: 4, "class": "c-draft-dot" }));
      var cRoom = W - padR - cx > 90;
      var under = !lastPt || cfLast.net < lastPt.net;   // 在实际末点下方就标在点下，免得压住实际末点数
      add(s, svg("text", { x: f(cRoom ? cx + 8 : cx - 8), y: f(under ? cy + 16 : cy - 8),
        "text-anchor": cRoom ? "start" : "end", "class": "c-draft-ink" }, "初稿 " + signed(cfLast.net)));
    }

    // 实际净值（阶梯，实线）
    if (points.length) {
      var dn = "M" + f(x(first)) + "," + f(y(0));
      points.forEach(function (p) { dn += " H" + f(x(p.day)) + " V" + f(y(p.net)); });
      if (eff && eff.day > lastPt.day) dn += " H" + f(x(eff.day));   // 结算后无新入账：净值原样延到实质日
      add(s, svg("path", { d: dn, "class": "c-net" }));
      var lx = x(lastPt.day), ly = y(lastPt.net);
      var below = lastPt.net < -(isNum(lastPt.line) ? lastPt.line : Infinity);
      add(s, svg("circle", { cx: f(lx), cy: f(ly), r: 5, "class": "c-dot" + (below ? " veto" : "") }));
      var rightRoom = W - padR - lx > 70;
      add(s, svg("text", { x: f(rightRoom ? lx + 8 : lx - 8), y: f(ly - 8), "text-anchor": rightRoom ? "start" : "end",
        "class": "c-ink" }, signed(lastPt.net)));
    }

    // 实质点（虚线下探 + 空心点）
    if (eff && isNum(eff.net)) {
      var startNet = lastPt ? lastPt.net : 0;
      var ex = x(eff.day);
      if (!lastPt) add(s, svg("path", { d: "M" + f(x(first)) + "," + f(y(0)) + " H" + f(ex), "class": "c-net" }));
      add(s, svg("path", { d: "M" + f(ex) + "," + f(y(startNet)) + " V" + f(y(eff.net)), "class": "c-eff" }));
      add(s, svg("circle", { cx: f(ex), cy: f(y(eff.net)), r: 5, "class": "c-hollow" }));
      var room = W - padR - ex > 110;
      add(s, svg("text", { x: f(room ? ex + 8 : ex - 8), y: f(y(eff.net) + 16), "text-anchor": room ? "start" : "end",
        "class": "c-ink" }, "实质 " + signed(eff.net)));
    }

    // 换线标注：竖段上的编号圈 + 新线数（窄屏只留编号圈，免得压住末点数）；全文写在图下（不可隐藏）
    moves.forEach(function (mv, i) {
      var mx = x(mv.day), my = (y(-mv.from) + y(-mv.to)) / 2;
      var g = put(s, svg("g", {}));
      add(g, svg("title", {}, mmdd(mv.day) + " 止损线 " + negLine(mv.from) + " → " + negLine(mv.to)));
      add(g, svg("circle", { cx: f(mx), cy: f(my), r: 9, "class": "c-mark" }));
      add(g, svg("text", { x: f(mx), y: f(my + 4), "text-anchor": "middle", "class": "c-mark-n" }, String(i + 1)));
      if (!narrow) add(g, svg("text", { x: f(mx + 6), y: f(y(-mv.to) + 15), "class": "c-veto" }, "→ " + negLine(mv.to)));
    });

    add(chartBox, s);
  }

  function renderCurve(v) {
    var sec = card("净值、空仓与止损线", "阶梯＝服务端逐日累计点；止损线每次挪动都标在图上");
    var curve = v.curve;
    if (!curve) { add(sec, el("p", "lg-error", "曲线读不出（见上方错误）")); return sec; }
    var legend = add(el("div", "lg-legend"),
      add(el("span", "lg-key"), el("i", "k-net"), el("span", null, "实际净值")),
      add(el("span", "lg-key"), el("i", "k-flat"), el("span", null, "空仓 0")),
      add(el("span", "lg-key"), el("i", "k-line"), el("span", null, "止损线")));
    if (curve.effective) add(legend, add(el("span", "lg-key"), el("i", "k-eff"), el("span", null, "实质（待结票按全损）")));
    add(sec, legend);
    legendBox = legend;
    if (!(curve.points || []).length && !curve.effective) add(sec, el("p", "lg-note", "本月无入账（空仓）。"));
    chartBox = put(sec, el("div", "lg-chart"));
    var moves = curve.moves || [];
    if (moves.length) {
      var ol = el("ol", "lg-moves");
      moves.forEach(function (mv, i) {
        var at = netOn(curve.points, mv.day);
        var li = add(el("li"), el("span", null, (i + 1) + " · " + mmdd(mv.day) + " 止损线 "),
          el("span", "mono", negLine(mv.from) + " → " + negLine(mv.to)));
        if (at) {
          add(li, el("span", null, at.day === mv.day ? " · 当日末净 " : " · 当时净（" + mmdd(at.day) + "）"),
            el("span", "mono", signed(at.net)));
        }
        add(ol, li);
      });
      add(sec, ol);
    }
    if (curve.effective) {
      var r = v.report || {};
      var pend = r.pending || {};
      add(sec, el("p", "lg-note", "实质点 " + mmdd(curve.effective.day) + " " + signed(curve.effective.net) +
        (pend.n ? "：待结 " + pend.n + " 张 " + yuan(pend.stake) + " 按全损计" : "")));
    }
    return sec;
  }

  // ---- 足彩逐期 / 竞彩出票日 ----
  function renderIssues(v) {
    var issues = v.issues || [];
    var sec = card("足彩逐期", "投入 · 返奖 · 净（记分牌）");
    if (!issues.length) { add(sec, el("p", "lg-note", "本月记分牌没有足彩条目。")); return sec; }
    var maxAbs = 0;
    issues.forEach(function (it) { if (isNum(it.net)) maxAbs = Math.max(maxAbs, Math.abs(it.net)); });
    var t = scrollTable(null, [["期"], ["张", "num"], ["投入", "num"], ["返奖", "num"], ["净", "num"], [""]]);
    issues.forEach(function (it) {
      var flat = !it.stake && isNum(it.net) && it.net === 0;
      var bar = add(el("div", "lg-bar"), el("span", isNum(it.net) && it.net > 0 ? "pos" : null));
      bar.firstChild.style.width = (maxAbs && isNum(it.net) ? Math.round(Math.abs(it.net) / maxAbs * 100) : 0) + "%";
      add(t.tbody, add(el("tr"),
        td(null, link("/issue/" + encodeURIComponent(it.issue), null, it.issue)),
        td("num", plain(it.slips)),
        td("num", plain(it.stake)),
        td("num", plain(it.payout)),
        td("num strong", flat ? el("span", "lg-muted", "空仓") : money(null, it.net)),
        td("lg-bar-cell", bar)));
    });
    return add(sec, t.wrap);
  }

  function renderJczq(v) {
    var days = v.jczq_days || [];
    var sec = card("竞彩出票日", "有投入的日子");
    if (!days.length) { add(sec, el("p", "lg-note", "本月竞彩没有出票日。")); return sec; }
    var t = scrollTable(null, [["日"], ["投入", "num"], ["净", "num"]]);
    days.forEach(function (d) {
      add(t.tbody, add(el("tr"),
        td(null, link("/jczq/" + encodeURIComponent(d.day), null, d.day)),
        td("num", plain(d.stake)), td("num strong", money(null, d.net))));
    });
    return add(sec, t.wrap);
  }

  // ---- 理由账 ----
  function reasonName(key) {
    var n = el("span", "lg-reason-name", key ? (REASONS[key] || key) : "偏离初稿未登记理由");
    if (key && REASONS[key]) add(n, el("small", null, key));
    return n;
  }
  function renderReasons(v) {
    var r = v.report || {};
    var sec = card("理由账", "人相对初稿的偏离，按理由结账");
    var dev = r.deviations;
    if (!dev) { add(sec, el("p", "lg-error", "月报读不出（见上方错误）")); return sec; }
    if (dev._error) { add(sec, el("p", "lg-error", "登记簿或记分牌读不出，理由账缺席——" + dev._error)); return sec; }
    add(sec, el("p", "lg-note", "本月 " + plain(dev.n) + " 张带理由的实购票"));
    var keys = Object.keys(dev.by_reason || {}).sort();
    var list = put(sec, el("div", "lg-reasons"));
    if (!keys.length) add(list, el("p", "lg-note", "无（偏离初稿而不登记理由的票不进这张账）"));
    keys.forEach(function (k) {
      var b = dev.by_reason[k];
      var row = add(el("div", "lg-reason"), reasonName(k),
        el("span", "num", plain(b.n) + " 张"), money("num", b.net));
      add(row, el("span", "lg-reason-sub", "投入 " + yuan(b.stake) + " · 返奖 " + yuan(b.payout) +
        (b.pending ? " · 待结 " + b.pending : "")));
      var preds = b.predictions || [];
      if (preds.length) {
        var det = add(el("details"), el("summary", null, "登记时的预言 " + preds.length + " 条"));
        var ul = put(det, el("ul", "lg-list"));
        preds.forEach(function (p) { add(ul, el("li", null, p)); });
        add(row, det);
      }
      add(list, row);
    });

    var late = dev.after_kickoff || {};
    var lateBox = put(sec, el("div", "lg-split"));
    add(lateBox, el("span", "lg-split-head", "开球后才写理由（单列，不计入上面）"));
    if (late.n) {
      add(lateBox, add(el("p", "lg-split-nums"), el("span", null, late.n + " 张 · 投入 " + yuan(late.stake) + " · 净 "),
        money(null, late.net), el("span", null, late.pending ? " · 待结 " + late.pending : "")));
      var lateDet = add(el("details"), el("summary", null, "票号 " + (late.slips || []).length + " 张"));
      var lul = put(lateDet, el("ul", "lg-list"));
      (late.slips || []).forEach(function (sid) { add(lul, el("li", null, sid)); });
      add(lateBox, lateDet);
    } else {
      add(lateBox, el("p", "lg-note", "无"));
    }

    var vt = r.vetoed || {};
    var vBox = put(sec, el("div", "lg-split"));
    add(vBox, el("span", "lg-split-head", "审票否决仍买（单列）"));
    if (vt._error) {
      add(vBox, el("p", "lg-error", vt._error));
    } else {
      var codes = Object.keys(vt.codes || {}).sort().map(function (c) { return c + "×" + vt.codes[c]; });
      add(vBox, add(el("p", "lg-split-nums"),
        el("span", null, plain(vt.n || 0) + " 张 · 投入 " + yuan(vt.stake || 0) + " · 返奖 " + yuan(vt.payout || 0) + " · 净 "),
        money(null, vt.net || 0), el("span", null, vt.pending ? " · 待结 " + vt.pending : "")));
      if (codes.length) add(vBox, el("p", "lg-note", "否决码计数：" + codes.join("、")));
      if (vt.unrecorded) add(vBox, el("p", "lg-note", vt.unrecorded + " 张登记时没存审票结论（10-06 前），不在此列"));
    }
    return sec;
  }

  // ---- 初稿账（懒加载 gym 回放） ----
  var DRAFT_ROWS = [["real", "实际出票"], ["zucai_draft", "机器初稿"], ["flat", "空仓"]];

  function overlayDraft(data) {   // 初稿账到了：反事实线进图例并重画（_error / 无 curve 不画）
    if (!data || data._error || !(data.curve || []).length || !legendBox) return;
    draftCurve = data.curve;
    add(legendBox, add(el("span", "lg-key"), el("i", "k-draft"), el("span", null, DRAFT_KEY)));
    if (view && view.curve) drawChart(view.curve);
  }

  function renderDraftBody(box, data) {
    clear(box);
    overlayDraft(data);
    if (!data || data._error) {
      add(box, el("p", "lg-error", "回放失败：" + ((data && data._error) || "无结果")));
      return;
    }
    add(box, el("p", "lg-note", "本月 " + plain(data.issues) + " 期；初稿＝处方忠实任九、帽 ¥400；两边都不套止损"));
    var t = scrollTable(null, [["口径"], ["票数", "num"], ["期数", "num"], ["投入", "num"], ["净", "num"],
      ["ROI", "num"], ["待结", "num"]]);
    DRAFT_ROWS.forEach(function (pair) {
      var row = data[pair[0]] || {};
      add(t.tbody, add(el("tr"),
        td("strong", row.label || pair[1]), td("num", plain(row.slips)), td("num", plain(row.keys)),
        td("num", plain(row.stake)), td("num strong", money(null, row.net)),
        td("num", isNum(row.roi) ? (row.roi > 0 ? "+" : row.roi < 0 ? "−" : "") + Math.abs(row.roi * 100).toFixed(1) + "%" : "—"),
        td("num", plain(row.pending))));
    });
    add(box, t.wrap);
  }

  function renderDraft() {
    var sec = card("初稿账", "实际出票 vs 机器初稿 vs 空仓（gym 回放）");
    var box = put(sec, el("div", null));
    add(box, el("p", "lg-wait", "回放中…"));
    function load() {
      fetch("/api/ledger/" + encodeURIComponent(month) + "/draft", { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
        .then(function (data) { renderDraftBody(box, data); })
        .catch(function (e) { renderDraftBody(box, { _error: String(e && e.message || e) }); });
    }
    // 页面画完就在后台取（回放约 0.2 s，进程内缓存）：反事实线在页顶的净值图上，不能等滚到这张卡
    setTimeout(load, 0);
    return sec;
  }

  // ---- 选择账 ----
  function formCell(col) {
    var box = el("div", "lg-form");
    if (!col || col.shape === null || col.shape === undefined) {
      add(box, el("span", "lg-muted", "无落盘 / 无法重建"));
      return box;
    }
    if (col.flat) {
      add(box, el("span", null, "空仓（" + col.shape + " " + yuan(col.form_stake) + "×0）"),
        el("span", "lg-small", "P " + pct(col.p)));
      return box;
    }
    var src = col.source && col.source !== "draft.json" ? "·" + col.source : "";
    add(box, el("span", null, col.shape + src + " ×" + plain(col.k) + " · " + yuan(col.stake)),
      el("span", "lg-small", "P " + pct(col.p) + " · 中 " + (col.payout === null || col.payout === undefined ? "待" : plain(col.hits || 0))));
    return box;
  }
  function formNet(col) {
    if (!col || col.shape === null || col.shape === undefined) return el("span", "lg-muted", "—");
    if (col.net === null || col.net === undefined) return el("span", "lg-muted", "待");
    return money(null, col.net);
  }
  function renderChoices(v) {
    var rows = (v.choices && v.choices.rows) || [];
    var sec = card("选择账", "同钱三列：Jun 实票 / 机器默认 / 丢光 C 档形");
    if (!rows.length) { add(sec, el("p", "lg-note", "本月没有足彩期次。")); return sec; }
    var t = scrollTable("lg-choices", [["期"], ["Jun 票形"], ["净", "num"], ["机器默认"], ["净", "num"],
      ["丢光 C 档形"], ["净", "num"]]);
    rows.forEach(function (r) {
      var j = r.jun || {};
      var jun = el("div", "lg-form");
      if (!j.n) add(jun, el("span", "lg-muted", "空仓"));
      else {
        add(jun, el("span", null, j.n + " 张 · " + yuan(j.stake)),
          el("span", "lg-small", "P 和 " + (isNum(j.p_sum) ? j.p_sum.toFixed(2) : "—") +
            (j.p_missing ? "（" + j.p_missing + " 张无 P）" : "") + " · 中 " + (j.pending ? "待" : plain(j.hits))));
      }
      var junNet = !j.n ? el("span", "lg-muted", "0") : (j.net === null || j.net === undefined)
        ? el("span", "lg-muted", "待（" + j.pending + " 张）") : money(null, j.net);
      add(t.tbody, add(el("tr"),
        td(null, link("/issue/" + encodeURIComponent(r.issue), null, r.issue)),
        td(null, jun), td("num strong", junNet),
        td(null, formCell(r.machine)), td("num strong", formNet(r.machine)),
        td(null, formCell(r.drop_c)), td("num strong", formNet(r.drop_c))));
    });
    add(sec, t.wrap);
    add(sec, el("p", "lg-note", "机器默认写了「空仓」的期按 0 计（括号里是当期的初稿形）；「待」＝赛果或官方奖金未到。"));
    return sec;
  }

  // ---- 桥后改动账 ----
  function renderBridges(v) {
    var bridges = v.bridges || [];
    var sec = card("桥后改动账", "B1（走桥时的票）与实票的差异格");
    if (!bridges.length) { add(sec, el("p", "lg-note", "本月没有走过桥的期。")); return sec; }
    var list = put(sec, el("div", "lg-bridges"));
    bridges.forEach(function (b) {
      var box = put(list, el("div", "lg-bridge"));
      add(box, add(el("div", "lg-bridge-head"),
        link("/issue/" + encodeURIComponent(b.issue), null, b.issue),
        el("span", "lg-note", "走桥 " + String(b.at || "—").replace("T", " ").slice(0, 16))));
      var faces = put(box, el("div", "lg-faces"));
      add(faces, el("span", "lg-muted", "B1"));
      Object.keys(b.b1_faces || {}).sort(function (a, c) { return Number(a) - Number(c); }).forEach(function (no) {
        add(faces, el("span", null, no + "·" + b.b1_faces[no]));
      });
      var rd = b.readout || {};
      add(box, el("p", "lg-note", "桥上差异 " + plain(rd.diffs) + " 格 · 理由指到矩阵行 " + plain(rd.matrix) +
        " · 矩阵外 " + plain(rd.outside) + " · 空 " + plain(rd.blank)));
      var real = b.real || [];
      if (!real.length) add(box, el("p", "lg-note", "实票未登记（同渠道）"));
      real.forEach(function (rs) {
        var changed = rs.changed || [];
        add(box, add(el("p", "lg-diff"), el("span", "mono", rs.slip_id),
          el("span", null, changed.length ? " 改了 " + changed.length + " 格：" : " 与 B1 无差异"),
          changed.length ? el("span", "mono", changed.join(" ")) : null,
          rs.alive_unknown && changed.length ? el("span", "lg-muted", "（活 / 死待 retro 按开奖串填）") : null));
      });
    });
    return sec;
  }

  // ---- 组装 ----
  function render(v) {
    Array.prototype.slice.call(root.children).forEach(function (c) {
      if (!c.classList.contains("ledger-head") && c !== errBox) c.remove();
    });
    chartBox = null; legendBox = null; draftCurve = null;
    renderMonths(v.months);
    renderKpis(v).forEach(function (n) { add(root, n); });
    add(root, renderCurve(v));
    add(root, add(el("div", "lg-cols"),
      add(el("div", "lg-col-main"), renderIssues(v), renderJczq(v)),
      add(el("div", "lg-col-side"), renderReasons(v))));
    add(root, renderDraft());
    add(root, renderChoices(v));
    add(root, renderBridges(v));
    if (v.curve) drawChart(v.curve);
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (view && view.curve && chartBox && Math.abs((chartBox.clientWidth || 0) - chartWidth) > 8) drawChart(view.curve);
    }, 150);
  });

  renderMonths([month]);
  fetch("/api/ledger/" + encodeURIComponent(month), { headers: { Accept: "application/json" } })
    .then(function (r) {
      return r.ok ? r.json() : r.text().then(function (t) { throw new Error("HTTP " + r.status + " " + t.slice(0, 200)); });
    })
    .then(function (v) {
      view = v;
      errors = (v.errors || []).slice();
      showErrors();
      render(v);
    })
    .catch(function (e) {
      errors = ["账房接口读取失败：" + String(e && e.message || e)];
      showErrors();
    });
})();
