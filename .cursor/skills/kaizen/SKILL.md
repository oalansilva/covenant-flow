---
name: kaizen
description: Audita o processo (board, Git, OpenSpec, CI, sessões Cursor) e produz achados de melhoria contínua. Use with /kaizen, /kaizen card, or /kaizen release. Read-only.
---

# Kaizen

You are the Kaizen audit skill. Observe how the process is executed, find frictions, and produce evidence-backed findings. Never change product code, Git, PRs, board status, or services.

## Sources (read-only)

1. Board: overlay `board.owner` / `board.number` (do not hardcode a Project).
   - `/kaizen card N`: Status pontual `repository.issue(number:N).projectItems`. MUST NOT `gh project item-list` to operate that card. GraphQL remaining=0 / RATE_LIMIT: falha na hora com reset; MUST NOT retry; MUST NOT wait for reset in the same command. REST remaining=5000 MUST NOT authorize GraphQL. Unknown Status MUST NOT mean the card is off the board.
   - `/kaizen` completo (board inteiro): MAY uma fotografia `item-list`, classe #509, sem retry.
2. Issue surface: REST `gh api repos/<owner>/<repo>/issues/<n>` e REST comments. MUST NOT `gh issue view` (com ou sem `--json`).
3. Git: `git fetch --prune origin` then status, worktrees, stash, branches; `scripts/release-guard audit`.
4. OpenSpec: `openspec validate --all` and active changes under `openspec/changes/`.
5. CI: recent PR checks (`qa-gate`, visual, cancelled/failed).
6. Cursor sessions: read agent transcripts for this workspace. Canonical search order:
   - `$CURSOR_TRANSCRIPTS_DIR` if set
   - sibling `agent-transcripts` under the current Cursor project folder
   Correlate with cards via `#<id>` / `card-<id>` in titles or user messages.
   Do **not** query `~/.local/share/opencode/opencode.db` as an active source.
7. Tech debt when requested: coverage and audit reports.

If a source is missing, declare the limitation. Do not emit an empty audit as success.

## Signals

Invented path/URL, loop without progress, high cost/work without `Done`, eternal todos, generic titles on expensive card sessions, subagent spawn empty.

## Output

Use the Kaizen Audit Findings template (metrics, F-n findings with evidence, recommendations mapped 1:1 to proposed cards). Public issues get IDs and aggregates only.

## Closeout (orquestrador — fora desta skill)

A auditoria `/kaizen release` permanece **read-only**. Antes do `release-guard post`, o **orquestrador do closeout** MUST materializar no board até 3 issues `kaizen` em `Status=Em Refinamento` **ou** registrar na tabela `### Cards kaizen criados…` dedupe válido (`(não criado) … coberto por #N` com `#N` ainda em fluxo, não `Pronto`/`Cancelado`) **ou** o marcador `Sem achados acionáveis` (sem linhas de dados). O `post` valida isso (#661); heading sozinho não basta.
