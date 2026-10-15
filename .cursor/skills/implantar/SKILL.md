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

Exige overlay já válido (join `board.status_options` nome→id; globs e board preenchidos) sem exigir mapa legado ou configuração operacional local existente.

```bash
/path/to/covenant-flow/install.sh --pin v1.1.4
```

Copia o nucleus e quatro adapters existentes (`.cursor/` `.grok/` `.opencode/` `.dsh/`), o quinto adapter local `.codex/`, `.agents/skills/` (pontes para canônicos, Impeccable e playwright-cli apenas se ainda ausentes), helpers (`publish-openspec-card-artifacts.sh`, `release-guard` genérico, `dsh_boot.sh`) e `AGENTS.md` gerado do overlay. Copia `.dsh/` **sempre**, mesmo quando o overlay omite `clients.dsh`. Instala `.cursor/model-policy.yaml` e o resolver/adapters; não lê/escreve escolhas operacionais nem injeta pares. Grava `pin` no overlay. **Não** injeta `clients.dsh`. **Não** sobrescreve o Markdown `overlay_doc`.

Bump: re-correr `--pin` com a tag nova; preserva chaves de projeto; o consumidor commita o diff.

### Canal de conta (só o registro dos hooks)

"Copiar e commitar" vale para tudo **exceto** o registro dos hooks de Claude Code, Cursor, Codex e OpenCode: a partir do pin com registro na conta, `--pin` **não grava** esse registro no consumidor, remove dos registros de projeto só as entradas do Covenant Flow (preservando as alheias; JSON inválido ou conflito recusa sem escrita parcial), move os plugins do adapter OpenCode para `.opencode/adapter/` (fora do auto-load) e grava o manifesto `.covenant-flow/adapters.json` (registro por cliente, protocolo do shim, pontos de entrada e arquivos com digest). Os registros de Grok Build (`.grok/hooks/process-fsm.json`) e dsh (`.dsh/cordis.patch.yml`, `dsh_boot.sh`) continuam copiados como antes. O registro vai para a conta do operador por outro comando, que não carrega FSM, adapters, skills nem política:

```bash
/path/to/covenant-flow/install.sh --account [--check|--remove]
python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record   # operador, depois de ler registro e adapter
```

Sem o shim instalado, uma sessão num consumidor com o pin novo fica sem hooks e o `process_event` recusa `hooks_inactive` (ver skill `covenant-flow`, "Registro dos hooks na conta"). Pin e `--account` nunca gravam confiança.

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
handlers alheios, remover somente handlers do Covenant Flow e recusar JSON
inválido ou conflito sem modificar o destino. (Um `[hooks]` em
`.codex/config.toml` já não é conflito do pin, que não escreve registro; o
instalador de conta recusa esse caso.) Mostrar o caminho de cada recusa e não
deixar outros arquivos do pin parcialmente escritos.

`install.sh --pin` faz preflight read-only de mecanismos/política e hooks/roles/bridges antes de copiar; não exige mapa legado nem lê/escreve `$HOME/.config/covenant-flow/model-selection.yaml`. Instala política/resolver/adapters e pacote Codex, nunca escolhas. Flags antigas de codex_models.py são compatibilidade sem leitura/escrita. Pin comunica que o operador revisa registro e adapter (`cf_shim.py trust --record`) e não concede confiança. Migração explícita e rollback: `docs/model-selection.md`.

O installer é entregue no nucleus; o consumidor não precisa copiá-lo para operar. Task3.4 foi implementada e ensaiada no worktree nucleus do mesmo #1080: seis testes reais de installer, incluindo resolver/hook funcional no destino pinado. Nenhuma escolha operacional é default de pin.

## Fail-closed

`--pin` recusa overlay ausente, vazio ou inválido (nome ≠ 12 colunas do yaml, id em falta). Não deixa peles a meio como caminho feliz.
