---
name: github-project-board
description: "Operar GitHub Projects v2 a partir do contexto correto do workspace: detectar o board pela pasta atual e AGENTS.md, ou por URL explícita, antes de listar itens, localizar cards e ler campos/status; movimento de Status só por `process_event` (o agente não move nem adiciona)."
---

# GitHub Project Board

Use esta skill quando o usuario pedir para consultar, filtrar ou atualizar itens de um GitHub Project.

## Regra principal

Nunca assuma um projeto fixo.

Antes de operar o board, descubra o alvo nesta ordem:

1. Se o usuario forneceu URL de project, use essa URL.
2. Senao, detecte pela pasta atual lendo `AGENTS.md` do diretorio atual e dos ancestrais ate a raiz do workspace.
3. Se houver contrato local com "GitHub Project", "Board operacional", `github.com/users/<owner>/projects/<numero>` ou comandos `gh project ... --owner ...`, use esse owner/numero.
4. Se a pasta atual nao tiver contrato especifico, use o `AGENTS.md` ancestral mais proximo que declare um projeto.
5. Se ainda nao houver alvo claro, pergunte qual board usar antes de editar. Para leitura simples, voce pode listar candidatos encontrados e pedir confirmacao.

Exemplos (pwd → board):

- O board vem do overlay `board.owner` / `board.number` e do `AGENTS.md` local (URL `github.com/users/<owner>/projects/<number>`).
- Noutro clone, o board vem do `AGENTS.md` / overlay daquela árvore. Não use um Project hardcoded neste ficheiro.

Comando util para descobrir contratos a partir da pasta atual:

```bash
pwd
dir="$PWD"
while [ "$dir" != "/" ]; do
  f="$dir/AGENTS.md"
  test -f "$f" && printf '\n== %s ==\n' "$f" && rg -n "GitHub Project|Board operacional|projects/[0-9]+|gh project" "$f"
  dir="$(dirname "$dir")"
done
```

## Convenção de status (este projeto)

- O campo `Status` e a fonte principal das colunas visuais.
- No **Project 1 / Cripto**, o caminho obrigatório e `Em Refinamento -> Todo -> Design -> Aprovação de Design -> Pronto para Dev -> Em desenvolvimento -> Code Review -> QA -> Done -> Homologado -> Pronto`. **Nao existe bypass** dessas colunas; `UI impact: none` e pedidos `implemente` nao autorizam pular. Portões do Alan (só Alan, no board ou por comando exato capturado fora do agente; ver skill `covenant-flow`, "Comandos de portão"): T1 `Em Refinamento -> Todo`, T2 cancelar, T6 `Aprovação de Design -> Design`, T7 `Aprovação de Design -> Pronto para Dev` e, em Done, o par `homologar` (`Done -> Homologado`, T15) / `nao_homologar` (`Done -> Em desenvolvimento`, T18). Homologado nao tem aresta inversa. Homologado -> Pronto e `process_event fechar_release` (T16). `Todo` nao e codigo. Arraste Done→Em desenvolvimento sem comentário `Não homologar:` + texto e fora-de-δ: o agente nao restaura o Status; comenta pedindo o motivo e nao segue o Apply ate o comentario existir; nao inventar UI no board.
- `Em Refinamento` e a entrada de todo card novo **e** a grelha da história (`grill-card` no body do issue). Alan escolhe/prioriza/cancela. O agente **nao** move Status nem adiciona item no Project: pede pelo `process_event` (o executor do board move; `process_event criar_card --card N` poe no board uma issue que ja existe). Sem `CONTEXT.md`.
- `Done` e fechamento tecnico; fechamento final e `Pronto` (exige deploy PROD no cripto).
- `Cancelado` e terminal, inclusive a partir de `Em Refinamento`.
- Se o Project tiver campo `Fluxo`, trate-o como substatus/legado. `Status` prevalece.
- Nao misture cards entre boards de repos diferentes.

## Superfície issue (REST)

Body, comentários e labels: `gh api repos/<owner>/<repo>/issues/<n>` GET/PATCH (ou `gh issue edit`). MUST NOT `gh issue view`.

## Status de um card (pontual)

Status / item id de **um** card N: query GraphQL pontual `repository.issue(number:N).projectItems` (a mesma família de `github_status_provider` / `_item_id_for_issue`). MUST NOT `gh project item-list` to operate one card. GraphQL remaining=0 ou `errors[].type=RATE_LIMIT` (HTTP 200 inclusive): falha na hora com o reset dos cabeçalhos. MUST NOT esperar o reset no mesmo comando. MUST NOT retry. MUST NOT inventar REST de coluna do Project. REST `GET /rate_limit` remaining=5000 MUST NOT autorizar GraphQL.

```bash
gh api graphql --include -f query='query($n:Int!){repository(owner:"OWNER",name:"REPO"){issue(number:$n){projectItems(first:20){nodes{id project{number owner{...on User{login}}} fieldValueByName(name:"Status"){...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}' -F n=N
```

Fotografia completa do board (`gh project item-list`) fica só para o fecho de lote (#509, uma por run) e `/kaizen` completo — não para operar um card.

## Quick start

1. Defina o alvo do board a partir do contexto:

```bash
OWNER="<owner_detectado>"
PROJECT_NUMBER="<numero_detectado>"
```

2. Valide autenticação e escopo do GitHub CLI:

```bash
gh auth status
```

Se faltar o escopo `project`, rode:

```bash
gh auth refresh -s project
```

3. Verifique o projeto:

```bash
gh project view "$PROJECT_NUMBER" --owner "$OWNER"
```

4. Liste campos antes de editar. Nao presuma que todo board usa apenas `Status`:

```bash
gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json
```

## Operações principais

- Abrir o board no navegador:

```bash
gh project view "$PROJECT_NUMBER" --owner "$OWNER" --web
```

- Listar campos do projeto:

```bash
gh project field-list "$PROJECT_NUMBER" --owner "$OWNER"
```

- Listar itens (fotografia completa do board; MUST NOT para operar um card N):

```bash
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --limit 200
```

- Status ou ITEM_ID de **um** card: query pontual acima. MUST NOT `gh project item-list` to operate one card.

- Filtrar o board inteiro por título (não é o caminho para um card N):

```bash
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
  | jq -r '.items[] | select(.title | test("termo"; "i")) | "\(.id)\t\(.title)"'
```

- Adicionar issue ao projeto ou mudar Status: **o agente nao move nem adiciona.** Pede pelo `process_event` (`process_event <evento> --card N` para as transições do agente; `process_event criar_card --card N` para pôr no board, em Em Refinamento, uma issue que ja existe). Quem escreve no Project e o executor do board, que confere a FSM; os portões do Alan sao do Alan (board ou comando exato). A Guard nega `item-edit`/GraphQL de Status e o disparo direto do executor.
- Arquivar item ou qualquer outra escrita no Project: e do Alan, no navegador.

## Observações

- A parte `views/1?layout=board` é apenas visual. Use sempre `owner + number` como identificadores principais.
- Em worktrees do consumidor, o `AGENTS.md` da árvore declara o board (gerado do overlay).
- Se houver erro de permissão, confirme que a conta atual tem acesso ao board e use `--owner` correto.

## Referência rápida

- [project-board-commands.md](references/project-board-commands.md): mapa de comandos, campos e filtros úteis em JSON.
