---
name: github-project-board
description: "Operar GitHub Projects v2 a partir do contexto correto do workspace: detectar o board pela pasta atual e AGENTS.md, ou por URL explícita, antes de listar itens, localizar cards, adicionar issues/PRs e atualizar campos/status."
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
- No **Project 1 / Cripto**, o caminho obrigatório e `Em Refinamento -> Todo -> Design -> Aprovação de Design -> Pronto para Dev -> Em desenvolvimento -> Code Review -> QA -> Done -> Homologado -> Pronto`. **Nao existe bypass** dessas colunas; `UI impact: none` e pedidos `implemente` nao autorizam pular. So Alan move `Aprovação de Design -> Pronto para Dev` e `Done -> Homologado`. Homologado -> Pronto e `process_event fechar_release` (T16). `Todo` nao e codigo.
- `Em Refinamento` e a entrada de todo card novo **e** a grelha da história (`grill-card` no body do issue). Alan escolhe/prioriza/cancela. O agente **nao** arrasta T1 (`Em Refinamento -> Todo`). Sem `CONTEXT.md`.
- `Done` e fechamento tecnico; fechamento final e `Pronto` (exige deploy PROD no cripto).
- `Cancelado` e terminal, inclusive a partir de `Em Refinamento`.
- Se o Project tiver campo `Fluxo`, trate-o como substatus/legado. `Status` prevalece.
- Nao misture cards entre boards de repos diferentes.

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

- Listar itens:

```bash
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --limit 200
```

- Filtrar itens por título no JSON:

```bash
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
  | jq -r '.items[] | select(.title | test("termo"; "i")) | "\(.id)\t\(.title)"'
```

- Adicionar issue/PR ao projeto:

```bash
gh project item-add "$PROJECT_NUMBER" --owner "$OWNER" --url "https://github.com/<owner>/<repo>/issues/<n>"
```

- Atualizar campo (ex.: Status):

1. Descubra IDs do projeto e do campo:

```bash
gh project view "$PROJECT_NUMBER" --owner "$OWNER" --format json
gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json
```

2. Edite o item:

```bash
gh project item-edit \
  --id "<ITEM_ID>" \
  --project-id "<PROJECT_ID>" \
  --field-id "<FIELD_ID>" \
  --single-select-option-id "<OPTION_ID>"
```

- Arquivar item:

```bash
gh project item-archive "$PROJECT_NUMBER" --owner "$OWNER" --id "<ITEM_ID>"
```

## Observações

- A parte `views/1?layout=board` é apenas visual. Use sempre `owner + number` como identificadores principais.
- Em worktrees do consumidor, o `AGENTS.md` da árvore declara o board (gerado do overlay).
- Se houver erro de permissão, confirme que a conta atual tem acesso ao board e use `--owner` correto.

## Referência rápida

- [project-board-commands.md](references/project-board-commands.md): mapa de comandos, campos e filtros úteis em JSON.
