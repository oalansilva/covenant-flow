import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(LIB_DIR, "..", "..");
const WRITEISH = new Set(["write", "edit", "apply_patch", "bash"]);
const PATCH_MARKERS = [
  "*** Add File:",
  "*** Update File:",
  "*** Delete File:",
  "*** Move to:",
  "*** Move File:",
];

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

export function assertAllow(decision, tool) {
  if (decision && (decision.permission === "deny" || decision.decision === "deny")) {
    throw new Error(
      decision.reason || decision.agent_message || "process-fsm-guard deny",
    );
  }
  if (!decision && WRITEISH.has(tool)) {
    throw new Error("process-fsm-guard deny reason=fail_closed");
  }
}

function firstPatchPath(text) {
  if (typeof text !== "string" || !text) return "";
  for (const line of text.split(/\r?\n/)) {
    const stripped = line.trim();
    for (const marker of PATCH_MARKERS) {
      if (stripped.startsWith(marker)) {
        const found = stripped.slice(marker.length).trim();
        if (found) return found;
      }
    }
  }
  return "";
}

export function mapAfterPayload(input = {}) {
  const args = input.args && typeof input.args === "object" ? input.args : {};
  let filePath = "";
  if (typeof args.filePath === "string" && args.filePath.trim()) {
    filePath = args.filePath.trim();
  } else if (typeof args.path === "string" && args.path.trim()) {
    filePath = args.path.trim();
  } else {
    filePath = firstPatchPath(args.patchText);
  }
  return {
    hook_event_name: "PostToolUse",
    file_path: filePath,
    tool: input.tool,
    args,
  };
}

export function mapIdlePayload() {
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
    env: { ...process.env, IMPECCABLE_HOOK_HARNESS: "opencode" },
  });
  return proc.status === null ? 0 : proc.status;
}
