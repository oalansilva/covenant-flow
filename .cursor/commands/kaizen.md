---
description: Kaizen — auditoria de melhoria contínua de processo e tech debt (board, Git, OpenSpec, CI, sessões Cursor). Uso: /kaizen, /kaizen card <id>, /kaizen release.
---

# Kaizen — Melhoria Contínua

Audita o processo de execução do projeto, detecta fricções (incluindo sessões Cursor onde o modelo se perde ou alucina) e cadastra melhorias como cards PO no board.

## Modos

| Comando | Uso |
| --- | --- |
| `/kaizen` | Auditoria completa (processo + tech debt + sessões recentes) |
| `/kaizen card <id>` | Mini-análise pós-card: sessões/CI/higiene daquele card |
| `/kaizen release` | Auditoria profunda pós-release (obrigatório no fechamento de lote) |

## Fluxo de execução

1. **Coletar evidências** com a skill `.cursor/skills/kaizen/SKILL.md` (read-only):
   - Board: `gh project item-list 1 --owner oalansilva --format json --limit 200`
   - Git: inventory + `scripts/release-guard audit`
   - OpenSpec: `openspec validate --all` e status das changes ativas
   - CI: checks recentes (falhas/cancelled, qa-gate, visual)
   - Sessões: transcripts Cursor do projeto (`agent-transcripts` da worktree Cursor). Não usar `opencode.db` como fonte ativa.
   - Tech debt (full/release): coverage, `pip-audit`/`npm audit`
2. **Consolidar relatório** em `docs/kaizen-log.md` (append-only).
3. **Registrar cards (PO)**: 1 issue por melhoria, `Status=Em Refinamento`, máximo 3 cards kaizen por release.
4. **Reportar** resumo gerencial curto.

## Regras

- Read-only na auditoria: não editar produto, não mutar Git/board/services.
- Issues públicas: métricas agregadas e IDs; trechos só em `docs/kaizen-log.md`.
- `/kaizen release` é obrigatório no fechamento de lote após deploy PROD validado.
