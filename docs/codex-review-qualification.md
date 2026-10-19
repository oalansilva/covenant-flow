# Revisão Codex em coordenador dedicado read-only

Adendo factual de 18/10/2026 (#1130): a onda de produto/verify-wave/checklist e QA da rota CLI interativa → exec foram comprovadas no fechamento #1098 (PR #1129, base consumidor `1a06caec`). A referência a produto pendente no histórico abaixo é anterior a esse fechamento. Principal exec independente pertence ao #1130; App/IDE ao #1128. Cada onda nova continua exigindo suas fontes, diff/SHA, Status e TTL. [Controller terminal de preparação automática](codex-terminal-flow.md).

## Protocolo de saída e diff grande

O preflight pertence ao coordenador e deve rodar **uma vez** na fase preparada. A coleta de context, probe e review exige sucesso nativo antes de todos os nascimentos, no mesmo turno: ready, phase/work_release corretos, fontes e ordinais preservados. Executá-lo depois dos filhos nunca regulariza a onda. O probe é o **primeiro comando de cada reviewer**, também **uma vez**. Duplicatas continuam invalidando a origem; truncamento ou dúvida não autorizam repetir tentativa de escrita. A falha deve voltar ao principal, sem parecer válido. O preflight usa orçamento explícito de 12000 tokens no comando e no wrapper; o probe e cada leitura usam 20000 no comando e 32000 no wrapper, com um resultado por saída.

O helper valida pacote/plano/captura/path/SHA antes da tentativa fixa e devolve deny/readback em JSON curto. Até 4096 caracteres e dentro dos limites serializados, entrega o diff em `diff_text`. Nos demais casos, devolve `delivery=native-json-bounded-pages-v2`, tamanhos, contagem, `read_command_template` informativo e `next_read_command` literal. As páginas são limitadas pelo JSON UTF-8 real (16000 bytes) e pelo envelope de retorno com escapes Unicode/JSON (28000 bytes, incluindo reserva de metadata), ambos abaixo do truncamento nativo observado em cerca de 64 KiB. O tamanho varia conforme aspas, controles e Unicode; não é um aumento fixo de caracteres. Esse manifesto **não** comprova entrega integral. Cada reviewer copia e executa literalmente o `next_read_command` do retorno anterior, no cwd nativo do worktree, sem reconstruir paths nem substituir pelo template. Paths relativos curtos reduzem transcrição; `../`, `./` acrescentado, cwd errado e comandos combinados continuam recusados pelo coletor. A sequência exige índices consecutivos `0..chunk_count-1`, leitura de cada `diff_text` e `next_read_command=null` apenas na última parte antes do parecer. Os comandos `read` não tentam escrever. Não concatenar várias partes em uma saída sujeita a truncamento; orçamento de contexto insuficiente exige `review_diff_delivery_incomplete` e nenhum veredito.

O coletor exige eventos nativos completos de todos os chunks, com argv canônico, mesma thread/turno/plano/path/SHA e saída exata. Cada `CommandExecution` precisa estar entre uma chamada nativa de ferramenta e seu retorno correspondente, contendo **um** comando e o JSON completo entregue ao modelo. O stdout registrado e o retorno de `exec`/`exec_command` podem truncar independentemente; validar somente `aggregated_output` é insuficiente. A prova preserva referências/hashes das duas camadas e não interpreta código JavaScript como fonte de execução. Formas desconhecidas, múltiplos comandos ou retorno ausente são recusados.

O coletor reconstrói os bytes em ordem e confere o digest completo. Falta, duplicata, alteração, truncamento ou parte anexada após o payload falham. Metadata sintética, resumo e afirmação do reviewer não substituem conteúdo entregue. Essa prova é de entrega por ferramenta; não atesta compreensão semântica nem contexto interno. Os dois reviewers devem cobrir independentemente o mesmo artefato.

Não se executa `codex_review.py verify` isolado no filho: o helper realiza a verificação inicial, e `verify-wave`/checklist pertencem ao principal gravável **após** ambos os payloads e coleta. A ordem evita dependência circular e mantém a recusa por probe ou leitura ausente. Testes de contrato com diff de 700740 bytes e saídas truncadas não qualificam a nova versão da rota no host; o próximo ciclo real continua obrigatório.

O principal do card permanece gravável. `codex_review_session.py` prepara e lança automaticamente um coordenador Codex dedicado com `exec --sandbox read-only`, e usa `exec ... resume <id>` para continuar a **mesma sessão**. Em18/10/2026, a rota diagnóstica TUI → exec foi qualificada na sessão `01a14c6d-8e42-79d3-bd0e-db78be7c3aca`: bootstrap/binding, contexto próprio, dois perfis nomeados/probes e lançamento/retorno reais PASS. [Provas sanitizadas e hashes](evidence/card-1098-dedicated-diagnostic-pass-20261018.md). Principal exec/App/IDE → exec e onda de produto continuam pendentes; flags/TOML/testes não qualificam essas rotas. O agente não alterna permissões da sessão principal, muda trust/conta ou executa review no principal/coordenador. Outros estágios continuam nativos no chat do card; não há fallback para outro cliente.

O ciclo evita a dependência circular de um chat novo: bootstrap sem filhos → contexto diagnóstico sem ferramentas no filho → qualificação C/S persistida pelo principal → dois perfis nomeados em diagnóstico de probe → qualificação da rota → onda produto. Todas as fases nascem e continuam somente leitura no coordenador. Arquivos de preparo, capturas, fixtures e qualificações são gravados pelo principal entre retomadas nativas; o coordenador só lê e retorna. Atuação de produto exige Status vivo Code Review e os gates humanos existentes.

## Preparação e lançamento

Execute do principal gravável vinculado ao worktree do card, após integração e revisão de trust quando necessária. O comando `prepare` não lança sessão. Retorna um path de pacote e o **comando exato** de lançamento; execute-o isoladamente via shell nativo, com saída integral. `<...>` representa saída real anterior, nunca dado observado preenchido manualmente.

```bash
python3 scripts/process-fsm/codex_review_session.py prepare --root <worktree-absoluto> --phase bootstrap
```

1. Execute o `command` retornado. O helper fixo lança o binário local com seleção de execução capturada, sandbox read-only e worktree explícito; mantém os JSONL nativos em arquivo exclusivo. O bootstrap só inspeciona contrato/binário/runtime e estabelece uma sentinela não secreta na própria conversa; não inicia filhos nem review. Não publique nem copie essa sentinela.
2. `binding --package <bootstrap>` exige o `CommandExecution` nativo completo do principal com argv/cwd/turno/exit/saída correspondentes, JSONL `thread.started`, sessão real exec e runtime observado read-only/modelo/esforço/cwd desde o nascimento. Enquanto a fonte não estiver disponível, recusa. A fonte não é reescrita para fazer o vínculo passar.

Configuração inicial nativa `thread_settings_applied` é aceita somente antes do uso de ferramentas, no primeiro turno, com identidade/coordenador, modelo/esforço, diretório/raiz e perfil gerenciado coerentes com o `turn_context` efetivo. O formato observado em exec 0.163.0 é filesystem restrito com uma entrada root/read e rede restrita; a declaração do evento sozinha não prova readonly. Os mesmos campos autorizadores podem reaplicar no começo da retomada, inclusive no intervalo nativo entre `task_complete` anterior e `task_started`/`turn_context` seguintes. Nesse intervalo são validados imediatamente contra a configuração original e ficam pendentes para validação contra o próximo turno efetivo. Mudança autorizadora, ampliação, campo desconhecido, terminal sem vínculo ou ferramentas antes do novo turno recusam. Evento depois de trabalho no turno ainda ativo continua recusado; repetir um `turn_context` não reinicia a fronteira.

`service_tier` é a única chave classificada como metadado não autorizador nessa comparação. A [referência oficial](https://learn.chatgpt.com/docs/config-file/config-reference) descreve a preferência de processamento para novos turnos como independente de modelo/esforço; a decisão de tratá-la separadamente deriva também do contrato local, que autoriza par observado, contexto, binding e permissões. O schema completo continua fechado e exige tier string não vazia. Uma mudança `default → priority` antes do trabalho pode coexistir com os mesmos campos autorizadores, sem afirmar que as configurações completas são iguais. Valores reais e hashes de cada evento são preservados por turno. Provider, modelo, esforço, permissões, cwd/raízes, aprovações, colaboração, plugins e campos desconhecidos continuam estritos; tier não permite mudança após trabalho nem concede trabalho de produto.

Na nova tentativa de 18/10, coordenador `01a14c8d-0db5-7b60-8f6d-c3ae88480673`, o único delta observado entre settings 8 e 26/27 foi `service_tier: default → priority`. O preflight recusou antes de qualquer spawn. A correção candidata passou na projeção sanitizada de metadados e em testes de contrato; não requalifica esse contexto nem altera a tentativa histórica. Novo ensaio exige integração/revisão pertinente e pacotes com os hashes novos.

Os digests de settings entre turnos pertencem à **próxima** continuação, nunca ao bootstrap já encerrado. Settings pendentes ainda sem próximo turno não concedem nascimento/preflight e não alteram refs históricos; o próximo turno real continua obrigatório. Isso mantém a origem vinculada sem retunar evidências por append. O trace real de 18/10 mostrou terminal25 → settings26/27 idênticos → started28 → contexto31; esse formato foi inspecionado somente por metadata, sem marcadores/prompts.

Correção do coletor altera os hashes de código fixados no pacote. Prepare novo bootstrap após integrar/revisar o adapter pertinente; não edite o pacote anterior, seus digests ou trace para reaproveitar prova. A aceitação dos metadados iniciais não qualifica a rota, o contexto C/S ou os reviewers por si só.

Execute também **uma vez** o `refusal_command` retornado pelo preparo bootstrap, depois do lançamento e antes de qualificar a rota. `route-check` deve retornar exit 1 / `review_route_unqualified`: essa recusa nativa real, além do positivo posterior, é revalidada por `qualify-route`. Não mudar dados observados ou copiar uma recusa de outra tentativa. Ausência da origem negativa mantém a rota pendente.

```bash
python3 scripts/process-fsm/codex_review_session.py binding --package <bootstrap-package>
python3 scripts/process-fsm/codex_review_session.py prepare --root <worktree-absoluto> --phase context --bootstrap <bootstrap-package>
```

3. Execute o novo `command` retornado. Ele retoma o ID comprovado do mesmo coordenador, ainda read-only. O principal já preparou captura, receipt pendente e plano C/S da próxima chamada. O prompt fornece o comando **exato** `preflight --package <context-package>` e exige `result=ready`, `phase=context`, `work_release=diagnostic_only` antes da chamada nativa `collaboration.spawn_agent`. `inspect` é exclusivo do bootstrap e não é preflight da continuação; seu uso com outro pacote retorna `review_action_phase_mismatch`. Runtime ativo sem v2 ou ferramenta nativa não exposta impede o nascimento; configuração/flags não substituem observação.

A sentinela fica somente no contexto anterior do coordenador; os arquivos contêm hashes, nunca seu valor. O controle C chega ao filho com `fork_turns=none`. O filho diagnóstico não usa ferramentas. O principal persiste/verifica a qualificação separada, usando o primeiro birth do pacote context:

```bash
python3 scripts/process-fsm/codex_context.py qualify --plan <birth.context-plan.json>
```

Isso exige contrato documentado ligado ao binário/runtime real, chamada nativa registrada, controle exato/completed/payload, filiação e ensaio sem canal contaminante observado. `internal_context_attestation=unavailable` permanece. Qualificação TUI/default não é copiada para exec nem para esse chat novo.

## Perfis nomeados e probes, sem produto

```bash
python3 scripts/process-fsm/codex_review_session.py prepare --root <worktree-absoluto> --phase probe --bootstrap <bootstrap-package> --diff <diff-diagnostico-descartavel>
```

4. Execute o novo `command`. O coordenador verifica o pacote uma vez e inicia `diff-reviewer` e `code-reviewer` nativos **no mesmo turno**, com capturas distintas da mesma seleção e `fork_turns=none`. Cada perfil permite explicitamente apenas a tentativa única do helper fixo na fixture precriada vinculada ao plano. Não permite escrita de produto, alvo arbitrário ou escalada. O helper registra errno/readback e entrega o diff inline ou por comandos de leitura em chunks conforme o protocolo de saída acima. Escrita permitida, fixture alterada, saída truncada, papel default ou probe/leitura ausente invalidam a tentativa. Não restaurar bytes para fabricar deny.
5. Após os dois payloads, o principal coleta os births originais, qualifica os probes e a rota separadamente:

```bash
python3 scripts/process-fsm/codex_evidence.py collect --birth <probe-birth-diff>
python3 scripts/process-fsm/codex_evidence.py collect --birth <probe-birth-code>
python3 scripts/process-fsm/codex_review_probe.py qualify --root <worktree-absoluto> --evidence <probe-evidence-diff> --evidence <probe-evidence-code>
python3 scripts/process-fsm/codex_review_session.py qualify-route --package <probe-package>
```

`qualify-route` revalida contexto próprio, rota principal→exec, dois papéis/filhos/mesmo turno, seleção, sandbox, diff e probes. Uma fixture ou diagnóstico no TUI não substitui essa prova. Cada rota TUI/exec/app/IDE permanece vinculada à identidade e superfície reais do principal e à sessão coordenadora observada.

## Onda produto

6. O principal materializa o diff exato com o mecanismo canônico, verifica SHA-256 e prepara nova tentativa `--phase review --bootstrap <bootstrap> --diff <diff-real>`. Esse preparo exige contexto, probes e rota qualificados; não executa a revisão. O preflight `pedir_review` inspeciona o pacote e o coordenador qualificado, mantendo o principal gravável. O pai usa `process_event` canônico; os gates humanos e a FSM não mudam.
7. Após Status=Code Review, execute primeiro o **`stage_check_command` exato** retornado pelo preparo, isolado em um comando nativo do principal; depois execute o `command` de lançamento. `stage-check` consulta o Status autoritativo no GitHub pelo provider canônico, confere card/branch e retorna prova ligada ao pacote/wave/principal/turno, com os horários reais da consulta. O lançamento exige a origem `CommandExecution` completa dessa consulta, reconsulta Code Review no principal e grava receipt exclusivo antes de retomar o coordenador. A janela entre o início da consulta e o preflight do coordenador é de **120 segundos**, fixa no helper; expiração exige nova tentativa/pacote, sem copiar ou renovar TTL. Consulta falha/indisponível ou estado alterado bloqueia antes do exec. Não há flag de Status observado preenchida pelo operador.
   O coordenador retoma read-only e seu preflight **somente lê** pacote, fonte nativa da consulta, receipt do lançamento, hashes, binding local e horários; não importa o Guard, escreve cache/temporários ou consulta a rede. A saída identifica a prova verificada, sem alegar consulta GitHub no filho. Só então inicia os dois perfis no mesmo turno. Cada reviewer executa o probe **antes** de qualquer outro comando/parecer e revisa somente o mesmo path/SHA. O coordenador reúne os payloads sem fazer review nem gravar receipts. Não se exige `verify-wave` final antes da produção dos probes.
8. Após ambos completed/payload, o principal gravável coleta/proxy pelas capturas e envelopes originais. `verify-wave` exige cadeia dedicada, mesmo coordenador/turno/pacote/path/SHA, dois filhos/perfis, contexto opção 2, read-only contínuo e probes revalidados. Persistência roda no principal comprovado; o coordenador nunca fica gravável. Execute também o checklist canônico antes de commit.

A coleta posterior revalida a consulta e o receipt contra a fonte nativa original, o hash devolvido pelo launcher e o horário do preflight dentro dos intervalos nativos de lançamento/preflight. Usa a janela **na execução original**, permitindo uma revisão longa sem renovar status ou exigir TTL atual para prova histórica. Pacote/turno/fonte ambíguos, horários ausentes, receipt alterado ou consulta não observada recusam. Um preflight nativo que falha preserva seu código específico na coleta; `exit0` do processo exec sozinho não oculta a falha nem aprova a onda.

O pacote review fixa também os hashes do provider/dependências diretas de Status e do overlay que identifica a autoridade do board. O coordenador confere esses bytes sem importar o provider nem interpretar o overlay; mudança de código ou autoridade invalida a tentativa. O preflight do principal seleciona o pacote mais novo da sessão/worktree antes de validar seus arquivos atuais, preservando os pacotes históricos que fixam código anterior.

```bash
python3 scripts/process-fsm/codex_proxy.py --capture <capture-diff> --activity diff-reviewer --band execucao --birth <birth-diff>
python3 scripts/process-fsm/codex_proxy.py --capture <capture-code> --activity code-reviewer --band execucao --birth <birth-code>
python3 scripts/process-fsm/codex_review.py verify-wave --root <worktree-absoluto> --wave-id <wave-do-pacote> --sha256 <sha-real> --bound-card <card>
```

## Estado, recuperação e limites

Pacotes têm schema `codex-dedicated-review-v1`, estado `pending_native_launch`, membros/hashes e origem principal. Births antecipados têm `envelope_state=pending_coordinator` e parent/turno `unavailable`. A resolução acontece **em memória**, relendo o pacote original e fontes autoritativas do lançamento/retorno e das chamadas de filhos. A evidência final conserva os bytes pendentes originais e acrescenta a cadeia nativa; um envelope pendente não é prova final. Parent arbitrário, receipt ligado ao principal, fonte ambígua/adulterada, escolha alterada ou completude falsa falham.

O principal vê o processo nativo de lançamento, seu estado/saída e os paths dos pacotes/JSONL. O retorno `binding` mostra principal, coordenador e fontes; o coletor mostra os child IDs e paths nativos. Controles de lista/inspeção/interação só contam quando expostos e observados na superfície usada; não se promete que uma interface TUI liste automaticamente uma sessão exec. Alan pode inspecionar a sessão pelo ID nativo usando os controles realmente oferecidos, sem alterar suas permissões para fazer a onda passar.

Ausência de `CommandExecution`, schema exec incompatível, herança de sandbox divergente, hook/trust recusado, retorno sem payload ou impossibilidade de retomar a mesma sessão mantém a etapa bloqueada com código específico. Preserve arquivos/falhas; não reedite traces, receipts ou qualificações. Não retome filho divergente nem copie positivo de outra superfície. O protocolo histórico de alternância manual de permissões foi substituído para Review. O diagnóstico dedicado real qualifica a rota indicada; não conclui review/QA de produto, checklist, distribuição canônica nova ou substituição integral. Para `pedir_review`, o pai ainda prepara pacote `--phase review` sobre diff final e passa pelos gates vivos. Tasks pendentes sem anotação de fase continuam bloqueando o checklist precommit; não se declara esse gate verde com o diagnóstico.

No diagnóstico anterior de18/10, coordenador `01a14c63-737e-7802-8620-2f8b343cfd0e`, os custom_tool_call `exec` observados eram chamadas de shell, sem spawn nativo. Um deles executou `inspect` com pacote context e falhou antes do filho. Após a correção integrada, o novo coordenador indicado acima produziu as chamadas nativas exigidas e passou na qualificação. O coletor continua exigindo origem nativa real: texto de shell/JavaScript, solicitação ou payload não fabrica filiação. O runtime observado tinha `multi_agent_version=v2`; listagem/configuração CLI não o reclassifica. Fontes e recusas anteriores foram preservadas.

## Núcleo sem overlay: autoridade explícita

O núcleo continua sem `.covenant-flow/overlay.yaml`. Execute o helper instalado
no próprio worktree nativo e acrescente `--authority-root <worktree-consumidor>`
a `codex_review_session.py prepare` (ou a `codex_terminal.py start --operation
review`). Sem a opção, Review usa o próprio worktree consumidor. Não há busca
implícita em outro checkout nem cópia de overlay. Nas continuações, o pacote
bootstrap conserva a mesma autoridade; uma tentativa não pode trocá-la.

A autoridade deve ser a raiz Git canônica de um worktree `card-N-*`, com branch
igual ao nome da pasta e o mesmo card do núcleo. Seu origin GitHub deve coincidir
com `overlay.repo`; overlay completo, repo, board, card, branch e hash dos bytes
ficam fixados no pacote. Paths com symlink, overlay ancestral/ausente, origin não
qualificado, identidade diferente ou fonte alterada recusam a tentativa. Somente
dados são lidos no consumidor: nenhum helper ou módulo externo é executado.
Raiz nativa, workspace roots, diff, capturas, helpers, fixtures e receipts continuam
contidos no núcleo.

Prepare e consultas vivas do principal usam essa autoridade; stage-check e
launch exigem Code Review. O pacote e as fontes são revalidados também no
preflight do coordenador e na coleta. O coordenador só relê dados e a prova
nativa do principal, sem rede nem escrita; permanecem TTL de 120 segundos,
ordenação dos comandos nativos, qualificação de contexto/rota/perfis e par
read-only no mesmo turno. Pacotes anteriores sem binding de autoridade devem
ser preservados e substituídos por um preparo novo.

Para T9 a partir do núcleo, o pai executa, no cwd nativo do núcleo:

```bash
python3 scripts/process-fsm/process_event.py pedir_review --card N --client codex --authority-root <worktree-consumidor>
```

Essa extensão de `process_event` aceita somente `pedir_review` e
`achar_bloqueante`, com cliente Codex. Consulta e edição do board usam a autoridade
explícita e revalidada; T9 exige a mesma autoridade do pacote Review qualificado.
Os artefatos de aprovação são lidos no worktree da autoridade, conservando I4:
Design alterado continua devolvendo a Design antes de iniciar Review. Preflight,
registro/trust e cwd observados continuam ligados ao núcleo. A opção não
redireciona integração, release nem gates humanos; essas operações conservam
seus contratos próprios.
