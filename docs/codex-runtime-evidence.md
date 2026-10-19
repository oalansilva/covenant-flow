# Evidência automática do Codex

Adendo factual de 18/10/2026 (#1130): #1098 encerrou Review de produto, verify-wave/checklist e QA da rota principal TUI no worktree → coordenador exec read-only, com 32/32 aceites desse recorte e integração PR #1129/base `1a06caec` no consumidor crypto. O parágrafo histórico abaixo antecede esse fechamento e não descreve mais seu estado final. Fluxo integral do terminal, incluindo refinamento e principal exec independente, pertence ao #1130; #1128 conserva App/IDE. O fechamento histórico não qualifica etapas futuras nem todas as sessões/raízes. [Preparação conduzida e contratos atuais](codex-terminal-flow.md).

Protocolo para diff grande: [leitura limitada por parte e prova de cobertura integral](codex-review-qualification.md#protocolo-de-saída-e-diff-grande). Preflight do coordenador e probe de cada filho são executados uma única vez; saídas curtas evitam repetir o probe após truncamento. Para patches grandes, somente os eventos nativos de todos os comandos `read`, vinculados ao mesmo plano/path/SHA/child e anteriores ao payload, comprovam entrega integral mediante reconstrução do digest. O manifesto do probe sozinho não comprova leitura. O principal conserva `verify-wave`/checklist finais após os retornos; nenhum parecer com prova ausente é aceito.

Estado de18/10/2026: implementação integrada e revisada pelo operador; rota diagnóstica **principal TUI gravável → coordenador exec read-only** qualificada com contexto próprio e ambos perfis nomeados. Bootstrap, recusa pré-qualificação, contexto, coleta verified/completed e qualificação de probes/rota PASS. [Provas sanitizadas e limites](evidence/card-1098-dedicated-diagnostic-pass-20261018.md). Onda de produto/verify-wave/checklist, QA, principal exec/App/IDE → exec e nova distribuição canônica permanecem pendentes. Atestação interna completa unavailable. A matriz datada abaixo preserva a evidência histórica.

O adapter lê o rollout local pelo driver `codex/rollout-v1`; envelope `codex-rollout-evidence-v1`. Exec conserva o identificador `codex_exec/rollout-v1` por compatibilidade. O nome do host é diagnóstico: o driver verifica os registros contra `ROLLOUT_SCHEMA` e exige qualificação real da superfície observada. Aceitar o schema não comprova nascimento, filiação, isolamento, modelo/esforço ou retorno; cada garantia continua sendo verificada no receipt e na coleta. A `cli_version` é registrada no receipt e na evidência e nunca recusa sozinha. O id antigo `codex_exec/0.162.1/rollout-v1` nomeia o mesmo schema: receipts, evidências e a qualificação privada já gravados com ele continuam válidos. O índice SQLite é localizador por UUID/path exatos. A prova vem de `session_meta`, `turn_context`, chamada/retorno nativos, `task_started`, `task_complete` e `agent_message` com `FINAL_ANSWER` no pai. Campo exigido ausente ou de outro tipo = `unsupported_schema` citando o tipo de registro, o campo e a versão observada. Evidência ausente ou divergente reprova em qualquer versão. `message` cifrado no spawn não é necessário nem é decifrado.

## Capacidade demonstrada em 2026-10-13

| Runtime observado | Fonte / resultado | Limite |
| --- | --- | --- |
| `codex_exec/0.162.1` | Rollout local; ensaio nativo #1095 com captura, modelo/esforço, filiação/UUID/turno, terminal, payload retornado, coleta e proxy consumidor aprovados | Suporte ao schema `codex_exec/rollout-v1` (a qualificação vale por schema do driver; uma `cli_version` nova com o mesmo formato passa no preflight sem novo ensaio). O ensaio teve sandbox workspace-write; sua seleção/lifecycle não satisfaz isolamento efetivo e onda read-only do contrato #1098. |
| Codex `0.162.0` | Exploração histórica/catálogo, sem ensaio deste coletor | Aceito se o rollout bate com o schema; não preencher a versão com a saída de um binário instalado. |
| `codex-tui/0.163.0` | Ensaio nativo #1098: nascimento, filiação, modelo/esforço, conclusão e retorno verificados; recusa real antes do nascimento | Somente qualificação em `/source`, com `danger-full-access`. Não comprova Design em outro worktree, UI inspecionada pelo operador ou revisão read-only. |
| App/IDE e demais superfícies | Contrato testado com fixtures; sem ensaio real | Schema ausente/incompatível: `unsupported_schema`; sem qualificação própria: `unverified`. Não anunciado como suporte comprovado. |

Prova sanitizada reproduzível: [evidence.md](../openspec/changes/archive/2026-10-16-card-1095-codex-evidencia/evidence.md). A qualificação privada precisa continuar íntegra e acessível: suporte documentado não substitui o preflight da sessão atual.

## Antes de cada nascimento

O resolver mantém seu contrato de seleção; resolver não spawna e não comprova disponibilidade do runtime. Execute também o preflight/prepare, mesmo já estando na coluna. Uma captura por nascimento, paths absolutos e task_name único (incluindo o needle do papel):

```bash
python3 scripts/process-fsm/model_selection.py resolve \
  --client codex --band execucao --role apply-coluna \
  --capture /tmp/cf-unique-apply.json
python3 scripts/process-fsm/codex_evidence.py prepare \
  --capture /tmp/cf-unique-apply.json --task-name apply_coluna_unique
```

`prepare` primeiro revalida a sessão ativa (`CODEX_THREAD_ID`), host/versão/schema, qualificação, cwd, captura e destino. O cwd autoritativo é o de `turn_context` ativo; o cwd inicial em `session_meta` pode ser histórico após um rebind nativo. Um `--root` ou `workdir` do shell não muda esse vínculo. Divergência retorna `worktree_mismatch` com os três diretórios. Filhos novos continuam exigindo o worktree esperado na metadata de nascimento e em todos os turnos. Para novas etapas, a implementação integrada #1098 exige qualificação operacional de contexto antes de persistir o receipt: contrato documentado aplicável ao binário/runtime nativo, chamada real fork_turns=none e ensaio completo C/S sem canal contaminante observado. Ausência/divergência retorna `stage_capability_missing`. Atestação interna completa e barreira diagnóstica permanecem unavailable. Qualificação de outra sessão/superfície não autoriza o nascimento. `--qualification` continua restrito a diagnóstico explícito sem produto/transição. Receipt diagnóstico retorna `birth` e o par literal, sem comprovar a etapa. No prompt autocontido, inclua as duas linhas:

```text
model_selection_capture: /tmp/cf-unique-apply.json
runtime_evidence_birth: <path-absoluto-birth-retornado>
```

Passe os `arguments` literalmente ao Agent nativo. `blocked` impede o nascimento; preserve Status/artefatos e resolva a causa. Hooks confiados e cobertos reutilizam o receipt e preflight; hooks ausentes/não confiados não constituem proteção nem bloqueio automático do caminho cooperativo. Não confiar automaticamente, alterar trust ou usar bypass. Pin/AGENTS.md não concedem trust. Codex continua cooperativo, sem modo Auto.

No `process_event`, os caminhos Codex `iniciar_design`, `recriticar`, `submeter_design`, `iniciar_apply`, `pedir_review`, `aceitar_sha` e `integrar_develop` conferem disponibilidade antes da mutação. `--client codex` é explícito; `CODEX_THREAD_ID` identifica o host nativo. Identidade explícita conflitante é recusada. Nenhuma aresta/estado ou aprovação humana muda. Outros adapters preservam seus contratos.

## Depois do retorno nativo

No pai gravável, após `completed` com payload:

```bash
python3 scripts/process-fsm/codex_proxy.py \
  --capture /tmp/cf-unique-apply.json --activity apply-coluna --band execucao \
  --birth <path-absoluto-birth>
```

O proxy coleta automaticamente, com espera padrão de 5 segundos (máximo permitido 10; `--wait-seconds`), e deriva observação/host/versão/identidade/sandbox/terminal/payload da fonte. `--evidence <envelope>` reutiliza uma coleta existente, sempre revalidando a origem. Nenhuma flag `--observed-*` produz sucesso ou acompanha o envelope. Registros históricos continuam legíveis; metadados manuais não são prova nova.

Todos os turnos aceitos precisam corresponder à captura original; último turno correto não apaga divergência anterior. Cada completion precisa do mesmo `turn_id`, payload não vazio e retorno nativo idêntico no pai. Um FINAL_ANSWER isolado não basta. O proxy é idempotente por tentativa, sem terceira entrada na onda.

Uma continuação válida preserva o primeiro `<attempt_id>.evidence.json` e publica um novo snapshot imutável `<attempt_id>.evidence-<sha256>.json`; recoletar o mesmo estado reutiliza esse snapshot. A verificação relê todos os turnos atuais e confere os campos fixos, os turnos/payloads anteriores e cada registro de origem por path/ordinal/digest contra todos os snapshots já aceitos. Alterar ou remover um turno aceito, apresentar continuação incompleta ou acrescentar divergência recusa também o envelope antigo. O proxy mantém sua referência/digest original quando os demais campos continuam iguais e revalida essa âncora, sem acrescentar outro registro da tentativa. Preserve todos os snapshots junto da captura/receipt; não substitua o primeiro envelope por uma revisão.

## Onda Code Review em coordenador dedicado

O principal prepara e persiste em contexto gravável. `codex_review_session.py` lança automaticamente um coordenador exec read-only no mesmo worktree e retoma essa mesma sessão para os diagnósticos/contexto/probes e para os dois reviewers nativos. Os dois reviewers nascem no mesmo turno do coordenador e permanecem read-only com ele até os payloads. Principal e coordenador não fazem review. Não há alternância manual de permissões nem fallback de cliente. Outros estágios continuam no chat nativo do card.

O ciclo novo prepara envelopes pendentes, resolve a identidade exclusivamente de `CommandExecution` real do principal + JSONL exec + rollout da sessão e chamadas nativas dos filhos, preserva contexto opção 2 próprio do coordenador e persiste pelo principal. `verify-wave` exige essa cadeia; o principal pode continuar gravável. A leitura/deny/readback por perfil continua obrigatória e não se infere do TOML. A qualificação viva TUI → exec está documentada acima; outras rotas/superfícies continuam exigindo ensaio próprio. Procedimento completo: [coordenação dedicada](codex-review-qualification.md).

## Qualificação e recuperação

Um host sem prova é `unverified`. A qualificação é por **schema e superfície observada**, não por versão do binário. Uma prova de exec não qualifica TUI/app. Qualificação de lifecycle não qualifica o critério operacional de contexto nem libera sozinha uma nova etapa pelo contrato #1098. Exec mantém `qualification.json`; outras superfícies usam `qualification-<digest do originator>.json`, permitindo coexistência sem sobrescrever a prova antiga. A origem da prova é revalidada, inclusive após cópia do arquivo. Alteração de formato: formato do rollout que mudou de verdade (`unsupported_schema`) exige revalidar o driver com um ensaio real. A exceção é ensaio explícito sem produto, sem transição e dentro das permissões existentes. Capture `codex/execucao`, execute `prepare --qualification`, spawne um filho nativo que apenas retorna conteúdo e colete/consuma pelo proxy. Registre recusas reais do coletor separadamente de fixtures; `qualify --evidence <envelope> --refusal <failure-json>` exige tentativa correspondente e persiste a qualificação privada. Não usar o ensaio como QA de produto/review de diff. Fixtures não qualificam hosts.

```bash
python3 scripts/process-fsm/codex_evidence.py preflight
python3 scripts/process-fsm/codex_evidence.py collect --birth <receipt> --wait-seconds 5
python3 scripts/process-fsm/codex_evidence.py verify --evidence <envelope>
```

Ausência/permissão revogada/flush incompleto: preserve receipt/captura e artefatos; recolete a mesma tentativa quando a fonte íntegra reaparecer. O failure fica separado da posterior prova, sem converter recusa em sucesso retroativo. `turn_aborted` é `interrupted`; falhas observadas de seleção/terminal/payload são `failed`, nunca completed nem bloqueio retroativo antes do nascimento. Divergência de modelo/esforço, filiação/nascimento/turno errado ou origem irrecuperável exige nascimento novo após preflight; não retunar/resumir o filho divergente. Um filho anterior à instalação deste mecanismo não recebe receipt fabricado retroativamente.

Armazenamento padrão `.cursor/tmp/codex-evidence/`: diretório 0700, arquivos 0600, publicação atômica exclusiva. Captura/receipt têm integridade e permanecem imutáveis; preserve também a captura original. A extração contém identidades, campos mínimos, ordinais/tipos e SHA dos bytes usados, nunca prompts/transcripts/payload completos. O digest estável não muda por eventos irrelevantes append-only. Consumidores releem a fonte e a extração: JSON com `successful=true` não basta. Fontes conflitantes são recusadas. Hash local detecta adulteração; não é atestado criptográfico do servidor nem proteção contra um operador que fabrica toda a origem local.

## Contexto operacional — critério aprovado #1098

O relato do candidato no próximo parágrafo é histórico, anterior à integração. O estado atual e a qualificação própria do coordenador constam no início desta página e no procedimento de contexto; o bloqueio histórico de permissões não descreve a rota dedicada hoje qualificada.

O candidato `codex_context.py` mantém qualificação separada por chat/card e escopo da ferramenta, com binário ancestral real, versão vinculada ao trace, hashes/offsets do contrato e fontes nativas revalidadas. Plano/prompt ficam REQUESTED; chamada real, retorno do controle C e canais observáveis são verificados independentemente. O texto nativo da tarefa pode ficar opaque, com essa limitação explícita. `internal_context_attestation=unavailable` permanece, sem garantia universal. S só existe no contexto anterior do pai; seu valor não entra em arquivos/capturas/filho nem no relatório. Novo receipt de etapa v3 fixa a qualificação e revalida fork_turns=none; envelopes v2 e legados conservam suas observações originais. Procedimento completo, incluindo execução do candidato inativo sem habilitar T8: [codex-context-qualification.md](codex-context-qualification.md). O pai executou ensaio C/S nativo no candidato: tentativa 7739e34e-0611-40db-be29-e26e015bd5a4, filho 01a14a96-b8e5-79f1-b701-f69723c6b90a, controle exato/sentinel null, sem ferramentas; collect/verify/qualify PASS. Preflight candidato iniciar_apply READY; pedir_review continua bloqueado pelas três garantias read-only/leitura/deny-readback ausentes. Adapter ativo e qualificação lifecycle não foram alterados.

### Coleta de Review após a integração da opção 2

O critério de contexto acima foi integrado e revisado por Alan antes da nova entrada T8. O estado anterior de candidato é histórico. A qualificação real foi revalidada no Apply sem publicar C/S: `passed`, chamada nativa `none`, atestação interna `unavailable`. A onda Review viva continua pendente.

`codex_review_probe.py` implementa a coleta diagnóstica de leitura/deny/readback pelo evento **nativo** `event_msg/item_completed/CommandExecution`, observado no TUI 0.163.0. A origem contém thread/turno, argv, cwd, status, exit e aggregated_output. O coletor aceita somente argv exatos do helper canônico com Python absoluto `-I`, fontes/hashes revalidados e JSON completo: o probe único registra errno/readback e entrega diff pequeno inline; para diff grande, exige todos os comandos de leitura em chunks e reconstrói o digest integral. O manifesto não substitui essa cobertura. Declaração no payload, simples `cat`, comando reescrito, outra thread/turno, truncamento ou arquivo alterado não contam. Isso prova entrega por ferramenta e comportamento do sandbox na fixture; não compreensão semântica nem contexto interno.

O preparo e a qualificação atuais seguem o ciclo dedicado descrito em [Qualificação nativa de Review](codex-review-qualification.md). O principal cria planos/fixtures, capturas e envelopes pendentes antes de cada retomada. Perfis nomeados permitem somente o probe fixo descartável, sem conceder produto write. A coleta de produto exige o preflight nativo no turno do coordenador, dois probes anteriores ao parecer e ambos os payloads; o principal executa proxies/verify-wave/checklist após os retornos. A qualificação default TUI histórica não foi usada para qualificar o coordenador exec: o diagnóstico dedicado próprio de18/10 forneceu o positivo dos perfis e da rota, integridade `3a8f19dc25fb945216b47c306c7172a809ba9344e6c5bb976cf903b4a9036886`. Revisão de produto e seus gates finais permanecem pendentes.

Repetições idênticas de `turn_context` no mesmo turno são um único turno lógico, com **todas** as linhas e hashes preservados nas fontes. Qualquer divergência de payload, incluindo campos desconhecidos, ou reaparição fora da sequência do turno recebe `turn_conflict`. Nenhum rollout ou envelope histórico é editado para adequar a origem.
