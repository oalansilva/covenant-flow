# Capacidades nativas Codex — #1098

Adendo factual de 18/10/2026 (#1130): o fechamento #1098 já comprovou Review de produto, verify-wave/checklist e QA (32/32 no seu escopo CLI TUI → exec), integrado ao consumidor crypto por PR #1129/base `1a06caec`. Os estados pendentes nas tabelas abaixo são históricos anteriores a esse fechamento. As células CLI restantes, refinamento e principal exec independente continuam no #1130; App/IDE continuam no #1128. Isso não comprova fluxo integral nem concede Auto/trust. [Contrato terminal e recuperação conduzida](codex-terminal-flow.md).

Estado reconciliado em 18/10/2026: implementação integrada no consumidor, adapter revisado pelo operador e rota diagnóstica **principal TUI → coordenador exec read-only** qualificada com ambos perfis nomeados. A nova distribuição canônica nucleus → consumidor permanece pendente após recusa `target_outside_binding`. Não declara substituição integral, revisão de produto aprovada, QA, novo pin ou proteção Auto. Testes de contrato e fatos vivos permanecem separados. Provas e limites: [diagnóstico dedicado](evidence/card-1098-dedicated-diagnostic-pass-20261018.md).

Critério de contexto (opção 2 aprovada): integrado/revisado pelo operador antes da nova entrada T8; qualificação do pai revalidada neste Apply com resultado `passed` e atestação interna `unavailable`. Sincronização canônica ainda bloqueada pelo Guard fora do binding. Procedimento: `docs/codex-context-qualification.md`. Fonte sanitizada: `.cursor/tmp/card-1098-context-contract-fix/live-native-context-essay.json`.

## Contrato e preflight

O driver `codex/rollout-v1` admite superfícies com schema compatível e qualificação própria revalidada. `codex_exec/rollout-v1` e o identificador legado continuam legíveis somente como exec; mudar originator ou copiar a qualificação não qualifica outra superfície. Versão é procedência, não autorização.

Novos nascimentos de etapa passam por `prepare` e pelos eventos Codex de `process_event`. O preflight exige fonte qualificada de filiação ao chat, seleção observável, vínculo de worktree e qualificação operacional de contexto. O critério aprovado combina contrato documentado aplicável ao runtime, chamada nativa real com `fork_turns=none` e ensaio completo de controle C/sentinela S sem canal contaminante observado. Review exige coordenador e filhos read-only, leitura do diff e escrita negada/readback por reviewer; o principal permanece gravável. Não se alteram T8, identidade, seleção, trust, Guard ou gates humanos.

`codex_context.py` coleta o contrato embutido do executável ancestral real do processo nativo: /proc, starttime, inode, SHA-256, offsets/fragmentos e versão comparada ao rollout v2. O caminho npm ou uma documentação de outro produto não substitui essa ligação. A qualificação fica separada de lifecycle, limitada ao chat/card, superfície, ferramenta, semântica e binário observados. Cada preflight revalida fontes; cada nascimento de etapa novo confere a chamada real e `fork_turns=none`. Mudança da implementação/contrato exige novo ensaio; o número da versão isolado nunca autoriza nem recusa uma versão.

O plano privado registra o prompt como **REQUESTED**, sem o valor de S. C é entregue nesse prompt e precisa retornar exatamente no payload final real, correlacionado ao filho/chamada. O rollout atual cifra o texto da tarefa; essa parte fica `opaque`, sem atestação do plaintext entregue. Chamada/IDs/fork_none, payload C e canais de ferramenta/steering são observados separadamente. Controle errado, vazamento de S, consulta por ferramenta, mensagem adicional, ensaio incompleto, fonte adulterada ou escopo divergente impedem a qualificação. Ausência de S sozinha não conta.

`context_isolation=verified` passa a designar somente esse critério operacional aprovado, computado após revalidar as três fontes. `internal_context_attestation` e `diagnostic_work_barrier` permanecem `unavailable`; o resultado não garante contexto interno completo, ausência universal de herança ou proteção Auto. `history_mode`, window id, flag manual e `fork_turns` solicitado não qualificam. Diagnóstico explicitamente `--qualification` não recebe produto nem transição e conserva `diagnostic_only`. Proxies/receipts v2 e legados preservam suas observações, sem promoção retroativa.

## Superfícies e fontes

| Superfície | Ferramenta, versão e fonte observadas | Garantias demonstradas | Garantias ausentes e resultado |
| --- | --- | --- | --- |
| Interativo | `collaboration.spawn_agent`; `codex-tui/0.163.0`; rollout local com session_meta, turn_context, chamada/retorno e terminais | Filiação/UUID, seleção/cwd/lifecycle; qualificação operacional própria C/S; lançamento/retorno real de coordenador exec pelo principal gravável | UI do operador e Guard vivo de escrita por card/etapa pendentes. O principal gravável só coordena Review pela rota dedicada qualificada; não executa o parecer. |
| Exec | `codex_exec/0.163.0`; coordenador `01a14c6d-8e42-79d3-bd0e-db78be7c3aca`; receipts sanitizados dedicados | Contexto próprio opção2, nascimento/continuidade read-only, retomada nativa, dois perfis no mesmo turno, seleção/filiação/cwd/completed/payload e leitura/deny/readback diagnósticos | Positivo limitado ao coordenador lançado pelo principal TUI e diff diagnóstico. Principal exec → exec não ensaiado; onda de produto e negativos vivos completos pendentes. Não generalizar o histórico exec0.162.1. |
| App | Schema app-server gerado localmente por `codex-cli 0.163.0`; nenhuma sessão App observada | Apenas contrato disponível para leitura/estado/itens | Originator real, runtime, qualificação própria, filiação, contexto efetivo e política de uma sessão App: unavailable. Etapas bloqueadas; schema não é ensaio vivo. |
| IDE | Mesmo schema app-server instalado; nenhuma sessão IDE observada | Apenas contrato disponível | Não foi observada instância IDE nem equivalência com App; todas as garantias runtime unavailable. Etapas bloqueadas. |

O cwd atual vem de turn_context; session_meta.cwd inicial é histórico após retomada nativa. O pai foi retomado pelo operador no worktree do #1098. A coleta dos filhos Design confirma metadata de nascimento e todos os turnos nesse worktree. `workdir` de shell e `--root` não fazem rebind. Branch/card/targets do Guard são verificações distintas desse vínculo runtime.

## Matriz por etapa

Cada célula cruza a etapa com a superfície acima, conservando suas fontes, versões, permissões e lacunas. `LC` significa apenas lifecycle/seleção/cwd verificados; `—` significa nenhum nascimento dessa etapa observado. O contexto operacional foi integrado e qualificado separadamente no principal e no coordenador. Diagnóstico não conclui uma etapa de produto nem comprova Guard/UI do operador.

| Etapa | Interativo | Exec | App | IDE |
| --- | --- | --- | --- | --- |
| Refinamento / grill-card | —; positivo interativo pendente | —; regressão pendente | —; sem sessão/qualificação | —; sem sessão/qualificação |
| Design autor | LC: `01a14a21-1780-7da2-b600-bf0ca66fbd7d` | — | — | — |
| Design crítico | LC: `01a14a23-e9af-70d1-8ccd-394c2ab40cae` | — | — | — |
| Apply | Retorno histórico `01a14a28-2482-7580-9090-d1ebb2dd8890` coletado pelo pai; Apply atual ainda depende da coleta final | — | — | — |
| diff-reviewer | Principal lança o coordenador qualificado; produto pendente | Diagnóstico nomeado `01a14c6e-cdfd-7130-95b1-98a4cbaad574`: verified/completed/payload, leitura/deny/readback | — | — |
| code-reviewer | Principal lança o coordenador qualificado; produto pendente | Diagnóstico nomeado `01a14c6e-e72b-7d91-86b2-559222325548`: verified/completed/payload, leitura/deny/readback | — | — |
| QA | —; revisão de produto pendente | — | — | — |

Design e Apply históricos são filhos do principal `01a14a14-8ad0-78b2-8278-c14aec2b4bf8`; os dois reviewers diagnósticos acima são filhos do coordenador `01a14c6d-8e42-79d3-bd0e-db78be7c3aca`, todos no card/worktree #1098. Capturas/proxies Design: `.cursor/tmp/codex-evidence/c0b98157-626a-473d-ae04-8c2289e3a5ed.evidence.json` e `d14573c1-edee-498b-ad39-e15682602fa2.evidence.json`. Receipt Apply histórico `40bcdd55-f3a0-4f83-a62a-3039ad9df906.birth.json`, coletado pelo pai. Apply desta entrada: captura `.cursor/tmp/card-1098-apply-automatic-review.capture.json`, birth `7139a39e-952e-4f36-9d67-3d2414742c6b.birth.json`; retorno final ainda cabe ao pai coletar. Arquivos são privados; não se publicam transcripts ou marcadores.

## Investigação app-server

Foi executado somente `codex app-server generate-json-schema --experimental --out /tmp/card-1098-app-server-schema`; nenhum servidor/sessão/turno foi iniciado, retomado ou alterado. O bundle instalado contém:

- ThreadReadResponse.Thread: id, parentThreadId, agentNickname/agentRole, cwd, model/reasoningEffort, originator/cliVersion, status e historyMode.
- ThreadItem: chamadas CollabAgentToolCall e estados pendingInit/running/interrupted/completed/errored; leitura paginada de itens/turnos.
- TurnStartParams e ThreadSettingsUpdateParams: cwd/model/effort/sandboxPolicy são entradas solicitadas. Sua existência não prova aplicação nem concede ao agente permissão de alterá-las.

Digests SHA-256 dos arquivos gerados: ThreadReadResponse `cabb1ed2c63497037d66eb12fb6f143916ee7a615aa7398b0d90f221f1899954`; ThreadSettingsUpdateParams `749419634bb7ed66216d72bf9d8734ecf0e6efaa8cd46fe51a117d1b42ed9657`; TurnStartParams `abf0d6d29d223b38c650ff1155cb9c9f9b4211e6d0e20c57d750a9e1babfdb41`.

Há caminhos documentados de consulta de thread e paginação de itens sem retomar a sessão. Ainda falta uma sessão App/IDE real e uma fonte autoritativa para contexto efetivo sem transcript, leitura do diff e deny/readback vinculados ao reviewer. Não foi implementado um coletor de API com observações fictícias. As garantias ausentes continuam unavailable; não há qualificação universal. Referência oficial: [Codex App Server](https://learn.chatgpt.com/docs/app-server).

## Controles do operador

Use nomes com papel e card; a lista e os retornos conservam o child id. A documentação oficial indica `/subagents` na CLI para localizar e abrir threads, e orientação/interrupção pelo chat pai. Em superfícies que exibem painel de agentes, os controles dependem do cliente. Não foi inspecionada a tela de Alan neste Apply; lista visível, inspeção, orientação entregue e retorno pela UI ainda precisam do ensaio vivo de 5.1. Ferramentas de coordenação disponíveis ao agente não comprovam o que a interface do operador mostrou. [Subagents — documentação oficial](https://learn.chatgpt.com/docs/agent-configuration/subagents).

Para Review, o principal permanece gravável e lança automaticamente coordenador dedicado exec read-only. Bootstrap e retomadas nativas da mesma sessão permitem ao principal persistir contexto/probes/receipts sem gravação no coordenador. Arquivo de papel ou instrução não cria isolamento; fontes reais precisam provar sandbox desde o nascimento. Não mudar conta/trust, alternar permissões manualmente nem retomar filho divergente para obter um positivo. Outras etapas continuam no mesmo chat do card.

## Cobertura do adapter e limite de revisão

`codex_adapter` preserva o evento original e normaliza command/cmd, recusando campos conflitantes. A identidade vem do cwd nativo do hook e, quando disponível, do turn_context da sessão; workdir só resolve alvos dentro desse vínculo. Status injetado na chamada não substitui o board. Todos os targets de patch/edição e mutações shell estáticas suportadas passam pelo Guard; caminhos reais, symlinks, checkout misto, mudança de card em OpenSpec e escapes são recusados antes da mutação. Diretórios novos usam o ancestral Git existente para manter a branch autorizada.

Shell dinâmico reconhecido com troca de diretório/substituições ou alvos não verificáveis é recusado. O adapter não é parser geral de shell nem sandbox: efeitos internos de scripts, hosted tools e rotas que não disparam PreToolUse não têm garantia de interceptação. Esses caminhos não contam como ensaio Guard vivo. Fixtures demonstram autorização/deny e bytes preservados nas rotas cobertas; o ensaio real de 5.3 continua pendente, inclusive cobertura/trust efetivos do hook. Hook ausente ou não revisado não é proteção.

A onda atual exige ambos os reviewers no mesmo turno do coordenador dedicado read-only, mesmo diff/path/SHA e pacote, contexto opção 2 próprio, dois perfis nomeados com leitura/deny/readback e ambos os payloads. O principal permanece gravável e verifica a cadeia principal→coordenador→filhos, verify-wave e checklist. O protocolo antigo de troca manual de permissões não é o contrato atual.

| Rota/garantia nova | Estado nesta entrega | Prova necessária |
| --- | --- | --- |
| CLI local `exec --sandbox read-only --json` e `exec resume` | qualificado no diagnóstico TUI → exec0.163.0 | lançamento/retorno e sandbox observados na sessão indicada; revalidar fontes |
| Bootstrap + contexto C/S persistidos pelo principal | PASS real no coordenador indicado | contrato/binário do exec, chamada real e ensaio próprio preservados em qualificação separada |
| Principal TUI → coordenador exec | qualificado no diagnóstico de18/10 | recibo de rota `3a8f19dc25fb945216b47c306c7172a809ba9344e6c5bb976cf903b4a9036886`; produto pendente |
| Principal exec → coordenador exec | não qualificado | qualificação distinta da rota real |
| Principal app/IDE → coordenador exec | não qualificado | transporte/origem de lançamento e retorno verificáveis |
| Perfis nomeados e probe descartável | ambos perfis reais PASS; fixtures positivas/negativas | evidências `6852663f-12a4-4d5c-9fc9-7750c921f963` e `f07c1233-796b-4483-8722-873f7c17b51d`, leitura/deny/readback diagnósticos |
| Onda produto dedicada | pendente | novo pacote sobre diff final, Status=Code Review, dois pareceres/proxies, verify-wave/checklist; diagnóstico não substitui |

O diagnóstico default TUI histórico não qualifica nenhuma dessas rotas novas. Envelopes pending mantêm parent unavailable; testes cobrem resolução em memória, parent arbitrário/ligado ao principal, fonte adulterada, sandbox gravável, turno divergente, papel default, interrupção, payload ausente e escrita permitida/alvo errado/probe ausente. Isso não substitui ensaio vivo nem conclui tasks de aceite. `internal_context_attestation=unavailable` permanece. Passos e recusas: [coordenação dedicada](codex-review-qualification.md).
