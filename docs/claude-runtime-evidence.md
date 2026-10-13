# Evidência de runtime do Claude Code

Adapter **não oficial** (card #1101): `AGENTS.md`, a descrição do board e a linha "Cliente ativo" da skill `covenant-flow` não citam o Claude Code como cliente até o card de seguimento de oficialização. O coletor `claude_evidence.py` (driver `claude-transcript-v1`, envelope `claude-transcript-evidence-v1`) lê **somente leitura** os transcripts JSONL locais da sessão; o formato é interno do host, não um contrato público, por isso cada versão do host precisa ser qualificada e qualquer outra é `unverified`.

## Fonte e versões qualificadas

| Fonte | Conteúdo usado |
| --- | --- |
| `~/.claude/projects/<slug>/<session_id>.jsonl` (pai) | registros `assistant` (`message.model`, `message.id`, `effort`, `perTurnEffort`, `cwd`, `version`, `entrypoint`), blocos `tool_use` do `Agent` (`input.description/model/effort/subagent_type`), `toolUseResult` (`agentId`, `status`, `resolvedModel`) e, para filho em segundo plano, o registro `queue-operation` `<agent-message from="<agentId>">` com o relatório final |
| `<session_id>/subagents/agent-<agentId>.jsonl` e `.meta.json` | turnos do filho (`isSidechain`, `agentId`, `sessionId`, `message.model`, `effort`), ferramentas usadas e `toolUseId`/`description`/`agentType`/`model`/`effort` do nascimento |

Qualificadas hoje: host `2.1.296`, superfície `cli` (formato observado numa sessão real desta conta; sanitizado nas fixtures de `claude_fixtures.py`). Outra versão ou superfície recusa o gate com `unverified`; schema inesperado vira `unsupported_schema`. Ampliar a lista exige ensaio real (task 8.2) e atualização de `QUALIFIED_VERSIONS`/`QUALIFIED_ENTRYPOINTS`. A versão do binário instalado não é prova de runtime.

## Antes de cada nascimento

```bash
python3 scripts/process-fsm/model_selection.py resolve \
  --client claude --band execucao --role apply-coluna \
  --capture /tmp/cf-unique-apply.json
python3 scripts/process-fsm/claude_evidence.py prepare \
  --capture /tmp/cf-unique-apply.json --task-name "apply-coluna 1101 unique-1"
```

`prepare` exige: `CLAUDE_CODE_SESSION_ID`, **heartbeat do `SessionStart`** (os hooks rodaram nesta sessão), digest dos hooks (bloco `hooks`, módulos Python do adapter e o `hook.mjs` do Impeccable com seus imports relativos, quando presentes) igual ao revisado pelo operador (`claude_adapter.py trust --record`) e ao do heartbeat, transcript legível de versão/superfície qualificadas, cwd da sessão dentro do worktree, `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` e `CLAUDE_CODE_EFFORT_LEVEL` indefinidas e host ≥ 2.1.292. Grava o receipt de nascimento selado (modo 0400) em `.cursor/tmp/claude-evidence/<attempt>.birth.json`. O `--task-name` é o `description` único do `Agent` e contém a agulha do papel.

Limite aceito por Alan: o próprio agente consegue rodar `claude_adapter.py trust --record` via `Bash` (grava em `~/.config`, fora do Guard) e assim autoconfirmar o digest; a revisão de confiança é cooperativa, não uma barreira contra o agente. O endurecimento (ex.: confirmação interativa/TTY) fica para card de seguimento.

O `Agent` leva `model` e `effort` literais dos `arguments` da captura e, no prompt:

```text
model_selection_capture: /tmp/cf-unique-apply.json
runtime_evidence_birth: <path-absoluto-birth>
```

Hooks revisados conferem o receipt no `PreToolUse`. `effort` é lido **só** de `tool_input.effort`; ausente = `unsupported_schema` (nunca o esforço da sessão nem `model` sozinho).

## Durante o filho

- Primeira escrita (`Edit`/`Write`/`MultiEdit`/`NotebookEdit` ou `Bash` de escrita): o último registro `assistant` do transcript do filho precisa ter `message.model`/`effort` iguais à captura; divergente, ausente ou ilegível = deny + `<attempt>.model_mismatch.json` e nascimento novo.
- `PostToolUse(Agent)`: `resolvedModel` ≠ id capturado marca `model_mismatch` e avisa o pai.
- `SubagentStop` só anota `<attempt>.subagent-stop.json`; nunca `decision: "block"`.

## Depois do retorno

```bash
python3 scripts/process-fsm/claude_proxy.py \
  --capture /tmp/cf-unique-apply.json --activity apply-coluna --band execucao \
  --birth <path-absoluto-birth>
```

Coleta com espera padrão de 5 s (máx. 10). Cada turno do filho precisa de `message.model` e `effort` iguais à captura; o resultado exige filho do mesmo `toolUseId`, sessão, versão e cwd; reviewer só pode ter usado `Read|Grep|Glob` (o canal de retorno `SubagentHandback` não conta). `completed` exige relatório final entregue ao pai; `failed`/`interrupted` ficam registrados e nunca são sucesso. O proxy fica em `.cursor/tmp/claude-child-proxies.jsonl` (cliente, pedido × observado, superfície, versão, status, payload, ferramentas) e é idempotente por tentativa.

Onda de review: `claude_review.py verify-wave --wave-id <id> --sha256 <diff> --bound-card <id>` exige dois papéis, filhos distintos, **mesma mensagem do pai**, mesmo SHA, só ferramentas de leitura, `completed` com payload e par observado igual à captura.

## Limites por superfície

| Superfície | Estado neste card |
| --- | --- |
| Terminal (CLI) na VM | referência, qualificada em `2.1.296` |
| IDE por Remote-SSH, Desktop SSH, web por Remote Control | `unverified` até o ensaio do piloto (task 9.4); falha visível, sem fallback |
| Desktop local sem VM, sessão de nuvem | sem seleção local, board nem transcripts: falha visível |

## Recuperação

Limpeza automática de transcripts (`cleanupPeriodDays`), arquivo truncado, versão não qualificada, filho de outra sessão ou digest de hooks alterado: coletar de novo no mesmo turno enquanto a fonte existir; origem irrecuperável ou divergente exige **nascimento novo**, nunca receipt retroativo. O trabalho e os artefatos do filho são preservados.

## Fecho de lote

`claude_evidence.py observe-parent` lê modelo e esforço do último turno do pai; `release_model_selection.check_claude_parent` compara com a captura `claude/execucao`. Divergente ou `unavailable` recusa T16 e `fecho-lote` e pede sessão nova configurada (`/model` + `/effort`).
