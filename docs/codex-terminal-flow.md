# Covenant Flow no terminal Codex

O contrato inclui principal interativo TUI e principal `exec`: criação/refinamento, Design/crítica, Apply, Review dedicado, QA/integração, homologação/T18 e release com pedido próprio. App/IDE permanecem fora desta entrega. Suporte implementado, fixture verde e etapa comprovada são fatos diferentes: consulte a matriz de aceitação do card consumidor antes de alegar fluxo integral.

## Preparação no mesmo chat

O pai resolve estado e vínculo; cada filho mantém captura própria. Na raiz nativa atual:

```bash
python3 scripts/process-fsm/codex_terminal.py start --card 123 --operation design --diagnostics-authorized
python3 scripts/process-fsm/codex_terminal.py advance --checkpoint <path-retornado>
```

Os exemplos usam card ilustrativo; o estado vivo deve admitir a operação. `start` não altera Status e `advance` reconsulta a autoridade. Só o pai executa eventos/Git. T1/T7/T15/T18 continuam atos de Alan; `implemente`, silêncio e um resultado de diagnóstico não os substituem. O Apply é um filho por entrada na coluna, nunca um filho por tarefa; o pai não executa trabalho delegado.

Criação usa `start --operation create` sem card, no workspace sem vínculo: o pai executa o T0 canônico, obtém a issue criada em Em Refinamento e inicia checkpoint `refine --card N`. No refinamento em source, o pai resolve captura de juízo/papel grill-card e usa `codex_evidence.py prepare --card N --capture <captura> --task-name <grill_card_N_unico>`. O receipt grava esse card explícito e o Status vivo; o hook revalida Em Refinamento/card e a presença de `#N` no prompt antes do spawn. Isso não altera o binding Git nem libera produto em source. Depois do retorno o pai coleta/proxy, preserva as perguntas/respostas no mesmo chat e o filho só escreve a história do card vinculado.

O pai executa automaticamente cada ação nativa devolvida e chama `advance` após seu término. Comando em andamento é acompanhado pelo mesmo ID; o resultado integral e o exit_code são preservados. Sem diagnóstico autorizado não nasce ensaio. Falhas ficam em journal privado imutável e encadeado, sob `.cursor/tmp/codex-terminal/`. Uma repetição automática por causa/fontes inalteradas é o teto. Restauração real de fontes permite recoleta da mesma tentativa; mudança de seleção/identidade requer novo nascimento. Interrupção e payload ausente não são sucesso. O journal não é evidência runtime nem autorização para uma transição.

## Descoberta de capacidade e migração

O checkpoint pode preparar diagnóstico antes do evento dependente, sem liberar trabalho da etapa: Design em Todo retorna `iniciar_design`; Apply em Pronto para Dev retorna `iniciar_apply`; QA em Code Review retorna `aceitar_sha`. Após revalidar as fontes, o pai executa esse evento existente e continua no mesmo checkpoint com a coluna nova observada. OpenSpec/Apply/QA de produto não nascem antes de seus gates. Em retorno T18, Em desenvolvimento já permite seguir sem T8.

O índice fica em `~/.config/covenant-flow/codex/qualifications-v1.json`: diretório privado 0700, arquivo/lock 0600, escrita atômica e exclusão mútua. Só guarda localizadores de origens imutáveis por superfície observada e schema rollout-v1. O verificador reabre receipt, envelope, recusas e fontes autoritativas; digest de registro detecta alteração. Índice, configuração, versão instalada e um selo de sucesso não são autoridade. O containment do escritor local de evidências permanece igual.

```bash
python3 scripts/process-fsm/codex_qualification.py register --surface codex-tui --reference <receipt-original-absoluto>
python3 scripts/process-fsm/codex_qualification.py discover --surface codex-tui
python3 scripts/process-fsm/codex_evidence.py preflight --qualification-reference <receipt-original-absoluto> --stage design-autor
```

Registro só depois de verificação integral; não concede trust. Superfície exec usa `codex_exec`. Sem referência explícita, o preflight consulta o índice exato e o receipt local legado; a lista explícita de origens legadas adicionais vem de `COVENANT_CODEX_LEGACY_QUALIFICATIONS`, separada por `os.pathsep`. Não há busca recursiva, escolha por mtime, cópia de `.cursor/tmp` ou importação de receipts para simular nascimento. Conflito requer seleção explícita de origem íntegra, sem apagar provas anteriores.

Capacidade compatível pode vir de outro worktree; contexto não: chat/root/binário/contrato e o ensaio C/S precisam corresponder à sessão atual. Versão compatível é registrada sem invalidar capacidade por seu número; binário/contrato alterado exige contexto novo. Review conserva qualificação própria por sessão/rota/perfis e por diff/SHA. `internal_context_attestation=unavailable` permanece.

## Retomada e perguntas em exec

`workdir` e `--root` não reatam o cwd nativo. O controller fornece comando literal com o UUID observado para o ato inevitável do operador. Formas verificadas no help local 0.163.0:

```bash
codex --cd <worktree> resume <UUID>
codex --cd <worktree> exec resume <UUID> --json -
```

A segunda forma lê o prompt explícito por stdin. Não usar `--last`, que perde identidade precisa, nem flags de trust/sandbox para contornar recusa. O controller não afirma rebind automático: depende de `turn_context` observado no destino e mesmo UUID. Se o runtime não o demonstrar, a célula permanece bloqueada.

Para pergunta humana no principal exec, `start --question <texto>` fixa pergunta e identidade. Entregue o checkpoint e aguarde. A mensagem humana da retomada contém duas linhas, `checkpoint: <id-retornado>` e `answer: <resposta explícita>`. Texto gerado pelo assistente, opções vazias, ausência de resposta ou outro UUID não liberam a ação. Depois da resposta, o pai executa `advance` e revalida Status/cwd/fontes. A resposta fica no chat do card; não se abre outro cliente silenciosamente.

## Review automático

O principal gravável materializa diff e inicia checkpoint `review --diff <path>`. O controller prepara bootstrap, contexto, probes e onda produto; retorna comandos literais para o pai executar com ferramenta nativa. Esse lançamento explícito mantém observável a cadeia principal → exec read-only → dois filhos nativos. O operador não alterna permissões. Cada fase é retomada na mesma sessão do coordenador; seus próprios C/S, perfis e probes são preservados.

O negativo inicial `route-check` tem exit1 esperado, não é erro de execução a ignorar. Depois dele o pai segue automaticamente. Preparação diagnóstica pode ocorrer em Em desenvolvimento; onda produto só com Code Review. `pedir_review` pertence ao pai. Cada pacote de produto requer stage-check autoritativo de até 120 segundos; TTL expirado produz pacote novo, sem renovar recibo antigo. Mudança de diff/SHA, Status, sandbox, sessão ou payload bloqueia. Não relançar um pacote cujo arquivo de eventos já existe após interrupção.

Ambos os reviewers nomeados nascem no mesmo turno, leem todos os chunks, demonstram deny/readback e entregam parecer completo. O principal coleta, persiste proxies e roda verify-wave. Lê os pareceres e aplica o teto 1+1/residual; P0 para. O checklist precommit roda **antes** de commit; fechamento usa intervalo próprio em checkpoint distinto. A task after-commit do fechamento não posterga o verify-wave/checklist pré-commit. [Protocolo detalhado](codex-review-qualification.md).

## QA, retornos e release

QA/checks usam SHA/PR reais, um filho QA e eventos canônicos no pai; pending/no_pr/dirty não significam Done. Após resolução, o pai repete o gate no mesmo turno. T14 integra, reinicia e valida DEV conforme overlay. T15 humano exige comentário; T18 só com motivo humano visível, volta ao mesmo card em branch a partir de develop atual e **não repete T8**. O controller de preparação não inventa esses fatos.

Release exige pedido próprio, captura de execução da operação e modelo/esforço observados no principal. `start --operation release --release-requested` registra esse escopo; `advance` recusa divergência. O pai usa o runbook de release e `release_closeout.py`, filho fecho-lote/Kaizen, guards pre/post, archive/sync no caminho permitido, PR/merge, deploy/hook/health do overlay, higiene e sincronização main → develop. Serviços/oneshots, banco e URLs vêm do overlay no momento da operação. Não há deploy, confiança ou T16 implícito em Apply/QA/homologação.

## Causas e próxima ação

| Causa | Ação conduzida |
| --- | --- |
| `unverified` + `qualification_reference_missing` | Diagnóstico autorizado do pai ou registrar origem íntegra conhecida; repetir preflight. |
| `qualification_index_corrupt` / `qualification_conflict` | Preservar índice/origens e informar conflito; origem explícita verificada pode ser usada sem regravar os fatos. |
| `qualification_reference_changed` / fonte inacessível | Restaurar original ou ensaio novo autorizado; não confiar no índice. |
| `stage_capability_missing` / contexto ausente | Ensaio C/S próprio e retry da operação pendente; não copiar contexto. |
| `worktree_mismatch` | Operador retoma o UUID no destino literal; depois revalidar cwd nativo e Status automaticamente. |
| `human_answer_missing` | Entregar pergunta/checkpoint; aguardar resposta explícita no mesmo UUID. |
| `hooks_unreviewed` / `hooks_changed` | Operador revisa R/A e `/hooks`; sessão nova quando o gate exigir. Agente nunca grava trust. |
| Review incompleto/expirado/interrompido | Preservar tentativa e causa; pacote/nascimento novo quando necessário; sem parecer ou commit antecipado. |

Matriz pública: uma linha por etapa/rota e inventário separado de sessões novas/retomadas nas duas raízes. Registre card/estado, SHA/pin real, captura, IDs, gate, referência privada com digest, recusa e próxima ação. Estados de relatório = planejado, diagnóstico, comprovado, bloqueado, aguardando ato humano; fixtures ficam em coluna própria. Done técnico pode preceder provas humanas/release, mas só todas as células reais obrigatórias permitem alegar fluxo integral. Esse compromisso continua no mesmo card de terminal.

Para Review de alterações no núcleo sem overlay, o principal permanece no
worktree nativo do núcleo e inicia o checkpoint com
`start --operation review --card N --diff <diff-do-núcleo> --authority-root
<worktree-consumidor> --diagnostics-authorized` (a última opção exige diagnóstico
já autorizado). O checkpoint fixa a autoridade antes do bootstrap e a repassa a
todas as fases; cada avanço revalida seus dados sem rebind de cwd/target-root.
A transição retornada `pedir_review` é executada pelo pai no núcleo com o mesmo
`--authority-root`; o evento verifica a autoridade do pacote qualificado, Status
vivo e aprovação. Dados alterados exigem tentativa nova, preservando a original.
O contrato completo, limites de escopo do evento e recusas estão em
[codex-review-qualification.md](codex-review-qualification.md#núcleo-sem-overlay-autoridade-explícita).
