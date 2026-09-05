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
const GRILL_CITATION_MARKERS = [
  "fronteira vazia",
  "do not re-interview",
  "não reentrevistar",
  "do not invoke grill-card",
  "não invocar grill-card",
  "closed grill",
  "grill-card dod",
  "dod grelhado",
  "grilled dod",
];

function collectDescriptionAndPrompt(value, seen, descriptionParts, promptParts) {
  if (value == null || typeof value !== "object") return;
  try {
    if (seen.has(value)) return;
    seen.add(value);
  } catch {
    return;
  }
  try {
    if (Array.isArray(value)) {
      for (const item of value) {
        collectDescriptionAndPrompt(item, seen, descriptionParts, promptParts);
      }
      return;
    }
    if (typeof value.description === "string") descriptionParts.push(value.description);
    if (typeof value.prompt === "string") promptParts.push(value.prompt);
    for (const child of Object.values(value)) {
      collectDescriptionAndPrompt(child, seen, descriptionParts, promptParts);
    }
  } catch {
    // cyclic / exotic objects must not throw
  }
}

function foldHaystack(parts) {
  return parts.map((part) => String(part).toLowerCase()).join(" ");
}

function hasCitationMarker(haystack) {
  for (const marker of GRILL_CITATION_MARKERS) {
    if (haystack.includes(marker)) return true;
  }
  return false;
}

export function isGrillShapedSpawn(tool, args) {
  if (tool !== "subagent" && tool !== "subagent_fork") return false;
  const descriptionParts = [];
  const promptParts = [];
  try {
    if (typeof args === "string") {
      try {
        const parsed = JSON.parse(args);
        if (parsed && typeof parsed === "object") {
          collectDescriptionAndPrompt(
            parsed,
            new WeakSet(),
            descriptionParts,
            promptParts,
          );
        } else {
          promptParts.push(args);
        }
      } catch {
        promptParts.push(args);
      }
    } else {
      collectDescriptionAndPrompt(args, new WeakSet(), descriptionParts, promptParts);
    }
  } catch {
    return false;
  }
  const descriptionHay = foldHaystack(descriptionParts);
  const promptHay = foldHaystack(promptParts);
  if (descriptionHay.includes(GRILL_CARD_NEEDLE)) return true;
  if (!promptHay.includes(GRILL_CARD_NEEDLE)) return false;
  if (hasCitationMarker(promptHay)) return false;
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

const ACCEPTED_REASONING_EFFORT = new Set(["minimal", "low", "medium", "high"]);
const REFUSED_REASONING_TOKENS = new Set(["none", "off", "", "null"]);
const EFFORT_NEEDLE_RE = /reasoning\.effort|reasoningeffort|unsupported_reasoning_effort/i;
const TOKEN_NEEDLE_RE = /\bnone\b|\boff\b|does not support/i;
const STATUS_400_RE = /invalid_request|\b400\b/i;
const RATE_LIMIT_RE = /rate[\s-]?limit|too many requests|\b429\b/i;
const UNAUTH_RE = /\b401\b|unauthorized/i;
const GUARD_DENY_RE = /process-fsm-guard deny/i;

function classifyReasoningEffort(value) {
  if (value === undefined) return { kind: "missing" };
  if (value === null) return { kind: "refused" };
  const token = String(value).trim().toLowerCase();
  if (REFUSED_REASONING_TOKENS.has(token)) return { kind: "refused" };
  if (ACCEPTED_REASONING_EFFORT.has(token)) return { kind: "accepted", value: token };
  return { kind: "other" };
}

export function sanitizeReasoningEffort(config) {
  const src =
    config && typeof config === "object" && !Array.isArray(config) ? config : {};
  const out = { ...src };
  const top = classifyReasoningEffort(out.reasoningEffort);
  let nested = { kind: "missing" };
  if (out.reasoning && typeof out.reasoning === "object" && !Array.isArray(out.reasoning)) {
    const reasoning = { ...out.reasoning };
    nested = classifyReasoningEffort(reasoning.effort);
    if (nested.kind === "refused") {
      delete reasoning.effort;
    } else if (nested.kind === "accepted") {
      reasoning.effort = nested.value;
    }
    out.reasoning = reasoning;
  }
  if (top.kind === "accepted") {
    out.reasoningEffort = top.value;
  } else if (top.kind === "missing" && nested.kind === "accepted") {
    out.reasoningEffort = nested.value;
  } else {
    out.reasoningEffort = "high";
  }
  return out;
}

function collectFailureFacts(value, parts, depth = 0) {
  if (value == null || depth > 5) return;
  const kind = typeof value;
  if (kind === "string" || kind === "number" || kind === "boolean") {
    parts.push(String(value));
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectFailureFacts(item, parts, depth + 1);
    return;
  }
  if (kind === "object") {
    for (const key of Object.keys(value)) {
      collectFailureFacts(value[key], parts, depth + 1);
    }
  }
}

function isGuardDenyFailure(failure) {
  if (!failure || typeof failure !== "object") return false;
  if (failure.kind === "deny") return true;
  const reason = String(failure.reason || failure.agent_message || "");
  return GUARD_DENY_RE.test(reason);
}

export function isReasoningEffortRejection(failure) {
  if (failure == null || failure === false) return false;
  if (isGuardDenyFailure(failure)) return false;
  const parts = [];
  collectFailureFacts(failure, parts);
  const text = parts.join(" ");
  const status =
    failure && typeof failure === "object" && typeof failure.status === "number"
      ? failure.status
      : undefined;
  if (status === 401 || UNAUTH_RE.test(text)) return false;
  if (status === 429 || RATE_LIMIT_RE.test(text)) return false;
  const effortNeedle = EFFORT_NEEDLE_RE.test(text);
  if (!effortNeedle) return false;
  const tokenNeedle = TOKEN_NEEDLE_RE.test(text);
  const status400 =
    status === 400 ||
    STATUS_400_RE.test(text) ||
    (failure &&
      typeof failure === "object" &&
      String(failure.code || "").toUpperCase() === "INVALID_REQUEST");
  return tokenNeedle || status400;
}

export function sessionHeaderOf(payload) {
  const agent = payload && payload.agent;
  const session = agent && agent.session;
  const header =
    (session && session.header) ||
    (agent && agent.header) ||
    {};
  return header && typeof header === "object" ? header : {};
}

export function agentSessionId(agent) {
  if (typeof agent === "string" && agent.trim()) return agent.trim();
  if (!agent || typeof agent !== "object") return "";
  if (typeof agent.id === "string" && agent.id.trim()) return agent.id.trim();
  const session = agent.session;
  if (typeof session === "string" && session.trim()) return session.trim();
  if (session && typeof session === "object") {
    if (typeof session.id === "string" && session.id.trim()) return session.id.trim();
    const header = session.header;
    if (header && typeof header.id === "string" && header.id.trim()) {
      return header.id.trim();
    }
  }
  return "";
}

export function isDshChildAgent(payload) {
  const header = sessionHeaderOf(payload);
  if (Number(header.delegationDepth) >= 1) return true;
  if (header.origin === "subagent") return true;
  if (header.parentSession) return true;
  return false;
}

export function childParentSessionKey(payload) {
  const header = sessionHeaderOf(payload);
  if (header.parentSession) return String(header.parentSession);
  const fallback =
    (payload && payload.parentSession) ||
    (payload && payload.agent && payload.agent.parentSession);
  return fallback ? String(fallback) : "";
}

export function spawnCallerSessionId(exec) {
  return agentSessionId(exec && exec.agent);
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
