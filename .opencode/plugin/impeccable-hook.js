// 1.18.18 legacy loader instantiates every named export; only default is the plugin.
import {
  mapAfterPayload,
  mapIdlePayload,
  resolveRepoCwd,
  runHookMjs,
} from "../../scripts/process-fsm/opencode_plugin_lib.js";

export default async function impeccableHook(input = {}) {
  const cwd = resolveRepoCwd(input.directory || input.worktree);
  return {
    "tool.execute.after": async (hookInput) => {
      try {
        runHookMjs(mapAfterPayload(hookInput || {}), cwd);
      } catch {
        // fail-open: never throw
      }
    },
    event: async (bus) => {
      try {
        const type = bus && bus.event && bus.event.type;
        if (type === "session.idle") {
          runHookMjs(mapIdlePayload(), cwd);
        }
      } catch {
        // fail-open: never throw
      }
    },
  };
}
