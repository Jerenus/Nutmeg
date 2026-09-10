(() => {
  "use strict";

  const feedback = document.querySelector("#action-feedback");
  const focusStorageKey = "nutmeg.operator.focus-after-command";

  function restoreCommandFocus() {
    if (sessionStorage.getItem(focusStorageKey) !== "true") return;
    sessionStorage.removeItem(focusStorageKey);
    const target = document.querySelector("[data-primary-command='true'] button")
      || document.querySelector("[data-primary-command='true']")
      || document.querySelector("#main-content");
    if (target) target.focus();
  }

  restoreCommandFocus();
  if (document.body.dataset.readOnly === "true") return;

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
    if (!response.ok) {
      const error = new Error(result.message || result.code);
      error.recoveryHref = result.details?.recovery_href || null;
      throw error;
    }
    return result;
  }

  function taskCoordinates(taskKey) {
    const separator = taskKey.indexOf(":");
    if (separator < 1 || separator === taskKey.length - 1) {
      throw new Error("当前任务标识无效，请返回 Today 重新进入。");
    }
    return [taskKey.slice(0, separator), taskKey.slice(separator + 1)];
  }

  async function currentOperatorTask(form) {
    const taskKey = form.dataset.taskKey;
    const [lane, businessKey] = taskCoordinates(taskKey);
    const response = await fetch(
      `/api/v2/operator/tasks/${encodeURIComponent(lane)}/${encodeURIComponent(businessKey)}`,
      {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      },
    );
    const task = await response.json();
    if (!response.ok) throw new Error(task.message || task.code || "无法刷新当前任务。");
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
      const result = await operation();
      if (feedback) feedback.textContent = "已保存，正在进入下一步。";
      sessionStorage.setItem(focusStorageKey, "true");
      window.location.assign(result.navigation_href || window.location.pathname);
    } catch (error) {
      controls.forEach((control) => { control.disabled = false; });
      if (feedback) feedback.textContent = error.message || "保存失败，请重试。";
      if (error.recoveryHref) {
        sessionStorage.setItem(focusStorageKey, "true");
        window.location.assign(error.recoveryHref);
      }
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
    const legacySnapshot = form.closest("[data-snapshot-token]");
    const expectedToken = legacySnapshot ? legacySnapshot.dataset.snapshotToken : null;

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

    if (action === "request-settlement") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "request_settlement",
          expected_snapshot_token: step.settlement_command_token,
          idempotency_key: `ui:operator:request-settlement:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
        });
      });
    }

    if (action === "grade-prediction-v2") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        const forecast = step.forecast_truth.find(
          (item) => item.prediction_review_token === form.dataset.predictionToken,
        );
        if (!forecast) throw new Error("预测复盘项已经变化，请刷新后重试。");
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "grade_prediction",
          expected_snapshot_token: forecast.grade_command_token,
          idempotency_key: `ui:operator:grade-prediction:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          prediction_review_token: forecast.prediction_review_token,
          outcome: values.get("outcome"),
          reason: values.get("reason"),
        });
      });
    }

    if (action === "record-scoreboard-effect") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        const intervention = step.intervention_quality;
        const disposition = values.get("disposition");
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "record_scoreboard_effect_disposition",
          expected_snapshot_token: intervention.effect_command_token,
          idempotency_key: `ui:operator:review-effect:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          review_token: intervention.review_token,
          effect: {
            disposition,
            metric_keys: disposition === "effect_required"
              ? commaValues(values.get("metric_keys"))
              : [],
            reason: values.get("reason"),
          },
        });
      });
    }

    if (action === "record-scoreboard-observation") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        const intervention = step.intervention_quality;
        const metricKey = form.dataset.metricKey;
        if (!intervention.required_metric_keys.includes(metricKey)) {
          throw new Error("治理指标已经变化，请刷新后重试。");
        }
        const optionalDecimal = (name) => {
          const value = values.get(name).trim();
          return value === "" ? null : value;
        };
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "record_scoreboard_observation",
          expected_snapshot_token: intervention.observation_command_token,
          idempotency_key: `ui:operator:review-observation:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          review_token: intervention.review_token,
          disposition_token: intervention.disposition_token,
          observation: {
            group_key: "review-effect",
            metric_key: metricKey,
            tally: values.get("tally"),
            detail: values.get("detail"),
            status: values.get("status"),
            numerator_decimal: optionalDecimal("numerator_decimal"),
            denominator_decimal: optionalDecimal("denominator_decimal"),
            value_decimal: optionalDecimal("value_decimal"),
            unit: values.get("unit"),
            evidence_ref_tokens: values.getAll("evidence_ref_token"),
            effective_at: new Date().toISOString(),
            supersedes_observation_token: null,
          },
        });
      });
    }

    if (action === "request-scoreboard-review-completion") {
      return submit(form, async () => {
        const step = await currentOperatorStep(form);
        const intervention = step.intervention_quality;
        const shadowToken = values.get("shadow_review_token");
        const selected = intervention.shadow_options.find(
          (item) => item.token === shadowToken && item.state === "ready",
        );
        if (!selected) throw new Error("影子核对记录已经变化，请刷新后重试。");
        return postJson("/api/v2/operator", {
          schema_version: "2",
          kind: "request_scoreboard_review_completion",
          expected_snapshot_token: intervention.completion_command_token,
          idempotency_key: `ui:operator:review-completion:${crypto.randomUUID()}`,
          task_key: form.dataset.taskKey,
          review_token: intervention.review_token,
          disposition_token: intervention.disposition_token,
          shadow_review_token: selected.token,
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
      const facePrecedents = [...form.querySelectorAll("[data-precedent-row]")]
        .map((row) => ({
          face_code: row.dataset.precedentFaceCode,
          precedent_ref: row.querySelector('input[name="precedent_ref"]').value.trim(),
          status: row.querySelector('select[name="precedent_status"]').value,
        }))
        .filter((precedent) => precedent.precedent_ref !== "");
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
        anchor_integrity: values.get("anchor_integrity"),
        face_precedents: facePrecedents,
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
  if (waiting) window.setTimeout(() => window.location.assign(window.location.href), 15000);
})();
