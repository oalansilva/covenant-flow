import {
  REPO_ROOT,
  mapAfterPayload,
  mapTurnStoppingPayload,
  runHookMjs,
} from "../../scripts/process-fsm/dsh_plugin_lib.js";

export const name = "covenant-flow-impeccable-hook";
export const inject = [];

export function apply(ctx) {
  const cwd = process.cwd() || REPO_ROOT;
  ctx.on("tools/post-execute", async (exec, _result, next) => {
    try {
      runHookMjs(
        mapAfterPayload({
          tool: exec && exec.name,
          args: (exec && exec.arguments) || {},
        }),
        cwd,
      );
    } catch {
      // fail-open: detector must not abort the turn
    }
    return next();
  });
  ctx.on("agent/turn-stopping", async () => {
    try {
      runHookMjs(mapTurnStoppingPayload(), cwd);
    } catch {
      // fail-open: detector must not continue the turn
    }
  });
}
