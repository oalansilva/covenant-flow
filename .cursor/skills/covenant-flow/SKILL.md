---
name: covenant-flow
description: "Use this skill for Alan's default operating process in any repo or workspace: cards/issues, GitHub Projects or Kanban, OpenSpec, implementation, validation, releases/publication, repo hygiene, AGENTS.md/rules cleanup, evidence reporting, and separating general workflow rules from project-specific rules."
---

# Covenant Flow

Contrato operacional do **consumidor pinado**. Canônico: `.cursor/skills/covenant-flow/` no git do consumidor. Não tratar `~/.codex/skills/` nem `/srv/knowledge/hermes-second-brain/skills/` como fonte.

Prioridade (δ e Guard > overlay > skill > wording):

1. **δ e Guard** (`.cursor/process-fsm.yaml`, `process_event`, hook Write).
2. **Overlay** (`overlay_doc` / stub `AGENTS.md`) — só quando a tarefa precisar de portas, Drive, banco ou release.
3. **Esta skill** (runbook).
4. **Wording** do chat (`implemente`, `autorizo`, `gostaria sempre`).

Cliente ativo: **Cursor Agent, Codex CLI, Grok Build, OpenCode ou dsh**. A sessão ativa conduz seus próprios filhos, sem transferir para outro cliente. **lista fechada isolada** (sem transcript do pai): `grill-card`, Design-autor, Apply-coluna, QA checks, Assessment A/B, `diff-reviewer`, `code-reviewer`. Review = diff **exato** e os mesmos dois papéis em qualquer cliente. Papéis/faixas, proibições e traduções são versionados em `.cursor/model-policy.yaml`; escolhas operacionais vêm só de `$HOME/.config/covenant-flow/model-selection.yaml`, na conta executora (VM no Desktop+SSH), compartilhadas entre repos/worktrees. `.cursor/model-map.yaml` é fonte histórica de migração explícita, nunca fallback. Trocar escolha local depois da migração dispensa card/commit/release e não concede autorização.

- **juízo:** grill-card, design-autor, design-critic, Assessment A/B.
- **execução:** apply-coluna, qa-gate, os dois reviewers, same-card-search e fecho-lote.

Antes de cada nascimento, resolver `scripts/process-fsm/model_selection.py resolve --client <cliente> --band <faixa> --role <papel> --capture <path-absoluto-novo.json>`. Passe literalmente `arguments` do JSON ao tool nativo e inclua `model_selection_capture: <path>` no prompt autocontido. Cursor Task (tipo nomeado **ou** `generalPurpose` com corpo colado) e Grok `spawn_subagent` passam `model`; esforço separado não está demonstrado nesse contrato e é rejeitado. Codex Agent passa `model` + `reasoning_effort` do catálogo nativo. dsh passa provider/model e esforço somente conforme metadata nativa; schema/política de seleção devem estar habilitados, descriptor recebe `cf=<attempt_id>` na description e guard da própria agent.ctx mantém a captura. OpenCode task recusa na versão instalada quando a rota SDK não preserva restrições/retorno/jobs nativos; nunca simular seleção com chat.params/preset. Detalhes e matriz de evidência: `docs/model-selection.md`. Host/provider recusado, capacidade ausente, arquivo/cliente/faixa inválidos: falha visível, sem omissão, herança ou substituição.

`composer-2.5-fast`, `inherit` e `auto` são proibidos por política. Rótulo/slug no handoff vêm da captura. Registre requested e observed separadamente; metadata runtime ausente = `unavailable` e falha do gate que a exige; esforço não aplicável = `not_applicable`. `completed` exige payload. Configuração nunca prova observado.

**Ondas reviewers/A-B:** o orquestrador prepara capturas antes da onda; cada nascimento relê a escolha, compara apenas cliente/faixa/argumentos efetivos e recebe `model_selection_wave_capture: <primeira-captura>` no prompt. `--wave-capture <primeira-captura>` no resolver rejeita `selection_changed`; cancele tentativa parcial e comece nova onda explicitamente. Edição alheia à faixa não invalida a onda. Autor e crítico posterior podem usar escolhas distintas, verificadas por suas próprias capturas de juízo.

**Destape/resume mantém captura de nascimento:** resume, subagentStop e follow-up de execução não retunam filhos após edição local. Validar runtime/faturação contra a captura aplicável (`model_proxy.verify_continuation`); divergência/proibição/unavailable não conta: MUST NOT `resume` divergente; requer spawn **novo**, com seleção local corrente e prompt autocontido. Cursor resume não aceita model. Busca no mesmo card usa generalPurpose com seleção explícita; MUST NOT `subagent_type` `explore` quando roteado a modelo proibido. fecho-lote sem sidecar/destape; ignorar auto-resume do host. Troca de modelo = sessão nova (#430).

**Release/lote — chat pai execução (única excepção ao silêncio do picker):** pedido explícito fechar lote / subir release / T16 + fecho-lote captura a escolha local de execução do próprio cliente. Pai observado deve corresponder a essa captura da operação (incluindo esforço quando aplicável); divergência/unavailable recusa T16/fecho-lote, exige sessão nova e não muda pai vivo. MUST NOT exigir modelo de outro cliente, forçar picker via Git/AGENTS.md/overlay clients.*.auto ou recomendar picker nos demais chats #<id>.

Overlay humano: `Read` o path `overlay_doc` de `.covenant-flow/overlay.yaml` quando a tarefa precisar de portas/Drive/banco/release.

## Comunicação

PT-BR curto. Não diga `concluído` / `Pronto` / `publicado` até a evidência do estado ser verdadeira. `Done` = Done técnico.

## Um chat por card

Título `#<id>` nos dois clientes (Em Refinamento → Done técnico). Homologado e Release/lote fora. Pai orquestra: `process_event` (o movimento de Status é do executor do board, a pedido do `process_event`; o agente não move nem adiciona card no Project), git, recusas, handoff, relaying do grill. **Não** grelha, não escreve OpenSpec/protótipo (exceção: só `## Design Critique` após A/B), não implementa, não review, não QA. Recusar executar outra atividade **no mesmo chat** — não pedir outro transcript. Sem Status=Pronto para Dev + `implemente`: uma frase com Status atual + “Apply só depois de Pronto para Dev (T7 teu)” + parar. Sem estado, evento, hook ou `enabled_tools` novo na FSM. `AGENTS.md` always-on não cresce com esta regra.

Filhos (Status tem que bater; mesmo worktree `card-<id>-*` pós-T1; grill no cwd atual sem branch; `working_directory` = worktree quando a árvore existir; filho MUST NOT `move_agent_to_root`):

| Atividade | Spawn |
| --- | --- |
| Em Refinamento | 1 filho `grill-card` (bind Status da issue N + N no prompt = `#<id>`) |
| Design | 1 filho autor; depois 1 crítico (sem-tela) ou onda A/B (com-tela) |
| Em desenvolvimento | 1ª entrada: pai `iniciar_apply` (T8), depois **um** filho Apply (único da coluna; loop interno até tasks feitas ou P0 visível). Recusa visível se devolver cedo sem P0 — não abre review nem segundo Apply. Pós-T18: já em Em desenvolvimento; **não** T8 |
| Code Review | **dois** Task no **mesmo turno** do pai (`diff-reviewer` + `code-reviewer`) sobre o intervalo já colado; fila do host não falha; não esperar destape do primeiro para nascer o segundo |
| QA | 1 filho checks/evidência; T14 no pai |

Cliente dsh: em Design, root spawna 1 Design-autor; o pai não escreve OpenSpec no próprio turno; a excepção grill não se aplica.

T7: Alan abre o **Snapshot Impeccable** linkado no comentário do card (path / blob). O Gist OpenSpec **não** é a crítica.

Handoff de Design/Apply/Review registra **proxies**: palavras de `design.md`, bytes de HTML gerado vs copiado (`cp`/clone = copied; delta = generated; sem protótipo = `N/A`), número de spawns, **uma linha por spawn** `proxy modelo: <papel> → <rótulo> (<slug>)` (papel = needle do spawn; rótulo/slug = captura local acima). Sem parser de usage Cursor/Grok e sem dashboard.

## Registro dos hooks na conta (Claude Code, Cursor, Codex, OpenCode)

O registro dos hooks do processo não vive no repositório consumidor: vive **na conta do operador**, um por host, e chama um **shim** fino do produto (`~/.config/covenant-flow/shim/current/cf_shim.py`; no OpenCode, um plugin global fino em `~/.config/opencode/plugin/`). A cada evento o shim acha o consumidor pelo cwd do evento (`.covenant-flow/overlay.yaml` com `pin`), confere o manifesto do pin (`.covenant-flow/adapters.json`) e a revisão de confiança, e executa o **adapter pinado** no worktree com o payload original; ele não tem FSM, Guard, paginação nem seleção de modelos. Pasta sem overlay ou sem `pin`: nada (sem página, sem deny). Pin anterior ao registro na conta: nada (o registro de projeto do pin antigo é o único que roda). Falhas visíveis, no formato de deny do host nos eventos que gateiam e na página no início de sessão: `adapter_missing`, `adapter_divergent`, `hooks_unreviewed`, `shim_incompatible`, `consumer_ambiguous`.

- **Instalar (operador, uma vez por conta):** `install.sh --account` a partir do checkout do `covenant-flow` (`--check` mostra por host `registration=account|unproven|not_installed`, shim e revisões faltando; `--remove` tira só as entradas do Covenant Flow). Preserva chaves e hooks alheios, recusa JSON inválido sem escrita parcial, é idempotente, não toca a seleção de modelos e **não grava confiança**. Codex também exige a revisão do host (`/hooks`).
- **Confiança em duas partes:** **R** (entradas da conta daquele host + arquivos do shim) e **A** (todos os arquivos do adapter pela lista do manifesto: `scripts/process-fsm/` sem testes, handlers do cliente e toda a árvore `.agents/skills/impeccable/scripts/**`). O operador lê e grava com `python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record` (`claude_adapter.py trust --record` delega). **R** diferente do da sessão = `hooks_changed` (sessão nova); **A** revisado novo vale no próximo evento, inclusive entre worktrees. Pin e instalação nunca gravam confiança.
- **Heartbeat:** o shim grava no `SessionStart` de qualquer pasta um registro privado da sessão (`~/.config/covenant-flow/sessions/<cliente>/<sessão>.json`); Claude Code e Codex exigem heartbeat da sessão (sem ele o `process_event` recusa `hooks_inactive`, citando cliente e recuperação, nas transições que exigem preflight); Cursor e OpenCode exigem shim, entrada do cliente e revisão. Host `registration=unproven` fica só com a falha visível.
- **Sessão aberta em `/source`:** funciona; entre no worktree do card (`EnterWorktree` no Claude Code) e o processo já está ativo.
- **Grok Build e dsh ficam fora:** mantêm o registro de projeto (`.grok/hooks/process-fsm.json`, `.dsh/cordis.patch.yml`), sem shim nem revisão nova. O pin novo remove do projeto só as entradas do Covenant Flow de Claude Code, Cursor, Codex e OpenCode e move os plugins do adapter OpenCode para `.opencode/adapter/`.

## Codex CLI local (cooperativo; sem Auto)

Skills são descobertas pelas pontes `.agents/skills/<nome>/SKILL.md`, que mandam ler o canônico completo em `.cursor/skills/<nome>/SKILL.md`; a ponte não concede autorização nem define estado. AGENTS.md permanece curto; a FSM (`.cursor/process-fsm.yaml` + `process_event`) define estado e transições, e `.cursor/model-policy.yaml` define política; o resolver local define pares por nascimento. Os hooks chegam pelo registro na conta (`install.sh --account`) → shim → adapter pinado (`scripts/process-fsm/codex_*.py`); detalhes de comandos, proxy, captura e verificação ficam nos scripts. `.codex/` não é fonte de estado nem de modelos.

Os hooks do Codex são registrados **na conta do operador** (`~/.codex/hooks.json`, via `install.sh --account`, ver "Registro dos hooks na conta"), não no projeto; o shim da conta chama `scripts/process-fsm/codex_adapter.py` pinado no worktree. Hooks não gerenciados só operam depois de **duas** revisões: a do operador (registro **R** e adapter **A**, `cf_shim.py trust --record`) e a do próprio Codex (`/hooks`, que grava `trusted_hash` em `config.toml`; o instalador nunca o grava). Nunca use `--dangerously-bypass-hook-trust`, atribua confiança ao pin ou trate hook ausente/não confiado como proteção. Pins anteriores ao registro na conta seguem com `.codex/hooks.json` do projeto. `SessionStart` injeta a página compartilhada e, sem Status, mantém `Write produto deny`. `PreToolUse` declara matcher `Bash|exec_command|apply_patch|Edit|Write|Agent`, mas spawn nativo `Agent`, hosted tools e rotas especializadas podem não dispará-lo. `PostToolUse` e `Stop` são advisory e não revertem efeitos; permissões nativas continuam ativas. `sandbox_mode` no perfil do Agent configura o filho; o sandbox ativo do turno pai pode ser herdado e não é alterado pelo perfil. Codex é cooperativo, sem modo Auto.

Protocolo por filho: leia o Status vinculado e confira a ação permitida pela FSM; classifique `juizo` (grill, Design-autor, crítica e avaliações) ou `execucao` (Apply, QA, reviewers e demais execução); resolva de novo a escolha local a cada spawn, materialize a captura e passe literalmente seu par de modelo/esforço da faixa. Na sessão Codex, use o Agent nativo do Codex. Para Code Review, aplique a ordem de preparação gravável, onda nativa `read-only` e persistência gravável descrita abaixo. `sandbox_mode=read-only` em `.codex/agents/*.toml` é declaração de perfil; não comprova nem altera permissões efetivas. Pai e filhos herdam o contexto nativo observado. MUST NOT encaminhá-los a Cursor Task, `cursor-agent` ou Composer. Quando disparado, `PreToolUse` confere faixa/modelo/esforço com a captura e faixa do papel; valores ausentes, inválidos, proibidos ou divergentes recebem deny visível. Não fixe pares em `.codex/config.toml` ou `.codex/agents/*.toml`, nem use fallback; configuração local ausente/inválida ou recusa do host falha visivelmente.

**Evidência Codex #1095:** depois da captura e antes de cada nascimento, execute `codex_evidence.py prepare --capture <path> --task-name <nome-unico>`; inclua `runtime_evidence_birth: <receipt-absoluto>` no prompt. `blocked` impede nascimento/transição dependente e preserva trabalho; host não qualificado é `unverified`. Só ensaio explícito sem produto/transição usa `--qualification`. Após retorno, pai gravável usa `codex_proxy.py --capture <path> --activity <papel> --band <faixa> --birth <receipt>`: coleta automática limitada, sem flags observadas manuais. Consumidores revalidam fonte/digest/binding de todos os turnos contra captura original. Coleta/recoleta não duplica tentativa; origem irrecuperável/divergência requer nascimento novo, nunca receipt retroativo. Comandos de coordenação da sessão read-only, fonte/versão suportadas, prova sanitizada e recuperação: `docs/codex-runtime-evidence.md`. Hooks só reutilizam preflight quando confiados e cobertos; ausência não é proteção.

Cada prompt é autocontido: `#<id>`, Status, branch/worktree e paths, ação autorizada, escopo, contexto necessário, skill canônica e contrato exato de saída. Não herde nem solicite transcript do pai. Registre pelo proxy script o par pedido e o par **observado pelo runtime/trace** (nunca inferido do pedido), host/versão, status e payload. `unavailable` deve ficar visível e é falha, sem fallback. Sucesso exige `completed`, payload retornado e par observado igual à captura; `completed` sem payload não basta. Só o pai move estado, pelo `process_event` permitido na FSM.

No Code Review, o principal permanece gravável e usa coordenador Codex dedicado automático **read-only desde o nascimento**, no mesmo worktree do card. Essa é a única exceção à delegação no mesmo chat do card; não mudar cliente, executar review no principal/coordenador nem pedir alternância manual de permissões. O caminho candidato `codex exec --sandbox read-only` e retomada nativa `exec resume` precisam de qualificação real, por superfície/rota. Não inferir suporte das flags ou do TOML.

1. Principal materializa/verifica diff exato e SHA, prepara pacote imutável, capturas distintas de mesma onda, prompts, planos/fixtures e envelopes pendentes com `codex_review_session.py prepare`. Birth pendente mantém parent/turno unavailable; não é prova final nem receipt ligado ao principal. O helper automático retorna comando exato; lançamento e retorno precisam de `CommandExecution` nativo completo, JSONL exec e rollout real da sessão.
2. Coordenador novo não herda qualificação do principal. Ciclo bootstrap sem filhos → contexto diagnóstico C/S → persistência/qualificação pelo principal → dois probes diagnósticos em perfis nomeados → qualificação da rota. O principal retoma a mesma sessão nativa read-only entre fases; o coordenador não grava receipts. `internal_context_attestation` permanece unavailable. Fonte ausente ou qualificação incompleta bloqueia antes de trabalho de produto.
3. Só com essas provas e Status=Code Review: coordenador verifica pacote/preflight/Status vivos e inicia **ambos** Agents nativos no mesmo turno, `diff-reviewer` e `code-reviewer`, filhos distintos, prompts autocontidos, `fork_turns=none`, capturas próprias e mesmo path/SHA. Perfis permitem apenas a tentativa do helper fixo na fixture descartável vinculada, exigindo deny/readback antes do parecer; produto write, alvo arbitrário e escalada continuam proibidos. `verify-wave` final só depois da produção das provas. Coordenador/filhos mantêm read-only até completed e ambos payloads.
4. Principal gravável coleta/proxy pelos envelopes/capturas originais. Coleta resolve parent real em memória a partir da cadeia principal→coordenador→filhos; não reescreve traces nem fabrica receipt posterior. `codex_review.py verify-wave` revalida cadeia, dois perfis/filhos, turno do coordenador, pacote/diff/SHA, seleção/contexto e read-only/probes. Persistência roda no principal comprovado. Depois `review_process_checklist.py`; commit só com ambos PASS. Recusas e receita completa: `docs/codex-review-qualification.md`.

**Diff grande e saída:** preflight uma vez no coordenador; probe fixo uma vez como primeiro comando de cada reviewer. Nunca repetir tentativa de escrita após truncamento. O helper verifica SHA/pacote; para diff grande, exige leitura de todas as partes pelo template sem escrita, conforme os budgets do prompt. O coletor valida bytes completos em `CommandExecution` **e** no retorno nativo entregue ao modelo, cobertura integral e digest reconstruído do mesmo artefato nos dois filhos; manifesto/resumo não prova leitura. Ausência/truncamento ou contexto insuficiente bloqueia parecer. `verify-wave` final permanece no principal após ambos os payloads; não se exige `codex_review.py verify` isolado no filho. Protocolo completo: `docs/codex-review-qualification.md`.

**Contexto #1098 (opção 2 aprovada):** lifecycle não qualifica contexto. Antes de uma nova etapa, exigir qualificação operacional separada no mesmo chat/card: contrato documentado do binário nativo ligado ao runtime, chamada real `fork_turns=none` e ensaio completo C/S sem canal contaminante observado. `codex_context.py` revalida fontes/digests/escopo; plano é REQUESTED, controle/payload são observados e texto nativo cifrado fica opaque. `internal_context_attestation` permanece unavailable: ausência de S sozinha, flags, history_mode e pedido não atestam contexto completo. `--qualification` é diagnóstico sem produto/transição, nunca T8; falta de qualificação bloqueia novos nascimentos. Receipts/proxies históricos conservam lifecycle sem promoção. Leitura do diff, deny/readback por reviewer e read-only efetivo #1049 permanecem obrigatórios; o coletor `codex_review_probe.py` só aceita execução/saída nativas de seu helper fixo e qualificação diagnóstica própria por dois filhos. Sem positivo real, Review/QA/commit dependentes continuam bloqueados. O preparo atual de Review usa pacote dedicado/envelopes pending e qualifica a sessão coordenadora; o protocolo histórico `--defer-review-turn` continua legível, mas não substitui a cadeia dedicada. `aceitar_sha` verifica a onda histórica após persistência no principal gravável comprovado. Procedimentos: `docs/codex-context-qualification.md` e `docs/codex-runtime-evidence.md`; matriz: `docs/codex-native-capabilities.md`.

## Claude Code (cooperativo; sem Auto)

Adapter **não oficial** (card #1101; o Claude Code não é cliente oficial): `AGENTS.md`, a descrição do board e a linha "Cliente ativo" acima não citam o Claude Code como cliente até o card de seguimento de oficialização (T1 de Alan). `CLAUDE.md` só importa `AGENTS.md`; `.claude/skills/<nome>/SKILL.md` são pontes que mandam ler o canônico em `.cursor/skills/<nome>/SKILL.md` (manifesto `.claude/skills/.covenant-flow-bridges.json`); nada em `.claude/` é fonte de estado, de lei ou de modelos. A FSM (`process_event --client claude`) define estado; `.cursor/model-policy.yaml` define política; o resolver local define o par por nascimento. Os hooks ficam registrados **na conta** (`~/.claude/settings.json`, via `install.sh --account`; o bloco `hooks` não existe mais no projeto a partir do pin com registro na conta) e chamam o shim, que chama `scripts/process-fsm/claude_adapter.py` pinado no worktree do cwd do evento. Só valem depois da revisão de confiança do operador em duas partes (`claude_adapter.py trust --record` delega a `cf_shim.py trust --record`); pin, instalação ou o diálogo de confiança do host não são essa revisão, hook ausente/desligado/não revisado não é proteção e não se usa bypass. Claude Code é cooperativo, sem modo Auto; o modo de permissão do host não autoriza processo. Quando o card do pedido ou do título da sessão (`#<id>`) difere do `bound_card` do git, a sessão entra no worktree `card-<id>-*` com `EnterWorktree` (path; criar antes com `git worktree add`, empilhado quando o card pedir), sem pedir ao operador para trocar de pasta; `process_event` e filhos só depois de a página mostrar `bound_card=<id>`. A sessão nasce em `/source` e o processo a segue: o shim da conta resolve o consumidor pelo cwd de cada evento e reinjeta a página do card por `PostToolUse(EnterWorktree)`, sem reabrir a sessão. Nota de uso após `EnterWorktree`: o host pode recusar comandos compostos com variável de shell; passe corpos longos por `--body-file` com **path literal**. O Claude Code roda **sempre local, pelo CLI**; sessão de nuvem não é suportada.

Protocolo por filho: leia o Status vinculado; classifique `juizo` ou `execucao`; resolva a escolha local a cada spawn (`model_selection.py resolve --client claude --band <faixa> --role <papel> --capture <path>`) e passe literalmente os `arguments` (`model` alias de família + `effort`) ao tool `Agent`; **`model` e `effort` explícitos em todo spawn**, nunca herança nem omissão (sem `effort` o host roda o filho em `medium`). Depois da captura e antes do nascimento rode `claude_evidence.py prepare --capture <path> --task-name "<papel> <id> <único>"`; o `description` do `Agent` é esse nome e o prompt autocontido traz `model_selection_capture:` e `runtime_evidence_birth:`. Design-autor, crítico, Assessment A/B, grill, Apply, QA e `fecho-lote` nascem como `general-purpose`; filho não cria filho (hook nega `Agent` com `agent_id`). Variáveis `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` e `CLAUDE_CODE_EFFORT_LEVEL` definidas, host sem `effort` por invocação (< 2.1.292) ou `tool_input.effort` ausente no payload (`unsupported_schema`) recusam o spawn. `resolvedModel` diferente da captura e modelo/esforço do transcript do filho diferentes antes da primeira escrita marcam `model_mismatch`: o filho é inválido e exige nascimento novo. Após o retorno, o pai grava o proxy com `claude_proxy.py --capture <path> --activity <papel> --band <faixa> --birth <receipt>` (coleta automática dos transcripts locais; nunca observação manual); `unavailable` reprova e `completed` sem payload não basta. Detalhes, versões qualificadas e recuperação: `docs/claude-runtime-evidence.md`.

Code Review: o pai materializa e verifica uma vez o diff e o SHA-256 (`materialize_review_diff.py`/`codex_review.py verify`; num card que sobe o pin do nucleus, `materialize_review_diff.py --nucleus <checkout do covenant-flow>` inclui no mesmo diff o do `install.sh` do nucleus, o único arquivo do pin que não chega ao consumidor), prepara as duas capturas `claude/execucao` (a segunda com `--wave-capture`) e os dois receipts e emite `diff-reviewer` e `code-reviewer` (`subagent_type` com o próprio nome, ferramentas `Read|Grep|Glob`) **na mesma mensagem**, com o mesmo `review_diff_path` + SHA-256. Depois dos dois retornos `completed` com payload, grava os dois proxies e roda `claude_review.py verify-wave`; commit só depois de `verify-wave` e `review_process_checklist.py` passarem.

Destape: no Claude Code o filho em primeiro plano devolve o resultado no turno do pai e o filho em segundo plano entrega a conclusão ao pai como mensagem (`<agent-message>`) ou como `queue-operation` com `<task-notification>`; o coletor aceita a notificação só com `<task-id>` igual ao `agentId` e `<tool-use-id>` igual ao do spawn (`completed` com o `<result>` como payload, `failed`, `killed` = interrompido) e forma desconhecida é `unsupported_schema` citando o campo, nunca espera eterna; não há sidecar `awaiting-task.json` nem poke. `SubagentStop` só anota o receipt e nunca devolve `decision: "block"`. Interrupção ou erro do filho não é sucesso.

Fecho de lote só por pedido explícito de Alan: o pai precisa estar observado em `claude/execucao` (modelo e esforço do último turno do pai no transcript, `claude_evidence.py observe-parent`) igual à captura; divergente ou `unavailable` recusa T16 e `fecho-lote` e pede sessão nova configurada; o próprio `process_event fechar_release --client claude [--capture <captura do fecho-lote>]` repete a conferência e recusa com `claude_evidence:parent_model` citando o par observado e o capturado. O filho `fecho-lote` nasce `general-purpose` com o par capturado; o pai chama `process_event fechar_release` só depois de `completed` e `release-guard post` PASS. Homologar continua só de Alan.

Superfícies: terminal (`cli`) na VM e **app desktop do Claude no Windows por SSH** (`claude-desktop`, cópia própria do Claude Code na VM; mesmo cliente `claude`, sem `--client` novo) são as duas conhecidas; IDE por Remote-SSH e web por Remote Control dirigindo sessão local dependem de ensaio; sessão de nuvem **não é suportada** (sem seleção local, board nem Guard; falha visível no resolver e no `process_event`). Versão do host não é lista: o coletor aceita qualquer versão cujo transcript bata com o schema `claude-transcript-v1` e recusa com `unsupported_schema` (tipo, campo e versão) quando o formato muda; só os pisos de capacidade (`effort` por invocação, 2.1.292; hooks com `onFailure: "block"`, 2.1.295, exigidos nos nascimentos e nas transições que dependem de hook) e a superfície (`cli` ou `claude-desktop`; mais de uma superfície no mesmo transcript = `unverified`) recusam. A versão do host vem da própria sessão (`AI_AGENT`, conferida com o `version` do transcript): dentro de uma sessão o `claude` do PATH nunca é consultado (o app roda outra cópia que o terminal) e a falta de `AI_AGENT` é `capability_unavailable` citando a superfície. Superfície sem hooks, sem `effort` por invocação ou com formato de evidência mudado falha visível, sem fallback para outra superfície ou cliente. Troca de cliente entre etapas é permitida pela mesma FSM: cada proxy registra cliente e modelo observado e o handoff repete os das etapas anteriores.

### Claude Code pelo app desktop (Windows, por SSH)

- **Abrir:** o app abre a sessão em `/source` (o checkout de `environments.dev.source` do overlay) com a opção *worktree* do app **desligada**. A sessão nasce em `develop` sem card; o pedido `#<id>` leva a própria sessão ao worktree `card-<id>-*` com `EnterWorktree`, e o shim reinjeta a página do card. Título da sessão do card: `#<id>` (ferramenta de título do app, classificada como permitida). O Status continua no board, no navegador.
- **Pasta do app = pasta sem card:** se o app abrir a sessão numa pasta que ele criou (opção *worktree*: `<raiz>/.claude/worktrees/<nome>`, branch do app), a página diz `pasta do app (sem card)`: escrita de produto e de OpenSpec negada, nenhum filho de etapa, `prepare` e `process_event` recusados (`claude_evidence:app_folder`). Saída: peça `#<id>` na mesma sessão (`EnterWorktree`); a pasta do app não é apagada nem adotada, Alan a arquiva no app. `.claude/worktrees/` fica no `.gitignore` do consumidor.
- **Filho só por `Agent`:** com card vinculado o hook nega as ferramentas `mcp__ccd_*` do app que criam sessão, mandam mensagem a outra sessão ou abrem sessão em outra pasta (`stage_child_only_agent`); leitura e layout ficam livres, e `mcp__ccd_*` nova, não classificada, vale como criadora até ser classificada. Cada filho leva `description` `<papel> <id> <único>` (aparece no painel de tarefas do app com a etapa e o estado).
- **Handoff por filho:** ao fim de cada filho o pai escreve no chat e no comentário do card **uma linha**, tirada do proxy e nunca do pedido: `claude_proxy.py ... --birth <receipt> --handoff [--gate <gate>]` imprime cliente, superfície (com versão do host e do app), modelo/esforço observados e status; com evidência ausente ou divergente a linha diz qual gate reprova.
- **Modo de permissão do app (`auto`) não autoriza processo:** o deny do hook vale em qualquer modo e nenhuma página reivindica Auto. Onde o app não oferecer hook, `effort` por invocação, versão legível, sessão identificável ou transcript no formato, a etapa para com o motivo no chat do app (`hooks_inactive`, `capability_unavailable`, `unsupported_schema`, `unverified`), sem passar ao terminal.
- **Comandos para o operador:** sempre para colar em bash comum, **sem `!` na frente e sem `cd … &&`** (o `!` é negado e o `&&` aborta em silêncio); um comando por bloco, com paths literais.
- **Depois da revisão da conta:** `install.sh --account` e a revisão R/A (`cf_shim.py trust --record`, no terminal do operador, com confirmação digitada; recusa dentro de sessão de agente) só valem em **sessão nova**: até lá o `prepare` responde `hooks_inactive` e `hooks_changed`.
- **Pins mistos:** se a sessão passou por worktrees com pins diferentes, a página avisa citando cada raiz e pin.
- **Revisão do instalador:** ao subir o pin, a onda de review inclui o diff do `install.sh` do nucleus: `materialize_review_diff.py --nucleus <checkout do covenant-flow> [--nucleus-base <tag anterior>]` junta o diff (com o prefixo `covenant-flow/`) ao `review_diff_path`.
- **T5 (`submeter_design`):** recusa `guard:design_tokens`, citando o token faltante, quando `design.md` não tem `UI impact`, `live_route` e `surface` parseáveis (o mesmo predicado do checklist do precommit).

## Modos Cursor (terminal vs Desktop+SSH)

Dois modos do **mesmo** cliente Cursor nesta VM — não abandonar um modo e não forçar um só host:

1. **modo terminal** — Agent/CLI no terminal Linux desta VM.
2. **modo Desktop+SSH** — Cursor Desktop Windows + Remote SSH a esta VM.

Cada etapa grelha / Design / Apply / review / QA / Done técnico passa **nos dois**. Grelhar num e Apply noutro **não** conta. Homologado / Release / lote fora deste chat. Grok / OpenCode / dsh fora (InstantiationService e Landlock/`uid_map` são Cursor; #822 não autoriza alargar). «Grok / OpenCode / dsh fora» não é deny de T5/`G_design`. Destape de pai mudo pós-`completed` = #879. Hang do host (S2) = #879. Unbound `develop` = #864. Impeccable cwd = #822. Um chat `#<id>` = #729 (título **não** `#<id> Apply`). MUST NOT dual-write lei em `.dsh/` nem `.grok/` nem `.opencode/` só por estes modos.

### Pasta (Q2)

Depois do Apply arrancar e existir worktree `card-<id>-*`, a raiz **visível** (explorer) é essa pasta.

- **modo Desktop+SSH Windows desta VM:** o pai **MUST NOT** chamar MCP `move_agent_to_root` (testemunha: `InstantiationService has been disposed`). Bind da raiz visível = **janela Remote-SSH nova** no worktree `card-<id>-*`, título `#<id>`. Operador MUST NOT File > Open. MUST NOT reload da **mesma** janela. MUST NOT retry do MCP após dispose. `working_directory` sozinho não satisfaz Q2 se o explorer ainda é `source` / `environments.dev.source`.
- URI (MUST = janela **nova**, InstantiationService nova; MUST NOT MCP): `vscode-remote://ssh-remote+<esta-VM><abs-path-worktree>`. Comando host residual (P3): `cursor --folder-uri <uri>` **só** se abrir janela nova **sem** dispose do serviço actual; equivalente que **não** dispose = Remote-SSH «Open Folder in New Window». Diálogo de aceite da janela nova **não** conta como Q2.
- **modo terminal:** o pai MAY `move_agent_to_root` ou já nascer com cwd no worktree.
- Filho isolado (qualquer modo): **MUST NOT** `move_agent_to_root`.

### Comando (Q3)

Shell do fluxo (git do runbook, `process_event`, pytest do harness) no worktree `card-<id>-*` neste par Desktop+SSH: `required_permissions: ["all"]` no **primeiro** attempt do turno. MUST NOT `workspace_readwrite` + clique extra. Falha Landlock / `uid_map` (`Failed to write /proc/self/uid_map`) fica **visível**; ecrã em branco sem explicação não passa. Ensaio = needles; não afirmar que o host nunca pinta cartão. `.cursor/cli.json` / `sandbox.mode` **não** é contrato sem prova viva **neste** Desktop (P3). Sem pin novo. Sem overlay `clients.*.auto`.

### Filho (Q4)

Sucesso da etapa só com host `completed` **e** payload de retorno. `Task was interrupted by the user` sem Stop visível no turno = **kill do host** (falha deste card). Pai MUST NOT executar a etapa no Desktop em substituição. Operador MUST NOT retomar cadáver. Stop explícito = aborto: não sucesso; restage = spawn **novo**, não resume. Pai MUST NOT mutar o workbench (MCP de raiz, reload) enquanto o filho corre.

### Ensaio e prova viva (Q5–Q6)

Prova viva pasta + comando + filho **só** no par Windows + SSH a esta VM (QA deste card, não card inteiro, não outro PC). Grelha / Design / review / QA: ensaio (pytest needles / goldens / rubrica), não runbook-only. Destape #879 e hang S2 continuam #879.

Rubrica prova viva (1.5):

1. Pasta visível = worktree `card-<id>-*` (não File > Open; não só `working_directory`).
2. Comando do fluxo no **mesmo turno** sem clique extra (`required_permissions: ["all"]` à primeira).
3. Um filho de etapa com host `completed`.

### Prompts autocontidos (grill / Design-autor / Apply / review / QA)

O pai cola o bloco no spawn isolado (sem transcript do pai). O pai passa o slug no parâmetro `model` do Task (captura local acima). MUST NOT depender do picker do pai. MUST NOT recomendar picker ao pai. Ensaio do pai **não** substitui filhos da faixa de juízo capturada. `working_directory` = worktree quando a árvore existir. Filho MUST NOT `move_agent_to_root`. Neste par Desktop+SSH: Shell do fluxo com `required_permissions: ["all"]` no primeiro attempt. MUST NOT `workspace_readwrite` + clique. Sucesso = host `completed`. `Task was interrupted by the user` sem Stop visível = kill do host. MUST NOT retomar cadáver. Título `#<id>` (não `#<id> Apply`).

**Apply-coluna** (único filho da coluna / não devolvas entre tasks): és o único filho Apply desta entrada em Em desenvolvimento. Loop interno até todas as tasks feitas ou um P0 visível. Não devolvas o turno entre tasks. Não spawnes reviewers. Não `process_event` / commit / push. Recusa visível no pai se devolveres cedo sem P0 (não abre review nem segundo Apply).

**Onda Code Review** (os dois nascem neste turno / não esperes destape do primeiro): no mesmo turno do pai, spawna `diff-reviewer` e `code-reviewer` sobre o intervalo já colado. Os dois nascem neste turno. Não esperes destape do primeiro. Fila do host não falha. Relógio = o mais lento.

**Teto em silêncio** (schema no dump; 1+1; residual no Done; sem Ask): o pai **copia** `gravidade`/`classe` do dump (não reclassifica prosa, não infla); `bloqueia_merge: sim` num nit ≠ terceiro ciclo; P0 pára a coluna; mecânicos juntos num Apply de correção **sem Ask**; juízo → residual (não ocupa o slot); após 1 correção + 1 onda, P1/P2 restante ou P1/P2 novo = residual no Done (handoff + comentário), card segue; MUST NOT terceiro ciclo; MUST NOT «autorizar extra / aceitar residual». Tabela destape: limpo → commit; só juízo → residual, card segue (não gasta correção); mecânico → no máximo um conserto + uma verificação; após 1+1 → residual, card segue; P0 → a coluna pára.

## Colunas (Project 1)

Caminho obrigatório:

`Em Refinamento → Todo → Design → Aprovação de Design → Pronto para Dev → Em desenvolvimento → Code Review → QA → Done → Homologado → Pronto`

`Cancelado` é terminal a qualquer momento, inclusive Em Refinamento.

Gates humanos (agente não cruza; só Alan, no board ou por comando exato capturado fora do agente, ver "Comandos de portão"): T1 Em Refinamento→Todo; T2 coluna viva→Cancelado; T6 Aprovação de Design→Design (devolver, com motivo); T7 Aprovação de Design→Pronto para Dev; em Done, o par `homologar` → Homologado (T15) e `nao_homologar` → Em desenvolvimento (T18, motivo visível `Não homologar:` + texto no issue). Homologado→Pronto é T16: `process_event fechar_release` após `release-guard post` PASS. Homologado sem aresta inversa. Arraste GitHub Done→Em desenvolvimento sem esse comentário é fora-de-δ: o agente não restaura o Status (não move Status); comenta pedindo o motivo e não segue o Apply até o comentário existir; não inventar UI no board.

| Status | Significado |
| --- | --- |
| `Em Refinamento` | Entrada **e** grelha da história (`grill-card` no issue). Alan escolhe, prioriza ou cancela. T1 só Alan (board ou `/priorizar N`, que já inicia o Design) |
| `Todo` | Backlog (história já afiada). **Não é código.** Próxima etapa: Design. Arrasto para Todo fica em Todo |
| `Design` | OpenSpec sintetiza o issue grelhado + crítica; Gist no card; protótipo se UI. Não reentrevistar |
| `Aprovação de Design` | Aguardando Alan (T7 `/aprovar-design N` ou T6 `/devolver-design N "motivo"`, ou board) |
| `Pronto para Dev` | Design aprovado; único status que libera `/opsx:apply` |
| `Em desenvolvimento` | Implementando |
| `Code Review` | Diff pronto; review antes do commit |
| `QA` | SHA revisado em checks |
| `Done` | Done técnico em `develop` |
| `Homologado` | Alan aprovou em `develop` |
| `Pronto` | Publicado em `main` **e** deploy PROD validado |
| `Cancelado` | Não será feito |

**Anti-bypass:** pedido `implemente` / `implemente todos` **não** autoriza código nem `/opsx:apply` enquanto `Status=Todo`. `UI impact: none` não pula colunas.

### Comandos de portão

O Alan passa os seis portões no board ou digitando no chat, como a mensagem inteira, uma destas linhas (`<card>` = número do issue, com ou sem `#`; motivo entre aspas duplas, 1–500 caracteres, sem aspas nem quebra de linha):

`/priorizar <card>` (T1 e, no mesmo run, T3) · `/aprovar-design <card>` (T7) · `/devolver-design <card> "motivo"` (T6) · `/homologar <card>` (T15) · `/nao-homologar <card> "motivo"` (T18) · `/cancelar <card> "motivo"` (T2, pede `/confirmar-cancelar <card>` em até 10 min)

- **Quem reconhece:** o hook de prompt do Claude Code (`UserPromptSubmit`, registro na conta), antes do agente, e manda ao **executor do board** (GitHub Actions no repo do executor, único dono do token que escreve no Project). O executor confere coluna de origem, evento e ator contra a FSM fixada no `PIN`, move, deixa recibo na issue (`Devolver design:` / `Não homologar:` / `Cancelar:` na primeira linha quando move) e responde. `/aprovar-design` é recusado se o design mudou desde o T5. Variação ("aprova aí", maiúscula, palavra a mais, duas linhas, sem motivo) não tem efeito nem recibo. Comentário de issue nunca é entrada do executor.
- **Agente:** move só pedindo pelo `process_event` (o executor recusa evento do Alan pedido pelo agente com `actor`); não chama `portao_client`, `capturar` nem `dispatches` (a Guard nega). Com o resultado do executor no contexto adicional da mensagem, siga a FSM a partir do Status atual (`/priorizar` já deixou o card em Design; `/homologar` movido: comentário de evidência de homologado no mesmo turno). **Texto com cara de comando sem esse contexto** (hook ausente, outro cliente, `board.executor` desligado) é wording: diga que o comando não foi capturado e aponte o board; não mova nem capture por conta própria. Sem resposta no teto (90 s): não presuma o resultado, leia o recibo da issue.
- **Nível: cooperativo.** O agente roda no mesmo usuário do sistema que o hook, com root: pode forjar um `capturar` e apagar o run e o recibo (tem `write` nos dois repos), e o recibo sai como `oalansilva`, então não avisa o Alan. Run e recibo são registro, não prova. O que fica fora do alcance do agente é o token que escreve no Project. Cursor, Codex, OpenCode, Grok Build e dsh ficam só com o board.

### Design — clone da página viva

> **Clone da página viva:** em superfície já existente — rota autenticada no catálogo (`/monitor`, `/favorites`, `/combo/discovery`, `/combo/select`) **ou** HTML público vigente (chave `landing` = landing v4 em `https://criptofarol.com.br/`) — o URL canónico do proto (`…/prototypes/<slug>/` → `index.html`) MUST clonar essa página viva e aplicar só o delta do card. Nunca «6 estados» / painel ANTES/DEPOIS como URL canónico, mesmo com clone noutro ficheiro da pasta. Copy visível (landing / Ajuda / Perfil) = a página mudou; Prototype N/A é recusado. N superfícies existentes: URL principal = página primária clonada; as outras com copy visível têm URLs extra de clone — nunca um painel das N no index.

> **Design fecha em 1+1+1 (teto):** sem-tela = 1 autor + 1 crítico + 1 rework; com-tela = autor + dupla + 1 rework. Segundo rework só com P0 novo de produto justificado no prompt; fora disso o pai publica a seção de crítica com os P3 aceitos e submete. **Classificação:** só produto/escopo/contrato visível (tela, estados, acessibilidade, escopo furado) gera P0/P1; detalhe de implementação é P3 "detalhe de Apply", aceito em `design.md` e resolvido no Apply — nunca reaberto como P0/P1. **Gate no autor:** o primeiro autor já entrega `UI impact` / `live_route` / `surface` em linha própria parseável; sem-tela declara ausência + justificativa curta (nunca rota de catálogo emprestada); com-tela marca só as regiões clonadas. O crítico/dupla verifica esses tokens como item da rubrica.

### Design — teto e validação

Validação do segundo rework: o pai justifica o P0 novo de produto no prompt; sem justificativa, o segundo rework não é spawnado. "Dupla" = "onda A/B" da tabela de filhos.

## Preflight

Antes de editar:

- `git status -sb`; não misturar outra change.
- Overlay on-demand: `overlay_doc` só se portas/Drive/banco/release.
- Consultar `Status` no board (`github-project-board`).
- Release/deploy/PROD: carregar também `covenant-flow-environments`.

## Grill-card (Em Refinamento)

Skill de entrada: `.cursor/skills/grill-card/` (adapter). Primitivo vendorado: `.cursor/skills/grilling/`. **Não** usar `grill-with-docs` nem `to-spec`.

Disparar quando Alan pede para grelhar/afiar **ou** Status da issue N é Em Refinamento **e** o body **ainda não** diz quem sofre e o que entra/não entra (N no prompt, mesmo em `develop`). **Card nítido:** quando o body já diz quem sofre e entra/não entra, o pai **não** spawna `grill-card`; posta ou mantém exactamente `card nítido; sem grill` (idempotente; não é o comentário T1). Pedido explícito grelhar/afiar continua. Não em todo T0. Não em Todo/Design. DoD da grelha = **3 seções** (`## Problema`, `## História`, `## Entra`; critérios dentro de Entra); MUST NOT exigir Vocabulário/Riscos no issue em Em Refinamento.

O **pai** spawna o filho `grill-card` (id no prompt, mesmo em `develop`). O filho reescreve o **body do issue N** e, com fronteira vazia, comenta o handoff T1. Pai só relaying das rodadas. Nas Qs fechadas, o pai chama a ferramenta do host com **todas as options** que o filho listou e não colapsa à recomendada. Com o host no ar, o prompt da Q é título + conflito; a recomendação é só a primeira option `(Recommended)`. Não arrasta Status. Não grava `CONTEXT.md` / `docs/adr/`. Não chama `/opsx:*`.
Tecto: Qs e options em português de operador em todo card em Em Refinamento; identificador do git é facto no body ou *como* no Design, não option no host; Other vazio, silêncio e «não percebi» / «isto é técnico» reclassificam e nunca aceitam a recomendada.
Cliente dsh: dsh não spawna filho grill.

## Card primeiro, OpenSpec mais completo

1. O card nasce primeiro (pode estar incompleto). Em Refinamento: `grill-card` afia o issue; T1 continua só Alan.
2. Design refina em OpenSpec + Gist secreto `crypto openspec <change>`, **sintetizando** o issue grelhado (não reentrevista).
3. O Gist SHALL ser **superset** do issue (**história copiada** — Problema, História, Entra/não entra — **+** *como* neste pacote). MUST NOT Gist só o *como*. `/opsx:apply` lê Gist + `openspec/changes/`, não o body do GitHub como spec paralela.
4. Sem Gist/comentário no card, Design está incompleto. Republicar: `--gist-id` + `--comment-id`.
5. HTML de protótipo **não** vai no Gist. URL HTTP em bloco separado. Protótipos HTTP: URL do consumidor (overlay), nunca HTML no Gist.
6. Se o body em Design **não** tiver Problema, História e Entra/não entra (briefing de 3 seções no *issue*): não `/opsx:ff`; comentar as seções em falta; permanecer em Design. `proposal.md` MUST copiar essas seções do body do issue (MUST NOT inventar história). `/opsx:explore` só para furo técnico (código/specs), nunca para reescrever a história.

Helper (path relativo a esta skill no repo):

```bash
.cursor/skills/covenant-flow/scripts/publish-openspec-card-artifacts.sh \
  --repo <overlay.repo> --issue <n> --change <change>
```

## OpenSpec

Usar skills `.cursor/skills/openspec-*` e CLI `openspec`. Não inventar artefatos fora de `openspec instructions`.

Ordem: `/opsx:new` → `/opsx:ff` → publicar Gist → Design → (Alan) Pronto para Dev → `/opsx:apply` → `/opsx:verify`. Archive só no fechamento de lote/release. Se o issue bound já tiver o briefing grelhado (Problema, História, Entra/não entra), o briefing **é** o issue; não perguntar de novo o que construir; não invocar `grill-card` para gerar `proposal.md`. Sem schema `grill-driven`.

## Implementação

Só com `Status=Pronto para Dev`. Pai chama `iniciar_apply` **antes** do spawn. Branch `card-<id>-<slug>` ou `change-<id>-<slug>` a partir de `develop`. Tecto: **um** filho Apply por entrada em Em desenvolvimento (loop interno até tasks feitas ou P0 visível). Recusa visível se o Apply devolver cedo sem P0: **não** abre review nem segundo Apply. O **filho** Apply edita o código (loop fatiado interno); **não** `process_event`, **não** commit/push, **não** spawna reviewers; devolve status ao pai só com tasks feitas ou P0 visível.

Pós-T18 (`nao_homologar`): q já é Em desenvolvimento no mesmo card. Reabrir ou criar `card-<id>-*` a partir do `develop` actual (squash T14 já está lá). Write só com I1 (não develop/main). **Não** chamar `iniciar_apply` (T8 é de Pronto para Dev). Segue `pedir_review` → … → T14 → Done; o par homologar / não homologar reaparece.

Pai: `pedir_review` (Code Review), materializa o intervalo em `.cursor/tmp/review-diff.patch` e spawna os **dois** Task (`diff-reviewer` + `code-reviewer`) **no mesmo turno** com `review_diff_path:` (MUST NOT pedir git ao filho). Fila do host não falha; destape do primeiro MUST NOT nascer o segundo (já spawnado). MAY spawnar esses reviewers como `generalPurpose` cujo prompt é o corpo do agent file **ou** como `subagent_type` nomeado; o matcher do destape cobre os dois. Continua a exigir `review_diff_path:` e a string exacta do `description` do Task no sidecar. O pai **copia** schema do dump (`gravidade`, `classe`); MUST NOT reclassificar; MUST NOT inflar gravidade. `bloqueia_merge: sim` num nit ≠ terceiro ciclo. P0 continua a parar a coluna. Mecânicos juntos num único Apply de correção (prompt = a lista) **sem Ask**; juízo vai a residual e **não** ocupa o slot. Após 1 correção + 1 onda, P1/P2 restante **ou P1/P2 novo** = residual no handoff de Done **e** no comentário do card; o card **segue** (commit, PR, QA). MUST NOT terceiro ciclo. MUST NOT perguntar «autorizar extra / aceitar residual». Pai MUST NOT corrigir no próprio transcript. Fecho vs `develop` cola `## Residual já no card`; residual já no comentário **não** reabre e **não** sobe; só defeito novo (ou reuse SHA). Fecho pós-commit continua **uma** onda. Depois da onda, correr `scripts/process-fsm/review_process_checklist.py` **antes** do commit (`--wave-same-turn yes` se os dois nasceram neste turno). Falha = `ERROR: process-checklist failed:` + item (bloqueio visível, não commita, não prosa de LLM). Depois: commit, closing vs develop, push. `aceitar_sha` só com PR `q_git`→develop (`no_pr` ⇒ abrir PR e repetir no mesmo turno). Depois: filho QA (checks), T14. `/review-bugbot` MUST NOT. `/review-security` MAY se Alan pedir explicitamente; o gate continua os dois reviewers locais.
**dsh:** após 400 desta classe (reasoning effort off/none) num filho, MUST NOT spawnar mais o mesmo preset (incl. retry 1/1 #518); registar `ERROR: subagent spawn failed/empty` e continuar no root com residual explícito.

## Code Review — cola do diff (S1)

Antes de spawnar `diff-reviewer` / `code-reviewer`, o **pai** materializa o intervalo (nunca o filho):

- Pré-commit: `python scripts/process-fsm/materialize_review_diff.py --mode pre-commit` (`git diff HEAD` + untracked de `git ls-files --others --exclude-standard`, **excluindo** `.impeccable/critique/` JSON/MD/PY/PNG — artefacto de processo, não produto).
- Fecho: `python scripts/process-fsm/materialize_review_diff.py --mode closing` (`git diff origin/develop...HEAD`, mesma exclusão de `.impeccable/critique/`).
- Grava `.cursor/tmp/review-diff.patch` (já gitignored via `.cursor/*`).
- No spawn: linha `review_diff_path:` apontando esse ficheiro. MAY colar bytes sob `## Diff`.
- MAY spawnar como Task `generalPurpose` (prompt = corpo do agent file) **ou** como `subagent_type` nomeado `diff-reviewer` / `code-reviewer`. O matcher do destape cobre os dois.
- MUST NOT pedir git ao filho. MUST NOT pedir Glob/listagem de `agent-transcripts`.
- Grelha, Apply e QA **não** recebem este contrato.

Pin overlay permanece `v1.1.16`. Stubs Grok/dsh/OpenCode: ponte ≤8 linhas; MUST NOT dual-write lei.

Checklist de review: se o OpenSpec estiver noutro checkout, passe `--change-root <consumer-root>`. O padrão `strict` continua exigindo todas as tasks marcadas. Antes do commit, use `--phase precommit`: tasks de implementação pendentes bloqueiam; só tarefas com a anotação explícita `<!-- covenant-flow:after-commit -->`, `<!-- covenant-flow:after-pin -->` ou `<!-- covenant-flow:after-qa -->` podem aguardar, vencendo respectivamente em `postcommit`, `postpin` e `postqa`. Depois do pin/QA, rode novamente com `--phase postqa` para revalidar todas as tasks.

## Destape — subagentStop (S2)

Quando o filho das quatro etapas (grelha / Apply / review / QA) **ou** Design-autor / crítico / Assessment A/B já devolveu (`status=completed`) e o pai ainda espera o mesmo Task, o hook `subagentStop` injecta `followup_message` com **ordem** (nunca pergunta `concluiu?` / `já acabou?` / `verifique se nao concluiu`). Matcher: `generalPurpose|diff-reviewer|code-reviewer` (cobre spawn `generalPurpose` e `subagent_type` nomeado).

O **pai**:

- Grava `.cursor/tmp/awaiting-task.json` **antes** do Task das quatro etapas **e** do Task Design-autor / crítico / Assessment A/B.
- Sidecar `description` MUST ser a string exacta do `description` do Task (título 3–5 palavras do spawn). Cursor `subagentStop` MAY colocar essa string em `task`. `task` no sidecar é o `subagent_type`, não o título. Não fuzzy-match (`Grill card` ≠ `grill-card 879`).
- Sidecar MUST ter `description` não-vazia. Vazio ≠ wildcard. `task` / `subagent_type` no sidecar são opcionais; se presentes, comparar com o `subagent_type` do stop (ou nested), NÃO com o `task` do stop.
- No `description` do Task (e no sidecar) MUST constar um needle do classificador. Títulos curtos sem needle MUST NOT destapar. Needles: `grill-card`, `apply-coluna`, `diff-reviewer`, `code-reviewer`, `qa-gate`, `design-autor`, `design-critic`, `Assessment A`, `Assessment B`.
- O classificador usa só sidecar.description ∪ stop.task (título curto) ∪ `subagent_type`. MUST NOT classificar a partir do prompt longo (`description` / corpo colado, p.ex. SKILL.md com needles `design-autor`).
- Sidecar **por** Task. Destape do primeiro reviewer da onda = espera o par (não commita, **não** spawna o outro reviewer agora). Poke do primeiro reviewer MUST NOT ser skip do segundo; commit só depois dos dois. Tabela destape (não pontues cláusula em falta): limpo → commit; só juízo → residual, card segue (não gasta correção); mecânico → no máximo um conserto + uma verificação; após 1+1 → residual, card segue; P0 → a coluna pára. Reviewer de processo MUST NOT pontuar cláusula em falta. MUST NOT dois sidecars.
- Apaga o sidecar ao tratar o resultado. O hook apaga o sidecar após o poke.
- Poke = ordem. Proibido `concluiu?` / `já acabou?`.
- Staff MUST NOT re-prompt enquanto o filho corre.
- Background, `error`/`aborted` e filho ainda a trabalhar: **fora** do destape. Destape MUST NOT afirmar que dispara para filhos em background nem que cura hang do host. `AGENTS.md` e overlay `clients.*.auto` intocados; sem aresta em `process-fsm.yaml`.

## QA closeout

**Cursor / Grok:** um filho QA isolado lê checks e MUST NOT `process_event`. O pai chama `integrar_develop` no mesmo turno do filho verde (ou quando o próprio pai vê `qa-gate` success). `qa-gate pending` ⇒ espera e repete T14 no turno. `no_pr` e `sync: dirty` são causas visíveis; o primeiro reject não encerra o turno. Sinal determinístico (inventário de teste, formatação, skip de ficheiro novo) fica no Apply/QA até verde ou teto; MUST NOT reabrir onda de juízo.

**dsh:** o root MUST NOT spawnar filho QA. O mesmo turno abre o PR antes de T11, espera `qa-gate` no turno (`job_output wait`, sem `continue`) e chama T14 (Moore/plugin `covenant-flow:moore`, não só o texto desta skill).

**Teste no DEV (`qa_dev.enabled` true no overlay; desligado, a T14 é a de sempre).** T14 tem duas fases na mesma aresta, sem estado nem evento novo:

1. **Fase 1:** `integrar_develop` pega a trava, integra, reinicia o DEV, grava o recibo, comenta e devolve `qa_dev_pendente`. O card fica em `QA`. `qa_dev_ocupado` é outro card em teste: espere e repita.
2. **Teste (só no Claude Code):** o pai roda `scripts/process-fsm/qa_dev.py plan --card <id>`, que devolve o plano com C1…Cn, protótipo, `admin` e FAIL abertos.
   - `status=nada_para_testar` ou `inconclusivo` (DEV ou serviço parado antes do navegador): vá direto ao `report`, sem filho.
   - `status=falha_ferramenta` (senha recusada, conta bloqueada): sem relatório; o `plan` já soltou a trava e comentou o que falta. O card fica em `QA`. Navegador que não abre: `qa_dev.py soltar --card <id> --motivo navegador`.
   - `status=pronto`: agrupe por tela ou fluxo, até 3 critérios por bloco. Um filho `qa-dev` novo por bloco, em sequência (`description` `qa-dev <id> bloco-<n>`, captura `--role qa-dev`), com a skill `qa-dev`. Critério que estourou o teto vai para o bloco seguinte. Bloco parado por DEV fora do ar repete uma vez quando a saúde voltar. Depois dos blocos de critério, um filho final faz a volta rápida.
3. **Relatório:** `qa_dev.py report --card <id> --run <run> --runtime "<linha do handoff>"` confere saúde e serviços de novo, junta os blocos, calcula o veredito, envia a evidência, passa o texto na varredura pública e posta. Varredura recusou: nada foi postado; reescreva no bloco o campo apontado, sem o valor, e rode de novo.
4. **Fase 2:** `integrar_develop` de novo lê o último relatório do autor `qa_dev.autor_relatorio`. `PASS`, `NAO_TESTADO` e `NADA_PARA_TESTAR` levam a `Done`.

O filho `qa-dev` MUST NOT `process_event`. Sem o navegador (Cursor, Codex, Grok, OpenCode, dsh), a T14 para em `qa_dev_pendente`, com mensagem para abrir a sessão `#<id>` no Claude Code; essa sessão continua do mesmo ponto.

**`qa_dev_fail` pausa.** O pai MUST NOT chamar T13 no turno do `qa_dev_fail`: T13 depois da integração não tem reteste sem diff. Mostre os critérios em FAIL, pergunte ao Alan e pare, sem prazo.

- Alan confirma o defeito: T13, depois o caminho pós-T18: branch nova a partir de `develop`, com o nome exato do change (a antiga, já integrada, é renomeada), Apply, Code Review, `QA` e T14. O reteste roda os critérios em FAIL e os tocados pelo diff: `plan --reteste-de <run> --criterios C3,C4`; os demais aparecem como PASS do run anterior.
- Alan discorda: reteste sem diff de FAIL contestado, `plan --reteste-de <run> --leitura "<leitura dele>"`. Refaz só os critérios em FAIL, com a leitura no plano; nada é integrado e o Status não muda.

**`qa_dev_inconclusivo` para com três saídas:** novo teste, sem diff; T13, se o card derrubou o DEV ou o worker; ou o comentário exato do próprio Alan, `/qa-dev-liberar <run>`. Nenhum agente posta essa linha. Depois dela, T14 de novo move para `Done` dizendo que houve liberação. FAIL não tem liberação.

Homologado: no **mesmo turno** do arraste/confirmação, `scripts/post-card-evidence-comment.sh --transition homologado` (mesmo sem lote).

## Release

Pedido explícito de Alan (`subir lote`, `fechar release`, …). **Pré-requisito (chat pai execução):** pai em juízo ou escolha divergente exige sessão nova de execução. Capture a escolha local de execução da operação e valide pai observado pelo `check_runtime_model(..., capture=...)`; valores ausentes/divergentes recusam T16. Nenhum modelo de outro cliente é obrigatório. Chat em escolha diferente exige sessão nova corretamente configurada — única excepção ao silêncio sobre picker nos chats de card. A frase de Design «mesmo modelo do chat» NÃO é gate de release. Overlay de ambiente em `covenant-flow-environments`. Detalhe humano: `overlay_doc`. `bound_card=⊥` / `enabled_events: (unbound)` são display do paging, não deny de T16; pedido explícito unbound em `develop`/`release-*` carrega overlay + `covenant-flow-environments` e segue T16; Write de produto continua deny. Guard: `scripts/release-guard pre` / `post`; `RELEASE_CARDS` nos exemplos de `pre` de lote; `PRESERVED_BRANCHES` no `pre` quando houver worktree in-flight. Homologação não autoriza `main`. Antes do `post`: `/kaizen release` no log **e** materialização Kaizen (1–3 cards em Em Refinamento, dedupe `coberto por #N` em fluxo, ou `Sem achados acionáveis`) — skill `kaizen` é read-only; o orquestrador cria os cards (#661). Branches de `RELEASE_BRANCHES` MUST estar ausentes local+remota **antes** do `post` PASS e **antes** de `Pronto`; `PRESERVED_BRANCHES` e worktree in-flight permanecem. MUST NOT desligar `qa-gate`. Com pedido explícito de release, sync e archive das changes concluídas do pacote Homologado em `release-*` seguem o `decide()` do #1022, sem o menu genérico `openspec-archive-change` («Sync now / Archive without syncing»), sem segunda allow-list e sem worktree do card + cherry-pick. Até esse `decide()` estar na árvore, deny de archive (pacote ou card não resolvido, ou pacote resolvido em `release-*` unbound com `fail_closed`) é bloqueio real que aponta #1022 — MUST NOT pedir a Alan aprovação extra por causa do texto do #1022. Conflito sem resolução, descarte ou excepção real continuam perguntados; silêncio não aprova. T18 continua `nao_homologar` de Alan. Tabela de decisão compartilhada: `scripts/process-fsm/release_closeout.py` (Cursor e Codex; diferença só encoding da pergunta e captura do próprio cliente).

### Filho isolado `fecho-lote` (Cursor)

No **mesmo turno** do pedido explícito de fechar lote / subir release, o pai spawna **um** filho isolado antes de T16:

- `description` MUST conter `fecho-lote` e MUST NOT conter needles do classificador de destape (`grill-card`, `apply-coluna`, `diff-reviewer`, `code-reviewer`, `qa-gate`, `design-autor`, `design-critic`, `Assessment A`, `Assessment B`, nem `\bqa\b` / `\bgrill\b` soltos). Título canónico: `fecho-lote kaizen`.
- Caminho Cursor: `generalPurpose` com `model` igual ao capturado de `cursor/execucao` da escolha local. No Grok Build: `spawn_subagent` com `model` capturado de `grok/execucao`; MUST NOT omitir `model`; MUST NOT herdar o picker.
- Prompt autocontido: és o filho `fecho-lote`; MUST NOT `process_event`; MUST NOT arrastar Status; MUST NOT commit/push; MUST NOT `move_agent_to_root`; Read overlay + `covenant-flow-environments`; corre `/kaizen release` (skill `kaizen`, read-only); devolve o relatório. O **pai** chama `process_event fechar_release` no mesmo turno após host `completed`.
- MUST NOT gravar `.cursor/tmp/awaiting-task.json` para este spawn. Destape MUST NOT disparar. MUST NOT needle novo no classificador. Shell do fluxo: `required_permissions: ["all"]` no primeiro attempt.

Quando o push do archive em `develop` for recusado por proteção (`qa-gate`), mesmo com pacote só Homologado: use `release-*` = `origin/develop` + archive → PR `release-* → main`; `pre` em `release-*` **não** exige archive em `origin/develop`. Após merge + deploy PROD, sync `main → develop` (um PR de merge normal) é obrigatório antes do `post` final até `origin/main` ser ancestral de `origin/develop` (extra na develop = aviso no `post`; recusar #926 e #913+#914+#915). Não dual-write o playbook completo neste `SKILL.md` nem no stub `AGENTS.md`.

Archive OpenSpec do pacote Homologado no caminho B (`q_git=release-*`), depois do pedido explícito de release: identificar cada change `card-<id>-*` / `issue-<id>-*`, Status vivo `Homologado`, e gravar o archive **nessa** `release-*` (`openspec/changes/<change>/` e `openspec/changes/archive/<YYYY-MM-DD>-<change>/`). O controlo de escrita é `decide()` em `scripts/process-fsm/guard.py`. `bound_card=⊥` não bloqueia esse archive. Lista declarada ou o nome da branch sozinhos não autorizam. Não pedir confirmação operacional extra a Alan (T7 continua o gate de Design). Não abrir worktree `card-<id>-*` nem cherry-pick só para furar `fail_closed`. #1059 consome esse mesmo `decide()` e não cria segunda allow-list. O próximo `/kaizen release` aplicável registra se a recorrência F-1/#1022 (`fail_closed` em `release-*` unbound) encerrou. Esta regra não entra em `AGENTS.md` nem nos stubs `.dsh`/`.grok`/`.opencode`.

## Higiene

Worktree por change. Stash só temporário, classificado. Não dual-write esta skill para hermes/`~/.codex`.
