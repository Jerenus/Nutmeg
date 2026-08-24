(() => {
  "use strict";

  const feedback = document.querySelector("#action-feedback");

  function report(message, state = "info") {
    if (!feedback) return;
    feedback.textContent = message;
    feedback.dataset.state = state;
  }

  async function localSession() {
    const response = await fetch("/api/v1/session", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("无法建立本地操作会话");
    return response.json();
  }

  async function submitIdentityMerge(form) {
    const submit = form.querySelector('button[type="submit"]');
    const values = new FormData(form);
    submit.disabled = true;
    report("正在验证身份合并…");

    try {
      const session = await localSession();
      const response = await fetch("/api/v1/actions", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": session.csrf_token,
        },
        body: JSON.stringify({
          action_type: "merge_entity",
          idempotency_key: `ui:merge:${crypto.randomUUID()}`,
          payload: {
            entity_type: "team",
            from_id: form.dataset.entityId,
            into_id: values.get("survivor_id"),
            reason: values.get("reason"),
          },
          expected_versions: {},
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.message || result.code || "身份合并被拒绝");
      }
      if (result.status !== "committed") {
        throw new Error(result.error_detail || "身份合并未提交");
      }
      report(`合并已提交：${result.action_id}`, "success");
      window.location.reload();
    } catch (error) {
      report(error instanceof Error ? error.message : "身份合并失败", "error");
      submit.disabled = false;
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest('[data-action="merge-identity"]');
    if (!form) return;
    event.preventDefault();
    submitIdentityMerge(form);
  });
})();
