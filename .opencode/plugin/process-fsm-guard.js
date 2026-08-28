// 1.18.18 legacy loader instantiates every named export; only default is the plugin.
import {
  REPO_ROOT,
  runGuard,
  runPage,
  assertAllow,
} from "../../scripts/process-fsm/opencode_plugin_lib.js";

export default async function processFsmGuard(input = {}) {
  const directory = input.directory || input.worktree || REPO_ROOT;
  return {
    "tool.execute.before": async (hookInput, output) => {
      const envelope = {
        tool: hookInput.tool,
        args: (output && output.args) || {},
        cwd: directory,
      };
      const decision = runGuard(envelope);
      assertAllow(decision, hookInput.tool);
    },
    "experimental.chat.system.transform": async (_hookInput, output) => {
      const page = runPage(directory);
      const body = page && page.additional_context;
      if (typeof body === "string" && body.trim() && output && Array.isArray(output.system)) {
        output.system.push(body);
      }
    },
  };
}
