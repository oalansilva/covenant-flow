import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(LIB_DIR, "..", "..");
const WRITEISH = new Set(["write", "edit", "bash"]);
const EDITOR_MUTATE = new Set(["create", "str_replace", "insert"]);

function pythonBin() {
  const venv = join(REPO_ROOT, "backend", ".venv", "bin", "python");
  if (existsSync(venv)) return venv;
  return "python3";
}

function parseJsonLine(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  const line = raw.split("\n").filter(Boolean).pop();
  try {
    const parsed = JSON.parse(line);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function runGuard(envelope) {
  const script = join(REPO_ROOT, "scripts", "process-fsm", "guard.py");
  const proc = spawnSync(pythonBin(), [script], {
    input: JSON.stringify(envelope),
    encoding: "utf8",
    cwd: envelope.cwd || REPO_ROOT,
    timeout: 30000,
    env: process.env,
  });
  return parseJsonLine(proc.stdout);
}

export function runPage(cwd) {
  const script = join(REPO_ROOT, "scripts", "process-fsm", "paging.py");
  const proc = spawnSync(pythonBin(), [script], {
    input: JSON.stringify({ cwd }),
    encoding: "utf8",
    cwd,
    timeout: 30000,
    env: process.env,
  });
  return parseJsonLine(proc.stdout);
}

export function isCordisRestricted(tool) {
  if (typeof tool !== "string" || !tool.startsWith("cordis_")) return false;
  if (tool.startsWith("cordis_inspect_")) return false;
  return true;
}

export function isWriteLike(tool, args = {}) {
  if (WRITEISH.has(tool)) return true;
  if (tool === "str_replace_editor") {
    return EDITOR_MUTATE.has(args && args.command);
  }
  if (isCordisRestricted(tool)) return true;
  return false;
}

export function denyFromDecision(decision, tool, args) {
  if (decision && (decision.permission === "deny" || decision.decision === "deny")) {
    return {
      kind: "deny",
      reason: decision.reason || decision.agent_message || "process-fsm-guard deny",
    };
  }
  if (!decision && isWriteLike(tool, args)) {
    return { kind: "deny", reason: "process-fsm-guard deny reason=fail_closed" };
  }
  return null;
}

export function mapAfterPayload(input = {}) {
  const args =
    (input.args && typeof input.args === "object" && input.args) ||
    (input.arguments && typeof input.arguments === "object" && input.arguments) ||
    {};
  let targetPath = "";
  if (typeof args.file_path === "string" && args.file_path.trim()) {
    targetPath = args.file_path.trim();
  } else if (typeof args.path === "string" && args.path.trim()) {
    targetPath = args.path.trim();
  }
  return {
    hook_event_name: "PostToolUse",
    file_path: targetPath,
    tool: input.tool,
    args,
  };
}

export function mapTurnStoppingPayload() {
  return { hook_event_name: "Stop" };
}

export function runHookMjs(payload, cwd) {
  const hook = join(REPO_ROOT, ".agents", "skills", "impeccable", "scripts", "hook.mjs");
  if (!existsSync(hook)) return 0;
  const proc = spawnSync("node", [hook], {
    input: JSON.stringify(payload),
    encoding: "utf8",
    cwd: cwd || REPO_ROOT,
    timeout: 30000,
    env: { ...process.env, IMPECCABLE_HOOK_HARNESS: "dsh" },
  });
  return proc.status === null ? 0 : proc.status;
}
