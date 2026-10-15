# Evidência de runtime do Claude Code

Adapter **não oficial** (card #1101): `AGENTS.md`, a descrição do board e a linha "Cliente ativo" da skill `covenant-flow` não citam o Claude Code como cliente até o card de seguimento de oficialização. O coletor `claude_evidence.py` (driver `claude-transcript-v1`, envelope `claude-transcript-evidence-v1`) lê **somente leitura** os transcripts JSONL locais da sessão; o formato é interno do host, não um contrato público. Por isso o driver aceita o host pelo **formato** que lê, nunca pelo número da versão: uma versão nunca vista cujos registros batem com o schema declarado segue (`ready`, nascimento, coleta), e um formato que mudou para com `unsupported_schema`.

## Fonte e aceitação por formato

| Fonte | Conteúdo usado |
| --- | --- |
| `~/.claude/projects/<slug>/<session_id>.jsonl` (pai) | registros `assistant` (`message.model`, `message.id`, `effort`, `perTurnEffort`, `cwd`, `version`, `entrypoint`), blocos `tool_use` do `Agent` (`input.description/model/effort/subagent_type`), `toolUseResult` (`agentId`, `status`, `resolvedModel`) e o retorno do filho como `queue-operation` `enqueue`: `<agent-message from="<agentId>">` (relatório final) ou `<task-notification>` (`<task-id>`, `<tool-use-id>`, `<status>`, `<result>`; filho em segundo plano) |
| `<session_id>/subagents/agent-<agentId>.jsonl` e `.meta.json` | turnos do filho (`isSidechain`, `agentId`, `sessionId`, `message.model`, `effort`), ferramentas usadas e `toolUseId`/`description`/`agentType`/`model`/`effort` do nascimento |

**Schema `claude-transcript-v1`** (campos por tipo de registro usado; campos extras e tipos de registro não usados são ignorados; está em `SCHEMA_FIELDS` de `claude_evidence.py`):

| Registro | Campos exigidos |
| --- | --- |
| `assistant` | `type`, `sessionId`, `version`, `entrypoint`, `cwd`, `message.id`, `message.model`, `effort` |
| `tool_use` do `Agent` (pai) | `input.description`, `input.model`, `input.effort` (`input.subagent_type` só se presente) |
| `toolUseResult` | `agentId`, `status`; `resolvedModel` (obrigatório, exceto em `async_launched`, onde o modelo passa a ser conferido nos turnos do filho) |
| `.meta.json` do filho | `toolUseId`, `description` (`agentType`/`model` só se presentes) |
| registros do filho | `isSidechain`, `agentId`, `sessionId` |
| payload de `PreToolUse(Agent)` | `tool_input.effort` (como já era) |

- A validação roda onde o coletor lê: `prepare` valida o último `assistant` do pai, como sonda, antes do nascimento; `collect` valida todos os registros usados. Campo ausente ou de outro tipo = `unsupported_schema` citando o **tipo de registro, o campo e a versão observada**.
- A versão observada nunca recusa sozinha: vai para o heartbeat da sessão, o receipt, a evidência e o proxy. Um transcript com mais de uma versão (sessão retomada depois de o host se atualizar) é aceito se cada registro valida; a evidência guarda o conjunto em `host_versions`. A identidade filho × pai usa a versão e o cwd do pai **gravados no receipt** do nascimento.
- **Pisos de capacidade ficam:** host abaixo de 2.1.292 (`effort` por invocação) ou de 2.1.295 (`onFailure: "block"`) recusa só por faltar a capacidade, com `capability_unavailable`. Superfície também fica: `QUALIFIED_ENTRYPOINTS = ("cli", "claude-desktop")` é tipo de host, não versão, e um valor de `entrypoint` desconhecido recusa citando o valor observado como mudança de superfície ou de formato; um transcript com **mais de uma** superfície (aberto no app e retomado no terminal) é `unverified`, porque a prova de duas superfícies nunca se mistura na mesma sessão.
- **Risco aceito:** formato igual com semântica nova. A mitigação são as checagens cruzadas que já existem: `resolvedModel` contra a captura, modelo e esforço por turno, filiação ao pai e payload entregue. Evidência ausente ou divergente reprova em qualquer versão.
- Ensaio e qualificação valem por **schema do driver**, não por versão (as fixtures `PRETOOL_AGENT_2_1_296`, `APP_SESSION_2_1_295` e `CLI_BACKGROUND_2_1_300` de `claude_fixtures.py` são a prova do formato; uma versão nova com o mesmo formato não precisa de ensaio). Se o formato mudar de verdade, revalide o driver contra uma sessão real e ajuste `SCHEMA_FIELDS`.

A versão do binário instalado não é prova de runtime. Dentro de uma sessão Claude Code (`CLAUDECODE=1`) a versão do host é a **da sessão**: `AI_AGENT` (`claude-code_2-1-295_agent`), conferida com o `version` do transcript no `prepare`. O `claude --version` do PATH só vale fora de sessão (o operador num shell comum): o app desktop roda uma cópia própria (`~/.claude/remote/ccd-cli/<versão>-<hash>`) e o terminal outra, e medir o PATH dentro da sessão certificaria o host errado. Sem `AI_AGENT` na sessão, `resolve` e `prepare` falham com `capability_unavailable` citando a superfície, sem consultar o PATH.

## Antes de cada nascimento

```bash
python3 scripts/process-fsm/model_selection.py resolve \
  --client claude --band execucao --role apply-coluna \
  --capture /tmp/cf-unique-apply.json
python3 scripts/process-fsm/claude_evidence.py prepare \
  --capture /tmp/cf-unique-apply.json --task-name "apply-coluna 1101 unique-1"
```

`prepare` exige: `CLAUDE_CODE_SESSION_ID`, **heartbeat do shim da conta** gravado no `SessionStart` (o registro da conta rodou nesta sessão; sem ele, `hooks_inactive`), as duas partes da confiança revisadas pelo operador (registro **R** e adapter **A**, `cf_shim.py trust --record`; `claude_adapter.py trust --record` delega ao shim) e o **R** atual igual ao do heartbeat (`hooks_changed` = sessão nova), transcript legível cujos registros batem com o schema (e superfície conhecida), cwd da sessão dentro do worktree, `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` e `CLAUDE_CODE_EFFORT_LEVEL` indefinidas e host ≥ 2.1.295 (piso de `effort` por invocação 2.1.292 e de hooks com `onFailure: "block"` 2.1.295; abaixo, `capability_unavailable`). Em pasta que o app desktop criou (`.claude/worktrees/<nome>` ou a pasta configurada) o `prepare` e o preflight de `process_event` recusam com `app_folder`. Grava o receipt de nascimento selado (modo 0400) em `.cursor/tmp/claude-evidence/<attempt>.birth.json`. O `--task-name` é o `description` único do `Agent` e contém a agulha do papel. O receipt grava o card vinculado pelo git; quando o git não vincula card (sessão nascida em `/source`, grelha em `develop`), grava o card do `--task-name` (`grill-card 703 ...`), e se o git vincula **outro** card o `prepare` recusa com `card_mismatch`. O receipt grava também a versão e o cwd do pai no nascimento.

Pins anteriores ao registro na conta (sem `.covenant-flow/adapters.json`) seguem com o heartbeat e o digest do registro de projeto, como antes.

A revisão de confiança é ato do operador: `cf_shim.py trust --record` (e o `claude_adapter.py trust --record`, que delega) exige terminal interativo com a confirmação digitada e **recusa dentro de sessão de agente** (variáveis do cliente ou ancestral de processo `claude`/`codex`/`cursor-agent`/`opencode`); `shim_verified()` não aceita `CF_SHIM_ACTIVE`/`CF_SHIM_ADAPTER_DIGEST` do ambiente como prova, confere contra o registro de confiança da conta e contra o digest atual do worktree. É um endurecimento contra o autoconfirmar acidental, não uma barreira contra um agente que contorne o processo de propósito.

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

Coleta com espera padrão de 5 s (máx. 10). Cada turno do filho precisa de `message.model` e `effort` iguais à captura; o resultado exige filho do mesmo `toolUseId` e sessão, e versão e cwd iguais aos do pai **gravados no receipt** (um filho nascido antes de `EnterWorktree` continua coletável); reviewer só pode ter usado `Read|Grep|Glob` (o canal de retorno `SubagentHandback` não conta). `completed` exige relatório final entregue ao pai; `failed`/`interrupted` ficam registrados e nunca são sucesso. **Retorno em segundo plano:** o host lança `Agent` em segundo plano (`toolUseResult.status="async_launched"`) e a conclusão chega como `queue-operation` `enqueue` com `<task-notification>`; só vale a notificação com `<task-id>` igual ao `agentId` **e** `<tool-use-id>` igual ao `call.id` do spawn (a de outra chamada, como a de um `SendMessage` que retomou o agente, não é o retorno deste filho); `<status>` `completed` → `completed` com o `<result>` como payload, `failed` → `failed`, `killed` → `interrupted`; spawn `async_launched` sem `resolvedModel` tem o modelo conferido nos turnos do filho (nunca pulado); forma desconhecida (nem `<agent-message>` nem `<task-notification>` reconhecível, ou `<status>` fora da lista) = `unsupported_schema` citando o campo, e `terminal_unavailable` fica só para filho ainda sem nenhuma notificação. Turno `<synthetic>` (gravado pelo host): o **último** turno `assistant` sendo `<synthetic>` classifica o filho como `failed` (não é `model_mismatch`) **só quando registra erro da API** (`isApiErrorMessage`/`apiError`, por exemplo HTTP 429) e o proxy registra a tentativa sem sucesso; um `<synthetic>` final sem erro fica fora da comparação e o status vem do último turno real; um `<synthetic>` intermediário seguido de turnos reais também fica fora da comparação de modelo e é contado em `synthetic_turns` (com `api_error`) na evidência. O par observado do proxy é o do último turno real (`unavailable` se o filho só produziu erros). O proxy fica em `.cursor/tmp/claude-child-proxies.jsonl` (cliente, pedido × observado, superfície, versão do host, versão do app desktop e marca SSH quando presentes, status, payload, ferramentas) e é idempotente por tentativa. `--handoff` imprime a linha de handoff do filho (cliente, superfície, modelo/esforço observados, status) tirada do proxy.

Onda de review: `claude_review.py verify-wave --wave-id <id> --sha256 <diff> --bound-card <id>` exige dois papéis, filhos distintos, **mesma mensagem do pai**, mesmo SHA, só ferramentas de leitura, `completed` com payload e par observado igual à captura.

## Limites por superfície

| Superfície | Estado neste card |
| --- | --- |
| Terminal (CLI) na VM (`entrypoint=cli`) | referência (formato ensaiado no `2.1.296` e no `2.1.300`; qualquer versão com o mesmo formato segue) |
| App desktop do Claude no Windows por SSH (`entrypoint=claude-desktop`) | cópia própria do Claude Code na VM (`~/.claude/remote/ccd-cli/<versão>-<hash>`, observada em `2.1.295`, app `2.37337.1`); mesmo cliente `claude`, mesma lei. Superfície conhecida **só junto da fixture real** `APP_SESSION_2_1_295` (transcript do app, pai e filho, sanitizado); o ensaio vivo (task 8.x do #1103) confirma hooks, heartbeat e nascimentos na cópia do app. Pisos: `effort` por invocação **2.1.292** e hooks bloqueantes **2.1.295**. O heartbeat do shim grava `entrypoint`, `host_version`, `desktop_app_version` e a marca `ssh`; receipt, evidência, proxy e handoff repetem superfície e versões. Abre em `/source` (opção *worktree* do app desligada); a pasta que o app cria é "pasta do app (sem card)". O app abre em `auto`: o modo não autoriza processo |
| IDE por Remote-SSH, web por Remote Control | `unverified` até o ensaio do piloto; falha visível, sem fallback |
| Desktop local sem VM | sem seleção local, board nem transcripts: falha visível |
| Sessão de nuvem (claude.ai/code em ambiente de nuvem) | **não suportada** por este card: o Claude Code roda sempre local, pelo CLI; sem Guard, seleção, board nem transcripts, falha visível no resolver e no `process_event` |

## Recuperação

Limpeza automática de transcripts (`cleanupPeriodDays`), arquivo truncado, formato que mudou (`unsupported_schema`), filho de outra sessão ou registro/adapter alterado: coletar de novo no mesmo turno enquanto a fonte existir; origem irrecuperável ou divergente exige **nascimento novo**, nunca receipt retroativo. O trabalho e os artefatos do filho são preservados.

Troca de worktree na mesma sessão (`EnterWorktree`) é suportada: o host move o transcript para o diretório do novo cwd, o hint inexistente do heartbeat é descartado e o shim atualiza o heartbeat da sessão a cada evento (transcript e cwd; `recorded_at` do início da sessão não muda). O registro da conta não depende da pasta de lançamento: uma sessão aberta em `/source` e levada ao worktree do card fica com o processo ativo, e o shim reinjeta a página do card por `additionalContext` de `PostToolUse(EnterWorktree)`.

A troca só segue `transcript_path` e `cwd`: o digest do registro **R** continua o do `SessionStart`, a única âncora do que o host carregou. Registro alterado depois exige reabrir a sessão (`hooks_changed`); o adapter **A** é conferido pelo shim a cada evento, então um **A** revisado diferente vale na hora, inclusive entre worktrees.

Nota de uso após `EnterWorktree`: o host pode recusar comandos compostos com variável de shell; passe corpos longos por `--body-file` com path literal.

## Fecho de lote

`claude_evidence.py observe-parent` lê modelo e esforço do último turno do pai; `release_model_selection.check_claude_parent` compara com a captura `claude/execucao`. Divergente ou `unavailable` recusa T16 e `fecho-lote` e pede sessão nova configurada (`/model` + `/effort`).
