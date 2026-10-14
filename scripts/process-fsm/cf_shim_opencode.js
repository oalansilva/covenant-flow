// Covenant Flow account shim for OpenCode: the in-process counterpart of `cf_shim.py`.
//
// OpenCode loads plugins in process, so this one global plugin asks the Python shim what to do for
// the session directory (`cf_shim.py opencode decide`), and only imports and calls the adapter
// modules that the pinned consumer manifest lists. It holds no FSM, Guard, paging or model-selection
// logic. Without a pin it does nothing; with a broken pin it denies the gating tools with the reason.
import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const SHIM = join(homedir(), ".config", "covenant-flow", "shim", "current", "cf_shim.py");
// Tools that can write or spawn; reading is never blocked by a shim failure.
const GATED = new Set(["write", "edit", "apply_patch", "patch", "multiedit", "bash", "task"]);

function decide(directory, tool) {
  try {
    const args = [SHIM, "opencode", "decide", "--cwd", directory];
    if (tool) args.push("--tool", tool);
    const out = execFileSync("python3", args, { encoding: "utf8", timeout: 30000 });
    return JSON.parse(out.trim().split("\n").pop());
  } catch (error) {
    return {
      action: "fail",
      code: "shim_error",
      message: `process-fsm-guard deny reason=shim_error. ${error && error.message ? error.message : error}. Recovery: check the shim with install.sh --account --check.`,
    };
  }
}

export default async function covenantFlowShim(ctx = {}) {
  const directory = ctx.directory || ctx.worktree || process.cwd();
  const loaded = new Map();
  let last = decide(directory, null);

  async function hooksFor(decision) {
    if (!decision || decision.action !== "run") return [];
    const found = [];
    for (const modulePath of decision.modules || []) {
      if (!loaded.has(modulePath)) {
        try {
          const module = await import(pathToFileURL(modulePath).href);
          loaded.set(modulePath, typeof module.default === "function" ? await module.default(ctx) : {});
        } catch (error) {
          loaded.set(modulePath, { __failed: String(error && error.message ? error.message : error) });
        }
      }
      const hooks = loaded.get(modulePath);
      if (hooks.__failed) throw new Error(`process-fsm-guard deny reason=adapter_missing. ${hooks.__failed}`);
      found.push(hooks);
    }
    return found;
  }

  async function forward(name, args, decision) {
    for (const hooks of await hooksFor(decision)) {
      if (typeof hooks[name] === "function") await hooks[name](...args);
    }
  }

  return {
    "tool.execute.before": async (input, output) => {
      const tool = String((input && input.tool) || "");
      last = decide(directory, tool);
      if (last.action === "fail" && GATED.has(tool)) throw new Error(last.message);
      await forward("tool.execute.before", [input, output], last);
    },
    "tool.execute.after": async (input, output) => {
      try {
        await forward("tool.execute.after", [input, output], last);
      } catch {
        // advisory: never throw
      }
    },
    "experimental.chat.system.transform": async (input, output) => {
      last = decide(directory, null);
      if (last.action === "fail") {
        if (output && Array.isArray(output.system)) output.system.push(`Covenant Flow: ${last.message}`);
        return;
      }
      try {
        await forward("experimental.chat.system.transform", [input, output], last);
      } catch {
        // page is advisory
      }
    },
    event: async (bus) => {
      try {
        await forward("event", [bus], last);
      } catch {
        // advisory: never throw
      }
    },
  };
}
