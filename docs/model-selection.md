# Seleção local de modelos

A única fonte operacional é `$HOME/.config/covenant-flow/model-selection.yaml` da conta que executa o cliente. Na sessão Desktop+SSH, é a conta na VM. Repos e worktrees migrados compartilham esse arquivo; não há override por repo, picker ou fallback para `.cursor/model-map.yaml`. O mapa Git é somente entrada explícita de migração. `.cursor/model-policy.yaml` versiona papéis, proibições, campos e contratos, sem escolher modelos.

O schema contém somente `version: 1` e `clients`. Cada cliente possui `juizo` e `execucao`, com `label` e `model`. Codex também exige `effort`; OpenCode exige `provider` e aceita `variant`; dsh exige `provider` e aceita `effort` somente conforme metadata do modelo nativo. Cursor/Grok não aceitam esforço no contrato ensaiado. Arquivo, faixa, modelo, capacidade ou campo inválido produzem erro visível, sem omissão nem tentativa com outro modelo.

## Nascimento e continuidade

No consumidor migrado, execute o resolver com path absoluto de captura único por nascimento:

```bash
python3 scripts/process-fsm/model_selection.py resolve \
  --client codex --band execucao --role apply-coluna \
  --capture /tmp/cf-attempt-unique.json
```

Passe os `arguments` retornados literalmente ao tool nativo. O prompt autocontido contém `model_selection_capture: /tmp/cf-attempt-unique.json`; o papel está no tipo/título/description nativos, nunca inferido do corpo longo. A captura exclusiva, modo 0400, contém digests da fonte/política, versão de capacidade, papel, banda, parâmetros e identidade da tentativa. Não reutilize captura para outro nascimento. O guard relê o arquivo antes do nascimento e rejeita seleção efetiva alterada.

Reviewers/A-B também recebem `model_selection_wave_capture: /tmp/cf-first.json`. Prepare cada captura com `--wave-capture /tmp/cf-first.json`; o primeiro filho aponta para a própria captura. Cada nascimento compara cliente/faixa/argumentos efetivos. Edição dessa escolha interrompe a onda com `selection_changed`; reinicie a onda explicitamente. Edição de outra faixa/cliente não a invalida.

Filhos vivos, resume, proxy e auditoria usam a captura de nascimento, sem reler a escolha atual. Resume não recebe novos parâmetros de modelo/esforço. Para dsh, inclua `cf=<attempt_id>` na description; o plugin associa o descriptor à captura própria da sessão e instala guard na `agent.ctx` do filho. O guard valida/reaplica somente valores capturados, nunca substitui por high. Captura gerida ausente recusa a próxima request. Root e filhos anteriores conservam seu comportamento histórico; os guards de grill/erro/dead turn permanecem.

`model_proxy.evidence` distingue requested de observed para os cinco clientes. `codex_proxy.py --capture <path>` e `codex_review.py verify-wave` mantêm os gates de dois papéis/filhos, diff SHA, sandbox read-only, status completed e payload. Metadata ausente é `unavailable`; parâmetro não suportado é `not_applicable`. Configuração e ensaio mock não provam runtime. Release compara o pai observado com a captura de execução da operação, no próprio cliente, sem retunar a sessão viva.

## Matriz inspecionada em 2026-10-08

| Cliente/versão instalada | Seleção nativa e fonte de capacidade | Evidência entregue / limite |
| --- | --- | --- |
| Cursor Agent `2026.09.28-64d2043` | Task `model`, nomeado e generalPurpose; catálogo real `cursor-agent models` | Hook/adapter ensaiados em contrato. Ambos modos Cursor ainda precisam nascimento runtime com captura. Esforço separado não demonstrado, rejeitado. |
| Codex CLI `0.162.0` | Agent `model` + `reasoning_effort`; `~/.codex/models_cache.json`, supported_reasoning_levels por slug | Adapter/proxy/review ensaiados. Trace deste Apply confirma `gpt-6.1-sol/high`, mas nasceu antes da migração; novo nascimento permanece after-qa. |
| Grok Build `1.0.25 (f7e67d6988e2)` | spawn_subagent/Task `model`; catálogo `~/.grok/models_cache.json` e definições nativas `~/.grok/config.toml` | Binary/schema validam model. Argumento independente de esforço para spawn não demonstrado. Catálogo tem default high; herança/persona podem alterar comportamento do host. Preserva-se modelo, sem alegar esforço runtime high ou configurabilidade. |
| dsh `0.1.5-rc.2` | subagent/subagent_fork provider/model/reasoning_effort com modelSelectionSettings, política enabled/allowedModels; llm.resolveModelInfo e resolveCallConfig | Código nativo inspecionado; plugin consumer ensaiado com schema/metadata mock, descriptor/captura/reuso/continuidade. Conta atual não habilita subagent-model-selection; recusa segura até ativação nativa em nova sessão. |
| OpenCode `1.18.32` | SDK v2 session.create/session.prompt model {providerID,modelID}/variant; tool task instalado sem esses parâmetros | Plugin recusa antes da criação de filho. Integração com nascimento selecionado indisponível nesta versão; cobertura positiva pendente. |

O task OpenCode instalado aceita somente description/prompt/subagent_type/task_id/command/background e herda modelo/variant do pai/agent preset. O SDK permite chat de filho, mas o plugin ToolContext não expõe extra.promptOps/jobs do task nativo. Substituí-lo por chat simples perderia permissions/depth/retorno `<task_result>`/background notices/promotion/continuation. Esta versão é recusada; não se usa chat.params, preset, alteração global ou fork de OpenCode. Versão futura precisa provar essas semânticas antes de habilitar o contrato versionado.

A conta dsh atual usa `deepseek-official/deepseek-flash`, effort high em agent-default-model. Antes do ensaio positivo, habilitar o serviço nativo `@deepseek-ai/dsh-tool-subagent/model-selection-settings`, preferência `subagent-model-selection.enabled: true`, allowedModels com a rota exata e modelSelectionSettings: true na composição dos delegation tools. O código nativo valida policy/provider/schema; abrir sessão nova após habilitar. Pin consumer não modifica settings/profiles da conta. Registrar metadata efetiva do filho, não copiar esta tabela como observado.

## Migração explícita preparada

Artefatos não secretos em `openspec/changes/card-1080-modelos-locais/evidence/`: migration-routes.yaml, migration-plan.json e metadata deste Apply. O pai aplicou create_only na conta executora e validate passou nos dez pares, sem sobrescrever existente; source_sha256 `6167e38fd93f8f00577de4adab6f73ab0c0f6942d72f610e85e989d78eabe9c4`. Cursor mantém Grok 4.6/Composer 2.5; Grok mantém Grok 4.7/Grok 4.6. Codex inicia Astra/medium e Sol/high. OpenCode materializa `opencode-go/muse-spark-1.2-contributor` variant xhigh e dsh materializa DeepSeek Flash/high nos dois papéis, a partir das rotas existentes. Materializar configuração não torna capaz um host indisponível.

Para conta ainda sem seleção, operador/pai aplica um plano validado create_only. Nesta conta já foi aplicado; executar novamente preserva o arquivo existente e recusa sobrescrita:

```bash
python3 scripts/process-fsm/model_selection.py migrate \
  --plan openspec/changes/card-1080-modelos-locais/evidence/migration-plan.json
python3 scripts/process-fsm/model_selection.py validate
```

Se a fonte mudou, gerar novo plano com migration-plan --legacy <path-absoluto> --routes <path-absoluto>. Qualquer seleção local existente prevalece integralmente: planner retorna preserve_existing, sem completar/normalizar/sobrescrever. Rota desconhecida deixa cliente unmigrated e plano incompleto sem escrita. Publicação atômica/create-only recusa corrida com arquivo criado depois do plano. Depois da migração, editar entrada local e validar basta; próximos filhos usam a escolha nova sem commit/card/release.

Hooks Codex não gerenciados exigem trust review explícito da definição atual pelo operador, conforme skill canônica. Instalação/pin não dão confiança; não usar bypass. Hook ausente/não confiado não é proteção. Os cinco clientes continuam cooperativos, sem reivindicação Auto.

## Pin, diagnóstico e rollback

codex_models.py mantém flags antigas de pin como compatibilidade sem ler/escrever mapas ou seleção local. O installer no worktree nucleus do mesmo #1080 entrega mecanismos/política/adapters e pacote Codex funcional. Preflight hooks/roles/bridges/mecanismos ocorre antes de qualquer cópia; pin não exige mapa nem lê/grava escolhas da conta. Seis testes installer reais, incluindo resolver/Agent guard no consumidor recém-pinado, passaram; consumer continua sem install.sh por ser artefato nucleus. Não aplicar pin antigo para normalizar esta conta.

Erro mostra path/client/faixa/razão. Resolver é primeiro diagnóstico; dsh faz preflight de schema/catálogo/policy; OpenCode explica capacidade task indisponível. Metadata ausente mantém gate pendente. Rollback preserva/backupeia seleção local e capturas; remover seleção é ação explícita do operador. Reverter consumidor/pin não altera arquivo da conta nem retuna filhos. Consumidor antigo pode ter contrato incompatível e deve recusá-lo, sem sobrescrever.

## Inventário normativo

Delta specs desta change substituem cláusulas antigas em cursor-harness, covenant-flow, cursor-code-review, developer-tooling, impeccable-design-gate, llm-flow-emission, process-harness e kaizen-continuous-improvement. Main specs ainda contêm mapa, pins frontmatter, pares fixos, auditoria pelo mapa atual e troca por card; sincronização pertence ao sync/archive posterior. Main specs/archives/outras changes não são fontes operacionais. Runbook, paging, agents, stubs, auditoria e helper consumer ativos usam seleção/captura; model-map.yaml permanece histórico/migração.

Nucleus implementado em `/srv/apps/dev/covenant-flow-worktrees/card-1080-modelos-locais`, branch do mesmo #1080. Main/source/branches1042 não alterados. A dependência inicialmente registrada como P0 foi resolvida após autorização de concluir pendências; não há gate extra por repo. O patch proposto anterior em evidence é histórico; o diff nucleus contém a implementação completa ensaiada.

Tentativa nativa Grok encontrou Not signed in; Cursor CLI em Plan não criou filho. Sem login/aprovação/bypass automático. Novos nascimentos e metadata verdadeiros continuam pendentes para QA; diagnóstico de auth não é incapacidade do adapter. dsh ainda precisa habilitação e ensaio nativos; a seleção materializada conserva sua rota.

Tasks after-qa exigem nascimento runtime com captura em cada caminho suportado, metadata observado real, completed/payload e denies reais. OpenCode indisponível permanece residual explícito. Ensaios de contrato e catálogo/API nativos verificam código/capacidade, sem substituir runtime. Checks precommit permitem apenas pendências anotadas; postpin/postqa revalidam os gates correspondentes.
