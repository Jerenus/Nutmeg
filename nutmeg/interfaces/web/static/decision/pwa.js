// static/decision/pwa.js —— 装到主屏幕后的一件事（2026-10-29 产品形态 Task 9.3）。
// 全屏模式没有地址栏、没有下拉刷新，切回前台时页面还停在切走那一刻：停售倒计时、刹车、
// 首发都是旧数。离开超过 5 分钟就重载一次；页上有没提交的输入就不重载，免得吞掉草稿。
// 浏览器里正常打开（非全屏）什么都不做。
(function () {
  "use strict";
  var standalone = window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  if (!standalone) return;
  var STALE_MS = 5 * 60 * 1000;
  var hiddenAt = 0;
  var dirty = false;
  document.addEventListener("input", function () { dirty = true; }, true);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && !dirty && Date.now() - hiddenAt > STALE_MS) window.location.reload();
  });
})();
