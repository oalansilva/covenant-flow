import {
  REPO_ROOT,
  runGuard,
  runPage,
  denyFromDecision,
  isCordisRestricted,
  isGrillShapedSpawn,
  readAgentsStub,
  createRepoDshSkillProvider,
  sanitizeReasoningEffort,
  isReasoningEffortRejection,
  agentSessionId,
  spawnCallerSessionId,
  attachAgentEffortGuards,
  createReasoningEffortRequestErrorHandler,
  formatChildRunFailure,
} from "../../scripts/process-fsm/dsh_plugin_lib.js";

export const name = "covenant-flow-process-fsm-guard";
export const inject = ["systemPrompt", "skills"];

const PLUGIN_NOTICE_SOURCE = {
  kind: "plugin",
  plugin: name,
  form: "notice",
};

function sessionIdFromSession(session) {
  if (typeof session === "string" && session.trim()) return session.trim();
  if (!session || typeof session !== "object") return "";
  if (typeof session.id === "string" && session.id.trim()) return session.id.trim();
  const header = session.header;
  if (header && typeof header.id === "string" && header.id.trim()) return header.id.trim();
  return "";
}

function headerFromSession(session) {
  if (!session || typeof session !== "object") return {};
  if (session.header && typeof session.header === "object") return session.header;
  return {};
}

function agentsMapOf(ctx) {
  try {
    if (typeof ctx.get === "function") {
      const viaGet = ctx.get("agents");
      if (viaGet && typeof viaGet.get === "function") return viaGet;
    }
  } catch {
    // ignore
  }
  const direct = ctx.agents;
  if (direct && typeof direct.get === "function") return direct;
  return null;
}

function parentLineageClosing(parent) {
  if (!parent || typeof parent !== "object") return false;
  if (parent.closing === true || parent.lineageClosing === true) return true;
  const status = parent.status;
  return status === "closed" || status === "disposed" || status === "disposing";
}

function deliverParentNotice(parent, message) {
  if (!parent || typeof parent !== "object") return;
  if (parentLineageClosing(parent)) {
    if (typeof parent.inject === "function") parent.inject(message);
    return;
  }
  if (parent.status === "idle" && typeof parent.followup === "function") {
    parent.followup(message);
    return;
  }
  if (typeof parent.steer === "function") parent.steer(message);
}

function resultTextOf(result) {
  if (result == null) return "";
  const raw = result.content;
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) {
    return raw
      .map((block) => (block && typeof block.text === "string" ? block.text : ""))
      .join(" ");
  }
  if (result.error && typeof result.error.message === "string") return result.error.message;
  return "";
}

function isForegroundOneShotSubagent(exec) {
  const tool = exec && exec.name;
  if (tool !== "subagent" && tool !== "subagent_fork") return false;
  const args = (exec && exec.arguments) || {};
  if (args.run_in_background === true) return false;
  return true;
}

function isForegroundSubagentFailureResult(result) {
  if (!result || result.isError !== true) return false;
  return /subagent run failed/i.test(resultTextOf(result));
}

function rewriteExecuteContent(result, text) {
  const out = { ...result, isError: true };
  if (Array.isArray(result && result.content)) {
    out.content = [{ type: "text", text }];
  } else {
    out.content = text;
  }
  return out;
}

function lookupChildFailure(store, exec) {
  const parentId = agentSessionId(exec && exec.agent);
  let found = null;
  for (const rec of store.values()) {
    const parentKey = rec && rec.header && rec.header.parentSession;
    if (parentId && parentKey && String(parentKey) === parentId) found = rec;
  }
  if (found) return found;
  for (const rec of store.values()) {
    if (rec && isReasoningEffortRejection(rec.reason)) return rec;
  }
  return null;
}

export function apply(ctx) {
  const cwd = process.cwd() || REPO_ROOT;
  const retriedAgents = new Set();
  const spawnBlockedParents = new Set();
  const effortState = { retriedAgents, spawnBlockedParents };
  const childTurnEnds = new Map();
  ctx.on("agent/request", async (payload, next) => sanitizeReasoningEffort(await next()));
  ctx.on("agent/request-error", createReasoningEffortRequestErrorHandler(effortState));
  ctx.on(
    "agent/created",
    (payload) => {
      try {
        const agent = payload && payload.agent;
        attachAgentEffortGuards(agent && agent.ctx, effortState);
      } catch {
        // attach MUST NOT veto child publication
      }
    },
    { global: true },
  );
  ctx.on(
    "session/event",
    (session, event) => {
      try {
        if (!event || event.type !== "turn/end") return;
        const data = event.data && typeof event.data === "object" ? event.data : {};
        const reason = data.reason || event.reason;
        if (!reason || reason.kind !== "error") return;
        const sid = sessionIdFromSession(session);
        const header = headerFromSession(session);
        const rec = { reason, header, stopReason: "error" };
        if (sid) childTurnEnds.set(sid, rec);
        const parentKey = header.parentSession ? String(header.parentSession) : "";
        if (!parentKey) return;
        const agents = agentsMapOf(ctx);
        const parent = agents && agents.get(parentKey);
        if (!parent) return;
        const text = formatChildRunFailure({ stopReason: "error", failure: reason });
        deliverParentNotice(parent, {
          content: [{ type: "text", text }],
          source: PLUGIN_NOTICE_SOURCE,
        });
      } catch {
        // session/event must not throw
      }
    },
    { global: true },
  );
  ctx.on("tools/execute", async (exec, next) => {
    if (!isForegroundOneShotSubagent(exec)) return next();
    const result = await next();
    if (!isForegroundSubagentFailureResult(result)) return result;
    const rec = lookupChildFailure(childTurnEnds, exec);
    const failure = rec ? rec.reason : { message: resultTextOf(result) };
    const text = formatChildRunFailure({
      stopReason: (rec && rec.stopReason) || "error",
      failure,
    });
    return rewriteExecuteContent(result, text);
  });
  ctx.on("tools/pre-execute", async (exec, next) => {
    const tool = exec && exec.name;
    const args = (exec && exec.arguments) || {};
    if (isGrillShapedSpawn(tool, args)) {
      return { kind: "deny", reason: "process-fsm-guard deny reason=dsh_grill_spawn" };
    }
    if (tool === "subagent" || tool === "subagent_fork") {
      const caller = spawnCallerSessionId(exec);
      if (caller && spawnBlockedParents.has(caller)) {
        return {
          kind: "deny",
          reason: "process-fsm-guard deny reason=dsh_reasoning_effort_spawn",
        };
      }
    }
    if (isCordisRestricted(tool)) {
      return { kind: "deny", reason: "process-fsm-guard deny reason=cordis_restrict" };
    }
    const decision = runGuard({ tool, args, cwd });
    const denied = denyFromDecision(decision, tool, args);
    if (denied) return denied;
    return next();
  });
  ctx.systemPrompt.section({
    name: "covenant-flow:agents",
    order: 40,
    text: () => readAgentsStub(),
  });
  ctx.systemPrompt.section({
    name: "covenant-flow:moore",
    order: 50,
    text: () => {
      const page = runPage(cwd);
      const body = page && page.additional_context;
      return typeof body === "string" ? body : "";
    },
  });
  if (typeof ctx.skills?.registerProvider === "function") {
    try {
      ctx.skills.registerProvider((control) => {
        void control;
        return createRepoDshSkillProvider(REPO_ROOT);
      });
    } catch {
      // provider throw must not skip deny
    }
  }
}
