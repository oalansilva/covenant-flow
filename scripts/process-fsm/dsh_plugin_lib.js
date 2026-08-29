import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
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

const GRILL_CARD_NEEDLE = "grill-card";

function grillHaystacks(args) {
  const out = [];
  if (args == null) return out;
  if (typeof args === "string") {
    out.push(args);
    try {
      const parsed = JSON.parse(args);
      if (parsed && typeof parsed === "object") {
        out.push(...grillHaystacks(parsed));
      }
    } catch {
      // parse fail → scan the raw string already pushed
    }
    return out;
  }
  if (typeof args === "object") {
    if (typeof args.description === "string") out.push(args.description);
    if (typeof args.prompt === "string") out.push(args.prompt);
    try {
      out.push(JSON.stringify(args));
    } catch {
      // ignore cyclic / unserializable
    }
  }
  return out;
}

export function isGrillShapedSpawn(tool, args) {
  if (tool !== "subagent" && tool !== "subagent_fork") return false;
  return grillHaystacks(args).some((item) =>
    String(item).toLowerCase().includes(GRILL_CARD_NEEDLE),
  );
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

const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const FRONTMATTER_RE = /^---\n([\s\S]*?)\n---\n/;
const PROCESS_PROVIDER = "covenant-flow-process";
const PROCESS_RANK = 300;

function unquoteYamlScalar(raw) {
  const value = String(raw || "").trim();
  if (
    (value.startsWith('"') && value.endsWith('"') && value.length >= 2) ||
    (value.startsWith("'") && value.endsWith("'") && value.length >= 2)
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function parseStubFrontmatter(text) {
  const match = FRONTMATTER_RE.exec(String(text || ""));
  if (!match) return null;
  const block = match[1];
  const nameMatch = /^name:\s*(.*)$/m.exec(block);
  const descMatch = /^description:\s*(.*)$/m.exec(block);
  if (!nameMatch || !descMatch) return null;
  const name = unquoteYamlScalar(nameMatch[1]);
  const description = unquoteYamlScalar(descMatch[1]);
  if (!SKILL_NAME_RE.test(name) || !description) return null;
  return { name, description };
}

export function readAgentsStub(root = REPO_ROOT) {
  try {
    return readFileSync(join(root, "AGENTS.md"), "utf8");
  } catch {
    return "";
  }
}

export function createRepoDshSkillProvider(root) {
  const skillsRoot = join(root, ".dsh", "skills");
  return {
    name: PROCESS_PROVIDER,
    async list(options) {
      void options;
      try {
        if (!existsSync(skillsRoot) || !statSync(skillsRoot).isDirectory()) {
          return [];
        }
        const out = [];
        for (const entry of readdirSync(skillsRoot, { withFileTypes: true })) {
          if (!entry.isDirectory()) continue;
          const directory = join(skillsRoot, entry.name);
          const path = join(directory, "SKILL.md");
          let text;
          try {
            text = readFileSync(path, "utf8");
          } catch {
            continue;
          }
          const parsed = parseStubFrontmatter(text);
          if (!parsed) continue;
          if (parsed.name !== entry.name) continue;
          out.push({
            name: parsed.name,
            description: parsed.description,
            invocation: { modelInvocable: true, userInvocable: true },
            source: "custom",
            rank: PROCESS_RANK,
            provider: PROCESS_PROVIDER,
            locator: { path, directory },
            path,
          });
        }
        return out;
      } catch {
        return [];
      }
    },
    async get(candidate, options) {
      void options;
      const path =
        (candidate &&
          (candidate.path ||
            (candidate.locator && candidate.locator.path))) ||
        "";
      const content = readFileSync(path, "utf8");
      return {
        name: candidate.name,
        description: candidate.description,
        invocation: candidate.invocation,
        source: candidate.source,
        rank: candidate.rank,
        provider: PROCESS_PROVIDER,
        locator: candidate.locator,
        path,
        content,
      };
    },
  };
}
