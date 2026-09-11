# Comandos GitHub Projects com alvo detectado por contexto

Nao use board fixo. Antes de rodar comandos, defina:

```bash
OWNER="<owner_detectado>"
PROJECT_NUMBER="<numero_detectado>"
```

Detecte o alvo pela URL informada pelo usuario ou pelo `AGENTS.md` mais proximo da pasta atual:

```bash
pwd
dir="$PWD"
while [ "$dir" != "/" ]; do
  f="$dir/AGENTS.md"
  test -f "$f" && printf '\n== %s ==\n' "$f" && rg -n "GitHub Project|Board operacional|projects/[0-9]+|gh project" "$f"
  dir="$(dirname "$dir")"
done
```

## Status de um card (pontual)

Status / ITEM_ID de issue N: query GraphQL pontual `repository.issue(number:N).projectItems`. MUST NOT `gh project item-list` to operate one card. GraphQL remaining=0: falha na hora com reset. Sem REST de coluna. MUST NOT `gh issue view`.

```bash
gh api graphql --include -f query='query($n:Int!){repository(owner:"OWNER",name:"REPO"){issue(number:$n){projectItems(first:20){nodes{id project{number owner{...on User{login}}} fieldValueByName(name:"Status"){...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}' -F n=N
```

Issue body/labels/comments: REST `gh api repos/<owner>/<repo>/issues/<n>` GET/PATCH, `gh issue edit`, REST comments. MUST NOT `gh issue view`.

## Comandos base

- `gh project view <N> --owner <owner>`: metadados do projeto.
- `gh project view <N> --owner <owner> --web`: abre o board no navegador.
- `gh project field-list <N> --owner <owner>`: lista campos (inclui Status e opções de coluna).
- `gh project item-list <N> --owner <owner> --format json`: fotografia completa do board (fecho de lote / `/kaizen` completo). MUST NOT para operar um card N.
- `gh project item-add <N> --owner <owner> --url <issue_or_pr_url>`: adiciona issue/PR.
- `gh project item-edit --id <item_id> --project-id <project_id> --field-id <field_id> --single-select-option-id <option_id>`: move status.
- `gh project item-edit --id <item_id> --project-id <project_id> --clear --field-id <field_id>`: limpa valor de campo.
- `gh project item-archive <N> --owner <owner> --id <item_id>`: arquiva item.

## Snippets úteis

### ITEM_ID / Status de um card N (pontual)

MUST NOT `gh project item-list` to operate one card.

```bash
gh api graphql --include -f query='query($n:Int!){repository(owner:"OWNER",name:"REPO"){issue(number:$n){projectItems(first:20){nodes{id project{number owner{...on User{login}}} fieldValueByName(name:"Status"){...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}' -F n="$ISSUE"
```

### Fotografia completa do board (não para um card)

```bash
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
  | jq -r '.items[] | "\(.id)\t\(.title)"'
```

### Mapear opções de Status

```bash
gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
  | jq -r '.[] | select(.name=="Status") | .options[] | "\(.id)\t\(.name)"'
```

### Mapear opções de Fluxo

Use quando o contrato local disser que `Fluxo` e o campo principal do workflow.

```bash
gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
  | jq -r '.[] | select(.name=="Fluxo") | .options[] | "\(.id)\t\(.name)"'
```

### Atualizar status de um item para "Done"

1. Descubra se o contrato local usa `Status`, `Fluxo` ou outro campo principal.
2. Descubra o `FIELD_ID` do campo correto e o `OPTION_ID` de `Done`.
3. Edite o item:

```bash
gh project item-edit \
  --id "ITEM_ID" \
  --project-id "PROJECT_ID" \
  --field-id "FIELD_ID" \
  --single-select-option-id "OPTION_ID"
```

## Pontos de falha comuns

- `requires project scope`: rodar `gh auth refresh -s project`.
- `HTTP 404` ao listar itens: projeto inacessível para o token atual.
- `item ID invalid`: IDs vêm da query pontual do card N; não use `item-list` para operar um card; não use número de issue/PR como substituto.

## Convenção de status do board

- Siga o `AGENTS.md` do repo atual.
- `Done` costuma significar tarefa concluida tecnicamente.
- Em Done o par humano e `homologar` → Homologado e `nao_homologar` → Em desenvolvimento (T18). Destino de T18 e Em desenvolvimento, nao Homologado.
- Arraste GitHub Done→Em desenvolvimento sem comentario `Não homologar:` + texto: restaurar Done e exigir o motivo. Nao inventar UI no board.
- `Homologado` exige validacao/aprovacao do Alan. Sem aresta inversa neste recorte.
- Nao descreva `Done` como card fechado/finalizado; use `Done tecnico` ou `aguardando homologacao`. Card fechado de verdade e `Pronto`.
- Nos projetos do Alan, `Status` e a fonte principal das colunas e do workflow quando existir. Se houver `Fluxo`, trate como substatus/legado e sincronize valores equivalentes quando aplicavel. Se nao houver equivalente, `Status` prevalece.
