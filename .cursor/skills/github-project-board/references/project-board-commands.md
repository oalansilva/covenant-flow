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

## Comandos base

- `gh project view <N> --owner <owner>`: metadados do projeto.
- `gh project view <N> --owner <owner> --web`: abre o board no navegador.
- `gh project field-list <N> --owner <owner>`: lista campos (inclui Status e opções de coluna).
- `gh project item-list <N> --owner <owner> --format json`: lista itens em JSON.
- `gh project item-add <N> --owner <owner> --url <issue_or_pr_url>`: adiciona issue/PR.
- `gh project item-edit --id <item_id> --project-id <project_id> --field-id <field_id> --single-select-option-id <option_id>`: move status.
- `gh project item-edit --id <item_id> --project-id <project_id> --clear --field-id <field_id>`: limpa valor de campo.
- `gh project item-archive <N> --owner <owner> --id <item_id>`: arquiva item.

## Snippets úteis

### Mapear Item ID / titulo

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
- `item ID invalid`: IDs vêm no JSON de `item-list`; não use número de issue/PR como substituto.

## Convenção de status do board

- Siga o `AGENTS.md` do repo atual.
- `Done` costuma significar tarefa concluida tecnicamente.
- `Homologado` exige validacao/aprovacao do Alan.
- Nao descreva `Done` como card fechado/finalizado; use `Done tecnico` ou `aguardando homologacao`. Card fechado de verdade e `Pronto`.
- Nos projetos do Alan, `Status` e a fonte principal das colunas e do workflow quando existir. Se houver `Fluxo`, trate como substatus/legado e sincronize valores equivalentes quando aplicavel. Se nao houver equivalente, `Status` prevalece.
