(() => {
  "use strict";

  if (document.body.dataset.readOnly === "true") return;

  const feedback = document.querySelector("#action-feedback");

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

  function taskSnapshotToken(hexDigest) {
    const bytes = hexDigest.match(/.{2}/g).map((pair) => Number.parseInt(pair, 16));
    const binary = String.fromCharCode(...bytes);
    return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  }

  async function currentOperatorTask(form) {
    const taskKey = form.dataset.taskKey;
    const response = await fetch(`/api/v1/operator/tasks/${encodeURIComponent(taskKey)}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const task = await response.json();
    if (!response.ok) throw new Error(task.message || task.code || "无法刷新当前任务。");
    const pageToken = form.closest("[data-snapshot-token]").dataset.snapshotToken;
    if (pageToken !== taskSnapshotToken(task.mutation_token)) {
      throw new Error("页面数据已经变化，请刷新后重试。");
    }
    return task;
  }

  async function currentOperatorStep(form) {
    return (await currentOperatorTask(form)).step;
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
    const expectedToken = form.closest("[data-snapshot-token]").dataset.snapshotToken;

    if (action === "create-ticket-batch") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "create_ticket_batch",
          expected_snapshot_token: step.command_token,
          idempotency_key: `ui:operator:create-ticket-batch:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          candidate_selection_token: step.candidate_selection_token,
        });
      });
    }

    if (action === "adjudicate-audit-warn") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        const findings = [...form.querySelectorAll('input[name="finding_token"]:checked')]
          .map((input) => {
            const index = Number.parseInt(input.value, 10);
            const row = input.closest("[data-finding-index]");
            return {
              finding_token: step.findings[index].finding_token,
              reason: row.querySelector("[data-warn-reason]").value,
              evidence_rejected_tokens: [],
            };
          });
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "adjudicate_audit_warn",
          expected_snapshot_token: step.command_token,
          idempotency_key: `ui:operator:audit-warn:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          ticket_batch_token: step.ticket_batch_token,
          findings,
        });
      });
    }

    if (action === "approve-ticket-batch") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "approve_ticket_batch",
          expected_snapshot_token: step.command_token,
          idempotency_key: `ui:operator:approve-ticket-batch:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          ticket_batch_token: step.ticket_batch_token,
        });
      });
    }

    if (action === "request-confirmation") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "request_confirmation",
          expected_snapshot_token: step.command_token,
          idempotency_key: `ui:operator:request-confirmation:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          ticket_artifact_token: step.ticket_artifact_token,
        });
      });
    }

    if (action === "record-no-ticket") {
      return submit(form, async () => {
        const task = await currentOperatorTask(form);
        const control = task.no_ticket || {
          command_token: task.step.no_ticket_command_token,
          comparison_candidate_token: task.step.comparison_candidate_token,
          rule_options: task.step.rule_options,
        };
        const ruleTokens = values.getAll("rule_index")
          .map((index) => control.rule_options[Number.parseInt(index, 10)].token);
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "record_no_ticket",
          expected_snapshot_token: control.command_token,
          idempotency_key: `ui:operator:no-ticket:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          reason_code: values.get("reason_code"),
          reason_basis: values.get("reason_basis"),
          reason_text: values.get("reason_text"),
          rule_tokens: ruleTokens,
          comparison_candidate_token: control.comparison_candidate_token,
        });
      });
    }

    if (action === "supersede-no-ticket") {
      return submit(form, async () => {
        const task = await currentOperatorTask(form);
        const control = task.no_ticket || {
          command_token: task.step.command_token,
          no_ticket_revision_token: task.step.no_ticket_revision_token,
        };
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "supersede_no_ticket",
          expected_snapshot_token: control.command_token,
          idempotency_key: `ui:operator:supersede-no-ticket:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          no_ticket_revision_token: control.no_ticket_revision_token,
          reason_text: values.get("supersede_reason"),
        });
      });
    }

    if (action === "freeze-evidence") {
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "freeze_evidence",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:evidence:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        requirement_revision_token: form.dataset.requirementToken,
      }));
    }

    if (action === "record-baseline-envelope") {
      const offerConstraints = [...form.querySelectorAll("[data-envelope-offer]")]
        .map((offer) => ({
          official_match_no: offer.dataset.officialMatchNo,
          market_code: offer.dataset.marketCode,
          allowed_face_bundles: [...offer.querySelectorAll(
            'input[name="allowed_face_bundle"]:checked',
          )].map((input) => ({
            bundle_code: input.value,
            face_codes: commaValues(input.dataset.faceCodes),
          })),
          omission_allowed: Boolean(offer.querySelector(
            'input[name="omission_allowed"]:checked',
          )),
        }))
        .filter((offer) => offer.allowed_face_bundles.length > 0);
      const structures = [...form.querySelectorAll("[data-envelope-structure]")]
        .filter((row) => row.querySelector('input[name="structure_code"]:checked'))
        .map((row) => ({
          kind: row.dataset.kind,
          structure_code: row.dataset.structureCode,
          eligible_official_match_nos: commaValues(row.dataset.eligibleMatches),
          pass_size: row.dataset.passSize ? Number(row.dataset.passSize) : null,
          required_offer_count: Number(row.dataset.requiredOfferCount),
          maximum_groups: Number(row.dataset.maximumGroups),
        }));
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "record_baseline_envelope",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:envelope:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        ticket_kind: values.get("ticket_kind"),
        capital_cap_minor: Number(values.get("capital_cap_minor")),
        currency: form.dataset.currency,
        maximum_ticket_count: Number(values.get("maximum_ticket_count")),
        offer_constraints: offerConstraints,
        structure_templates: structures,
        maximum_exhaustive_candidate_count: Number(
          values.get("maximum_exhaustive_candidate_count"),
        ),
      }));
    }

    if (action === "commit-match-judgment") {
      const factors = [...form.querySelectorAll("[data-factor-row]")]
        .filter((row) => row.querySelector('input[name="factor_id"]:checked'))
        .map((row) => ({
          factor_id: row.dataset.factorId,
          scope_key: row.dataset.scopeKey,
          evidence_ref_tokens: [...row.querySelectorAll(
            'input[name="factor_evidence_ref_token"]',
          )].map((input) => input.value),
          offsets: [...row.querySelectorAll('input[name="factor_offset"]')]
            .map((input) => ({
              face_code: input.dataset.faceCode,
              offset_probability_decimal: input.value,
            })),
        }));
      const expressionBundles = [...form.querySelectorAll(
        'input[name="face_bundle"]:checked',
      )].map((input) => ({
        bundle_code: input.value,
        face_codes: commaValues(input.dataset.faceCodes),
      }));
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "commit_match_judgment",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:judgment:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        official_match_no: form.dataset.officialMatchNo,
        market_code: form.dataset.marketCode,
        belief: [...form.querySelectorAll('input[name="belief_probability_decimal"]')]
          .map((input) => ({
            face_code: input.dataset.faceCode,
            probability_decimal: input.value,
          })),
        factors,
        expression_bundles: expressionBundles,
        rule_ids: values.getAll("rule_id"),
        evidence_ref_tokens: values.getAll("judgment_evidence_ref_token"),
        falsifier: values.get("falsifier"),
        rationale: values.get("rationale"),
      }));
    }

    if (action === "freeze-judgment-prescription") {
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "freeze_judgment_prescription",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:prescription:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        judgment_revision_tokens: values.getAll("judgment_revision_token"),
      }));
    }

    if (action === "request-candidate-generation") {
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "request_candidate_generation",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:candidates:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        market_prior_baseline_token: values.get("market_prior_baseline_token"),
        baseline_envelope_token: values.get("baseline_envelope_token"),
        judgment_prescription_token: values.get("judgment_prescription_token"),
      }));
    }

    if (action === "select-ticket-candidate") {
      const candidateToken = values.get("candidate_token");
      return submit(form, () => postJson("/api/v2/operator", {
        schema_version: "2",
        kind: "select_candidate",
        expected_snapshot_token: form.dataset.commandToken,
        idempotency_key: `ui:operator:candidate-selection:${crypto.randomUUID()}`,
        task_key: form.dataset.taskKey,
        candidate_token: candidateToken,
        reason: values.get("reason"),
      }));
    }

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

    if (action === "request-telegram-confirmation") {
      return submit(form, () => postJson(
        `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}`
          + "/telegram-confirmation",
        {
          schema_version: "1",
          expected_snapshot_token: expectedToken,
          dry_run: false,
          idempotency_key: `ui:operator:telegram:${crypto.randomUUID()}`,
        },
      ));
    }

    if (action === "grade-prediction") {
      return submit(form, () => postJson(
        `/api/v1/operator/tasks/${encodeURIComponent(form.dataset.taskId)}`
          + "/grade-prediction",
        {
          schema_version: "1",
          expected_snapshot_token: expectedToken,
          prediction_id: form.dataset.predictionId,
          outcome: values.get("outcome"),
          reason: values.get("reason"),
          idempotency_key: `ui:operator:grade:${crypto.randomUUID()}`,
        },
      ));
    }
  });

  const waiting = document.querySelector("[data-auto-refresh='waiting']");
  if (waiting) window.setTimeout(() => window.location.reload(), 15000);
})();
