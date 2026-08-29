---
name: grill-card
description: "Grelha a história de um card em Em Refinamento no body do GitHub issue. Use when Project Status of issue N is Em Refinamento, N is in the spawn prompt matching parent #id, and Alan asks to grill/afiar or the issue body lacks the DoD sections. Not for Todo, Design, or OpenSpec. Does not require git branch card-N-*."
disable-model-invocation: false
---

# grill-card

Porta de refinamento **deste repo**. Primitivo: `.cursor/skills/grilling/SKILL.md` (vendor; fronteira, uma rodada, recomendação, fato ≠ decisão). Ledger = **body do issue**, não `CONTEXT.md`.

Não é `grill-with-docs`. Não é `to-spec`.

## Precondição

Só corre se **as duas** forem verdade:

1. Número da issue N no prompt (título `#<id>` do pai = N). Não exige branch `card-<id>-*` nem worktree de card.
2. Project 1 `Status=Em Refinamento` **dessa** issue N.

Senão: recusar (id ausente, N ≠ `#<id>` do pai, ou Status ≠ Em Refinamento). Não editar issue de outro card. Não grelhar em Todo ou Design.

`bound_card` aqui é o id N no prompt, não o git.

## Quando disparar

- **Sim:** Alan pede grelhar/afiar, **ou** Status de N é Em Refinamento **e** o body não tem as 6 seções do DoD. Oferecer; não arrastar coluna. Vale em `develop` se N e Status baterem.
- **Não:** automático em todo T0; não em Todo/Design; cards já nítidos (DoD completo) podem T1 sem grill.

## Como

1. Ler `.cursor/skills/grilling/SKILL.md` e aplicar o loop (árvore, fronteira, uma rodada, recomendação).
2. Fatos (código, specs, board): buscar com tools. Decisões: Alan responde. Uma rodada por turno; esperar.
3. Despejar no **body** do issue bound (PT-BR), via `gh issue edit`, as 6 seções do DoD:

   1. **Problema** — uma frase, quem sofre.
   2. **História** — Como / quero / para.
   3. **Entra** / **não entra**.
   4. **Vocabulário** — `Termo`: definição curta; `_Avoid:` sinônimos.
   5. **Critérios de aceite** — observáveis (Given/When/Then ou lista comportamental).
   6. **Riscos / perguntas abertas**.

4. Se a fronteira **não** zerou: o card **fica** em Em Refinamento. Não comentar o handoff T1 (não postar segunda cópia do canônico). Não ir para Todo com furo bloqueante.
5. Se a fronteira **zerou** e o body tem as 6 seções: exatamente um comentário canônico (texto exato):

   `grill-card: fronteira vazia; história no body; à espera de T1 (Alan).`

   Idempotente: texto exato já no issue = deixar; texto canônico errado = editar/minimizar esse comentário; **não** postar segundo.

## Cliente: Cursor e Grok

O **pai** spawna este skill isolado (sem transcript) e só faz relaying das rodadas. Este filho escreve o body de N e **não** chama a ferramenta do host.

### Perguntas da rodada (host)

O filho **não** chama a ferramenta do host. Devolve dump D5: cada Q fechada com as N alternativas reais listadas (A/B/…, recomendada primeiro) + recomendação, para o pai mapear 1:1 em `options[]` na mesma ordem. Quem chama `AskUserQuestion` (Cursor) / `ask_user_question` (Grok) é o **pai**.

- **Q fechada** (alternativas mutuamente exclusivas reais): N≥2 em `options[]`. Recomendada primeiro, label com `(Recommended)`. A linha automática **Other não conta** no N e não substitui alternativa em falta. Proibido apresentar só 1 option. Com o host no ar, o prompt da Q é título + conflito; MUST NOT incluir a linha `➡️` nem `Recomendada:` + o texto da option. A recomendação é só a primeira option `(Recommended)`.
- **Q aberta** (texto livre): markdown e/ou Other; **não** inventar `options[]` fictícias.
- **Fallback Matt** (host indisponível): escolhas no **corpo** da Q fechada; `➡️` só a recomendação (não só a seta). Sem `options[]` do host, o `➡️` no corpo é o único sítio da recomendação.

## Cliente: dsh

Esta regra **não** vale para Cursor, Grok nem OpenCode.

O runtime root executa `grill-card` e o primitivo `grilling`, actualiza o issue N com `gh issue edit`, e pergunta as Qs fechadas neste turno. O runtime root chama `ask_user_question`. Qs fechadas: N≥2; recomendada primeiro, label com `(Recommended)`; Other automático não conta no N. O prompt de cada Q fechada é título + conflito. A recomendação vive só na primeira option com `(Recommended)`. Não copie `➡️` nem `Recomendada:` + o texto da option para o prompt.

Comentário canónico T1 só depois das respostas ou quando a fronteira for só-fato. Não postar cópia nova do canónico enquanto a rodada fechada estiver sem resposta.

## Proibido

- `gh project item-edit` no campo Status
- `process_event priorizar` (T1 é só Alan)
- Write `CONTEXT.md`
- `docs/adr/`
- `/opsx:new`, `/opsx:ff`, `/opsx:explore`, `/opsx:apply` (e qualquer `/opsx:*`)
- Dual-write para Hermes, `/srv/knowledge/hermes-second-brain/skills/`, `~/.codex/skills/`
