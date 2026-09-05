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
  isDshChildAgent,
  agentSessionId,
  childParentSessionKey,
  spawnCallerSessionId,
} from "../../scripts/process-fsm/dsh_plugin_lib.js";

export const name = "covenant-flow-process-fsm-guard";
export const inject = ["systemPrompt", "skills"];

export function apply(ctx) {
  const cwd = process.cwd() || REPO_ROOT;
  const retriedAgents = new Set();
  const spawnBlockedParents = new Set();
  ctx.on("agent/request", async (payload, next) => sanitizeReasoningEffort(await next()));
  ctx.on("agent/request-error", async (payload, next) => {
    if (!isReasoningEffortRejection(payload && payload.failure)) {
      return next();
    }
    if (isDshChildAgent(payload)) {
      const parentKey = childParentSessionKey(payload);
      if (parentKey) spawnBlockedParents.add(parentKey);
    }
    const sessionId = agentSessionId(payload && payload.agent);
    const retryKey = sessionId || "__missing_session__";
    if (retriedAgents.has(retryKey)) {
      return next();
    }
    retriedAgents.add(retryKey);
    return { kind: "retry" };
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
