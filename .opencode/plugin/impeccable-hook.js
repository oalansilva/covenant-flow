// 1.18.18 legacy loader instantiates every named export; only default is the plugin.
import {
  REPO_ROOT,
  mapAfterPayload,
  mapIdlePayload,
  runHookMjs,
} from "../../scripts/process-fsm/opencode_plugin_lib.js";

export default async function impeccableHook(input = {}) {
  const directory = input.directory || input.worktree || REPO_ROOT;
  return {
    "tool.execute.after": async (hookInput) => {
      try {
        runHookMjs(mapAfterPayload(hookInput || {}), directory);
      } catch {
        // fail-open: never throw
      }
    },
    event: async (bus) => {
      try {
        const type = bus && bus.event && bus.event.type;
        if (type === "session.idle") {
          runHookMjs(mapIdlePayload(), directory);
        }
      } catch {
        // fail-open: never throw
      }
    },
  };
}
