from __future__ import annotations
import json
import subprocess
from pathlib import Path
import pytest
import yaml
from model_selection_fixtures import machine_models
from model_selection import resolve, save_capture, validate_spawn, SelectionError
from model_selection_adapter import pre_tool

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/process-fsm/model_selection_lib.js"


def node(code):
    proc = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def args_for(tmp_path, client, role="apply-coluna", wave=None):
    band = "juizo" if role == "design-autor" else "execucao"
    cap = resolve(client, band, role=role)
    path = tmp_path / (client + "-" + cap["attempt_id"] + ".json")
    save_capture(path, cap)
    args = {**cap["arguments"], "description": f"{role} 1080 cf={cap['attempt_id']}", "prompt": f"model_selection_capture: {path}"}
    if wave: args["prompt"] += f"\nmodel_selection_wave_capture: {wave}"
    return args, cap, path


@pytest.mark.parametrize("client", ["cursor", "grok"])
@pytest.mark.parametrize("named", [True, False])
def test_native_named_and_general_purpose_hooks_explicit_model_no_effort(tmp_path, client, named):
    args, cap, _ = args_for(tmp_path, client)
    if named: args["subagent_type"] = "apply-coluna"; args["description"] = "card 1080"
    else: args["subagent_type"] = "generalPurpose"
    # Exact same role in description and native type is one classifier match.
    assert pre_tool(client, {"toolInput": args})["decision"] == "allow"
    assert set(cap["arguments"]) == {"model"}
    args["reasoning_effort"] = "high"
    assert pre_tool(client, {"tool_input": args})["decision"] == "deny"


def test_spawn_wave_rechecks_each_birth_and_resume_retains_capture(tmp_path, machine_models):
    first_args, first, first_path = args_for(tmp_path, "codex", "diff-reviewer")
    first_args["prompt"] += f"\nmodel_selection_wave_capture: {first_path}"
    assert validate_spawn("codex", first_args) == first
    doc = yaml.safe_load(machine_models.read_text());doc["clients"]["cursor"]["execucao"]["model"] = "different";machine_models.write_text(yaml.safe_dump(doc))
    second_args, _, _ = args_for(tmp_path, "codex", "code-reviewer", first_path)
    assert validate_spawn("codex", second_args)
    doc["clients"]["codex"]["execucao"].update(model="gpt-6.1-sol", effort="high");machine_models.write_text(yaml.safe_dump(doc))
    changed_args, _, _ = args_for(tmp_path, "codex", "code-reviewer", first_path)
    with pytest.raises(SelectionError, match="selection_changed"): validate_spawn("codex", changed_args)
    resume = {"description": "diff-reviewer 1080", "resume": "existing-child", "prompt": f"model_selection_capture: {first_path}"}
    assert validate_spawn("codex", resume) == first
    resume["model"] = "gpt-6.1-sol"
    with pytest.raises(SelectionError, match="retune"): validate_spawn("codex", resume)


def test_dsh_schema_effort_and_provider_refusal_before_birth(tmp_path):
    _, capture, _ = args_for(tmp_path, "dsh")
    code = f'''
import {{ nativeDshSelectionAvailable }} from {json.dumps(str(LIB))};
const cap = {json.dumps(capture)};
const fields = Object.fromEntries(Object.keys(cap.arguments).map(k => [k, {{ type:"string" }}]));
let preflights=0;
const llm = {{ resolveModelInfo: async () => ({{ reasoning:{{efforts:[{{id:"medium"}}]}} }}), resolveCallConfig:async c => {{preflights++;return c;}} }};
const ctx={{ tools:{{get:()=>({{parameters:{{properties:fields}}}})}},llm }};
const exec={{name:"subagent"}};
await nativeDshSelectionAvailable(ctx,exec,cap);
const failures=[];
for (const scenario of ["disabled","missing","incompatible","provider","substitution"]) {{
 const c=JSON.parse(JSON.stringify(cap));
 const testctx={{...ctx,llm:{{...llm}}}};
 if(scenario==="disabled") testctx.tools={{get:()=>({{parameters:{{properties:{{}}}}}})}};
 if(scenario==="missing") delete c.arguments.reasoning_effort;
 if(scenario==="incompatible") c.arguments.reasoning_effort="max";
 if(scenario==="provider") testctx.llm.resolveModelInfo=async()=>{{throw new Error("provider refused");}};
 if(scenario==="substitution") testctx.llm.resolveCallConfig=async c=>({{...c,model:"fallback"}});
 try {{await nativeDshSelectionAvailable(testctx,exec,c);failures.push(false);}}catch(e){{failures.push(e.message);}}
}}
process.stdout.write(JSON.stringify({{preflights,failures}}));
'''
    result=node(code)
    assert result["preflights"] == 1
    assert all(result["failures"])
    assert "provider refused" in result["failures"][3]
    assert "substituted" in result["failures"][4]


def test_dsh_managed_child_own_context_after_edit_no_high_fallback(tmp_path, machine_models):
    _, birth, _ = args_for(tmp_path, "dsh")
    doc=yaml.safe_load(machine_models.read_text());doc["clients"]["dsh"]["execucao"]["effort"]="high";machine_models.write_text(yaml.safe_dump(doc))
    result=node(f'''
import {{ applyCapturedDshRequest }} from {json.dumps(str(LIB))};
import {{ attachAgentEffortGuards }} from {json.dumps(str(ROOT / "scripts/process-fsm/dsh_plugin_lib.js"))};
const capture={json.dumps(birth)};
const handlers={{}};
attachAgentEffortGuards({{on:(name,fn)=>{{handlers[name]=fn;}}}},{{}},c=>applyCapturedDshRequest(c,capture));
const valid=await handlers["agent/request"]({{}},async()=>({{provider:"test-provider",model:"test-model"}}));
let invalid="";try{{await handlers["agent/request"]({{}},async()=>({{reasoningEffort:"none"}}));}}catch(e){{invalid=e.message;}}
process.stdout.write(JSON.stringify({{valid,invalid}}));
''')
    assert result["valid"]["reasoningEffort"] == "medium"
    assert "no high substitution" in result["invalid"]


def test_dsh_nonreasoning_route_never_invents_effort(tmp_path, machine_models):
    doc=yaml.safe_load(machine_models.read_text());del doc["clients"]["dsh"]["execucao"]["effort"];machine_models.write_text(yaml.safe_dump(doc))
    _, capture, _=args_for(tmp_path,"dsh")
    result=node(f'''
import {{ nativeDshSelectionAvailable, applyCapturedDshRequest }} from {json.dumps(str(LIB))};
const cap={json.dumps(capture)};
const fields=Object.fromEntries(Object.keys(cap.arguments).map(k=>[k,{{type:"string"}}]));
await nativeDshSelectionAvailable({{tools:{{get:()=>({{parameters:{{properties:fields}}}})}},llm:{{resolveModelInfo:async()=>({{}}),resolveCallConfig:async c=>c}}}},{{name:"subagent"}},cap);
process.stdout.write(JSON.stringify(applyCapturedDshRequest({{}},cap)));
''')
    assert "reasoningEffort" not in result


def test_opencode_refusal_is_before_task_execution(tmp_path):
    args, _, _=args_for(tmp_path,"opencode")
    result=node(f'''
import plugin from {json.dumps(str(ROOT / ".opencode/plugin/process-fsm-guard.js"))};
const hooks=await plugin({{directory:{json.dumps(str(tmp_path))}}});
let refusal="";try{{await hooks["tool.execute.before"]({{tool:"task"}},{{args:{json.dumps(args)}}});}}catch(e){{refusal=e.message;}}
process.stdout.write(JSON.stringify({{refusal}}));
''')
    assert "capability_unavailable" in result["refusal"]
    assert "preserved task semantics" in result["refusal"]


def test_dsh_plugin_birth_descriptor_own_capture_and_reuse_guard(tmp_path):
    # Contract integration with the real consumer plugin; mocked host metadata,
    # not a claim that the installed dsh executed a child.
    from test_dsh_adapter import _mock_ctx_prelude
    args, capture, _ = args_for(tmp_path, "dsh")
    result = node(f'''
{_mock_ctx_prelude()}
import {{ apply }} from {json.dumps(str(ROOT / ".dsh/plugin/process-fsm-guard.js"))};
const ctx=mockCtx();
ctx.tools={{get:()=>({{parameters:{{properties:{{provider:{{type:"string"}},model:{{type:"string"}},reasoning_effort:{{type:"string"}}}}}}}})}};
ctx.llm={{resolveModelInfo:async()=>({{reasoning:{{efforts:[{{id:"medium"}}]}}}}),resolveCallConfig:async c=>c}};
apply(ctx);
const args={json.dumps(args)};
let called=false;
const allowed=await ctx.events["tools/pre-execute"]({{name:"subagent",arguments:args}},async()=>{{called=true;return {{kind:"allow"}};}});
const events=[{{type:"subagent/descriptor",data:{{label:args.description}}}}];
const own={{}};
const child={{ctx:{{on:(n,f)=>{{own[n]=f;}}}},session:{{ownEvents:()=>events,append:(type,data)=>events.push({{type,data}})}}}};
ctx.events["agent/created"]({{agent:child}});
const request=await own["agent/request"]({{}},async()=>({{}}));
const resumed={{ctx:{{on:(n,f)=>{{own[n]=f;}}}},session:child.session}};
ctx.events["agent/created"]({{agent:resumed}});
const resumedRequest=await own["agent/request"]({{}},async()=>({{}}));
const reuse=await ctx.events["tools/pre-execute"]({{name:"subagent",arguments:args}},async()=>{{throw new Error("reuse executed");}});
const missing={{ctx:{{on:(n,f)=>{{own[n]=f;}}}},session:{{ownEvents:()=>[{{type:"subagent/descriptor",data:{{label:"apply-coluna cf=11111111-1111-1111-1111-111111111111"}}}}]}}}};
ctx.events["agent/created"]({{agent:missing}});
let absent="";try{{await own["agent/request"]({{}},async()=>({{}}));}}catch(e){{absent=e.message;}}
process.stdout.write(JSON.stringify({{called,allowed,request,resumedRequest,reuse,absent,events}}));
''')
    assert result["called"] and result["allowed"]["kind"] == "allow"
    assert result["request"] == result["resumedRequest"] == {"provider": "test-provider", "model": "test-model", "reasoningEffort": "medium"}
    assert result["events"][-1]["data"]["attempt_id"] == capture["attempt_id"]
    assert "reused birth capture" in result["reuse"]["reason"]
    assert "birth capture unavailable" in result["absent"]
