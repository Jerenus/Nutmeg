// Workshop UI — 判读工作台 前端
// poll /events 增量拉取 · 点议程设线程锚 · #send POST /thread ·
// 卡片按钮 POST /action/* (成功移卡 / 400 翻"被拒"态显示逐字 errors)。
(function () {
  "use strict";

  var topbar = document.querySelector(".topbar");
  if (!topbar) return; // 附属只读页无工作台
  var DATE = topbar.getAttribute("data-date");

  var flowEl = document.getElementById("flow");
  var stageEl = document.getElementById("stage");
  var verdictEl = document.getElementById("verdict");
  var turnsEl = document.getElementById("turns");
  var anchorEl = document.getElementById("thread-anchor");
  var askEl = document.getElementById("ask");
  var sendEl = document.getElementById("send");
  var sseEl = document.getElementById("sse");
  var vcountEl = document.getElementById("vcount");
  var mvBadge = document.getElementById("mv-badge");
  var flowCount = document.getElementById("flow-count");

  var cursor = 0;
  var allEvents = [];
  var selectedObj = null;
  var judgments = {}; // obj_id -> 已落库判读 payload(桥接投影,只读)
  var dayRegime = null; // 日级盘面诊断(只攒样本,不进决策)

  function pct(x) { return Math.max(0, Math.round((Number(x) || 0) * 100)); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }

  // ---- attention flow ------------------------------------------------
  function renderAttention(e) {
    if (flowEl.querySelector('.fitem[data-obj="' + e.id + '"]')) return;
    var empty = flowEl.querySelector(".empty");
    if (empty) empty.remove();
    var item = el("article", "fitem");
    item.setAttribute("data-obj", e.id || "");
    item.appendChild(el("div", "m", e.match || "(未命名)"));
    var why = el("div", "why");
    if (e.group) why.appendChild(el("span", "tagmini", e.group));
    if (e.note) why.appendChild(document.createTextNode(e.note));
    item.appendChild(why);
    item.addEventListener("click", function () { selectObj(e.id, e.match); });
    flowEl.appendChild(item);
    if (flowCount) flowCount.textContent = flowEl.querySelectorAll(".fitem").length;
  }

  // ---- mini prior→belief track --------------------------------------
  function miniTrack(dist, isBelief) {
    var t = el("div", "mini-track" + (isBelief ? " bel" : ""));
    ["home", "draw", "away"].forEach(function (k, i) {
      var s = el("span", "s " + "hda"[i], String(pct(dist[k])));
      s.style.flex = pct(dist[k]) || 1;
      t.appendChild(s);
    });
    return t;
  }

  // belief 轨:只把「真正移动的那一档」染朱砂(诚实读数,跟市场则无朱砂)
  function beliefTrack(prior, belief) {
    var t = el("div", "mini-track");
    ["home", "draw", "away"].forEach(function (k, i) {
      var shifted = Math.abs((belief[k] || 0) - (prior[k] || 0)) > 0.005;
      var s = el("span", "s " + (shifted ? "shift" : "hda"[i]), String(pct(belief[k])));
      s.style.flex = pct(belief[k]) || 1;
      t.appendChild(s);
    });
    return t;
  }

  // ---- verdict: Read draft card -------------------------------------
  function renderReadDraft(e) {
    if (verdictEl.querySelector('[data-card="' + e.id + '"]')) return;
    var r = e.payload || {};
    var card = el("article", "acard");
    card.setAttribute("data-card", e.id || "");
    var inner = el("div", "inner");
    var type = el("div", "actype", "Read 草稿");
    type.appendChild(el("span", "kind", "typed action"));
    inner.appendChild(type);
    inner.appendChild(el("div", "acmatch", r.match_id || e.match || ""));
    inner.appendChild(el("div", "acmarket",
      "market = " + (r.market || "had") + " · judge = " + (r.judge || "claude")));
    if (r.prior && r.belief) {
      var md = el("div", "mini-dev");
      var pt = miniTrack(r.prior, false); pt.style.marginBottom = "4px";
      md.appendChild(pt);
      md.appendChild(miniTrack(r.belief, true));
      inner.appendChild(md);
    }
    var f = (r.factors || [])[0];
    if (f) {
      var meta = el("div", "acmeta");
      var row = el("div", "row");
      row.appendChild(el("span", "l", "因子"));
      var v = el("span", "v");
      v.appendChild(el("span", "fchip", f.factor_id || "?"));
      v.appendChild(document.createTextNode(
        " " + (f.direction || "") + " +" + (f.weight_pp || 0) + "pp"));
      row.appendChild(v);
      meta.appendChild(row);
      inner.appendChild(meta);
    }
    inner.appendChild(el("div", "gate", "批准 → ingest_reads() 同一校验入库"));
    var btns = el("div", "acbtns");
    var reject = el("button", "btn", "拒绝");
    var approve = el("button", "btn primary", "批准入库");
    reject.addEventListener("click", function () {
      post("/action/reject-read", { obj_id: e.id, date: DATE, reason: "人工拒绝" })
        .then(function () { removeCard(card); });
    });
    approve.addEventListener("click", function () {
      post("/action/approve-read", { obj_id: e.id, read: r }).then(function (res) {
        if (res && res.ok) { removeCard(card); }
        else { rejectCard(card, (res && res.errors) || ["校验失败"]); }
      });
    });
    btns.appendChild(reject); btns.appendChild(approve);
    inner.appendChild(btns);
    card.appendChild(inner);
    verdictEl.appendChild(card);
    refreshVcount();
  }

  // ---- verdict: leg proposal card -----------------------------------
  function renderLegsProposal(e) {
    if (verdictEl.querySelector('[data-card="' + e.id + '"]')) return;
    var leg = e.payload || {};
    var card = el("article", "acard pine");
    card.setAttribute("data-card", e.id || "");
    var inner = el("div", "inner");
    var type = el("div", "actype", "legs 提案");
    type.appendChild(el("span", "kind", "typed action"));
    inner.appendChild(type);
    inner.appendChild(el("div", "acmatch",
      (leg.match_id || "") + " " + (leg.selection || "")));
    inner.appendChild(el("div", "acmarket",
      "bucket = " + (leg.bucket || "main") + " · @" + (leg.odds || "?")));
    inner.appendChild(el("div", "gate", "确认 → 预算闸 + schema → legs.json"));
    var btns = el("div", "acbtns");
    var remove = el("button", "btn", "移除");
    var confirm = el("button", "btn pine", "确认出票");
    remove.addEventListener("click", function () { removeCard(card); });
    confirm.addEventListener("click", function () {
      post("/action/confirm-legs", { date: DATE, legs: [leg] }).then(function (res) {
        if (res && res.ok) { removeCard(card); }
      });
    });
    btns.appendChild(remove); btns.appendChild(confirm);
    inner.appendChild(btns);
    card.appendChild(inner);
    verdictEl.appendChild(card);
    refreshVcount();
  }

  // ---- verdict: 我的方案（已登记实票，只读；没入账=没打，登记簿里没有就不显示）----
  var FACE_ZH = { "3": "胜", "1": "平", "0": "负" };
  function renderSlip(e) {
    if (verdictEl.querySelector('[data-card="' + e.id + '"]')) return;
    var p = e.payload || {};
    var card = el("article", "acard pine slip");
    card.setAttribute("data-card", e.id || "");
    var inner = el("div", "inner");
    var type = el("div", "actype", "我的方案 · 已出票");
    type.appendChild(el("span", "kind", (p.channel || "") + (p.purchased === false ? " · 试玩" : "")));
    inner.appendChild(type);
    inner.appendChild(el("div", "acmatch", p.slip_id || ""));
    var ph = (p.hit_probability == null) ? "—" : (p.hit_probability * 100).toFixed(2) + "%";
    inner.appendChild(el("div", "acmarket",
      (p.notes || 0) + " 注 × " + (p.multiplier || 1) + " = ¥" + (p.stake_yuan || 0) +
      " · P(全对) " + ph + (p.scheme_no ? "" : " · ⚠️方案号待补")));
    var meta = el("div", "acmeta");
    (p.legs || []).forEach(function (lg) {
      var row = el("div", "row");
      row.appendChild(el("span", "l", String(lg.key || "")));
      var v = el("span", "v");
      var faces = (lg.market === "had" && lg.selections)
        ? lg.selections.map(function (sel) {
            return FACE_ZH[{ home: "3", draw: "1", away: "0" }[sel] || sel] || sel; }).join("/")
        : (lg.market || "") + (lg.line != null ? "[" + lg.line + "]" : "") + " " + (lg.selections || []).join("/");
      v.appendChild(el("span", "fchip", faces));
      v.appendChild(document.createTextNode(" " + (lg.name || "") +
        (lg.coverage != null ? " · 盖 " + (lg.coverage * 100).toFixed(1) + "%" : "")));
      row.appendChild(v); meta.appendChild(row);
    });
    inner.appendChild(meta);
    card.appendChild(inner);
    verdictEl.appendChild(card);
    refreshVcount();
  }

  function removeCard(card) { card.remove(); refreshVcount(); }
  function rejectCard(card, errors) {
    card.classList.add("rejected");
    var old = card.querySelector(".reason");
    if (old) old.remove();
    card.querySelector(".inner").appendChild(
      el("div", "reason", "被拒：" + errors.join("；")));
  }
  function refreshVcount() {
    var n = verdictEl.querySelectorAll(".acard:not(.slip)").length;  // 我的方案不算「待裁决」
    if (vcountEl) vcountEl.textContent = n;
    if (mvBadge) mvBadge.textContent = n ? String(n) : "";
  }

  // ---- center stage: view_block -------------------------------------
  function renderViewBlock(e) {
    var crumb = stageEl.querySelector(".crumb");
    if (crumb && crumb.textContent.indexOf("选择议程项") >= 0) crumb.remove();
    var blk = el("div", "vblock");
    blk.appendChild(el("div", "vbhead", e.block || "视图块"));
    var body = el("div", "profile-line");
    body.textContent = typeof e.payload === "string"
      ? e.payload : JSON.stringify(e.payload || {});
    blk.appendChild(body);
    stageEl.appendChild(blk);
  }

  // ---- 进球轴读数器(ttg total_0..7 分布,模态高亮) -----------------------
  var GOALS = ["total_0", "total_1", "total_2", "total_3",
    "total_4", "total_5", "total_6", "total_7"];
  function goalsAxis(ttg) {
    var dist = ttg.belief || {};
    var modal = GOALS.reduce(function (a, k) {
      return (dist[k] || 0) > (dist[a] || 0) ? k : a;
    }, GOALS[0]);
    var wrap = el("div", "vblock");
    var head = el("div", "vbhead", "进球轴 · total 分布");
    head.appendChild(el("span", "tick", "conf" + (ttg.confidence || "?")));
    wrap.appendChild(head);
    var bar = el("div", "mini-track");
    GOALS.forEach(function (k) {
      var p = pct(dist[k]);
      if (!p) return;
      var s = el("span", "s " + (k === modal ? "h" : "d"),
        k.slice(6) + "球 " + p);
      s.style.flex = p;
      bar.appendChild(s);
    });
    wrap.appendChild(bar);
    wrap.appendChild(el("div", "profile-line",
      "模态 " + modal.slice(6) + " 球（" + pct(dist[modal]) + "%）· " +
      (ttg.note || "")));
    return wrap;
  }

  // ---- 舞台默认态:今日盘面诊断(day-regime,只攒样本不进决策) ---------------
  function renderDayRegime() {
    stageEl.innerHTML = "";
    if (!dayRegime) {
      stageEl.appendChild(el("div", "crumb", "选择议程项查看盘口 / 画像 / 读数器"));
      return;
    }
    var r = dayRegime;
    var blk = el("div", "vblock");
    blk.appendChild(el("div", "vbhead", "今日盘面诊断 · day-regime"));
    var grid = el("div", "profile-line");
    grid.innerHTML =
      "在售 <b>" + (r.n_matches || 0) + "</b> 场 · 重热门 <b>" +
      (r.n_heavy_fav || 0) + "</b> · 抛硬币 <b>" + (r.n_tossup || 0) +
      "</b> · 均期望进球 <b>" +
      (r.mean_expected_goals != null ? r.mean_expected_goals.toFixed(2) : "—") +
      "</b>";
    blk.appendChild(grid);
    blk.appendChild(el("div", "gate",
      "只攒样本，不进决策（n<30 反积累免疫）· 不得引作判读理由"));
    stageEl.appendChild(blk);
    stageEl.appendChild(el("div", "crumb", "← 点左侧议程项查看单场判读读数器"));
  }

  // ---- center stage: 已落库判读(桥接 judgment,只读,含偏移读数器) --------
  function renderStageJudgment(objId) {
    var j = judgments[objId];
    stageEl.innerHTML = "";
    if (!j) { renderDayRegime(); return; }
    var crumb = el("div", "crumb");
    var h = el("span", "h serif", j.match || objId);
    crumb.appendChild(h);
    if (j.competition) {
      crumb.appendChild(el("span", "sep", "·"));
      crumb.appendChild(el("span", null, j.competition));
    }
    crumb.appendChild(el("span", "sep", "·"));
    crumb.appendChild(el("span", "meta mono", (j.market || "had") + " · conf" + (j.confidence || "?")));
    stageEl.appendChild(crumb);

    var blk = el("div", "vblock");
    blk.appendChild(el("div", "vbhead", "判读读数 · prior → belief（已入库）"));
    if (j.prior && j.belief) {
      var pt = miniTrack(j.prior, false); pt.style.marginBottom = "5px";
      blk.appendChild(pt);
      blk.appendChild(beliefTrack(j.prior, j.belief));
    }
    var f = (j.factors || [])[0];
    var delta = el("div", "acmeta");
    var drow = el("div", "row");
    drow.appendChild(el("span", "l", f ? "偏移" : "判读"));
    var dv = el("span", "v");
    if (f) {
      dv.appendChild(el("span", "fchip", f.factor_id || "?"));
      dv.appendChild(document.createTextNode(
        " " + (f.direction || "") + " +" + (f.weight_pp || 0) + "pp"));
    } else {
      dv.appendChild(document.createTextNode("跟市场（belief = prior）"));
    }
    drow.appendChild(dv); delta.appendChild(drow);
    blk.appendChild(delta);
    stageEl.appendChild(blk);

    if (j.note) {
      var nb = el("div", "vblock");
      nb.appendChild(el("div", "vbhead", "理由"));
      nb.appendChild(el("div", "profile-line", j.note));
      stageEl.appendChild(nb);
    }
    if (j.ttg) stageEl.appendChild(goalsAxis(j.ttg)); // 进球轴读数器(约束 h)
  }

  // ---- anchored thread ----------------------------------------------
  function selectObj(objId, label) {
    selectedObj = objId;
    if (anchorEl) anchorEl.textContent = label || objId || "未选中判断";
    flowEl.querySelectorAll(".fitem").forEach(function (n) {
      n.classList.toggle("sel", n.getAttribute("data-obj") === objId);
    });
    renderStageJudgment(objId);
    renderTurns();
  }
  function renderTurns() {
    turnsEl.innerHTML = "";
    allEvents.filter(function (e) {
      return e.obj_id === selectedObj &&
        (e.kind === "user_message" || e.kind === "agent_reply");
    }).forEach(appendTurn);
  }
  function appendTurn(e) {
    var you = e.kind === "user_message";
    var turn = el("div", "turn " + (you ? "you" : "ai"));
    turn.appendChild(el("span", "who", you ? "你" : "判"));
    turn.appendChild(el("span", "txt", e.text || ""));
    turnsEl.appendChild(turn);
    turnsEl.scrollTop = turnsEl.scrollHeight;
  }

  function sendAsk() {
    var text = (askEl.value || "").trim();
    if (!text || !selectedObj) return;
    askEl.value = "";
    appendTurn({ kind: "user_message", obj_id: selectedObj, text: text });
    post("/thread", { date: DATE, obj_id: selectedObj, text: text });
  }
  if (sendEl) sendEl.addEventListener("click", sendAsk);
  if (askEl) askEl.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); sendAsk(); }
  });

  // ---- mobile tabs ---------------------------------------------------
  document.querySelectorAll(".mtab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".mtab").forEach(function (t) { t.classList.remove("on"); });
      tab.classList.add("on");
      var col = tab.getAttribute("data-col");
      document.querySelectorAll(".wbbody .col").forEach(function (c) {
        c.classList.toggle("active", c.classList.contains(col));
      });
    });
  });

  // ---- SOP 任务栏(阶段一):同一条命令,从页面按 -----------------------------
  var sopSteps = document.getElementById("sop-steps");
  var sopIssue = document.getElementById("sop-issue");
  function loadSopSteps() {
    var issue = ((sopIssue && sopIssue.value) || "").trim();
    if (!sopSteps || !issue) return;
    fetch("/api/sop-steps?issue=" + encodeURIComponent(issue) +
          "&date=" + encodeURIComponent(DATE))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        sopSteps.innerHTML = "";
        (d.steps || []).forEach(function (s) {
          var b = el("button", "btn sopstep" + (s.done === true ? " done" : s.done === null ? " nostate" : ""), s.label);
          b.setAttribute("data-step", s.step_id);
          b.addEventListener("click", function () {
            b.disabled = true; b.classList.add("running");
            post("/action/run-task", {
              step_id: s.step_id, issue: issue, date: DATE,
              legs_file: s.needs_legs ? window.prompt("legs 文件路径") : null,
            }).then(function () {
              b.disabled = false; b.classList.remove("running"); loadSopSteps();
            });
          });
          sopSteps.appendChild(b);
        });
      })
      .catch(function () { /* 任务栏拉不到不影响判读三栏 */ });
  }
  if (sopIssue) { sopIssue.addEventListener("change", loadSopSteps); loadSopSteps(); }

  function renderTaskEvent(e, state) {
    var id = "task-" + (e.step_id || "");
    var old = stageEl.querySelector('[data-task="' + id + '"]');
    if (old) old.remove();
    var crumb = stageEl.querySelector(".crumb");
    if (crumb && crumb.textContent.indexOf("选择议程项") >= 0) crumb.remove();
    var blk = el("div", "vblock task " + state);
    blk.setAttribute("data-task", id);
    blk.appendChild(el("div", "vbhead",
      (e.label || e.step_id || "任务") + " · " +
      (state === "running" ? "运行中"
        : state === "done" ? "完成 exit=" + e.exit_code
          : "失败 exit=" + e.exit_code)));
    if (e.argv) blk.appendChild(el("div", "mono small", "$ nutmeg " + e.argv.join(" ")));
    if (e.text) { var pre = el("pre", "tasklog"); pre.textContent = e.text; blk.appendChild(pre); }
    stageEl.appendChild(blk);
  }

  // 舞台被 renderDayRegime 清空后重放任务卡(任务不属于某个 obj,不随选中切换)
  function replayTaskEvents() {
    allEvents.forEach(function (e) {
      if (e.kind === "task_started") renderTaskEvent(e, "running");
      else if (e.kind === "task_done") renderTaskEvent(e, "done");
      else if (e.kind === "task_failed") renderTaskEvent(e, "failed");
    });
  }

  // ---- event dispatch + polling -------------------------------------
  function ingest(e) {
    allEvents.push(e);
    if (e.seq && e.seq > cursor) cursor = e.seq;
    switch (e.kind) {
      case "attention": renderAttention(e); break;
      case "judgment": judgments[e.obj_id] = e.payload || {}; break;
      case "day_regime": dayRegime = e.payload || null; break;
      case "read_draft": renderReadDraft(e); break;
      case "legs_proposal": renderLegsProposal(e); break;
      case "slip": renderSlip(e); break;
      case "view_block": renderViewBlock(e); break;
      case "task_started": renderTaskEvent(e, "running"); break;
      case "task_done": renderTaskEvent(e, "done"); break;
      case "task_failed": renderTaskEvent(e, "failed"); break;
      case "agent_reply":
      case "user_message":
        if (e.obj_id === selectedObj) appendTurn(e);
        break;
    }
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .catch(function () { return {}; });
  }

  function sseOn(ok) {
    if (!sseEl) return;
    sseEl.classList.toggle("stale", !ok);
    sseEl.lastChild.textContent = ok ? "实时" : "断连";
  }

  function poll() {
    fetch("/events?date=" + encodeURIComponent(DATE) + "&since=" + cursor)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.events || []).forEach(ingest);
        if (typeof data.cursor === "number") cursor = data.cursor;
        sseOn(true);
      })
      .catch(function () { sseOn(false); });
  }

  function boot() {
    fetch("/api/workbench?date=" + encodeURIComponent(DATE))
      .then(function (r) { return r.json(); })
      .then(function (state) {
        flowEl.innerHTML = "";
        (state.events || []).forEach(ingest);
        if (!flowEl.querySelector(".fitem")) {
          flowEl.appendChild(el("p", "empty", "今日 agent 尚未开工——在终端说「今天的方案」。"));
        }
        if (!selectedObj) { renderDayRegime(); replayTaskEvents(); } // 未选中→舞台显今日盘面
      })
      .catch(function () { /* 保留服务端渲染的降级视图 */ })
      .finally(function () { setInterval(poll, 2000); });
  }

  boot();
})();
