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

  function commaValues(value) {
    return String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function optionalNumber(value) {
    return value === null || String(value).trim() === "" ? null : Number(value);
  }

  function ticketLegs(form) {
    return [...form.querySelectorAll("[data-ticket-match]")]
      .map((card) => {
        const primary = card.querySelector('input[type="radio"]:checked');
        if (!primary) return null;
        const faces = [...card.querySelectorAll(".ticket-face:checked")]
          .map((input) => input.value)
          .join("");
        const directionalFlags = commaValues(
          card.querySelector('[name="directional_flags"]')?.value,
        ).map((item) => {
          const [flag, face = ""] = item.split("=", 2);
          return [flag.trim(), face.trim()];
        });
        return {
          leg_key: `${card.dataset.matchId}:${card.dataset.marketId}:${primary.value}`,
          match_id: card.dataset.matchId,
          match_no: Number(card.dataset.matchNo),
          name: card.dataset.matchName,
          market_definition_id: card.dataset.marketId,
          selection_id: primary.dataset.selectionId,
          outcome_key: primary.value,
          faces,
          forecast_revision_id: card.dataset.forecastId,
          entry_quote_id: primary.dataset.quoteId,
          odds: Number(primary.dataset.odds),
          line: primary.dataset.line || null,
          bucket: card.querySelector('[name="bucket"]').value,
          fair: {
            home: Number(card.dataset.fairHome),
            draw: Number(card.dataset.fairDraw),
            away: Number(card.dataset.fairAway),
          },
          confidence: Number(card.querySelector('[name="confidence"]').value),
          directional_flags: directionalFlags,
          nondirectional_flags: commaValues(
            card.querySelector('[name="nondirectional_flags"]').value,
          ),
          anchor_integrity: card.querySelector('[name="anchor_integrity"]').value,
          precedents: [],
        };
      })
      .filter(Boolean);
  }

  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("无法读取出票回执"));
      reader.onload = () => {
        const encoded = String(reader.result).split(",", 2)[1];
        if (!encoded) reject(new Error("出票回执为空"));
        else resolve(encoded);
      };
      reader.readAsDataURL(file);
    });
  }

  async function issueConfirmation(form) {
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    report("正在签发一次性确认口令…");
    try {
      const artifactId = form.dataset.ticketArtifactId;
      const result = await postJson(
        `/api/v1/ticket-artifacts/${artifactId}/confirmations`,
        {
          schema_version: "1",
          idempotency_key: `ui:ticket-confirmation:${crypto.randomUUID()}`,
        },
      );
      const confirmationForm = form.parentElement.querySelector(
        '[data-action="confirm-ticket-placement"]',
      );
      confirmationForm.elements.confirmation_id.value = result.confirmation_id || "";
      confirmationForm.elements.nonce.value = result.nonce || "";
      report(
        `一次性口令已签发；服务端失效时间 ${result.expires_at || "未返回"}`,
        "success",
      );
    } catch (error) {
      report(error instanceof Error ? error.message : "操作失败", "error");
      button.disabled = false;
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-action]");
    if (!form) return;
    event.preventDefault();
    const values = valuesFor(form, event.submitter);
    const action = form.dataset.action;

    if (action === "create-ticket-batch") {
      submitMutation(form, "正在由服务器构票并执行 C0–C7…", () =>
        postJson("/api/v1/ticket-batches", {
          schema_version: "1",
          run_date: form.dataset.runDate,
          channel: values.get("channel"),
          account_id: values.get("account_id"),
          currency: values.get("currency"),
          deadline_at: values.get("deadline_at"),
          legs: ticketLegs(form),
          idempotency_key: `ui:ticket-batch:${crypto.randomUUID()}`,
        }),
      );
      return;
    }

    if (action === "remove-ticket-leg") {
      const batchId = form.dataset.ticketBatchId;
      submitMutation(form, "正在创建移除腿后的新版本…", () =>
        postJson(`/api/v1/ticket-batches/${batchId}/remove-leg`, {
          schema_version: "1",
          leg_key: form.dataset.legKey,
          expected_revision_no: Number(form.dataset.revisionNo),
          idempotency_key: `ui:ticket-remove:${crypto.randomUUID()}`,
        }),
      );
      return;
    }

    if (action === "ticket-warn-adjudication") {
      const rejected = commaValues(values.get("evidence_rejected"));
      const noEvidenceRejectedAcknowledged =
        values.get("no_evidence_rejected") === "acknowledged";
      submitMutation(form, "正在写入 WARN 人工裁决…", () => {
        if (!rejected.length && !noEvidenceRejectedAcknowledged) {
          throw new Error("请填写拒绝的证据，或明确确认没有拒绝任何证据");
        }
        return postJson("/api/v1/actions", {
          action_type: "record_adjudication",
          idempotency_key: `ui:ticket-warn:${crypto.randomUUID()}`,
          payload: {
            subject_type: "ticket_audit_finding",
            subject_id: form.dataset.findingId,
            decision: "accept_warning",
            reason: values.get("reason"),
            evidence_rejected: rejected.map((objectId) => ({
              object_type: "claim",
              object_id: objectId,
            })),
            alternative: {
              no_evidence_rejected_acknowledged:
                !rejected.length && noEvidenceRejectedAcknowledged,
            },
          },
          expected_versions: {},
        });
      });
      return;
    }

    if (action === "approve-ticket-batch") {
      const batchId = form.dataset.ticketBatchId;
      submitMutation(form, "正在批准不可变批次版本…", () =>
        postJson(`/api/v1/ticket-batches/${batchId}/approve`, {
          schema_version: "1",
          expected_revision_no: Number(form.dataset.revisionNo),
          idempotency_key: `ui:ticket-approve:${crypto.randomUUID()}`,
        }),
      );
      return;
    }

    if (action === "issue-ticket-confirmation") {
      issueConfirmation(form);
      return;
    }

    if (action === "confirm-ticket-placement") {
      const artifactId = form.dataset.ticketArtifactId;
      const receipt = values.get("receipt");
      submitMutation(form, "正在确认人工出票并原子入账…", async () => {
        if (!(receipt instanceof File) || !receipt.size) {
          throw new Error("请选择出票回执");
        }
        return postJson(`/api/v1/ticket-artifacts/${artifactId}/confirm`, {
          schema_version: "1",
          confirmation_id: values.get("confirmation_id"),
          nonce: values.get("nonce"),
          ticket_hash: form.dataset.ticketHash,
          amount: Number(form.dataset.amount),
          currency: form.dataset.currency,
          channel: form.dataset.channel,
          placement_mode: "manual",
          external_reference: values.get("external_reference"),
          receipt_base64: await fileBase64(receipt),
          receipt_content_type: receipt.type || "application/octet-stream",
          idempotency_key: `ui:ticket-placement:${crypto.randomUUID()}`,
        });
      });
      return;
    }

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

    if (action === "record-scoreboard-observation") {
      submitMutation(form, "正在记录人工观察…", () =>
        postJson("/api/v1/actions", {
          action_type: "record_scoreboard_observation",
          idempotency_key: `ui:scoreboard-observation:${crypto.randomUUID()}`,
          payload: {
            group_key: values.get("group_key"),
            metric_key: values.get("metric_key"),
            tally: values.get("tally"),
            detail: values.get("detail"),
            status: values.get("status"),
            numerator: optionalNumber(values.get("numerator")),
            denominator: optionalNumber(values.get("denominator")),
            value: optionalNumber(values.get("value")),
            unit: values.get("unit") || null,
            evidence_refs: [
              {
                object_type: values.get("evidence_type"),
                object_id: values.get("evidence_id"),
              },
            ],
            effective_at: values.get("effective_at"),
            supersedes_observation_id: null,
          },
          expected_versions: {},
        }),
      );
      return;
    }

    if (action === "factor-lifecycle-adjudication") {
      submitMutation(form, "正在记录生命周期裁决…", async () => {
        const decision = values.get("decision");
        const adjudication = await postJson("/api/v1/actions", {
          action_type: "record_adjudication",
          idempotency_key: `ui:factor-adjudication:${crypto.randomUUID()}`,
          payload: {
            subject_type: "factor_definition",
            subject_id: form.dataset.factorId,
            decision,
            reason: values.get("reason"),
            evidence_rejected: [],
            alternative: {
              proposal_id: form.dataset.proposalId,
              proposed_status: form.dataset.toStatus,
            },
          },
          expected_versions: {},
        });
        if (decision === "reject") return adjudication;
        const adjudicationRef = adjudication.result_refs.find(
          (ref) => ref.object_type === "adjudication",
        );
        if (!adjudicationRef) throw new Error("裁决未返回 Adjudication 引用");
        return postJson("/api/v1/actions", {
          action_type: "apply_factor_status",
          idempotency_key: `ui:factor-status:${crypto.randomUUID()}`,
          payload: {
            proposal_id: form.dataset.proposalId,
            factor_definition_id: form.dataset.factorId,
            expected_current_status: form.dataset.fromStatus,
            target_status: form.dataset.toStatus,
            adjudication_id: adjudicationRef.object_id,
          },
          expected_versions: {
            [`factor_definition:${form.dataset.factorId}`]: Number(
              form.dataset.factorVersion,
            ),
          },
        });
      });
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
