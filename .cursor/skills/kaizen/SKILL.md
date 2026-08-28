---
name: kaizen
description: Audita o processo (board, Git, OpenSpec, CI, sessões Cursor) e produz achados de melhoria contínua. Use with /kaizen, /kaizen card, or /kaizen release. Read-only.
---

# Kaizen

You are the Kaizen audit skill. Observe how the process is executed, find frictions, and produce evidence-backed findings. Never change product code, Git, PRs, board status, or services.

## Sources (read-only)

1. Board: overlay `board.owner` / `board.number` via `gh project view` / `item-list` (do not hardcode a Project).
2. Git: `git fetch --prune origin` then status, worktrees, stash, branches; `scripts/release-guard audit`.
3. OpenSpec: `openspec validate --all` and active changes under `openspec/changes/`.
4. CI: recent PR checks (`qa-gate`, visual, cancelled/failed).
5. Cursor sessions: read agent transcripts for this workspace. Canonical search order:
   - `$CURSOR_TRANSCRIPTS_DIR` if set
   - sibling `agent-transcripts` under the current Cursor project folder
   Correlate with cards via `#<id>` / `card-<id>` in titles or user messages.
   Do **not** query `~/.local/share/opencode/opencode.db` as an active source.
6. Tech debt when requested: coverage and audit reports.

If a source is missing, declare the limitation. Do not emit an empty audit as success.

## Signals

Invented path/URL, loop without progress, high cost/work without `Done`, eternal todos, generic titles on expensive card sessions, subagent spawn empty.

## Output

Use the Kaizen Audit Findings template (metrics, F-n findings with evidence, recommendations mapped 1:1 to proposed cards). Public issues get IDs and aggregates only.

## Closeout (orquestrador — fora desta skill)

A auditoria `/kaizen release` permanece **read-only**. Antes do `release-guard post`, o **orquestrador do closeout** MUST materializar no board até 3 issues `kaizen` em `Status=Em Refinamento` **ou** registrar na tabela `### Cards kaizen criados…` dedupe válido (`(não criado) … coberto por #N` com `#N` ainda em fluxo, não `Pronto`/`Cancelado`) **ou** o marcador `Sem achados acionáveis` (sem linhas de dados). O `post` valida isso (#661); heading sozinho não basta.
