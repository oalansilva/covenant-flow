---
name: design-critic
description: Preparar ou refatorar entregas de design de qualquer card no Cursor Agent, executar crítica independente em Task isolada, registrar evidência e veredito no design.md e entregar o card para aprovação humana. Use durante Status=Design, antes de solicitar Aprovação de Design. Todo card passa por Design; não existe bypass.
---

# Designer/Critic Agent

Conduzir a entrega de design sem substituir a aprovação humana de Alan.

## Guardrail obrigatório

1. **Todo card** passa por `Design -> Aprovação de Design -> Pronto para Dev` antes de qualquer implementação de código de produção.
2. `UI impact: none` **não** autoriza pular colunas. Só reduz o peso da evidência (Prototype pode ser N/A explícito).
3. Pedidos como `implemente`, `pode codar` ou equivalentes **não** autorizam pular este gate.
4. OpenSpec `design.md` ≠ coluna Kanban `Design`: o artefato pode existir cedo, mas o card ainda precisa visitar as colunas e aguardar Alan em `Aprovação de Design`.
5. **Fidelidade ao sistema atual (quando a tela já existir):** o protótipo MUST partir da UI real em DEV/produção (shell, nav, tokens, densidade, componentes) e redesenhar só o delta do card. Proibido inventar layout paralelo. Se a tela ainda não existir, desenhar a nova superfície alinhada a `DESIGN.md`, à folha de tokens e ao shell autenticado do app.
6. **Um chat `#<id>`.** Recusar executar Apply/Review/Release neste transcript (sem spawn Apply até `Pronto para Dev`). Sem pedir outro chat. Sem evento FSM. Sem dual-write da lei em `.grok/`.

## Avaliação vs emissão

- **Avaliação** permanece intacta: rubrica Impeccable (especificidade, heurísticas, carga cognitiva, 2–3 personas relevantes, estados), pipeline `context → shape → prototype → critique → audit → polish → browser`, dual critic, detector, browser real, zero P0/P1.
- **Emissão** (chat do operador e seções Impeccable/Design Critique de `design.md`): só bullets P0–P3, disposition e verdict. Achados extras = mais bullets (sem teto rígido de linhas). Proibido tabela Nielsen, ensaio de personas ou Brief/Critique/Audit/Trace integrais no chat ou no `design.md`. Truncar achado por limite de linhas é proibido.
- Relatório longo: `.impeccable/critique/` (git-tracked). Apply e Code Review **não lêem** esse arquivo. Gist OpenSpec **não** envia a pasta. Alan abre o snapshot no T7 pelo link no card.
- `$impeccable critique` vendor **não** é a emissão da coluna Design; o contrato desta coluna é este skill.

## Preflight

1. Confirmar o card/change e, na sessão orquestradora, ler `AGENTS.md`, `rules.md`, a folha `.agents/skills/impeccable/references/cripto-farol-token-sheet.md` (quando UI) e `DESIGN.md` como autoridade visual (não reescrever). Não despejar o YAML inteiro no chat.
2. Confirmar `Status=Design`. Declarar `UI impact: affected` ou `UI impact: none` com justificativa não vazia.
3. O **pai** spawna um filho Design-autor (mesmo modelo, prompt autocontido, sem transcript) para criar o scaffold OpenSpec e os artifacts. O pai **não** escreve `design.md`/protótipo, salvo depois de A/B: **somente** `## Design Critique`. Não editar código de produção enquanto `Status=Design`.
4. A crítica usa `Task` / `spawn_subagent` isolada com inherit de **modelo**, prompt autocontido, **sem inherit de transcript**, disparada pelo **pai** após os artefatos (não nested no filho autor). Critics MAY escrever **apenas** `.impeccable/critique/**`. MUST NOT editar `design.md`, HTML de protótipo ou produto. P0/P1 abertos → pai re-despacha o filho autor com os achados no prompt; o pai não faz polish. `process_event submeter_design` é só o pai.
5. Se a superfície já existir, clonar a tela atual (folha de tokens + rota); não mandar HTML fonte no prompt dos critics.

## Integração Impeccable no Cursor

Esta integração é obrigatória para `UI impact: affected`. Corre **no filho autor** (shape/protótipo/polish) e na **onda A/B do pai** (crítica isolada). O pai não executa o pipeline nem spawna A/B de dentro do filho autor. Navegador e visão: filho autor (validação) e B (detector), não o transcript do orquestrador.

Antes do `PASS`, o **filho autor** executa shape/protótipo/polish e o **pai** dispara A/B, sempre contra a superfície versionada da change:

`context -> shape -> prototype -> critique -> audit -> targeted fixes -> polish -> browser gate`

- Executar `node .agents/skills/impeccable/scripts/context.mjs --target <surface>` uma vez por sessão. Conservar `PRODUCT.md`. Usar a folha de tokens para clone+delta. `DESIGN.md` permanece a autoridade visual canônica e **não pode ser reescrito**.
- Usar a skill Impeccable `shape` para brief, direção, escopo, estados, interação e restrições **antes** de editar a direção visual. O brief **integral** vai para o snapshot; `design.md` guarda só recorte (audience, outcome, direction, scope).
- O **pai** dispara Assessment A e B em Tasks distintas (não o filho autor), mesmo modelo, prompt autocontido (URL, digest, screenshot, folha, rubrica, contrato de saída). Sem transcript do pai. Detector/browser de B; o filho autor não nested-spawna A/B.
- Executar audit e aplicar somente `harden`, `adapt` ou `clarify` quando houver achado correspondente. Polish = **patch** no arquivo do protótipo (`StrReplace`); proibido reemitir o HTML inteiro na LLM.
- Repetir o gate de navegador real desktop/mobile e os asserts depois do polish. O hook Cursor pode alertar durante a edição, mas não substitui a crítica, o audit nem a validação final.

### Modelo e isolamento dos critics

Assessment A e Assessment B usam o **mesmo modelo do chat** (`Task` `inherit` / Grok `spawn_subagent` inherit) em sessões distintas. Prompt autocontido; não compartilham transcript/resultados antes da síntese. Podem gravar só `.impeccable/critique/**`. Retorno ao pai: bullets P0–P3 + disposition + verdict + path do snapshot. Sem Task de crítica, o veredito é `BLOCKED` sem fallback. Snapshot vazio ou ausente em UI affected ⇒ `BLOCKED`.

Nome do snapshot: helper `critique-storage.mjs` quando couber; senão `<card>-<change>-<utc>.md` em `.impeccable/critique/`.

## Produzir a solução

Estas etapas são do **filho autor**. O pai não as executa.

### Quando `UI impact: affected`

1. Explicitar no `design.md` o problema, o usuário afetado, a hipótese de produto, o resultado esperado e `## Apply contract`.
2. Shape confirma direção antes do protótipo. Brief integral no snapshot, não no `design.md`.
3. **Base do protótipo (clone+delta):**
   - Tela já existente: copiar shell atual (sidebar 224px, header workspace, tokens `--bg-*`/`--accent-primary`/`--text-*`/`--border-default`, Inter, nav autenticada real) e aplicar só a mudança do card.
   - Tela nova: shell autenticado + folha de tokens; não usar landing genérica.
   - Remoção de UI existente: mostrar a tela/shell atual **sem** o elemento removido (delta negativo), não um mock abstrato.
4. **HTML nunca fica no Gist, no chat, nem no `design.md`.** Design/critics usam URL + screenshot + digest. Apply continua lendo o arquivo do disco (`frontend/public/prototypes/<slug>/`) como spec de layout (#530). Para protótipo HTML neste repo:
   - publicar em `frontend/public/prototypes/<change-or-card-slug>/` (entrada preferencial `index.html`);
   - servir na URL DEV navegável `https://dev.criptofarol.com.br/prototypes/<change-or-card-slug>/`. No host Cripto, `/prototypes*` não passa pelo preview SPA: o unit `criptofarol-dev-prototypes` serve o HTML do worktree/`public`/`dist`. Não copiar para `source` nem rebuild do frontend DEV só para o link público;
   - no comentário do card: bloco OpenSpec = só Markdown do Gist; bloco **Protótipo navegável** = link HTTP; bloco **Snapshot Impeccable** = path (e blob URL da branch quando existir);
   - usar `publish-openspec-card-artifacts.sh --prototype-url <url> --snapshot-path <path>` (o script não envia `prototype/**` nem `.impeccable/critique/` ao Gist).
5. Registrar em `## Prototype`: URL HTTP, caminho versionado, digest, desktop/mobile, base usada, fluxos/estados, delta. Sem fonte HTML.
6. Aplicar tokens/padrões da folha + `DESIGN.md`. Registrar exceção e justificativa.

## Gate de validação do protótipo

O **filho autor** valida o protótipo. Não emite `PASS` e não chama `process_event submeter_design`.

1. Publicar/servir a versão final do protótipo e abri-la em **navegador real** (Playwright ou equivalente). `curl`, HTTP 200, build verde, leitura do HTML ou inspeção estática **não** validam comportamento visual.
2. Validar pelo menos um viewport desktop e um mobile.
3. Exercitar o **estado padrão** e todas as interações relevantes.
4. Converter critérios visuais críticos em asserts observáveis (remoção/adição/interação/fidelidade).
5. Verificar erros de console/página e recursos quebrados.
6. Registrar em `design.md`, `## Prototype Validation`: URL, viewports, ações/asserts e resultado (resumo, não dump).
7. Reexecutar depois de **qualquer** alteração final. Evidência de versão anterior é inválida.
8. Confirmar que a versão validada é a polida no snapshot (digest; sem erros de console/página com impacto).

Se navegador real estiver indisponível, se qualquer assert falhar, se a versão servida divergir, ou se o snapshot estiver vazio, o veredito MUST ser `BLOCKED`. Não promover o card.

### Quando `UI impact: none`

1. Explicitar no `design.md` o problema, a decisão, o escopo, riscos e o que explicitamente não muda na UI. `## Apply contract` curto.
2. Em `## Prototype`, registrar `N/A` com justificativa não vazia.
3. Impeccable/`DESIGN.md`/Playwright = `N/A` justificado. O filho **não** escreve `## Design Critique`. T7 permanece. Snapshot N/A justificado neste caso.

## Criticar de forma independente

Depois da primeira entrega de design, A avalia com a rubrica; B corre detector + browser. Procurar problemas concretos antes do veredito.

Com UI, cobrir:

- **Fidelidade (se tela já existir):** o protótipo ainda parece o produto atual? Shell/nav/tokens batem com DEV? O delta é óbvio?
- **Produto:** problema, usuário, hipótese, valor e aderência ao escopo.
- **UX:** hierarquia, fluxo, carga cognitiva, clareza de ações e prevenção/recuperação de erro.
- **Acessibilidade:** teclado, foco, nomes acessíveis, contraste, semântica e equivalência ao drag-and-drop.
- **Responsividade:** desktop, mobile, touch, conteúdo longo e densidade.
- **Estados:** loading, vazio, erro, sucesso, permissão negada, dado obsoleto e rework.

Tratar falta de fidelidade em tela existente como achado **bloqueante** (não emitir `PASS`).

Sem UI nova, cobrir no mínimo: escopo, regressão de produto, riscos operacionais e confirmação de que nenhuma superfície visual nova/alterada ficou sem classificação.

Achado bloqueante: o pai **re-despacha o filho autor** com os bullets no prompt. O pai não faz polish. O filho autor patcha o protótipo e as seções curtas de `design.md`. Não marcar como resolvido sem evidência. Não colar tabela Nielsen nem Brief integral no `design.md`.

## Registrar a entrega

O **pai** (não o filho autor) adiciona `## Design Critique` no `design.md` **só** com:

- bullets P0–P3 e disposition;
- riscos ou pendências não bloqueantes (bullets);
- referências do design e do protótipo (URL/digest) ou `Prototype: N/A` justificado;
- path do snapshot (UI affected) ou N/A justificado;
- `Design Agent verdict: PASS` ou `Design Agent verdict: BLOCKED`.

Para `UI impact: affected`, o mesmo `design.md` também deve conter seções **curtas** (não integrais):

- recorte de audience/outcome/direction/scope (não `## Impeccable Brief` integral);
- `## Apply contract`;
- `## Prototype` + `## Prototype Validation` resumidos;
- bullets Impeccable/Design Critique + verdict.

O relatório completo (Brief/Critique/Audit/Trace, tabela Nielsen, personas, metadata de modelo) vive **somente** no snapshot `.impeccable/critique/`.

`PASS` exige zero P0/P1 aberto, nenhum finding determinístico sem classificação, browser gate e asserts críticos verdes, nenhum erro de console/página com impacto no fluxo, evidência de crítica isolada no mesmo modelo **sem transcript**, e snapshot **não vazio** (UI affected). Ausência de qualquer evidência mantém `BLOCKED`. HTTP 200 isolado nunca é evidência de PASS.

Publicar novamente os artefatos OpenSpec no card quando a entrega mudar. Handoff MUST incluir link do snapshot (UI affected), URL do protótipo quando houver HTML, e **proxies**: palavras de `design.md`, bytes HTML gerado vs copiado (`cp`/clone = copied; delta = generated; sem protótipo = `N/A`), número de spawns.

## Handoff permitido

- Com `BLOCKED`, manter `Status=Design`, registrar o motivo e parar.
- Com `PASS` e evidência completa, o **pai** chama `process_event submeter_design` e registra handoff com change, design digest, protótipo/versão ou N/A, snapshot path ou N/A, proxies, resumo em bullets e pendências aceitas. O filho autor MUST NOT T5.
- Nunca mover `Aprovação de Design -> Pronto para Dev`, nunca autoaprovar, nunca enviar `actor=Alan` nem alegar identidade humana. Essa transição pertence exclusivamente a Alan autenticado. T7: Alan abre o snapshot linkado; o Gist não é a crítica.
- Se o design ou protótipo mudar depois da aprovação, considerar a aprovação obsoleta e bloquear desenvolvimento até nova aprovação humana.
- Não mover nenhum outro status. Desenvolvimento / `/opsx-apply` começa somente depois que o card estiver em `Pronto para Dev`, no **mesmo** chat `#<id>`, via filho Apply (pai `iniciar_apply` antes do spawn).

## Saída

Reportar de forma curta:

- card/change e status observado;
- UI impact;
- protótipo URL/digest, ou N/A justificado;
- snapshot path, ou N/A justificado;
- bullets da crítica + veredito;
- proxies;
- movimento realizado ou bloqueio;
- próximo passo humano (`Aprovação de Design` aguardando Alan).
