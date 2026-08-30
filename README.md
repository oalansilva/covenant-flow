# Covenant Flow — processo portátil de 12 colunas (núcleo + adapters)

## O que é

Covenant Flow é o processo de 12 colunas que viaja com o git do consumidor. Sem este produto, cada repositório reimplementa o fluxo e diverge.

Quem usa: Alan e os agentes nos quatro clientes (Cursor, Grok, OpenCode e dsh).

Três papéis:

- **Núcleo** — o repositório `oalansilva/covenant-flow`: peles (FSM, adapters, skills, helpers). Este repo **não** tem overlay.
- **Consumidor** — o git do projeto (primeiro consumidor: Cripto, `oalansilva/crypto`) que recebe as peles e as **commita**.
- **Overlay** — chaves do consumidor (board, globs, ambientes, `clients.*`) em `.covenant-flow/overlay.yaml`; o Markdown humano fica no path `overlay_doc`.

Canal v1 = copiar as peles para o consumidor e **commitar**. Não é submodule, marketplace nem template-clone.

## Clientes

Quatro clientes, por nome: **Cursor**, **Grok**, **OpenCode** e **dsh**. Os quatro são cooperativos.

- **Cooperativo** — Cursor por contrato; Grok, OpenCode e dsh até ensaio deny PASS na branch de integração. Overlay `clients.*.auto` é claim de máquina e **não** conduz o stub `AGENTS.md`.
- **Auto** — **não** autoriza cruzar colunas: o agente não arrasta o card. MUST NOT reivindicar Auto em Grok, OpenCode ou dsh.

## As 12 colunas

- **Em Refinamento** — entrada do card e afiação da história; Alan escolhe, prioriza ou cancela.
- **Todo** — backlog com história afiada; não é código; a próxima coluna é Design.
- **Design** — síntese OpenSpec do issue grelhado e crítica; Gist no card; protótipo se houver UI.
- **Aprovação de Design** — espera decisão de Alan sobre o design.
- **Pronto para Dev** — design aprovado; único status que libera `/opsx:apply`.
- **Em desenvolvimento** — implementação no worktree do card.
- **Code Review** — diff pronto; review antes do commit.
- **QA** — SHA revisado nos checks.
- **Done** — done técnico em `develop`.
- **Homologado** — Alan aprovou em `develop`.
- **Pronto** — publicado em `main` e deploy PROD validado.
- **Cancelado** — não será feito (coluna terminal).

Alan prioriza Em Refinamento→Todo; só Alan Aprovação de Design→Pronto para Dev; Alan homologa Done→Homologado.

O runbook do operador é a skill `covenant-flow` no consumidor pinado.

## Install

No produto:

```bash
git clone git@github.com:oalansilva/covenant-flow.git
cd covenant-flow
```

No repositório **consumidor**:

```bash
/path/to/covenant-flow/install.sh --init --target /path/to/consumer
# preencha .covenant-flow/overlay.yaml (board, globs, ambientes, overlay_doc)
/path/to/covenant-flow/install.sh --pin v1.1.6 --target /path/to/consumer
```

`--init` escreve as chaves obrigatórias **vazias** e não chuta valores do projeto.
`--pin` copia núcleo, adapters (`.cursor/` `.grok/` `.opencode/` `.dsh/`), `.agents/skills/` (impeccable, design-critic, playwright-cli), helpers e um `AGENTS.md` gerado. Copia `.dsh/` mesmo quando o overlay omite `clients.dsh`. Recusa overlay vazio ou inválido. O consumidor **commita** essas árvores. Não sobrescreve o Markdown em `overlay_doc`.

v1 **não** instala via git submodule, ponteiros gitignore, marketplace nem template-clone.

## Pin

O campo `pin` do overlay é uma tag semver `vMAJOR.MINOR.PATCH`. Mudança que quebra o schema do overlay é tag major (`v2.0.0`). Bump = voltar a correr `--pin` com a tag nova e commitar o diff; as chaves de projeto mantêm-se.

Exemplo deste entregável: `--pin v1.1.6`.

## Layout

- Núcleo: `.cursor/process-fsm.yaml`, `scripts/process-fsm/`
- Adapters: `.cursor/`, `.grok/`, `.opencode/`, `.dsh/`
- Overlay máquina (consumidor): `.covenant-flow/overlay.yaml`
- Overlay humano: path em `overlay_doc`
- Skills: `covenant-flow`, `covenant-flow-environments`, `implantar`, mais OpenSpec, grill, board, kaizen, design-critic, impeccable, playwright-cli
