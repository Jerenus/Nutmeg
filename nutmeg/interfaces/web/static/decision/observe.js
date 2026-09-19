window.Observe = (function () {
  "use strict";

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function getJson(url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function showErrors(selector, errors) {
    var box = document.querySelector(selector);
    if (!box || !errors || !errors.length) return;
    box.hidden = false;
    box.textContent = "部分数据暂不可用：" + errors.join("；");
  }

  function chartsAvailable() {
    return typeof echarts !== "undefined";
  }

  function chartFallback(dom, detail) {
    dom.replaceChildren(element("span", "obs-chart-fallback", "图表引擎暂不可用 · " + detail));
  }

  function ring(dom, progress, label) {
    if (!chartsAvailable()) {
      chartFallback(dom, label);
      return;
    }
    var chart = echarts.init(dom, null, { renderer: "svg" });
    chart.setOption({
      series: [{
        type: "gauge", startAngle: 90, endAngle: -270, min: 0, max: 1,
        progress: { show: true, width: 7, itemStyle: { color: "#168A96" } },
        axisLine: { lineStyle: { width: 7, color: [[1, "#D7DFD6"]] } },
        axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
        pointer: { show: false }, anchor: { show: false },
        detail: { formatter: label, fontSize: 11, color: "#5C6B63", offsetCenter: [0, 0] },
        data: [{ value: Math.min(progress, 1) }]
      }]
    });
  }

  function ciBar(dom, ci, threshold) {
    if (!chartsAvailable()) {
      chartFallback(dom, "CI " + ci[0] + " / " + ci[1] + " · 阈值 " + threshold);
      return;
    }
    var chart = echarts.init(dom, null, { renderer: "svg" });
    var low = Math.min(ci[0], threshold) - 5;
    var high = Math.max(ci[1], threshold) + 5;
    chart.setOption({
      animationDuration: 450,
      grid: { left: 8, right: 8, top: 7, bottom: 20 },
      xAxis: { min: low, max: high, axisLabel: { fontSize: 9 }, splitLine: { show: false } },
      yAxis: { show: false, min: 0, max: 1 },
      series: [{
        type: "custom", data: [0],
        renderItem: function (params, api) {
          var x0 = api.coord([ci[0], 0.5])[0];
          var x1 = api.coord([ci[1], 0.5])[0];
          var tx = api.coord([threshold, 0.5])[0];
          var y = api.coord([0, 0.5])[1];
          return { type: "group", children: [
            { type: "rect", shape: { x: x0, y: y - 5, width: Math.max(x1 - x0, 2), height: 10 }, style: { fill: "#168A96" } },
            { type: "line", shape: { x1: tx, y1: y - 14, x2: tx, y2: y + 14 }, style: { stroke: "#B23A2C", lineWidth: 2 } }
          ] };
        }
      }]
    });
  }

  function experimentCard(data) {
    var card = element("a", "obs-card " + data.color);
    card.href = "/observe/exp/" + encodeURIComponent(data.exp_id);
    var id = element("div", "obs-id", data.exp_id);
    id.appendChild(element("span", "obs-status", data.status));
    card.appendChild(id);
    card.appendChild(element("div", "obs-claim", data.claim));
    var ringBox = element("div", "obs-ring");
    var ciBox = element("div", "obs-ci");
    card.appendChild(ringBox);
    card.appendChild(ciBox);
    var foot = element("div", "obs-foot");
    var distance = data.distance_to_falsifier_pp == null ? "距判决 --" : "距判决 " + data.distance_to_falsifier_pp + "pp";
    foot.appendChild(element("span", "obs-distance", distance));
    var gaps = element("div", "obs-gaps");
    gaps.appendChild(element("span", "obs-gap-label", "缺口 " + data.gap_count));
    (data.gaps || []).forEach(function (gap) {
      var cell = element("span", "obs-gap");
      cell.title = gap;
      gaps.appendChild(cell);
    });
    foot.appendChild(gaps);
    card.appendChild(foot);
    window.setTimeout(function () {
      ring(ringBox, data.progress, data.n_cum + "/" + data.n_min);
      if (data.ci) ciBar(ciBox, data.ci, data.threshold_pp);
      else ciBox.appendChild(element("span", "obs-muted", "尚无 CI"));
    }, 0);
    return card;
  }

  function panorama(selectors) {
    function load() {
      getJson("/api/observe").then(function (data) {
        var cards = document.querySelector(selectors.cards);
        cards.replaceChildren();
        if (!data.experiments.length) cards.appendChild(element("p", "obs-muted", "暂无实验"));
        data.experiments.forEach(function (item) { cards.appendChild(experimentCard(item)); });
        if (data.wind) {
          document.querySelector(selectors.wind).textContent = "今日风向 " + (data.wind.regime || "--") + " · 各级 " + JSON.stringify(data.wind.tiers || {}) + " · 建议帽档 " + (data.wind.cap_band || "--");
        }
        var duties = document.querySelector(selectors.duties);
        duties.replaceChildren(element("div", "obs-section-title", "今日到期 " + data.duties_today.length + " · 明日 " + data.duties_tomorrow.length));
        data.duties_today.forEach(function (duty) {
          var row = element("div", "obs-duty");
          row.appendChild(element("time", "", String(duty.due_at || "").slice(11, 16)));
          row.appendChild(element("span", "", duty.duty_id));
          duties.appendChild(row);
        });
        showErrors(selectors.errors, data.errors);
      }).catch(function (error) { showErrors(selectors.errors, [error.message]); });
    }
    load();
    window.setInterval(load, 60000);
  }

  function life(selectors, expId) {
    getJson("/api/observe/exp/" + encodeURIComponent(expId)).then(function (timeline) {
      var registered = timeline.find(function (event) { return event.kind === "registered"; });
      if (registered) {
        var freeze = document.querySelector(selectors.freeze);
        freeze.replaceChildren();
        var rule = element("div", "");
        rule.appendChild(element("div", "obs-section-title", "冻结判据"));
        rule.appendChild(element("div", "obs-freeze-code", JSON.stringify(registered.falsifier || {})));
        freeze.appendChild(rule);
        freeze.appendChild(element("div", "obs-freeze-code", registered.frozen_hash || ""));
      }
      var grades = timeline.filter(function (event) { return event.kind === "grade"; });
      var chartBox = document.querySelector(selectors.chart);
      var threshold = registered && registered.falsifier ? registered.falsifier.threshold_pp : null;
      if (chartsAvailable()) {
        var chart = echarts.init(chartBox, null, { renderer: "svg" });
        chart.setOption({
          tooltip: { trigger: "axis" }, legend: { bottom: 0 },
          grid: { left: 48, right: 22, top: 24, bottom: 46 },
          xAxis: { type: "category", data: grades.map(function (grade) { return String(grade.at).slice(0, 10); }) },
          yAxis: { name: "pp", splitLine: { lineStyle: { color: "#D7DFD6" } } },
          series: [
            { type: "line", name: "CI 上界", data: grades.map(function (grade) { return grade.ci_high_pp; }), itemStyle: { color: "#B77714" }, markLine: threshold == null ? undefined : { symbol: "none", data: [{ yAxis: threshold, name: "falsifier" }] } },
            { type: "line", name: "CI 下界", data: grades.map(function (grade) { return grade.ci_low_pp; }), itemStyle: { color: "#168A96" } }
          ]
        });
      } else {
        chartFallback(chartBox, grades.length + " 个 grade");
      }
      var list = document.querySelector(selectors.list);
      list.replaceChildren();
      if (!timeline.length) list.appendChild(element("p", "obs-muted", "暂无时间线"));
      timeline.forEach(function (event) {
        var row = element("article", "obs-event");
        row.appendChild(element("div", "obs-event-time", event.at || ""));
        row.appendChild(element("div", "obs-event-kind", event.kind + (event.verdict ? " → " + event.verdict : "")));
        if (event.n_cum != null) row.appendChild(element("div", "obs-event-meta", "n=" + event.n_cum + " · CI " + event.ci_low_pp + " / " + event.ci_high_pp));
        list.appendChild(row);
      });
    });
  }

  function renderRows(selector, rows, emptyText, render) {
    var box = document.querySelector(selector);
    box.replaceChildren();
    if (!rows.length) box.appendChild(element("span", "obs-muted", emptyText));
    rows.forEach(function (row) { box.appendChild(render(row)); });
  }

  function day(selectors, date) {
    getJson("/api/observe/day/" + encodeURIComponent(date)).then(function (data) {
      var tree = document.querySelector(selectors.tree);
      if (data.tree.nodes.length) {
        tree.textContent = "";
        if (chartsAvailable()) {
          var chart = echarts.init(tree, null, { renderer: "svg" });
          chart.setOption({
            tooltip: { formatter: function (x) { return x.data.reason || x.name; } },
            series: [{ type: "graph", layout: "force", roam: true, emphasis: { focus: "adjacency" },
              force: { repulsion: 260, edgeLength: 110 }, edgeSymbol: ["none", "arrow"],
              label: { show: true, formatter: "{b}", fontSize: 10 },
              data: data.tree.nodes.map(function (node) { return { name: node.id, value: node.p_all, reason: node.reason, symbolSize: node.verdict === "chosen" ? 30 : 19, itemStyle: { color: node.verdict === "chosen" ? "#2B8056" : node.verdict === "rejected" ? "#78827C" : "#168A96" } }; }),
              links: data.tree.edges }]
          });
        } else {
          chartFallback(tree, data.tree.nodes.map(function (node) { return node.id; }).join(" → "));
        }
      }
      var plan = document.querySelector(selectors.plan);
      if (data.plan) {
        plan.replaceChildren(element("div", "obs-plan-main", data.plan.plan_id + " · " + data.plan.cap_source));
        var metrics = element("div", "obs-metrics");
        [["矩阵 max P", data.plan.max_p_matrix], ["strict max P", data.plan.max_p_strict], ["所选 P", data.plan.chosen_p]].forEach(function (item) {
          var metric = element("div", "obs-metric"); metric.appendChild(element("b", "", item[1] == null ? "--" : String(item[1]))); metric.appendChild(element("span", "", item[0])); metrics.appendChild(metric);
        });
        plan.appendChild(metrics);
        plan.appendChild(element("div", "obs-row", "门代价 " + (data.plan.gate_cost_pp == null ? "--" : data.plan.gate_cost_pp + "pp")));
      }
      renderRows(selectors.slips, data.slips, "当日暂无实票", function (slip) {
        var row = element("div", "obs-row"); row.appendChild(element("b", "", slip.slip_id || "实票")); row.appendChild(element("span", "", (slip.notes || 0) + " 注 · ¥" + (slip.stake_yuan || 0))); return row;
      });
      renderRows(selectors.judgments, data.judgments, "当日暂无判读", function (judgment) {
        var row = element("div", "obs-row"); row.appendChild(element("b", "", judgment.match || judgment.obj_id || "判读")); row.appendChild(element("span", "", judgment.market || "")); return row;
      });
      showErrors(selectors.errors, data.errors);
    }).catch(function (error) { showErrors(selectors.errors, [error.message]); });
  }

  return { panorama: panorama, life: life, day: day };
})();
