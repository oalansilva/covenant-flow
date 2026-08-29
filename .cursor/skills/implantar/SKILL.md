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

Exige overlay já válido (join `board.status_options` nome→id; globs e board preenchidos).

```bash
/path/to/covenant-flow/install.sh --pin v1.1.1
```

Copia: nucleus (`.cursor/process-fsm.yaml`, `scripts/process-fsm/`), quatro adapters (`.cursor/` `.grok/` `.opencode/` `.dsh/`), `.agents/skills/` (`impeccable`, `design-critic`, `playwright-cli`), helpers (`publish-openspec-card-artifacts.sh`, `release-guard` genérico, `dsh_boot.sh`), `AGENTS.md` gerado do overlay. Copia `.dsh/` **sempre**, mesmo quando o overlay omite `clients.dsh`. Grava `pin` no overlay. **Não** injeta `clients.dsh`. **Não** sobrescreve o Markdown `overlay_doc`.

Bump: re-correr `--pin` com a tag nova; preserva chaves de projeto; o consumidor commita o diff.

## Fail-closed

`--pin` recusa overlay ausente, vazio ou inválido (nome ≠ 12 colunas do yaml, id em falta). Não deixa peles a meio como caminho feliz.
