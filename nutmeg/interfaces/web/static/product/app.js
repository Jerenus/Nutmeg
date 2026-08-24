(() => {
  "use strict";

  const feedback = document.querySelector("#action-feedback");
  const eventState = document.querySelector("[data-event-state]");
  const eventCursorKey = "nutmeg:event-cursor";
  let eventSource;
  let reconnectTimer;

  function showEventState(state, label) {
    if (!eventState) return;
    eventState.dataset.eventState = state;
    eventState.lastChild.textContent = ` ${label}`;
  }

  function rememberEvent(event) {
    if (!event.lastEventId) return;
    sessionStorage.setItem(eventCursorKey, event.lastEventId);
  }

  function connectEventStream() {
    if (!eventState || typeof EventSource === "undefined") return;
    const cursor = sessionStorage.getItem(eventCursorKey) || "0";
    eventSource = new EventSource(
      `/api/v1/events/stream?after=${encodeURIComponent(cursor)}`,
    );
    eventSource.onopen = () => showEventState("connected", "事件流已连接");
    for (const topic of ["action.committed", "action.rejected", "action.failed"]) {
      eventSource.addEventListener(topic, rememberEvent);
    }
    eventSource.onerror = () => {
      showEventState("offline", "事件流离线");
      eventSource.close();
      window.clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connectEventStream, 1200);
    };
  }

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

  async function postJson(url, payload) {
    const session = await localSession();
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
    if (!response.ok) {
      throw new Error(result.message || result.code || "操作被拒绝");
    }
    if (result.status !== "committed") {
      throw new Error(result.error_detail || "操作未提交");
    }
    return result;
  }

  async function submitMutation(form, label, operation) {
    const buttons = [...form.querySelectorAll('button[type="submit"]')];
    buttons.forEach((button) => {
      button.disabled = true;
    });
    report(label);
    try {
      const result = await operation();
      report(`操作已提交：${result.action_id}`, "success");
      window.location.reload();
    } catch (error) {
      report(error instanceof Error ? error.message : "操作失败", "error");
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  }

  function valuesFor(form, submitter) {
    return submitter ? new FormData(form, submitter) : new FormData(form);
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-action]");
    if (!form) return;
    event.preventDefault();
    const values = valuesFor(form, event.submitter);
    const action = form.dataset.action;

    if (action === "merge-identity") {
      submitMutation(form, "正在验证身份合并…", () =>
        postJson("/api/v1/actions", {
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
      );
      return;
    }

    if (action === "copilot-investigate") {
      const matchId = form.dataset.matchId;
      submitMutation(form, "正在生成带引用的调查 Proposal…", () =>
        postJson(`/api/v1/matches/${matchId}/copilot`, {
          schema_version: "1",
          idempotency_key: `ui:copilot:${crypto.randomUUID()}`,
          prompt: values.get("prompt"),
          as_of: form.dataset.asOf,
        }),
      );
      return;
    }

    if (action === "claim-adjudication") {
      submitMutation(form, "正在写入 Claim 裁决…", () =>
        postJson("/api/v1/actions", {
          action_type: values.get("claim_action"),
          idempotency_key: `ui:claim:${crypto.randomUUID()}`,
          payload: { claim_id: form.dataset.claimId },
          expected_versions: {},
        }),
      );
      return;
    }

    if (action === "proposal-resolution") {
      const proposalId = form.dataset.proposalId;
      submitMutation(form, "正在写入 Proposal 裁决…", () =>
        postJson("/api/v1/actions", {
          action_type: "resolve_agent_proposal",
          idempotency_key: `ui:proposal:${crypto.randomUUID()}`,
          payload: {
            agent_proposal_id: proposalId,
            resolution: values.get("resolution"),
          },
          expected_versions: {
            [`agent_proposal:${proposalId}`]: Number(form.dataset.proposalVersion),
          },
        }),
      );
      return;
    }

    if (action === "record-adjudication") {
      submitMutation(form, "正在记录证据裁决…", () =>
        postJson("/api/v1/actions", {
          action_type: "record_adjudication",
          idempotency_key: `ui:adjudication:${crypto.randomUUID()}`,
          payload: {
            subject_type: form.dataset.subjectType,
            subject_id: form.dataset.subjectId,
            decision: values.get("decision"),
            reason: values.get("reason"),
            evidence_rejected: values.getAll("evidence_rejected").map(
              (objectId) => ({ object_type: "claim", object_id: objectId }),
            ),
            alternative: {},
          },
          expected_versions: {},
        }),
      );
      return;
    }

    if (action === "forecast-commit") {
      const matchId = form.dataset.matchId;
      const marketId = form.dataset.marketId;
      const proposalId = values.get("agent_proposal_id");
      const selectedProposal = form.elements.agent_proposal_id.selectedOptions[0];
      const expectedVersions = {
        [`forecast:${matchId}:${marketId}`]: Number(form.dataset.forecastVersion),
      };
      const payload = {
        match_id: matchId,
        market_definition_id: marketId,
        cutoff_at: form.dataset.asOf,
        belief_distribution: {
          home: values.get("belief_home"),
          draw: values.get("belief_draw"),
          away: values.get("belief_away"),
        },
        factors: [],
        commitment_tier: "judged",
      };
      if (proposalId) {
        payload.agent_proposal_id = proposalId;
        expectedVersions[`agent_proposal:${proposalId}`] = Number(
          selectedProposal.dataset.version,
        );
      }
      submitMutation(form, "正在执行 Forecast 审计与冻结…", () =>
        postJson("/api/v1/actions", {
          action_type: "commit_forecast",
          idempotency_key: `ui:forecast:${crypto.randomUUID()}`,
          payload,
          expected_versions: expectedVersions,
        }),
      );
    }
  });
  window.addEventListener("beforeunload", () => eventSource?.close());
  connectEventStream();
})();
