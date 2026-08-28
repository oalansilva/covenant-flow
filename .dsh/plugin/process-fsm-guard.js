import {
  REPO_ROOT,
  runGuard,
  runPage,
  denyFromDecision,
  isCordisRestricted,
} from "../../scripts/process-fsm/dsh_plugin_lib.js";

export const name = "covenant-flow-process-fsm-guard";
export const inject = ["systemPrompt"];

export function apply(ctx) {
  const cwd = process.cwd() || REPO_ROOT;
  ctx.on("tools/pre-execute", async (exec, next) => {
    const tool = exec && exec.name;
    const args = (exec && exec.arguments) || {};
    if (isCordisRestricted(tool)) {
      return { kind: "deny", reason: "process-fsm-guard deny reason=cordis_restrict" };
    }
    const decision = runGuard({ tool, args, cwd });
    const denied = denyFromDecision(decision, tool, args);
    if (denied) return denied;
    return next();
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
}
