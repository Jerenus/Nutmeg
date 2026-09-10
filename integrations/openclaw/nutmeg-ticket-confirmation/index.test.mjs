import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createNutmegTicketConfirmationPlugin } from "./index.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

const CONFIG = {
  projectRoot: "/tmp/nutmeg-project",
  accountId: "nutmeg",
  ownerInstanceId: "openclaw-primary",
  allowedChatIds: ["chat-71"],
  allowedSenderIds: ["owner-71"],
  heartbeatIntervalSeconds: 30,
  leaseSeconds: 90,
};

function fakeApi(mode = "full") {
  const interactive = [];
  const services = [];
  return {
    api: {
      registrationMode: mode,
      pluginConfig: CONFIG,
      registerInteractiveHandler(value) {
        interactive.push(value);
      },
      registerService(value) {
        services.push(value);
      },
    },
    interactive,
    services,
  };
}

function callbackContext(overrides = {}) {
  const responses = [];
  return {
    responses,
    context: {
      channel: "telegram",
      accountId: "nutmeg",
      callbackId: "callback-17",
      senderId: "owner-71",
      auth: { isAuthorizedSender: true },
      callback: {
        data: "ntc:opaque-token",
        namespace: "ntc",
        payload: "opaque-token",
        messageId: 991,
        chatId: "chat-71",
      },
      respond: {
        async reply(value) {
          responses.push(["reply", value]);
        },
        async editMessage(value) {
          responses.push(["editMessage", value]);
        },
        async editButtons(value) {
          responses.push(["editButtons", value]);
        },
        async clearButtons() {
          responses.push(["clearButtons"]);
        },
        async deleteMessage() {
          responses.push(["deleteMessage"]);
        },
      },
      ...overrides,
    },
  };
}

test("package and manifest expose one matching repository plugin", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(HERE, "package.json"), "utf8"));
  const manifest = JSON.parse(
    fs.readFileSync(path.join(HERE, "openclaw.plugin.json"), "utf8"),
  );
  const plugin = createNutmegTicketConfirmationPlugin();
  const metadata = plugin[
    Symbol.for("openclaw.plugin-sdk.tool-plugin.metadata")
  ];

  assert.deepEqual(packageJson.openclaw.extensions, ["./index.js"]);
  assert.equal(manifest.id, "nutmeg-ticket-confirmation");
  assert.equal(manifest.configSchema.additionalProperties, false);
  assert.equal(manifest.configSchema.properties.token, undefined);
  assert.equal(metadata.id, manifest.id);
  assert.deepEqual(metadata.tools, []);
  assert.deepEqual(manifest.contracts.tools, []);
});

test("non-full registration modes have no runtime side effects", () => {
  for (const mode of ["discovery", "tool-discovery", "setup-only", "setup-runtime", "cli-metadata"]) {
    const calls = [];
    const plugin = createNutmegTicketConfirmationPlugin({
      runBridge: async () => calls.push("bridge"),
    });
    const state = fakeApi(mode);

    plugin.register(state.api);

    assert.deepEqual(state.interactive, []);
    assert.deepEqual(state.services, []);
    assert.deepEqual(calls, []);
  }
});

test("full mode registers exactly one ntc handler and heartbeat service", () => {
  const plugin = createNutmegTicketConfirmationPlugin({ runBridge: async () => ({ ok: true }) });
  const state = fakeApi();

  plugin.register(state.api);

  assert.equal(state.interactive.length, 1);
  assert.equal(state.interactive[0].channel, "telegram");
  assert.equal(state.interactive[0].namespace, "ntc");
  assert.equal(state.services.length, 1);
  assert.equal(state.services[0].id, "nutmeg-ticket-confirmation-heartbeat");
});

test("valid callback captures ingress first, uses stdin bridge, and never submits AI text", async () => {
  const events = [];
  const invocations = [];
  const plugin = createNutmegTicketConfirmationPlugin({
    now: () => {
      events.push("clock");
      return new Date("2026-09-05T09:59:55.000Z");
    },
    runBridge: async (invocation) => {
      events.push("bridge");
      invocations.push(invocation);
      return { ok: true, message: "Placement recorded." };
    },
  });
  const state = fakeApi();
  plugin.register(state.api);
  const { context, responses } = callbackContext();

  const result = await state.interactive[0].handler(context);

  assert.deepEqual(events, ["clock", "bridge"]);
  assert.deepEqual(result, { handled: true });
  assert.equal(Object.hasOwn(result, "submitText"), false);
  assert.equal(invocations.length, 1);
  assert.equal(invocations[0].subcommand, "callback");
  assert.equal(invocations[0].shell, false);
  assert.equal(invocations[0].stdin.server_ingress_at, "2026-09-05T09:59:55.000Z");
  assert.equal(invocations[0].stdin.callback_data, "ntc:opaque-token");
  assert.equal(invocations[0].stdin.token, undefined);
  assert.equal(invocations[0].stdin.artifact, undefined);
  assert.deepEqual(responses, [["editMessage", { text: "Placement recorded.", buttons: [] }]]);
});

test("every ntc rejection is handled locally and keeps a recoverable button", async () => {
  const rejected = [
    { accountId: "default" },
    { auth: { isAuthorizedSender: false } },
    { senderId: "other-sender" },
    { callback: { data: "ntc:x", namespace: "ntc", payload: "x", messageId: 1, chatId: "other-chat" } },
    { callback: { data: "other:x", namespace: "ntc", payload: "x", messageId: 1, chatId: "chat-71" } },
  ];
  for (const override of rejected) {
    let bridgeCalls = 0;
    const plugin = createNutmegTicketConfirmationPlugin({
      runBridge: async () => {
        bridgeCalls += 1;
        return { ok: true };
      },
    });
    const state = fakeApi();
    plugin.register(state.api);
    const { context, responses } = callbackContext(override);

    const result = await state.interactive[0].handler(context);

    assert.deepEqual(result, { handled: true });
    assert.equal(bridgeCalls, 0);
    assert.equal(responses.length, 1);
    assert.equal(responses[0][0], "reply");
    assert.ok(responses[0][1].text.length <= 160);
  }
});

test("bridge timeout and failure stay handled without submitText", async () => {
  for (const failure of [new Error("timeout"), { ok: false, retryable: true }]) {
    const plugin = createNutmegTicketConfirmationPlugin({
      runBridge: async () => {
        if (failure instanceof Error) throw failure;
        return failure;
      },
    });
    const state = fakeApi();
    plugin.register(state.api);
    const { context, responses } = callbackContext();

    const result = await state.interactive[0].handler(context);

    assert.deepEqual(result, { handled: true });
    assert.equal(responses.at(-1)[0], "reply");
    assert.ok(responses.at(-1)[1].text.length <= 160);
  }
});

test("service pulses immediately, every interval, and stops without a final pulse", async () => {
  const calls = [];
  let intervalHandler;
  let cleared;
  const plugin = createNutmegTicketConfirmationPlugin({
    runBridge: async (invocation) => {
      calls.push(invocation);
      return { ok: true };
    },
    setIntervalFn(handler, milliseconds) {
      intervalHandler = handler;
      assert.equal(milliseconds, 30_000);
      return "timer-1";
    },
    clearIntervalFn(timer) {
      cleared = timer;
    },
  });
  const state = fakeApi();
  plugin.register(state.api);

  await state.services[0].start({ logger: { warn() {}, error() {}, info() {} } });
  await intervalHandler();
  await state.services[0].stop({ logger: { warn() {}, error() {}, info() {} } });

  assert.deepEqual(calls.map((call) => call.subcommand), ["heartbeat", "heartbeat"]);
  assert.equal(cleared, "timer-1");
});
