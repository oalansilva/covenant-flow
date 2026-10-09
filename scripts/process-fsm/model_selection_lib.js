// Shared Python resolver is the only selection/policy implementation.
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "model_selection.py");
export function selectionCommand(command, client, input) {
  const result = spawnSync("python3", [SCRIPT, command, "--client", client], {
    input: JSON.stringify(input), encoding: "utf8", timeout: 10000, env: process.env,
  });
  if (result.status !== 0) throw new Error(`model_selection: ${String(result.stderr || result.error || "resolver failed").trim()}`);
  return JSON.parse(result.stdout);
}

export function prepareSelection(client, args) {
  return selectionCommand("prepare", client, args);
}

export function validateNativeSpawn(client, args) {
  return selectionCommand("validate-spawn", client, args);
}

export function checkCapturedRequest(client, capture) {
  return selectionCommand("check-request", client, { capture, role: capture.role }).capture;
}

export function selectionCaptureForDsh(path, role) {
  const result = spawnSync("python3", [SCRIPT, "verify-capture", "--client", "dsh", "--role", role, "--capture", path], {
    encoding: "utf8", timeout: 10000, env: process.env,
  });
  if (result.status !== 0) throw new Error(String(result.stderr || result.error || "birth capture unavailable").trim());
  return JSON.parse(result.stdout);
}

export function assertExplicitArguments(capture, args) {
  for (const [key, value] of Object.entries(capture.arguments)) {
    if (JSON.stringify(args[key]) !== JSON.stringify(value)) {
      throw new Error(`model_selection: ${capture.client}/${capture.band} explicit ${key} mismatch; no inheritance/fallback`);
    }
  }
  // A supported field never becomes an ignored extra request parameter.
  for (const key of ["provider", "model", "effort", "reasoning_effort", "reasoningEffort", "variant"]) {
    if (key in args && !(key in capture.arguments)) throw new Error(`model_selection: unsupported spawn parameter ${key}`);
  }
}

export function applyCapturedDshRequest(config, capture) {
  const birth = checkCapturedRequest("dsh", capture);
  const args = birth.arguments;
  const out = { ...config };
  for (const key of ["provider", "model"]) {
    if (out[key] !== undefined && out[key] !== args[key]) throw new Error(`model_selection: living child ${key} differs from birth capture`);
    out[key] = args[key];
  }
  const effort = out.reasoningEffort ?? out.reasoning?.effort;
  if (effort !== undefined && effort !== args.reasoning_effort) throw new Error("model_selection: living child effort differs from birth capture; no high substitution");
  if (args.reasoning_effort === undefined) delete out.reasoningEffort;
  else out.reasoningEffort = args.reasoning_effort;
  if (out.reasoning && typeof out.reasoning === "object") {
    out.reasoning = { ...out.reasoning };
    if (args.reasoning_effort === undefined) delete out.reasoning.effort;
    else out.reasoning.effort = args.reasoning_effort;
  }
  return out;
}

export async function nativeDshSelectionAvailable(ctx, exec, capture) {
  const tools = typeof ctx.get === "function" ? ctx.get("tools") : ctx.tools;
  const definition = tools?.get?.(exec.name, exec.agent);
  const fields = definition?.parameters?.properties;
  if (!Object.keys(capture.arguments).every((key) => fields?.[key]?.type === "string")) {
    throw new Error("model_selection: dsh capability_unavailable; enable native modelSelectionSettings/policy before spawn");
  }
  const llm = typeof ctx.get === "function" ? ctx.get("llm") : ctx.llm;
  if (typeof llm?.resolveModelInfo !== "function" || typeof llm?.resolveCallConfig !== "function") throw new Error("model_selection: dsh capability_unavailable: native LLM route metadata/preflight absent");
  const args = capture.arguments;
  const model = await llm.resolveModelInfo(args.provider, args.model, exec.signal);
  const efforts = model.reasoning?.efforts?.map((e) => e.id) || [];
  if (efforts.length && !efforts.includes(args.reasoning_effort)) throw new Error("model_selection: missing/incompatible required effort for exact native dsh model");
  if (!efforts.length && args.reasoning_effort !== undefined) throw new Error("model_selection: effort unsupported for exact native dsh model");
  const effective = await llm.resolveCallConfig({ provider: args.provider, model: args.model, ...(args.reasoning_effort === undefined ? {} : { reasoningEffort: args.reasoning_effort }) }, exec.signal);
  if (effective.provider !== args.provider || effective.model !== args.model || effective.reasoningEffort !== args.reasoning_effort) throw new Error("model_selection: native dsh route/effort substituted; spawn refused");
}

export function refuseOpenCodeTask(args) {
  // The installed SDK exposes session.create/prompt, but the plugin before-hook
  // cannot replace task execution while preserving its permissions/result lifecycle.
  // Refuse before task creates a child. Do not simulate with chat.params/settings.
  const capture = prepareSelection("opencode", args);
  throw new Error(`model_selection: opencode capability_unavailable (${capture.capability_version}); native task provider/model/variant routing with preserved task semantics is unproven`);
}
