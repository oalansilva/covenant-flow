# Bounded Review v1 — bootstrap inativo

Este protocolo compõe revisão nativa; não cria estados/eventos, não comita,
não decide findings e não concede trust. O MVP preserva arquivos inteiros; um
patch adicionado pode ser separado recursivamente pelos arquivos internos,
com spans contíguos e cobertura exata de todos os bytes, inclusive preâmbulos.
Unidades da mesma área são agrupadas quando cabem, preservando contratos. O legado pequeno
continua disponível. Cada unidade/grupo usa o controller terminal existente,
coordenador novo read-only, bootstrap/contexto/probes próprios e ambos os
perfis nativos no mesmo turno. Hash, bytes e sucesso mecânico não provam
entendimento: cada perfil entrega parecer independente com cobertura explícita.

## Caminho do principal

Comandos abaixo rodam no principal gravável, no worktree vinculado. Não execute
os comandos retornados dentro de um subprocesso Python: use o tool nativo de
comando, retenha resultado completo/IDs e aguarde o mesmo processo. `advance`
retorna no máximo uma ação por chamada e nunca executa eventos da FSM.

```
python3 scripts/process-fsm/codex_bounded_review.py capture --root "$PWD" --out "$PWD/.cursor/tmp/bounded/run-1" --mode precommit --base HEAD
python3 scripts/process-fsm/codex_bounded_review.py plan --snapshot .cursor/tmp/bounded/run-1/snapshot.json --budget .cursor/tmp/bounded-budget.json --diagnostic
python3 scripts/process-fsm/codex_bounded_review.py ledger --plan .cursor/tmp/bounded/run-1/plan.json --out .cursor/tmp/bounded/run-1/ledger.json
python3 scripts/process-fsm/codex_bounded_review.py advance --ledger .cursor/tmp/bounded/run-1/ledger.json
```

Repita `advance` somente depois da conclusão da ação nativa pedida. Nunca
reexecute um comando pendente. `pending` reabre fontes originais e identifica
trabalho pendente. `retry --ledger ... --item <id>` cria checkpoint novo só
para pendência com falha registrada, com teto de uma recuperação explícita.
Falhas, capturas e births antigos permanecem; recolher não cria nascimento.
Retry é recuperação técnica, uma vez e só de pendência. Findings semânticos ou
dependências novas exigem correção e novo snapshot/plano; não se sorteia outro
parecer sobre os mesmos bytes para apagar um finding.
Uma falha de conteúdo/contexto/plano invalida globalmente. Crie novo snapshot
para replanejar: não edite um pacote completo nem recicle receipts. O MVP
conservador não subdivide pacotes completos nem mantém cache entre snapshots.

Para fechamento, `capture --mode closing --base <commit-base-exato> --target
<commit-alvo-exato>` fixa o intervalo. Resolva merge-base antes, se necessário.
Pré-commit captura árvore do índice e árvore de todos os paths de working tree
mais untracked não ignorados. As duas fases do inventário mantêm uma alteração
staged mesmo quando o working tree a desfaz; nada é excluído por extensão,
tamanho ou pasta de processo. O diretório de saída deve ser ignorado previamente,
para não inventar uma exclusão por efeito da captura. Symlinks são blobs de
link, sem seguir alvo; submodules e binários sem material inspecionável bloqueiam.
Refs locais `refs/covenant-review/*` retêm árvores de índice/working tree; os
pacotes e patches ficam no diretório ignorado. Preserve refs e artefatos junto
com o ledger, inclusive após rollback. Não há GC/limpeza automática.

## Plano e orçamento

`bounded-budget.json` contém `limit`, `limit_source`, `overhead` e
`uncertainty_percent`. `limit_source` identifica `session`, `path`, `ordinal`,
`raw_sha256`, `model` e `effort` de um `event_msg/token_count` nativo com
`info.model_context_window`; a fonte original é reaberta pelo locator. O limite
escolhido deve ser no máximo o observado. Modelo novo exige orçamento e
qualificação novos. Metadados ausentes bloqueiam: bytes ou páginas não inventam
janela de contexto. Reservas inteiras positivas são necessárias nas categorias
`instructions`, `tools`, `calls`, `outputs`, `framing`, `analysis`, `verdict`;
incerteza mínima de 25%. Use reservas conservadoras para o host/prompt real.

A estimativa conta duas entregas JSON escapadas integrais, uma por origem do
comando e outra pelo tool entregue, mais todas as reservas e incerteza. O bound
por bytes UTF-8 evita razão fixa caracteres/tokens. Opcionalmente, o orçamento
inclui `tokenizer={"method":"dual-tiktoken-v1","version":"0.14.0"}`. Isso conta
duas vezes o maior resultado entre `o200k_base` e `cl100k_base` sobre a entrega
JSON escapada, antes de somar as mesmas reservas e margem. É um proxy versionado:
não é tokenizer certificado para o modelo. Método/versão indisponível bloqueia;
trocar para fallback requer replanejamento explícito. É estimativa conservadora,
nunca prova de cabimento. O runtime ainda deve demonstrar entrega integral em
ambas as fontes nativas e nenhuma compactação, inclusive após última página.

O MVP não aceita declaração autoral de relações vazias: reconstrói uma análise
determinística das fontes congeladas. Registra paths, hashes de material,
imports/referências, símbolos exportados e seus consumidores, testes,
configurações e vínculos conservadores na mesma família de módulo/teste dentro
do diretório. Um diretório inteiro de helpers não vira relação entre todos os
seus arquivos. Símbolos genéricos definidos em vários paths não são prova de
contrato cruzado; imports/paths/configurações continuam analisados.
Os headers de transporte do próprio diff não são referências entre módulos de
mesmo basename; seus bytes continuam integralmente presentes na revisão.
Um átomo isolado continua com seus fatos verificáveis; não basta o autor dizer "nenhum".
O grafo inclui essas dependências candidatas, sem inventar todos os pares de
componentes independentes. Relações internas a uma unidade são julgadas ali pelos dois
perfis; relações entre unidades são atribuídas exatamente uma vez a grupos
de integração que podem compartilhar pontas. Uma matriz compacta usa índices
locais ligados aos IDs imutáveis: isso deduplica metadados, nunca código ou
obrigações. Cada grupo recebe os diffs e código real base/índice/target das
pontas, fechamento por testes pertinentes, configurações, imports Python e
referências explícitas a paths. Busca por prefixos limita tentativas de
tokenização sem alegar empacotamento ótimo; pontas menores com vínculos pendentes
têm prioridade e pontas sem vínculo com o grupo não consomem seu orçamento.
O plano registra unidades, grupos,
pares, reviewers, births e chamadas esperados; o grafo conservador ainda pode
ser operacionalmente caro. Cabimento individual não atesta viabilidade total.
Dependência dinâmica desconhecida ou pacote indivisível
sem margem bloqueia antes de births; não omita contexto para fazê-lo caber.
Descoberta pelos reviewers também bloqueia e exige novo plano. `plan
--context-map arquivo.json` aceita resoluções explícitas de chamadas dinâmicas,
vinculadas ao path/SHA/linha/chamada, com justificativa e fontes reais existentes;
não aceita simplesmente declarar que não há relações. Este corte não promete
que todo repositório caiba nem que qualquer plano estimado passe no host real.

Cada reviewer devolve um JSON completo com `schema`, `item`, `snapshot`, `role`,
`changes`, `relations`, `verdict`, `findings`, `discovered_relations`. `PASS`
requer ausência de findings e relações desconhecidas. O MVP conservador bloqueia
findings em vez de automatizar dispensa; o pai aplica teto 1+1/residual vigente.
Unidades não abrem ciclos adicionais. Um teste de contrato de integração não é
parecer real de LM.

## Ativação e gates

Remover `--diagnostic` pede produto, que permanece inativo sem `--activation
<manifesto>`. O manifesto é um índice selado, não autorização; `require_activation`
revalida sua cadeia a cada uso. Não há flag `enabled` aceita. A estrutura é:

- `version=bounded-review-v1`, `root` e `implementation` com hashes correntes;
- `bootstrap`: `trusted_base` (export retido v1.1.25), `git_root` com objetos da
  base aprovada `c8b794c76c1c69017f4bef84c220d7e42a15286a`, `support_root`,
  `target` commit do corte, `diff`, `diff_sha256`, `wave_id`, `card`, `proxy_log`;
- `legacy_review` e `legacy_checklist`: `session`, `root`, `command`,
  `source={source,ordinal,raw_sha256}` e SHA-256 dos bytes de `aggregated_output`
  em `output_sha256`. Checklist também informa `change_root`;
- `diagnostics`: ledgers completos e revalidados nas duas superfícies
  `codex-tui` e `codex_exec`, produzidos após instalação do mesmo suporte.

A árvore de helpers da base retida é comparada byte a byte com os objetos Git
aprovados; a verificação base deve executar o comando exato `python
<base>/scripts/process-fsm/codex_review.py verify-wave --root <support_root>
--wave-id ... --sha256 ... --bound-card ...`, e o checklist base usa `--root`,
`--change-root`, `--phase precommit --wave-same-turn yes`. O patch deve reproduzir
o intervalo completo base→target e o código instalado deve corresponder ao
revisado. Cada proxy original é revalidado. A revisão do próprio suporte nunca
usa o verifier alterado como aceite. Depois pin real e trust humano separado,
os diagnósticos instalados qualificam o protocolo sem produto/transição.
O checker de registro existente exige adapter/registro revisados e heartbeat;
trust do host Codex continua obrigatório. Nenhum comando aqui grava confiança.

Depois de todas essas provas, uma nova onda de produto é conduzida por
`advance --activation ...`. O TTL de 120s continua obrigatório para cada novo
lançamento; resultados completos revalidam o stage-check no tempo histórico
nativo de seu preflight, sem renová-lo. O fechamento reconsulta Status vivo.
`codex_review.py verify-wave --bounded-ledger ... --activation ...` exige todas
as unidades/grupos. O checklist recebe os mesmos argumentos e ainda valida
suas regras anteriores, tasks e FSM. A verificação global registra ponte
`.cursor/tmp/bounded-review-current.json` para o preflight/gates existentes.
Os proxies de cada item ficam em log privado, fora do log canônico legado.
O patch usado pelo checklist deve ser o `global.patch` do snapshot integral.
Sem essa ponte, o legado recusa um pacote composto como prova global.

Distribua pelo instalador/manifests normais e revise trust depois do pin;
instalar não ativa. Rollback do pin desativa o protocolo: preserve ledger e
fontes e remova somente a seleção da ponte após registrar o rollback. O legado
não recebe os PASS parciais no seu log canônico e a versão nova também recusa
um pacote `BOUNDED-REVIEW-V1` isolado como revisão global válida.
Ondas antigas continuam falhas. Aceite vivo do diff preservado de 1.586.532 bytes,
duas rotas, retomada e integração continua obrigatório em 9.x; fixtures não o
substituem. O harness opcional `BOUNDED_RETAINED_PATCH` testa preservação,
planejamento e verificação integral do artefato histórico como patch adicionado
em repositório fixture. Não reconstrói sua árvore original nem representa
julgamento semântico vivo. Seu orçamento, tempo e fan-out devem ser publicados
separadamente dos ensaios instalados e da janela observada no host.

Novas cópias derivadas pesadas podem usar índice para objeto durável já retido
somente com origem, base/target, SHA e receita de reprodução byte a byte. Teste
disponibilidade e reprodução primeiro. Sem origem durável mantenha o artefato e
orce todo conteúdo lógico; não exclua patches, testes, docs ou história do Review.
