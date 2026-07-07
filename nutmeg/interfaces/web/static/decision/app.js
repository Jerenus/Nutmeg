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

  function removeCard(card) { card.remove(); refreshVcount(); }
  function rejectCard(card, errors) {
    card.classList.add("rejected");
    var old = card.querySelector(".reason");
    if (old) old.remove();
    card.querySelector(".inner").appendChild(
      el("div", "reason", "被拒：" + errors.join("；")));
  }
  function refreshVcount() {
    var n = verdictEl.querySelectorAll(".acard").length;
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

  // ---- center stage: 已落库判读(桥接 judgment,只读,含偏移读数器) --------
  function renderStageJudgment(objId) {
    var j = judgments[objId];
    stageEl.innerHTML = "";
    if (!j) {
      stageEl.appendChild(el("div", "crumb", "选择议程项查看盘口 / 画像 / 读数器"));
      return;
    }
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
      blk.appendChild(miniTrack(j.belief, true));
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

  // ---- event dispatch + polling -------------------------------------
  function ingest(e) {
    allEvents.push(e);
    if (e.seq && e.seq > cursor) cursor = e.seq;
    switch (e.kind) {
      case "attention": renderAttention(e); break;
      case "judgment": judgments[e.obj_id] = e.payload || {}; break;
      case "read_draft": renderReadDraft(e); break;
      case "legs_proposal": renderLegsProposal(e); break;
      case "view_block": renderViewBlock(e); break;
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
      })
      .catch(function () { /* 保留服务端渲染的降级视图 */ })
      .finally(function () { setInterval(poll, 2000); });
  }

  boot();
})();
