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

Cliente: **Cursor Agent**. Task/subagent usa `inherit` salvo pedido explícito no chat. **Exceção — lista fechada isolada** (inherit de modelo, **sem** transcript do pai): `grill-card`, Design-autor, Apply-coluna, QA checks, Assessment A/B, `diff-reviewer`, `code-reviewer`. Review = diff **exato** (não “Codex review”).

Overlay humano: `Read` o path `overlay_doc` de `.covenant-flow/overlay.yaml` quando a tarefa precisar de portas/Drive/banco/release.

## Comunicação

PT-BR curto. Não diga `concluído` / `Pronto` / `publicado` até a evidência do estado ser verdadeira. `Done` = Done técnico.

## Um chat por card

Título `#<id>` nos dois clientes (Em Refinamento → Done técnico). Homologado e Release/lote fora. Pai orquestra: `process_event`, git, recusas, handoff, relaying do grill. **Não** grelha, não escreve OpenSpec/protótipo (exceção: só `## Design Critique` após A/B), não implementa, não review, não QA. Recusar executar outra atividade **no mesmo chat** — não pedir outro transcript. Sem Status=Pronto para Dev + `implemente`: uma frase com Status atual + “Apply só depois de Pronto para Dev (T7 teu)” + parar. Sem estado, evento, hook ou `enabled_tools` novo na FSM. `AGENTS.md` always-on não cresce com esta regra.

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

Handoff de Design/Apply/Review registra **proxies**: palavras de `design.md`, bytes de HTML gerado vs copiado (`cp`/clone = copied; delta = generated; sem protótipo = `N/A`), número de spawns. Sem parser de usage Cursor/Grok e sem dashboard.

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

O pai cola o bloco no spawn isolado (`inherit`, sem transcript). `working_directory` = worktree quando a árvore existir. Filho MUST NOT `move_agent_to_root`. Neste par Desktop+SSH: Shell do fluxo com `required_permissions: ["all"]` no primeiro attempt. MUST NOT `workspace_readwrite` + clique. Sucesso = host `completed`. `Task was interrupted by the user` sem Stop visível = kill do host. MUST NOT retomar cadáver. Título `#<id>` (não `#<id> Apply`).

**Apply-coluna** (único filho da coluna / não devolvas entre tasks): és o único filho Apply desta entrada em Em desenvolvimento. Loop interno até todas as tasks feitas ou um P0 visível. Não devolvas o turno entre tasks. Não spawnes reviewers. Não `process_event` / commit / push. Recusa visível no pai se devolveres cedo sem P0 (não abre review nem segundo Apply).

**Onda Code Review** (os dois nascem neste turno / não esperes destape do primeiro): no mesmo turno do pai, spawna `diff-reviewer` e `code-reviewer` sobre o intervalo já colado. Os dois nascem neste turno. Não esperes destape do primeiro. Fila do host não falha. Relógio = o mais lento.

**Teto em silêncio** (schema no dump; 1+1; residual no Done; sem Ask): o pai **copia** `gravidade`/`classe` do dump (não reclassifica prosa, não infla); `bloqueia_merge: sim` num nit ≠ terceiro ciclo; P0 pára a coluna; mecânicos juntos num Apply de correção **sem Ask**; juízo → residual (não ocupa o slot); após 1 correção + 1 onda, P1/P2 restante ou P1/P2 novo = residual no Done (handoff + comentário), card segue; MUST NOT terceiro ciclo; MUST NOT «autorizar extra / aceitar residual». Tabela destape: limpo → commit; só juízo → residual, card segue (não gasta correção); mecânico → no máximo um conserto + uma verificação; após 1+1 → residual, card segue; P0 → a coluna pára.

## Colunas (Project 1)

Caminho obrigatório:

`Em Refinamento → Todo → Design → Aprovação de Design → Pronto para Dev → Em desenvolvimento → Code Review → QA → Done → Homologado → Pronto`

`Cancelado` é terminal a qualquer momento, inclusive Em Refinamento.

Gates humanos (agente não cruza): (0) Em Refinamento→Todo; (1) Aprovação de Design→Pronto para Dev (só Alan); (2) em Done, o par `homologar` → Homologado (T15) e `nao_homologar` → Em desenvolvimento (T18, só Alan, motivo visível `Não homologar:` + texto no issue). Homologado→Pronto é T16: `process_event fechar_release` após `release-guard post` PASS. Homologado sem aresta inversa. Arraste GitHub Done→Em desenvolvimento sem esse comentário é fora-de-δ: restaurar Done e exigir o motivo; não inventar UI no board.

| Status | Significado |
| --- | --- |
| `Em Refinamento` | Entrada **e** grelha da história (`grill-card` no issue). Alan escolhe, prioriza ou cancela. T1 só Alan |
| `Todo` | Backlog (história já afiada). **Não é código.** Próxima etapa: Design |
| `Design` | OpenSpec sintetiza o issue grelhado + crítica; Gist no card; protótipo se UI. Não reentrevistar |
| `Aprovação de Design` | Aguardando Alan |
| `Pronto para Dev` | Design aprovado; único status que libera `/opsx:apply` |
| `Em desenvolvimento` | Implementando |
| `Code Review` | Diff pronto; review antes do commit |
| `QA` | SHA revisado em checks |
| `Done` | Done técnico em `develop` |
| `Homologado` | Alan aprovou em `develop` |
| `Pronto` | Publicado em `main` **e** deploy PROD validado |
| `Cancelado` | Não será feito |

**Anti-bypass:** pedido `implemente` / `implemente todos` **não** autoriza código nem `/opsx:apply` enquanto `Status=Todo`. `UI impact: none` não pula colunas.

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

Disparar quando Alan pede para grelhar/afiar **ou** Status da issue N é Em Refinamento **e** o body não tem as 6 seções do DoD (N no prompt, mesmo em `develop`). Não em todo T0 (cards nítidos podem T1 direto). Não em Todo/Design.

O **pai** spawna o filho `grill-card` (id no prompt, mesmo em `develop`). O filho reescreve o **body do issue N** e, com fronteira vazia, comenta o handoff T1. Pai só relaying das rodadas. Nas Qs fechadas, o pai chama a ferramenta do host com **todas as options** que o filho listou e não colapsa à recomendada. Com o host no ar, o prompt da Q é título + conflito; a recomendação é só a primeira option `(Recommended)`. Não arrasta Status. Não grava `CONTEXT.md` / `docs/adr/`. Não chama `/opsx:*`.
Tecto: Qs e options em português de operador em todo card em Em Refinamento; identificador do git é facto no body ou *como* no Design, não option no host; Other vazio, silêncio e «não percebi» / «isto é técnico» reclassificam e nunca aceitam a recomendada.
Cliente dsh: dsh não spawna filho grill.

## Card primeiro, OpenSpec mais completo

1. O card nasce primeiro (pode estar incompleto). Em Refinamento: `grill-card` afia o issue; T1 continua só Alan.
2. Design refina em OpenSpec + Gist secreto `crypto openspec <change>`, **sintetizando** o issue grelhado (não reentrevista).
3. O Gist SHALL ser **superset** do issue. `/opsx:apply` lê Gist + `openspec/changes/`, não o body do GitHub como spec paralela.
4. Sem Gist/comentário no card, Design está incompleto. Republicar: `--gist-id` + `--comment-id`.
5. HTML de protótipo **não** vai no Gist. URL HTTP em bloco separado. Protótipos HTTP: URL do consumidor (overlay), nunca HTML no Gist.
6. Se o body em Design **não** tiver o DoD: não `/opsx:ff`; comentar as seções em falta; permanecer em Design. `/opsx:explore` só para furo técnico (código/specs), nunca para reescrever a história.

Helper (path relativo a esta skill no repo):

```bash
.cursor/skills/covenant-flow/scripts/publish-openspec-card-artifacts.sh \
  --repo <overlay.repo> --issue <n> --change <change>
```

## OpenSpec

Usar skills `.cursor/skills/openspec-*` e CLI `openspec`. Não inventar artefatos fora de `openspec instructions`.

Ordem: `/opsx:new` → `/opsx:ff` → publicar Gist → Design → (Alan) Pronto para Dev → `/opsx:apply` → `/opsx:verify`. Archive só no fechamento de lote/release. Se o issue bound já tiver o DoD do `grill-card`, o briefing **é** o issue; não perguntar de novo o que construir; não invocar `grill-card` para gerar `proposal.md`. Sem schema `grill-driven`.

## Implementação

Só com `Status=Pronto para Dev`. Pai chama `iniciar_apply` **antes** do spawn. Branch `card-<id>-<slug>` ou `change-<id>-<slug>` a partir de `develop`. Tecto: **um** filho Apply por entrada em Em desenvolvimento (loop interno até tasks feitas ou P0 visível). Recusa visível se o Apply devolver cedo sem P0: **não** abre review nem segundo Apply. O **filho** Apply edita o código (loop fatiado interno); **não** `process_event`, **não** commit/push, **não** spawna reviewers; devolve status ao pai só com tasks feitas ou P0 visível.

Pós-T18 (`nao_homologar`): q já é Em desenvolvimento no mesmo card. Reabrir ou criar `card-<id>-*` a partir do `develop` actual (squash T14 já está lá). Write só com I1 (não develop/main). **Não** chamar `iniciar_apply` (T8 é de Pronto para Dev). Segue `pedir_review` → … → T14 → Done; o par homologar / não homologar reaparece.

Pai: `pedir_review` (Code Review), materializa o intervalo em `.cursor/tmp/review-diff.patch` e spawna os **dois** Task (`diff-reviewer` + `code-reviewer`) **no mesmo turno** com `review_diff_path:` (MUST NOT pedir git ao filho). Fila do host não falha; destape do primeiro MUST NOT nascer o segundo (já spawnado). MAY spawnar esses reviewers como `generalPurpose` cujo prompt é o corpo do agent file **ou** como `subagent_type` nomeado; o matcher do destape cobre os dois. Continua a exigir `review_diff_path:` e a string exacta do `description` do Task no sidecar. O pai **copia** schema do dump (`gravidade`, `classe`); MUST NOT reclassificar; MUST NOT inflar gravidade. `bloqueia_merge: sim` num nit ≠ terceiro ciclo. P0 continua a parar a coluna. Mecânicos juntos num único Apply de correção (prompt = a lista) **sem Ask**; juízo vai a residual e **não** ocupa o slot. Após 1 correção + 1 onda, P1/P2 restante **ou P1/P2 novo** = residual no handoff de Done **e** no comentário do card; o card **segue** (commit, PR, QA). MUST NOT terceiro ciclo. MUST NOT perguntar «autorizar extra / aceitar residual». Pai MUST NOT corrigir no próprio transcript. Fecho vs `develop` cola `## Residual já no card`; residual já no comentário **não** reabre e **não** sobe; só defeito novo (ou reuse SHA). Fecho pós-commit continua **uma** onda. Depois da onda, correr `scripts/process-fsm/review_process_checklist.py` **antes** do commit (`--wave-same-turn yes` se os dois nasceram neste turno). Falha = `ERROR: process-checklist failed:` + item (bloqueio visível, não commita, não prosa de LLM). Depois: commit, closing vs develop, push. `aceitar_sha` só com PR `q_git`→develop (`no_pr` ⇒ abrir PR e repetir no mesmo turno). Depois: filho QA (checks), T14. `/review-bugbot` MUST NOT. `/review-security` MAY se Alan pedir explicitamente; o gate continua os dois reviewers locais.
**dsh:** após 400 desta classe (reasoning effort off/none) num filho, MUST NOT spawnar mais o mesmo preset (incl. retry 1/1 #518); registar `ERROR: subagent spawn failed/empty` e continuar no root com residual explícito.

## Code Review — cola do diff (S1)

Antes de spawnar `diff-reviewer` / `code-reviewer`, o **pai** materializa o intervalo (nunca o filho):

- Pré-commit: `git diff HEAD` (staged+unstaged vs HEAD) **mais** untracked de `git ls-files --others --exclude-standard` como hunks de ficheiro novo.
- Fecho: `git diff origin/develop...HEAD` (`integration_branch` do overlay).
- Grava `.cursor/tmp/review-diff.patch` (já gitignored via `.cursor/*`).
- No spawn: linha `review_diff_path:` apontando esse ficheiro. MAY colar bytes sob `## Diff`.
- MAY spawnar como Task `generalPurpose` (prompt = corpo do agent file) **ou** como `subagent_type` nomeado `diff-reviewer` / `code-reviewer`. O matcher do destape cobre os dois.
- MUST NOT pedir git ao filho. MUST NOT pedir Glob/listagem de `agent-transcripts`.
- Grelha, Apply e QA **não** recebem este contrato.

Pin overlay permanece `v1.1.14`. Stubs Grok/dsh/OpenCode: ponte ≤8 linhas; MUST NOT dual-write lei.

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

Homologado: no **mesmo turno** do arraste/confirmação, `scripts/post-card-evidence-comment.sh --transition homologado` (mesmo sem lote).

## Release

Pedido explícito de Alan (`subir lote`, `fechar release`, …). Overlay de ambiente em `covenant-flow-environments`. Detalhe humano: `overlay_doc`. `bound_card=⊥` / `enabled_events: (unbound)` são display do paging, não deny de T16; pedido explícito unbound em `develop`/`release-*` carrega overlay + `covenant-flow-environments` e segue T16; Write de produto continua deny. Guard: `scripts/release-guard pre` / `post`; `RELEASE_CARDS` nos exemplos de `pre` de lote; `PRESERVED_BRANCHES` no `pre` quando houver worktree in-flight. Homologação não autoriza `main`. Antes do `post`: `/kaizen release` no log **e** materialização Kaizen (1–3 cards em Em Refinamento, dedupe `coberto por #N` em fluxo, ou `Sem achados acionáveis`) — skill `kaizen` é read-only; o orquestrador cria os cards (#661).

Quando o push do archive em `develop` for recusado por proteção (`qa-gate`), mesmo com pacote só Homologado: use `release-*` = `origin/develop` + archive → PR `release-* → main`; `pre` em `release-*` **não** exige archive em `origin/develop`. Após merge + deploy PROD, sync `main → develop` é obrigatório antes do `post` final (reexecutar `post` se as árvores ainda divergirem). Não dual-write o playbook completo neste `SKILL.md` nem no stub `AGENTS.md`.

## Higiene

Worktree por change. Stash só temporário, classificado. Não dual-write esta skill para hermes/`~/.codex`.
