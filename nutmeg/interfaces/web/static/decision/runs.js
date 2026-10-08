/* 作业进度页。数据来自 /api/runs/<日>；筛选写进网址（?lane=&status=），可收藏可转发。 */
const Runs = (() => {
  const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  const STATUS_ORDER = ["ok", "warn", "fail", "missing", "upcoming", "skip", "unknown", "inactive"];
  const STATUS_COLOR = {
    ok: "var(--pine)", warn: "var(--gold)", fail: "var(--cinnabar)", missing: "var(--cinnabar)",
    upcoming: "var(--line-2)", skip: "var(--faint)", unknown: "var(--faint)", inactive: "var(--line)",
  };
  const TIER_TEXT = { deep_research: "深研", price_only: "只看价格", market_anchor: "市场锚" };
  let root, data, refreshTimer;
  const params = new URLSearchParams(location.search);
  const state = { lane: params.get("lane") || "all", status: params.get("status") || "all" };

  const $ = (sel) => root.querySelector(sel);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (hm) => {
    const [h, m] = hm.split(":").map(Number);
    return ((h * 60 + m) / 1440) * 100;
  };
  const query = () => {
    const q = new URLSearchParams();
    if (state.lane !== "all") q.set("lane", state.lane);
    if (state.status !== "all") q.set("status", state.status);
    const s = q.toString();
    return s ? `?${s}` : "";
  };
  const dayUrl = (d) => `/runs/${d}${query()}`;
  const laneOk = (lane) => state.lane === "all" || state.lane === lane;
  const statusOk = (status) => state.status === "all" || state.status === status;

  function mount(el) {
    root = el;
    const input = $("#rn-date-input");
    input.value = root.dataset.date;
    input.addEventListener("change", () => { if (input.value) location.href = dayUrl(input.value); });
    document.getElementById("rn-preview-close").addEventListener("click", () =>
      document.getElementById("rn-preview").close());
    load(true);
  }

  async function load(first) {
    try {
      const res = await fetch(`/api/runs/${root.dataset.date}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      $("#rn-summary").textContent = `读取失败（${err.message}）。确认 decision-web 在运行，然后刷新页面。`;
      return;
    }
    render(first);
    clearTimeout(refreshTimer);
    if (data.is_today) refreshTimer = setTimeout(() => load(false), 60_000);
  }

  function render(first) {
    renderHead();
    renderDays();
    renderFilters();
    renderChart(first);
    renderList();
    renderOutputs();
    const errors = $("#rn-errors");
    errors.hidden = !data.errors.length;
    errors.innerHTML = data.errors.map(esc).join("<br>");
  }

  function renderHead() {
    const d = new Date(`${data.date}T00:00:00`);
    $("#rn-title").textContent = `${d.getMonth() + 1}月${d.getDate()}日`;
    const rel = data.is_today ? "，今天" : data.date > data.today ? "，还没到" : "";
    $("#rn-weekday").textContent = `${WEEK[d.getDay()]}${rel}`;
    document.title = `作业进度 ${data.date} · Nutmeg`;
    const c = data.counts;
    const total = STATUS_ORDER.reduce((n, k) => n + (c[k] || 0), 0);
    const parts = [];
    if (c.ok) parts.push(`完成 <b>${c.ok}</b> 次`);
    if (c.warn) parts.push(`<b>${c.warn}</b> 次有警告`);
    if (c.fail) parts.push(`<b>${c.fail}</b> 次失败`);
    if (c.missing) parts.push(`<b>${c.missing}</b> 次到点没跑`);
    if (c.upcoming) parts.push(`还有 <b>${c.upcoming}</b> 次未到`);
    if (c.skip) parts.push(`<b>${c.skip}</b> 次无需运行`);
    if (c.unknown) parts.push(`<b>${c.unknown}</b> 次没留下记录`);
    if (c.inactive) parts.push(`<b>${c.inactive}</b> 次对应的作业那时还没上线`);
    const who = data.is_today ? "今天" : "这天";
    const now = data.now ? `现在 ${data.now}。` : "";
    $("#rn-summary").innerHTML =
      `${who}共 <b>${data.jobs.length}</b> 项定时作业、<b>${total}</b> 次运行：${parts.join("，")}。${now}`;
  }

  function renderDays() {
    const days = [...new Set([...data.days, data.today, data.date])].sort();
    const strip = $("#rn-days");
    strip.innerHTML = days.map((d) => {
      const dt = new Date(`${d}T00:00:00`);
      const cur = d === data.date ? ' aria-current="date"' : "";
      const label = d === data.today ? "今天" : WEEK[dt.getDay()];
      return `<a class="rn-day" href="${dayUrl(d)}"${cur}><b>${dt.getMonth() + 1}/${dt.getDate()}</b><small>${label}</small></a>`;
    }).join("");
    strip.querySelector('[aria-current="date"]')?.scrollIntoView({ inline: "center", block: "nearest" });
    const i = days.indexOf(data.date);
    const prev = $("#rn-prev");
    const next = $("#rn-next");
    prev.href = i > 0 ? dayUrl(days[i - 1]) : "#";
    prev.setAttribute("aria-disabled", String(i <= 0));
    next.href = i < days.length - 1 ? dayUrl(days[i + 1]) : "#";
    next.setAttribute("aria-disabled", String(i >= days.length - 1));
  }

  function renderFilters() {
    const laneBox = root.querySelector('[data-filter="lane"]');
    const statusBox = root.querySelector('[data-filter="status"]');
    const lanes = [["all", "全部"], ...Object.entries(data.lanes)];
    laneBox.innerHTML = '<span class="rn-filter-name">泳道</span>' + lanes.map(([k, v]) =>
      `<button type="button" class="rn-chip" data-lane="${k}" aria-pressed="${state.lane === k}">${esc(v)}</button>`,
    ).join("");
    const statuses = [["all", "全部"], ...STATUS_ORDER.filter((k) => data.counts[k] || state.status === k)
      .map((k) => [k, data.status_text[k]])];
    statusBox.innerHTML = '<span class="rn-filter-name">状态</span>' + statuses.map(([k, v]) => {
      const dot = k === "all" ? "" : `<i class="rn-dot" style="background:${STATUS_COLOR[k]}"></i>`;
      const n = k === "all" ? "" : `<span class="n">${data.counts[k] || 0}</span>`;
      return `<button type="button" class="rn-chip" data-status="${k}" aria-pressed="${state.status === k}">${dot}${esc(v)}${n}</button>`;
    }).join("");
    laneBox.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setFilter("lane", b.dataset.lane)));
    statusBox.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setFilter("status", b.dataset.status)));
  }

  function setFilter(key, value) {
    state[key] = state[key] === value ? "all" : value;
    history.replaceState(null, "", `/runs/${data.date}${query()}`);
    renderDays();
    renderFilters();
    renderChart(false);
    renderList();
  }

  function renderChart(animate) {
    const grid = $("#rn-grid");
    const hours = Array.from({ length: 9 }, (_, i) => i * 3);
    let html = `<div class="rn-axis"><div></div><div class="rn-hours">${hours.map((h) =>
      `<span style="left:${(h / 24) * 100}%">${String(h).padStart(2, "0")}:00</span>`).join("")}</div></div>`;
    if (data.markers.length) {
      // 按标签实际宽度贪心分层：同一层里后一个标签的左缘必须在前一个右缘之后
      const trackPx = Math.max(400, grid.clientWidth - 188);
      const ends = [];
      const pills = data.markers.map((m) => {
        const text = m.kind === "deadline" ? `${m.at} ${m.label}` : `${m.at} ${m.label.split(" ")[0]}`;
        const half = ((text.length * 6.6 + 16) / trackPx) * 50;
        const left = pct(m.at) - half;
        let lv = ends.findIndex((end) => end < left - 0.4);
        if (lv === -1) { lv = ends.length; ends.push(0); }
        ends[lv] = pct(m.at) + half;
        return `<span class="rn-pill ${m.kind}" style="left:${pct(m.at)}%;--lv:${lv}" title="${esc(m.at)} ${esc(m.label)}">${esc(text)}</span>`;
      }).join("");
      html += `<div class="rn-row rn-events" style="--levels:${ends.length}"><div class="rn-name">开球与截止</div><div class="rn-track">${pills}</div></div>`;
    }
    for (const [lane, laneName] of Object.entries(data.lanes)) {
      const jobs = data.jobs.filter((j) => j.lane === lane);
      if (!jobs.length || !laneOk(lane)) continue;
      html += `<div class="rn-lane"><h3>${esc(laneName)}</h3><div class="rn-track"></div></div>`;
      for (const job of jobs) html += job.kind === "frequent" ? frequentRow(job) : timedRow(job);
    }
    html += `<div class="rn-vlines">${Array.from({ length: 25 }, (_, h) =>
      `<i class="rn-vline${h % 6 === 0 ? " major" : ""}" style="left:${(h / 24) * 100}%"></i>`).join("")}`;
    for (const m of data.markers) {
      html += `<i class="rn-marker ${m.kind}" style="left:${pct(m.at)}%"></i>`;
    }
    if (data.now) html += `<i class="rn-now" style="left:${pct(data.now)}%"><span>现在 ${data.now}</span></i>`;
    html += "</div>";
    grid.innerHTML = html;
    grid.classList.toggle("is-entering", animate);
    grid.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", () => focusItem(b.dataset.key)));
    $("#rn-legend").innerHTML = ["ok", "warn", "fail", "missing", "upcoming"].map((k) =>
      `<span><i class="sw ${k}"></i>${data.status_text[k]}</span>`).join("")
      + (data.markers.length ? '<span>绿色虚线是竞彩开球，红线是足彩截止</span>' : "");
  }

  function timedRow(job) {
    const marks = job.slots.map((s, i) => {
      const at = s.planned || s.at;
      if (!at) return "";
      const dim = statusOk(s.status) ? "" : " is-dim";
      const tip = `${job.name} ${s.planned ? "计划 " + s.planned : "补跑"}${s.at ? "，" + s.at + " 完成" : ""}：${data.status_text[s.status]}${s.summary ? "。" + s.summary : ""}`;
      return `<button type="button" class="rn-mark ${s.status}${s.extra ? " extra" : ""}${dim}" data-key="${job.id}#${i}" style="left:${pct(at)}%;--d:${Math.round(pct(at) * 9)}ms" title="${esc(tip)}" aria-label="${esc(tip)}"></button>`;
    }).join("");
    return `<div class="rn-row" data-lane="${job.lane}"><div class="rn-name" title="${esc(job.what)}">${esc(job.name)}<small>${job.slots.filter((s) => s.planned).length > 1 ? `${job.slots.filter((s) => s.planned).length} 次` : esc(job.schedule)}</small></div><div class="rn-track">${marks}</div></div>`;
  }

  function frequentRow(job) {
    const [from, to] = job.window;
    const band = `<i class="rn-window" style="left:${pct(from)}%;width:${pct(to) - pct(from)}%"></i>`;
    const ticks = job.runs.filter((r) => r.at).map((r) =>
      `<i class="rn-tick ${r.status}" style="left:${pct(r.at)}%;--d:${Math.round(pct(r.at) * 9)}ms"></i>`).join("");
    const dim = statusOk(job.status) ? "" : " is-dim";
    const tip = `${job.name}：已跑 ${job.run_count} 次，应跑 ${job.due} 次。${job.last}`;
    // 日志只有次数没有时刻（义务巡检）：用「跑到哪了」的进度条代替逐次刻度
    const reach = data.now && data.now < to ? data.now : to;
    const fill = ticks || !job.run_count ? "" : `<i class="rn-fill ${job.status}${dim}" style="left:${pct(from)}%;width:${Math.max(0, pct(reach) - pct(from))}%"></i>`;
    return `<div class="rn-row" data-lane="${job.lane}"><button type="button" class="rn-name" data-key="${job.id}#f" title="${esc(tip)}">${esc(job.name)}<small>${job.run_count}/${job.due} 次</small></button><div class="rn-track">${band}${fill}${ticks}</div></div>`;
  }

  function listItems() {
    const items = [];
    for (const job of data.jobs) {
      if (job.kind === "frequent") {
        items.push({ key: `${job.id}#f`, job, status: job.status, sort: job.window[0],
          time: "全天", sub: job.schedule.replace(/（.*）/, ""),
          text: `已跑 ${job.run_count} 次，到现在应跑 ${job.due} 次。${job.last ? "最近一次：" + job.last : ""}`,
          evidence: null });
        continue;
      }
      job.slots.forEach((s, i) => items.push({
        key: `${job.id}#${i}`, job, status: s.status, sort: s.planned || s.at || "99",
        time: s.planned || s.at || "—",
        sub: s.planned ? (s.at && s.at !== s.planned ? `${s.at} 完成` : "") : "计划外补跑",
        text: s.summary || emptyText(s.status), evidence: s.evidence,
      }));
    }
    return items.sort((a, b) => a.sort.localeCompare(b.sort));
  }

  function emptyText(status) {
    return {
      upcoming: "还没到计划时刻。",
      missing: "到点了，但没有找到这次运行留下的产物或日志。",
      unknown: "这项作业只保留最近一次日志，看不到这天的记录。",
      inactive: "这项作业那天还没上线。",
    }[status] || "";
  }

  function renderList() {
    const items = listItems().filter((it) => laneOk(it.job.lane) && statusOk(it.status));
    $("#rn-list").innerHTML = items.map((it) => `
      <li class="rn-item" id="item-${esc(it.key.replace(/[^\w-]/g, "_"))}">
        <span class="rn-time">${esc(it.time)}<small>${esc(it.sub)}</small></span>
        <i class="rn-dot" style="background:${STATUS_COLOR[it.status]}" aria-hidden="true"></i>
        <span class="rn-job">${esc(it.job.name)}<small>${esc(data.lanes[it.job.lane])}</small></span>
        <span class="rn-what"><span class="rn-state">${esc(data.status_text[it.status])}</span>${esc(it.text)}</span>
        ${it.evidence ? `<button type="button" class="rn-open" data-path="${esc(it.evidence)}">查看产物</button>` : "<span></span>"}
      </li>`).join("");
    $("#rn-list-empty").hidden = items.length > 0;
    root.querySelectorAll(".rn-open").forEach((b) => b.addEventListener("click", () => preview(b.dataset.path)));
  }

  function focusItem(key) {
    const el = document.getElementById(`item-${key.replace(/[^\w-]/g, "_")}`);
    if (!el) return;
    el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    el.classList.add("is-flash");
    setTimeout(() => el.classList.remove("is-flash"), 1400);
  }

  async function preview(path) {
    const dialog = document.getElementById("rn-preview");
    document.getElementById("rn-preview-path").textContent = path;
    const pre = document.getElementById("rn-preview-text");
    pre.textContent = "正在读取…";
    dialog.showModal();
    try {
      const res = await fetch(`/api/runs-file?path=${encodeURIComponent(path)}`);
      const body = await res.json();
      pre.textContent = res.ok ? body.text + (body.truncated ? "\n\n（文件较长，只显示前 6 万字）" : "")
        : `打不开：${body.detail || res.status}`;
    } catch (err) {
      pre.textContent = `打不开：${err.message}`;
    }
  }

  function broadcastText(key) {
    const [subject, window] = String(key).split("@");
    const who = subject.replace(/^(read|plan|rsi):/, (_, kind) => (kind === "plan" ? "足彩 " : ""));
    const when = { T30: "截止前 30 分", T10: "截止前 10 分" }[window] || window;
    return ` ${who} ${when}`;
  }

  function renderOutputs() {
    const o = data.outputs;
    const j = o.jczq;
    const board = j.board.map((m) => `<li><span class="code">${esc(m.code)}</span><span class="ko">${esc(m.kickoff || "")}</span><span>${esc(m.name)}</span><span class="tier${m.tier === "deep_research" ? " deep" : ""}">${esc(TIER_TEXT[m.tier] || m.tier || "")}</span></li>`).join("");
    const jczq = `<div class="rn-col"><h3>竞彩</h3>
      <p class="lead">${j.matches ? `板面 <b>${j.matches}</b> 场，深研 <b>${j.deep}</b> 场，判读偏离市场 <b>${j.moved}</b> 场。` : "这天没有竞彩板面。"}</p>
      ${board ? `<ul class="rn-board">${board}</ul>` : ""}</div>`;
    const z = o.zucai;
    const zucai = `<div class="rn-col"><h3>足彩</h3>${z.issue ? `
      <p class="lead"><b>${esc(z.issue)}</b> 期，截止 <b>${esc((z.deadline || "").slice(5))}</b>。</p>` : '<p class="lead">这天没有在售的足彩期。</p>'}
      ${o.broadcasts.length ? `<h3 style="margin-top:18px">截止播报</h3><ul class="rn-pending">${o.broadcasts.map((b) => `<li>${esc(b.at)} 提醒${esc(broadcastText(b.key))}，当时还剩 ${esc(b.minutes_left)} 分</li>`).join("")}</ul>` : ""}</div>`;
    const duties = o.rsi.duties.map((d) => {
      const done = (d.done / d.total) * 100;
      const gap = (d.expired / d.total) * 100;
      const note = d.expired ? `，${d.expired} 条过期未交` : "";
      return `<div class="rn-duty"><div class="rn-duty-head"><b>${esc(d.duty)}</b><span>${d.done}/${d.total}${note}</span></div>
        <div class="rn-bar" role="img" aria-label="${esc(d.duty)} 已交 ${d.done} 共 ${d.total}"><i class="done" style="width:${done}%"></i><i class="gap" style="width:${gap}%"></i></div></div>`;
    }).join("");
    const rsi = `<div class="rn-col"><h3>RSI 观察义务</h3>
      ${duties || '<p class="lead">这天没有排观察义务。</p>'}
      ${o.rsi.pending.length ? `<h3 style="margin-top:18px">待你决定</h3><ul class="rn-pending">${o.rsi.pending.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</div>`;
    const retro = o.retro ? `<div class="rn-retro"><h3>复盘底稿</h3><pre>${esc(o.retro.split("\n").slice(0, 24).join("\n"))}</pre>
      <button type="button" class="rn-open" data-path="daily/${esc(data.date)}/retro.md">打开全文</button></div>` : "";
    $("#rn-out").innerHTML = jczq + zucai + rsi + retro;
    $("#rn-out").querySelectorAll(".rn-open").forEach((b) => b.addEventListener("click", () => preview(b.dataset.path)));
  }

  return { mount };
})();
