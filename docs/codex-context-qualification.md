# Qualificação operacional de contexto Codex — #1098

O critério aprovado é contrato documentado aplicável + chamada nativa registrada `fork_turns=none` + ensaio complementar completo de controle C e sentinela S. Ele não atesta contexto interno completo. O verificador mantém `internal_context_attestation=unavailable`; ausência de S isoladamente nunca qualifica. T8 continua um evento de etapa, com os mesmos gates, identidade, captura, hooks/trust e Guard.

## Fontes e limites

`codex_context.py inspect --qualification` descobre o executável **ancestral real** do processo de ferramentas via /proc. Não aceita argumento para fornecer outro executável. Compara starttime, inode e alvo de exe antes/depois da leitura/consulta `--version`, verifica a versão contra session_meta, exige trace `multi_agent_version=v2` e instrução developer nativa correspondente. O contrato documentado vem dos fragmentos reais do binário, com hash e offsets: `fork_turns="none"` sem contexto circundante, schema de parent history e rejeição de fork_context legado. Binário npm encontrado no PATH, mensagem do agente e docs da Responses API não substituem essa ligação.

A qualificação operacional é privada, separada da qualificação de lifecycle e limitada ao chat/card, ferramenta/superfície, binário e semântica observados. Receipts de tentativas são imutáveis; novo ensaio preserva o anterior. Para preflight, a tentativa mais recente na ordem das fontes do pai precisa ser íntegra; não há fallback para uma antiga após falha da mais recente. Nova implementação/contrato requer requalificar. Versão é procedência; seu número isolado não concede capacidade.

O plano registra o prompt preparado como **REQUESTED**, nunca observed. C é fornecido ao filho; S permanece em contexto anterior exclusivo do pai, sem valor em arquivo/captura/prompt/variável de ambiente, título, nome de caminho ou mensagem ao filho. Apenas hashes de S/C aparecem no relatório sanitizado. O plano privado contém o pedido e C. O rollout TUI cifra a tarefa: o coletor mantém `native_task_text=opaque`, hashes da chamada/envelope e a limitação explícita. Não afirma observar o plaintext entregue. O retorno final legível com C exato comprova o controle empírico; IDs, seleção, cwd, chamada e terminais vêm das fontes nativas. Ferramentas, entradas adicionais, steering, continuação, S em canal de ferramenta, divergência de fork, controle errado ou payload incompleto impedem qualificação. Não se afirma ausência universal de canais internos não observáveis.

## Receita histórica do candidato inativo, antes da ativação

O critério foi integrado e revisado pelo operador antes da nova entrada T8. A receita abaixo preserva o ensaio anterior; não deve substituir o adapter integrado por um candidato antigo. No ciclo dedicado atual, o coordenador novo precisa de qualificação própria, persistida pelo principal gravável conforme [coordenação dedicada](codex-review-qualification.md).

Executar no **mesmo chat pai do card**, com CODEX_THREAD_ID nativo preservado. Não injetar IDs/thread/cwd/sandbox; shell workdir não faz rebind. Não carregar plugin pytest, fixture ou runtime mock no ensaio vivo. Os comandos abaixo selecionam os módulos candidatos por PYTHONPATH, sem copiar arquivos ao adapter ativo. A qualificação nova fica em sidecar separado e o adapter antigo continua recusando T8. Não executar transição, trust, proxy ou nova qualificação lifecycle durante o ensaio.

1. No contexto do pai, estabelecer uma S **nova, não secreta**, em uma mensagem anterior, numa linha `context_sentinel: <24–128 caracteres alfanuméricos/_/->`. Não passar seu valor a comando, arquivo, filho ou outro canal. Não incluir no prompt do ensaio nem repetir S no relatório. A mensagem é contexto só do pai; o filho nasce com none.
2. Inspecionar contrato e localizar o ordinal da mensagem sem imprimir S:

```bash
PYTHONPATH=.cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm:scripts/process-fsm python3 .cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm/codex_context.py inspect --qualification --sentinel
```

3. Resolver seleção legítima para esta nova tentativa. `qa-gate` identifica faixa de execução do diagnóstico, sem executar QA ou produto. O ensaio 01 já foi executado; o exemplo usa captura 02 e nome contendo qa_gate para preservar a classificação do hook, quando a rota o dispara:

```bash
python3 scripts/process-fsm/model_selection.py resolve --client codex --band execucao --role qa-gate --capture .cursor/tmp/card-1098-context-diagnostic-02.capture.json
```

4. Preparar o plano passando somente o **ordinal** encontrado, nunca S. Substituir ORDINAL pelo inteiro real retornado:

```bash
PYTHONPATH=.cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm:scripts/process-fsm python3 .cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm/codex_context.py prepare --qualification --capture .cursor/tmp/card-1098-context-diagnostic-02.capture.json --task-name qa_gate_context_1098_diagnostic_02 --sentinel-record ORDINAL
```

O comando devolve birth/context_plan, `message` completo e argumentos de seleção. Ele não imprime S. Copiar **literalmente** message, model e reasoning_effort para a ferramenta nativa `collaboration.spawn_agent`, com task_name `qa_gate_context_1098_diagnostic_02`, `fork_turns="none"` e sem herdar histórico. Não usar exec externo, sessão substituta, prompt adicional, título derivado de S ou produto. A captura local descreve o pedido; o coletor só verifica a chamada real depois do nascimento. O hook ativo pode conferir seleção/receipt quando cobrir essa rota; o ensaio não presume interceptação inexistente.

5. Aguardar o único retorno pelo canal nativo do pai. Não enviar steering/follow-up, retomar o filho, orientar por sentinela, abrir arquivos no filho ou pedir nova resposta se falhar. O filho deve responder apenas `{"control":"<C exato>","sentinel":null}` quando não recebeu sentinela. Se recebeu uma, deve devolvê-la; isso reprova o ensaio. C errado, vazio, palpite, silêncio ou interrupção não são sucesso.
6. Coletar usando **somente o candidato**, com os paths birth/context_plan reais retornados (substituir BIRTH e PLAN). Sem flags de observado:

```bash
PYTHONPATH=.cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm:scripts/process-fsm python3 .cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm/codex_evidence.py collect --birth BIRTH --wait-seconds 5
PYTHONPATH=.cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm:scripts/process-fsm python3 .cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm/codex_context.py verify --plan PLAN
PYTHONPATH=.cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm:scripts/process-fsm python3 .cursor/tmp/card-1098-context-contract-fix/files/scripts/process-fsm/codex_context.py qualify --plan PLAN
```

Não usar `codex_evidence.py qualify` para substituir a qualificação lifecycle ativa por um receipt v3 antes da integração. Não registrar proxy ativo desse diagnóstico com o coletor antigo. `codex_context qualify` escreve apenas sua qualificação operacional separada; não move estado nem habilita o adapter antigo. `failed` ou `incomplete` são resultados do ensaio, sem mudança FSM; não contam como positivo. Se a versão/framework mudar o schema nativo, preservar fontes e revisar o driver em vez de inventar metadados.

## Após integração revisada

Integrar os arquivos verificados byte a byte, gerar/check do manifesto com o gerador **do consumidor** e manter revisão de trust exclusivamente com o operador. Os comandos operacionais passam a `python3 scripts/process-fsm/codex_context.py ...`, sem PYTHONPATH candidato. Depois, o preflight de `iniciar_apply` revalida lifecycle e qualificação operacional real desse mesmo chat; somente então o motor atual decide T8. Falta/divergência/adulteração continua recusando.

Novos receipts de etapa v3 fixam a qualificação/escopo usados. Coleta e recolheita verificam esse vínculo e a chamada de cada novo filho com none. Receipts/proxies v2 e legados mantêm seus fatos históricos e não recebem capacidade nova retroativamente. Review exige coordenador/filhos read-only, leitura de diff e deny/readback por reviewer, com principal gravável. O contexto não comprova essas garantias: o ciclo dedicado exige suas fontes separadas.

## Qualificação própria do coordenador — 18/10/2026

O pai executou `codex_context qualify` com resultado PASS na sessão exec `01a14c6d-8e42-79d3-bd0e-db78be7c3aca`, birth `3029674d-411d-4468-9cd5-7933914440f4`, child `01a14c6e-1cc2-7af2-bfa8-3dddcba9723d`. Contrato/binário, chamada nativa `fork_turns=none` e ensaio complementar `passed` estão no receipt sanitizado `.cursor/tmp/codex-evidence/context-qualification-e5fef58078181ab0-3029674d-411d-4468-9cd5-7933914440f4.json`, integridade `015cda677284e0d05829a41d6f53db3b4b9e2de0ab247976c76fcca321075434`. Não se copiou a qualificação TUI. O Apply inspecionou somente a prova sanitizada e não publicou/leu os marcadores do trace. `internal_context_attestation=unavailable` permanece. Escopo e qualificação posterior dos probes/rota: [evidência reconciliada](evidence/card-1098-dedicated-diagnostic-pass-20261018.md). Onda de produto, demais rotas e aceites QA continuam separados.

## Histórico anterior à integração — 17/10/2026

O relato abaixo conserva o estado do candidato antes da integração. A ativação já ocorreu no consumidor; a distribuição canônica nucleus → consumidor continua pendente. A qualificação própria do coordenador atual está registrada acima.

Inspeção viva documental do candidato: PASS em 17/10/2026 no filho Apply original, host codex-tui/0.163.0, binário ancestral daemon SHA-256 `8a96f66d059d653e68bfd5f3c79337e6f1d7d170d80bf705eb7d0249b34c0ece`. Offsets dos três fragmentos: 200662246, 203362368 e 203502009. Isso não é o ensaio empírico do pai nem uma qualificação para outro chat. O pai executou o ensaio nativo diagnóstico 01 antes da integração: tentativa 7739e34e-0611-40db-be29-e26e015bd5a4, chamada call_2370965566b64921a784a625ef15caf3, filho 01a14a96-b8e5-79f1-b701-f69723c6b90a no mesmo chat, fork_turns none e gpt-6.1-sol/high. Controle exato, sentinel null e nenhuma ferramenta; collect/verify/qualify PASS. O preflight candidato de iniciar_apply ficou READY; pedir_review continuou bloqueado somente por parent_read_only, review_diff_read e review_write_denial_readback. O falso negativo inicial de novidade foi corrigido reconhecendo apenas o espelho item_completed/response_item com mesma identidade/turno/conteúdo; duplicata histórica distinta continua recusada. Fontes e hashes sanitizados: `.cursor/tmp/card-1098-context-contract-fix/live-native-context-essay.json`. Nenhuma transição ou alteração do lifecycle/trust/adapter ativo foi executada. Ativação e sincronização canônica permanecem pendentes.
