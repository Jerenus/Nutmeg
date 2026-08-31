(() => {
  "use strict";

  const feedback = document.querySelector("#action-feedback");

  function snapshotHex(encoded) {
    const padded = encoded.replace(/-/g, "+").replace(/_/g, "/")
      + "=".repeat((4 - encoded.length % 4) % 4);
    return [...atob(padded)]
      .map((character) => character.charCodeAt(0).toString(16).padStart(2, "0"))
      .join("");
  }

  function commaValues(value) {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }

  async function postJson(url, payload) {
    const sessionResponse = await fetch("/api/v1/session", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const session = await sessionResponse.json();
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || result.code);
    return result;
  }

  async function submit(form, operation) {
    const controls = [...form.querySelectorAll("button, input, select, textarea")];
    controls.forEach((control) => { control.disabled = true; });
    if (feedback) feedback.textContent = "正在保存…";
    try {
      await operation();
      if (feedback) feedback.textContent = "已保存，正在进入下一步。";
      window.location.reload();
    } catch (error) {
      controls.forEach((control) => { control.disabled = false; });
      if (feedback) feedback.textContent = error.message || "保存失败，请重试。";
    }
  }

  function updateCandidateFields(form, candidateId) {
    form.querySelectorAll("[data-candidate-group]").forEach((group) => {
      const selected = group.dataset.candidateGroup === candidateId;
      group.hidden = !selected;
      group.querySelectorAll("input, textarea").forEach((control) => {
        control.disabled = !selected;
      });
    });
  }

  document.addEventListener("change", (event) => {
    const radio = event.target.closest('input[name="candidate_id"]');
    if (!radio) return;
    updateCandidateFields(radio.form, radio.value);
  });

  document.querySelectorAll('[data-action="select-ticket-version"]').forEach((form) => {
    const selected = form.querySelector('input[name="candidate_id"]:checked');
    if (selected) updateCandidateFields(form, selected.value);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-action]");
    if (!form) return;
    event.preventDefault();
    const values = new FormData(form);
    const action = form.dataset.action;
    const encodedToken = form.closest("[data-snapshot-token]").dataset.snapshotToken;
    const expectedToken = snapshotHex(encodedToken);

    if (action === "resolve-issue-adjudication") {
      submit(form, () => postJson(
        `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/adjudications`,
        {
          schema_version: "1",
          expected_snapshot_token: expectedToken,
          adjudication_key: form.dataset.adjudicationKey,
          decision: values.get("decision"),
          reason: values.get("reason"),
          selected_option: values.get("selected_option") || values.get("option_text"),
          evidence_rejected: [],
          idempotency_key: `ui:operator:adjudication:${crypto.randomUUID()}`,
        },
      ));
    }

    if (action === "select-ticket-version") {
      const candidateId = values.get("candidate_id");
      const deviations = [...form.querySelectorAll(
        `[data-deviation-candidate="${CSS.escape(candidateId)}"]`,
      )].map((row) => ({
        match_no: Number(row.dataset.deviationMatch),
        rule_ids: commaValues(row.querySelector("[data-deviation-rules]").value),
        reason: row.querySelector("[data-deviation-reason]").value,
      }));
      submit(form, () => postJson(
        `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/candidate`,
        {
          schema_version: "1",
          expected_snapshot_token: expectedToken,
          candidate_id: candidateId,
          reason: values.get("reason"),
          deviations,
          idempotency_key: `ui:operator:candidate:${crypto.randomUUID()}`,
        },
      ));
    }

    if (action === "record-deployment") {
      submit(form, () => postJson(
        `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}/deployment`,
        {
          schema_version: "1",
          expected_snapshot_token: expectedToken,
          candidate_id: form.dataset.candidateId,
          decision: values.get("decision"),
          reason: values.get("reason"),
          idempotency_key: `ui:operator:deployment:${crypto.randomUUID()}`,
        },
      ));
    }
  });
})();
