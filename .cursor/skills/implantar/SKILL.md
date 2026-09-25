---
name: implantar
description: "Implantar Covenant Flow num repositório consumidor: --init (overlay vazio) e --pin <tag> (copia nucleus, adapters, helpers). Canal v1 = copiar e commitar; recusa submodule, gitignore, marketplace e template-clone."
---

# implantar

Cliente: Cursor Agent / Grok Build / OpenCode / dsh. Canónico: `.cursor/skills/implantar/` neste produto.

Prioridade: δ e Guard > overlay > esta skill > wording.

## Canal v1

Copiar peles para o consumidor e **commitar** no git do consumidor. Recusar:

- git submodule como canal
- gitignore das peles como método de install
- marketplace nativo Cursor/OpenCode
- template-clone como primário (não atualiza por pin)

## --init

No repo alvo (cwd ou `--target`):

```bash
/path/to/covenant-flow/install.sh --init
```

Cria `.covenant-flow/overlay.yaml` a partir do template com as chaves obrigatórias **presentes e vazias**. Lista as chaves ainda vazias. **Não** chuta board ids, globs ou environments de nenhum consumidor.

Preencha o overlay **antes** de `--pin`. Overlay vazio a meio **não** é sucesso.

## --pin

Exige overlay já válido (join `board.status_options` nome→id; globs e board preenchidos) e `.cursor/model-map.yaml` existente no destino.

```bash
/path/to/covenant-flow/install.sh --pin v1.1.4
```

Copia o nucleus e quatro adapters existentes (`.cursor/` `.grok/` `.opencode/` `.dsh/`), o quinto adapter local `.codex/`, `.agents/skills/` (pontes para canônicos, Impeccable e playwright-cli apenas se ainda ausentes), helpers (`publish-openspec-card-artifacts.sh`, `release-guard` genérico, `dsh_boot.sh`) e `AGENTS.md` gerado do overlay. Copia `.dsh/` **sempre**, mesmo quando o overlay omite `clients.dsh`. Adiciona os pares Codex ao mapa único no destino; preserva bytes dos campos Cursor e de `forbid`. Grava `pin` no overlay. **Não** injeta `clients.dsh`. **Não** sobrescreve o Markdown `overlay_doc`.

Bump: re-correr `--pin` com a tag nova; preserva chaves de projeto; o consumidor commita o diff.

### Inventário de descoberta Codex

O instalador de pin copia o adapter local para `.codex/` e as pontes de skills
para `.agents/skills/`. Nesta árvore, `.agents/skills/` já contém `impeccable`
do fornecedor, `design-critic` (que deve apontar ao canônico em
`.cursor/skills/design-critic/`) e `playwright-cli` (skill existente, sem
equivalente canônico em `.cursor/skills/`). O inventário canônico vem de cada
`.cursor/skills/<nome>/SKILL.md`; o pin gera pontes para esses nomes sem copiar
os runbooks.

No destino, um `.agents/skills/impeccable/` existente é propriedade do
fornecedor e deve permanecer byte a byte intacto. Um `.codex/hooks.json`
existente pode conter hooks locais do operador: preservar todas as chaves e
handlers alheios, mesclar somente handlers do Covenant Flow e recusar JSON
inválido ou conflito sem modificar o destino. Um `.codex/config.toml` com
`[hooks]` também é uma fonte ativa de hooks; o pin deve detectá-lo e recusar a
instalação automática até a composição ficar explícita. Mostrar o caminho de
cada recusa e não deixar outros arquivos do pin parcialmente escritos.

`install.sh --pin` faz primeiro preflight read-only de `.codex/hooks.json`,
`.codex/config.toml`, roles em `.codex/agents/`, pontes de `.agents/skills/` e
`.cursor/model-map.yaml`. Somente após todos passarem copia peles; depois mescla
hooks, adiciona roles/bridges sem remover skills alheias e estende o mapa no
destino. Map ausente ou um par Codex já divergente da especificação exige
reconciliação explícita. Repetir o pin deve ser idempotente.

## Fail-closed

`--pin` recusa overlay ausente, vazio ou inválido (nome ≠ 12 colunas do yaml, id em falta). Não deixa peles a meio como caminho feliz.
