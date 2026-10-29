// static/decision/lab.js —— 实验室页（2026-10-28 产品形态第 8 阶段 Task 8.2，画布 Lab.dc.html）。
// 动态数全来自 /api/lab（Task 8.1）：实验看板 board.live / board.settled（实证标签与 `rsi columns`
// 同一实现）、研究层消费量 cites、运维 ops。页面不判、不算：标签、n、n_min 照印，进度条只是
// n / n_min 的排版。写死的两块（否决卡、gym 卡）每块带出处行，文字只抄出处里有的。
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
  function link(href, cls, text) { var a = el("a", cls, text); a.href = href; return a; }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function bold(text) { return el("b", null, text); }

  // 北京日期（只用来拼 /runs/<今天> 的链接；服务端 /runs 也按北京日）
  function bjToday() { return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10); }

  // claim 首句：按 。/； 切第一段，超 60 字截断；全文留在 title
  function firstSentence(claim) {
    var s = String(claim || "").split(/[。；]/)[0].trim();
    return s.length > 60 ? s.slice(0, 60) + "…" : s;
  }

  // 标签只换颜色，不改字
  function labelClass(label) {
    var s = String(label || "");
    if (s.indexOf("实证") === 0) return "lab-label lab-good";
    if (s.indexOf("已证伪") === 0) return "lab-label lab-bad";
    if (s.indexOf("测不出") === 0 || s.indexOf("退役") === 0) return "lab-label lab-flat";
    return "lab-label";
  }

  // ---- 外壳 ----
  var root = document.getElementById("lab");
  if (!root) return;
  var errBox = document.getElementById("errors");
  var head = root.querySelector(".lab-head");

  function showErrors(list) {
    clear(errBox);
    list.forEach(function (e) { add(errBox, el("span", null, e)); });
    errBox.hidden = list.length === 0;
  }

  function card(title, tag) {
    var sec = el("section", "lab-card");
    var h = add(el("div", "lab-card-head"), el("h2", null, title));
    if (tag) add(h, el("span", "lab-tag", tag));
    return add(sec, h);
  }

  // ---- 1. 哪条规则有资格拦你（写死；出处见每张卡与卡组下的出处行） ----
  var VETOES = [
    { kind: "实证否决", title: "V1 期望回报率 < 0.5",
      body: "E[派奖]/投入 < 0.5；足彩用奖金模型。实证：403 天回放帽内 max-P 竞彩 −20%、任九 −58%，CI 不含 0；「中了也亏」的双选×双选。" },
    { kind: "实证否决", title: "V2 共享裸单",
      body: "与同日/同期/跨渠道已购票共享裸单＝假分散。实证：26122 四票联死 73.8%、26133 两票联死 ≈60%。" },
    { kind: "宪法纪律", title: "止损 · 刹车档 · 日帽", discipline: true,
      body: "不是实证规则，是你签过的线：月度止损 −\u2060¥8,000、连续两期全灭次期减半、日总帽 ¥2,000。预审 ⛔，登记不受限。" },
  ];
  function renderVetoes() {
    var sec = el("section", "lab-section");
    var grid = el("div", "lab-vetoes");
    VETOES.forEach(function (v) {
      add(grid, add(el("div", "lab-veto" + (v.discipline ? " lab-discipline" : "")),
        el("span", "lab-veto-kind", v.kind), el("span", "lab-veto-title", v.title),
        el("span", "lab-veto-body", v.body)));
    });
    return add(sec, el("h2", null, "哪条规则有资格拦你"), grid,
      el("p", "lab-src", "出处：docs/sop/RULEBOOK.md「八、审票否决表」V1 / V2 / 止损 / 日帽行（与「〇、规则实证表」同纪律）；宪法 §4「注金与刹车」。"));
  }

  // ---- 2. live 表 ----
  function progress(row) {
    var box = el("div", "lab-prog");
    var n = isNum(row.n) ? row.n : 0;
    if (isNum(row.n_min) && row.n_min > 0) {
      var bar = el("div", "lab-bar");
      var fill = el("span");
      fill.style.width = Math.max(0, Math.min(100, n / row.n_min * 100)).toFixed(1) + "%";
      add(bar, fill);
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", "样本 " + n + " / " + row.n_min);
      add(box, bar, el("span", "lab-n", n + " / " + row.n_min));
    } else {
      add(box, el("span", "lab-n", "n=" + n));
    }
    return box;
  }
  function cell(cls, key, content) {
    var c = el("div", cls);
    if (key) add(c, el("span", "lab-cell-k", key));
    if (content) add(c, content);
    return c;
  }
  function renderLive(live) {
    var sec = card("决策表上的列 · 离判决还有多远", "全部只展示");
    if (!live.length) {
      add(sec, el("p", "lab-wait", "没有在跑的实验（或内核读不出，见页顶错误）。"));
    } else {
      var grid = el("div", "lab-grid");
      add(grid, add(el("div", "lab-row lab-row-head"),
        el("span", null, "编号"), el("span", null, "它量什么"), el("span", null, "样本 n / n_min"),
        el("span", null, "状态"), el("span", null, "在表上是哪一列")));
      live.forEach(function (r) {
        var what = el("span", "lab-what", firstSentence(r.claim));
        what.title = String(r.claim || "");
        var cols = (r.columns || []).length ? r.columns.join(" · ") : "—";
        add(grid, add(el("div", "lab-row"),
          cell("lab-c-id", null, link("/observe/exp/" + encodeURIComponent(r.exp_id), "lab-id", r.exp_id)),
          cell("lab-c-what", null, what),
          cell("lab-c-n", null, progress(r)),
          cell("lab-c-label", null, el("span", labelClass(r.label), r.label || "—")),
          cell("lab-c-col", "在表上：", el("span", "lab-col", cols))));
      });
      add(sec, grid);
    }
    return add(sec, el("p", "lab-note",
      "一列只有过了登记的 bound 才有资格变成否决；在那之前，它在决策表上永远是虚线框。"),
      el("p", "lab-src", "数据：/api/lab · 与 nutmeg rsi status / rsi columns 同一份读法。"));
  }

  // ---- 3. gym 结论卡（写死；数字逐个出自两份证据） ----
  function renderGym() {
    var sec = el("section", "lab-gym");
    var nums = add(el("div", "lab-gym-nums"),
      add(el("div", "lab-gym-num"), el("span", "lab-gym-big", "−20%"),
        el("span", "lab-gym-k", "竞彩帽内 max-P，403 天，CI 不含 0")),
      add(el("div", "lab-gym-num"), el("span", "lab-gym-big", "≈ 市场"),
        el("span", "lab-gym-k", "换 belief 没用：终盘与市场 belief 的 max-P 账几乎重合")));
    return add(sec, el("span", "lab-gym-kicker", "回放 gym · 403 天"),
      el("span", "lab-gym-head", "没有一条策略族在全跨度上 ROI 为正、CI 不含 0"),
      nums,
      el("p", "lab-gym-foot", "这是「机器不出票、只审票」的依据，常驻在这里，不藏在 evidence 目录。"),
      el("p", "lab-src", "出处：docs/superpowers/evidence/2026-10-01-history-expansion.md（全跨度表、结论 1 / 5）；2026-10-01-replay-gym.md（结论 3）。"));
  }

  // ---- 4. 已判决 · 退役 ----
  function renderSettled(settled) {
    var sec = card("已判决 · 退役");
    if (!settled.length) return add(sec, el("p", "lab-wait", "还没有已判决或退役的实验。"));
    var judged = settled.filter(function (r) { return String(r.label || "").indexOf("退役") !== 0; });
    var retired = settled.filter(function (r) { return String(r.label || "").indexOf("退役") === 0; });
    function rows(target, group) {
      group.forEach(function (r) {
        var claim = el("span", "lab-settled-claim", firstSentence(r.claim));
        claim.title = String(r.claim || "");
        add(target, add(el("div", "lab-settled-row"),
          link("/observe/exp/" + encodeURIComponent(r.exp_id), "lab-id", r.exp_id),
          el("span", labelClass(r.label), r.label || "—"), claim));
      });
    }
    var list = el("div", "lab-settled");
    if (judged.length) {
      add(list, el("div", "lab-settled-group", "已判决 · " + judged.length));
      rows(list, judged);
    }
    // 退役只会越攒越多、也不再产生读数：默认折起，已判决常开
    if (retired.length) {
      var fold = add(el("details", "lab-settled-fold"),
        el("summary", "lab-settled-group", "退役 · " + retired.length));
      rows(fold, retired);
      add(list, fold);
    }
    return add(sec, list);
  }

  // ---- 5. 研究层消费量 ----
  function renderCites(c) {
    var sec = card("研究层消费量");
    if (!c) return add(sec, el("p", "lab-wait", "读不出（见页顶错误）。"));
    add(sec, el("span", "lab-big", "[" + c.matrix + " / " + c.diffs + "]"));
    if (!c.diffs) add(sec, el("p", "lab-note", "还没有桥后改动。"));
    add(sec, add(el("div", "lab-counts"),
      add(el("span"), document.createTextNode("走过桥 "), bold(String(c.issues)), document.createTextNode(" 期")),
      add(el("span"), document.createTextNode("矩阵外 "), bold(String(c.outside))),
      add(el("span"), document.createTextNode("空白 "), bold(String(c.blank)))));
    return add(sec, el("p", "lab-note",
      "桥后改动里，理由引用了研究行（§1c 反证矩阵）的次数 / 改动总数。引用不到的记「矩阵外」，没写理由的记「空白」。研究做了不算成果，被用了才算。"));
  }

  // ---- 6. 运维一行 ----
  function renderOps(o) {
    var sec = el("section", "lab-ops");
    var bad = !o || (o.alarms || []).length > 0 || o.failed_runs > 0;
    var text = el("span", "lab-ops-text");
    if (!o) {
      add(text, document.createTextNode("读不出（见页顶错误）"));
    } else {
      add(text, document.createTextNode("launchd "), bold(String(o.jobs)), document.createTextNode(" 个作业 · 告警 "));
      if ((o.alarms || []).length) add(text, el("span", "lab-alarm", o.alarms.length + "：" + o.alarms.join("、")));
      else add(text, bold("0"));
      add(text, document.createTextNode(" · 今天失败段 "),
        o.failed_runs > 0 ? el("span", "lab-alarm", String(o.failed_runs)) : bold("0"));
    }
    var dot = el("span", "lab-dot" + (bad ? " lab-dot-bad" : ""));
    dot.setAttribute("aria-hidden", "true");
    return add(sec, dot, el("span", "lab-ops-title", "运维"), text,
      link("/runs/" + bjToday(), "lab-btn", "看今天的 runs.jsonl"));
  }

  function render(v) {
    var board = v.board || {};
    var trio = add(el("div", "lab-trio"), renderGym(), renderSettled(board.settled || []), renderCites(v.cites));
    add(root, renderVetoes(), renderLive(board.live || []), trio, renderOps(v.ops));
  }

  add(head, el("span", "lab-kicker", "数据：/api/lab（rsi status · rsi columns · 桥记录 · launchd / runs.jsonl）"));
  fetch("/api/lab", { headers: { Accept: "application/json" } })
    .then(function (r) {
      return r.ok ? r.json() : r.text().then(function (t) { throw new Error("HTTP " + r.status + " " + t.slice(0, 200)); });
    })
    .then(function (v) {
      showErrors((v.errors || []).slice());
      render(v);
    })
    .catch(function (e) {
      showErrors(["实验室接口读取失败：" + String(e && e.message || e)]);
    });
})();
