import { spawn } from "node:child_process";
import path from "node:path";


const PLUGIN_ID = "nutmeg-ticket-confirmation";
const CONTRACT_VERSION = "openclaw-telegram-interactive-v1";
const MAX_OUTPUT_BYTES = 16_384;
const BRIDGE_TIMEOUT_MS = 10_000;


function requireConfig(raw) {
  const config = raw && typeof raw === "object" ? raw : {};
  const projectRoot = String(config.projectRoot ?? "").trim();
  const accountId = String(config.accountId ?? "").trim();
  const ownerInstanceId = String(config.ownerInstanceId ?? "").trim();
  const allowedChatIds = Array.isArray(config.allowedChatIds)
    ? config.allowedChatIds.map(String)
    : [];
  const allowedSenderIds = Array.isArray(config.allowedSenderIds)
    ? config.allowedSenderIds.map(String)
    : [];
  const heartbeatIntervalSeconds = Number(config.heartbeatIntervalSeconds ?? 30);
  const leaseSeconds = Number(config.leaseSeconds ?? 90);
  if (!path.isAbsolute(projectRoot)) {
    throw new Error("projectRoot must be absolute");
  }
  if (accountId !== "nutmeg" || !ownerInstanceId) {
    throw new Error("Nutmeg Telegram owner identity is invalid");
  }
  if (allowedChatIds.length === 0 || allowedSenderIds.length === 0) {
    throw new Error("Telegram owner allowlists are required");
  }
  if (!Number.isInteger(heartbeatIntervalSeconds) || heartbeatIntervalSeconds < 10) {
    throw new Error("heartbeatIntervalSeconds is invalid");
  }
  if (!Number.isInteger(leaseSeconds) || leaseSeconds < heartbeatIntervalSeconds) {
    throw new Error("leaseSeconds is invalid");
  }
  return {
    projectRoot,
    accountId,
    ownerInstanceId,
    allowedChatIds: new Set(allowedChatIds),
    allowedSenderIds: new Set(allowedSenderIds),
    heartbeatIntervalSeconds,
    leaseSeconds,
  };
}


function childEnvironment(authorityEnv) {
  const inherited = {};
  for (const key of [
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "UV_CACHE_DIR",
    "NUTMEG_DATA_DIR",
    "NUTMEG_PRODUCTION_DATA_DIR",
    "NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS",
  ]) {
    if (typeof process.env[key] === "string") {
      inherited[key] = process.env[key];
    }
  }
  return { ...inherited, ...authorityEnv };
}


function defaultRunBridge(request) {
  return new Promise((resolve, reject) => {
    const script = path.join(
      request.projectRoot,
      "scripts",
      "openclaw",
      "nutmeg_ticket_confirmation_bridge.py",
    );
    const argv = [
      "run",
      "python",
      script,
      request.subcommand,
      "--contract-version",
      CONTRACT_VERSION,
    ];
    const child = spawn("uv", argv, {
      cwd: request.projectRoot,
      env: childEnvironment(request.authorityEnv),
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = Buffer.alloc(0);
    let stderrBytes = 0;
    let settled = false;
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish(() => reject(new Error("Nutmeg bridge timed out")));
    }, BRIDGE_TIMEOUT_MS);
    child.stdout.on("data", (chunk) => {
      stdout = Buffer.concat([stdout, chunk]);
      if (stdout.length > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        finish(() => reject(new Error("Nutmeg bridge output exceeded limit")));
      }
    });
    child.stderr.on("data", (chunk) => {
      stderrBytes += chunk.length;
      if (stderrBytes > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        finish(() => reject(new Error("Nutmeg bridge error output exceeded limit")));
      }
    });
    child.on("error", (error) => finish(() => reject(error)));
    child.on("close", (code) => {
      finish(() => {
        if (code !== 0) {
          reject(new Error("Nutmeg bridge rejected the request"));
          return;
        }
        try {
          const parsed = JSON.parse(stdout.toString("utf8"));
          if (!parsed || parsed.ok !== true || typeof parsed.message !== "string") {
            throw new Error("invalid response");
          }
          resolve(parsed);
        } catch {
          reject(new Error("Nutmeg bridge returned an invalid response"));
        }
      });
    });
    child.stdin.end(`${JSON.stringify(request.stdin)}\n`, "utf8");
  });
}


function authorityEnvironment(config) {
  return {
    NUTMEG_TELEGRAM_ACCOUNT_ID: config.accountId,
    NUTMEG_TELEGRAM_OWNER_INSTANCE_ID: config.ownerInstanceId,
  };
}


function heartbeatRequest(config) {
  return {
    projectRoot: config.projectRoot,
    subcommand: "heartbeat",
    shell: false,
    authorityEnv: authorityEnvironment(config),
    stdin: {
      contract_version: CONTRACT_VERSION,
      plugin_id: PLUGIN_ID,
      account_id: config.accountId,
      owner_instance_id: config.ownerInstanceId,
      transport_label: "openclaw-telegram",
      router_version: "ntc-v1",
      lease_seconds: config.leaseSeconds,
    },
  };
}


async function safeReply(ctx, text) {
  try {
    await ctx.respond?.reply?.({ text: text.slice(0, 160) });
  } catch {
    // The update is still handled locally even when Telegram cannot render a reply.
  }
}


export function createNutmegTicketConfirmationPlugin(dependencies = {}) {
  const now = dependencies.now ?? (() => new Date());
  const runBridge = dependencies.runBridge ?? defaultRunBridge;
  const setIntervalFn = dependencies.setIntervalFn ?? setInterval;
  const clearIntervalFn = dependencies.clearIntervalFn ?? clearInterval;
  return {
    id: PLUGIN_ID,
    name: "Nutmeg Ticket Confirmation",
    register(api) {
      if (api.registrationMode !== "full") return;
      const config = requireConfig(api.pluginConfig);
      let heartbeatTimer;
      api.registerInteractiveHandler({
        channel: "telegram",
        namespace: "ntc",
        async handler(ctx) {
          const ingressAt = now();
          const data = ctx.callback?.data;
          const chatId = String(ctx.callback?.chatId ?? "");
          const senderId = String(ctx.senderId ?? "");
          const messageId = ctx.callback?.messageId;
          if (ctx.accountId !== config.accountId) {
            await safeReply(ctx, "确认通道不匹配。");
            return { handled: true };
          }
          if (
            ctx.auth?.isAuthorizedSender !== true
            || !config.allowedChatIds.has(chatId)
            || !config.allowedSenderIds.has(senderId)
          ) {
            await safeReply(ctx, "无权执行该确认。");
            return { handled: true };
          }
          if (typeof data !== "string" || !data.startsWith("ntc:")) {
            await safeReply(ctx, "无法确认：按钮格式不匹配。");
            return { handled: true };
          }
          if (
            typeof ctx.callbackId !== "string"
            || !ctx.callbackId
            || !senderId
            || !chatId
            || (typeof messageId !== "string" && typeof messageId !== "number")
          ) {
            await safeReply(ctx, "无法确认：回调信息不完整。");
            return { handled: true };
          }
          const document = {
            contract_version: CONTRACT_VERSION,
            plugin_id: PLUGIN_ID,
            account_id: config.accountId,
            owner_instance_id: config.ownerInstanceId,
            callback_query_id: ctx.callbackId,
            sender_id: senderId,
            chat_id: chatId,
            message_id: String(messageId),
            authorized: true,
            namespace: "ntc",
            callback_data: data,
            server_ingress_at: ingressAt.toISOString(),
          };
          try {
            const response = await runBridge({
              projectRoot: config.projectRoot,
              subcommand: "callback",
              shell: false,
              authorityEnv: authorityEnvironment(config),
              stdin: document,
            });
            if (!response || response.ok !== true || typeof response.message !== "string") {
              throw new Error("Nutmeg bridge rejected the callback");
            }
            await ctx.respond?.editMessage?.({
              text: response.message.slice(0, 160),
              buttons: [],
            });
          } catch {
            await safeReply(ctx, "确认暂未写入，请稍后重试。");
          }
          return { handled: true };
        },
      });
      api.registerService({
        id: "nutmeg-ticket-confirmation-heartbeat",
        async start(ctx) {
          const pulse = async () => {
            try {
              await runBridge(heartbeatRequest(config));
            } catch {
              ctx.logger?.warn?.("Nutmeg Telegram owner heartbeat failed");
            }
          };
          await pulse();
          heartbeatTimer = setIntervalFn(
            pulse,
            config.heartbeatIntervalSeconds * 1000,
          );
        },
        async stop() {
          if (heartbeatTimer !== undefined) {
            clearIntervalFn(heartbeatTimer);
            heartbeatTimer = undefined;
          }
        },
      });
    },
  };
}


export default createNutmegTicketConfirmationPlugin();
