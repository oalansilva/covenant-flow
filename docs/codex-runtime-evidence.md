# Evidência automática do Codex

O adapter lê o rollout local pelo driver `codex_exec/0.162.1/rollout-v1`; envelope `codex-rollout-evidence-v1`. O índice SQLite é localizador por UUID/path exatos. A prova vem de `session_meta`, `turn_context`, chamada/retorno nativos, `task_started`, `task_complete` e `agent_message` com `FINAL_ANSWER` no pai. `message` cifrado no spawn não é necessário nem é decifrado.

## Capacidade demonstrada em 2026-10-13

| Runtime observado | Fonte / resultado | Limite |
| --- | --- | --- |
| `codex_exec/0.162.1` | Rollout local; ensaio nativo #1095 com captura, modelo/esforço, filiação/UUID/turno, terminal, payload retornado, coleta e proxy consumidor aprovados | Suporte a este schema/fonte. O ensaio teve sandbox workspace-write; a onda read-only tem testes de contrato e exige observação real da sessão em cada execução. |
| Codex `0.162.0` | Exploração histórica/catálogo, sem qualificação deste coletor | `unverified`; não preencher a versão com a saída de um binário instalado. |
| Outros hosts/versões; app-server | Nenhum driver/prova equivalentes | Indisponíveis neste driver; sem fallback. |

Prova sanitizada reproduzível: [evidence.md](../openspec/changes/card-1095-codex-evidencia/evidence.md). A qualificação privada precisa continuar íntegra e acessível: suporte documentado não substitui o preflight da sessão atual.

## Antes de cada nascimento

O resolver mantém seu contrato de seleção; resolver não spawna e não comprova disponibilidade do runtime. Execute também o preflight/prepare, mesmo já estando na coluna. Uma captura por nascimento, paths absolutos e task_name único (incluindo o needle do papel):

```bash
python3 scripts/process-fsm/model_selection.py resolve \
  --client codex --band execucao --role apply-coluna \
  --capture /tmp/cf-unique-apply.json
python3 scripts/process-fsm/codex_evidence.py prepare \
  --capture /tmp/cf-unique-apply.json --task-name apply_coluna_unique
```

`prepare` revalida a sessão ativa (`CODEX_THREAD_ID`), host/versão/schema, qualificação, cwd, captura e destino. Persiste o receipt de nascimento privado antes do spawn; retorna `birth` e o par literal. No prompt autocontido, inclua as duas linhas:

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

## Onda Code Review

1. O pai gravável materializa/verifica o diff e prepara as duas capturas de execução, com `--wave-capture` e mesma escolha efetiva. Não grave evidência na sessão da onda.
2. Abra a sessão nativa dedicada no mesmo worktree sob read-only. Confirme no rollout o UUID/turno e sandbox ativo; perfil do Agent não prova o sandbox do pai. Sem essa fonte, recuse antes de qualquer reviewer.
3. Ainda no orquestrador gravável, prepare dois receipts apontando ao UUID real dessa sessão. O diretório privado deve existir antes da onda. `--thread` é identificador de fonte, nunca observação manual:

```bash
python3 scripts/process-fsm/codex_evidence.py prepare \
  --capture /tmp/cf-unique-diff.json --task-name diff_reviewer_unique \
  --thread <UUID-real-da-sessao-read-only> \
  --wave-id <onda-unica> --review-diff-sha256 <sha256>
python3 scripts/process-fsm/codex_evidence.py prepare \
  --capture /tmp/cf-unique-code.json --task-name code_reviewer_unique \
  --thread <mesmo-UUID> \
  --wave-id <mesma-onda> --review-diff-sha256 <mesmo-sha256>
```

4. A sessão read-only reexecuta preflight `--review` antes dos spawns, lê os receipts e recebe os paths no prompt. Cria os dois Agents no mesmo turno, com sandbox read-only, mesmo diff/path/SHA e capturas próprias; mantém leitura até ambos retornarem. O preflight de review abre o diretório preparado para inspeção e exige modo 0700; não exige `W_OK`, cria arquivo ou corrige permissões na sessão read-only. O `prepare` executado pelo pai gravável testa escrita efetiva no destino antes de persistir cada receipt, mesmo quando `--thread` aponta à sessão read-only. Uma sessão dedicada deve aguardar o preparo dos receipts antes dos spawns. Se seu host não oferece coordenação entre a sessão de leitura e o orquestrador, recuse o nascimento; não emule read-only.
5. Após ambos os retornos, o pai gravável executa `codex_proxy.py --birth` uma vez por reviewer. O mesmo comando/recibo suporta recoleta idempotente. A coleção lê a sessão de spawn via UUID do receipt, mesmo que o orquestrador seja outra sessão.
6. Execute `codex_review.py verify-wave --wave-id <onda> --sha256 <digest> --bound-card <card>` e `review_process_checklist.py` como antes. O gate revalida proveniência, dois papéis/capturas/filhos distintos, mesma sessão/turno read-only, onda/diff e completed/payload; recusa envelopes `qualification=true`, exclusivos de ensaio. A evidência não substitui conteúdo da revisão nem aprovação humana.

Em 2026-10-13, uma sessão comprovadamente read-only recusou o preflight porque ele consultava `W_OK` no seu próprio sandbox, apesar de destino 0700 e receipts preparados pelo pai gravável. O follow-up separou inspeção e escrita; regressões controladas comprovam essa separação. A onda real após a correção permanece pendente do pai, conforme [registro operacional](../openspec/changes/card-1095-codex-evidencia/evidence.md). A qualificação workspace-write anterior não é promovida a prova dessa onda.

## Qualificação e recuperação

Um host sem prova é `unverified`. A exceção é ensaio explícito sem produto, sem transição e dentro das permissões existentes. Capture `codex/execucao`, execute `prepare --qualification`, spawne um filho nativo que apenas retorna conteúdo e colete/consuma pelo proxy. Registre recusas reais do coletor separadamente de fixtures; `qualify --evidence <envelope> --refusal <failure-json>` exige tentativa correspondente e persiste a qualificação privada. Não usar o ensaio como QA de produto/review de diff. Fixtures não qualificam hosts.

```bash
python3 scripts/process-fsm/codex_evidence.py preflight
python3 scripts/process-fsm/codex_evidence.py collect --birth <receipt> --wait-seconds 5
python3 scripts/process-fsm/codex_evidence.py verify --evidence <envelope>
```

Ausência/permissão revogada/flush incompleto: preserve receipt/captura e artefatos; recolete a mesma tentativa quando a fonte íntegra reaparecer. O failure fica separado da posterior prova, sem converter recusa em sucesso retroativo. Divergência de modelo/esforço, filiação/nascimento/turno errado ou origem irrecuperável exige nascimento novo após preflight; não retunar/resumir o filho divergente. Um filho anterior à instalação deste mecanismo não recebe receipt fabricado retroativamente.

Armazenamento padrão `.cursor/tmp/codex-evidence/`: diretório 0700, arquivos 0600, publicação atômica exclusiva. Captura/receipt têm integridade e permanecem imutáveis; preserve também a captura original. A extração contém identidades, campos mínimos, ordinais/tipos e SHA dos bytes usados, nunca prompts/transcripts/payload completos. O digest estável não muda por eventos irrelevantes append-only. Consumidores releem a fonte e a extração: JSON com `successful=true` não basta. Fontes conflitantes são recusadas. Hash local detecta adulteração; não é atestado criptográfico do servidor nem proteção contra um operador que fabrica toda a origem local.
