---
name: github-project-board
description: "Operar GitHub Projects v2 a partir do contexto correto do workspace: detectar o board pela pasta atual e AGENTS.md, ou por URL explícita, antes de listar itens, localizar cards e ler campos/status; movimento de Status só por `process_event` (o agente não move nem adiciona)."
---

# github-project-board

Cliente: OpenCode. MUST Read `.cursor/skills/github-project-board/SKILL.md` and follow it as the runbook.
Resolver local: `scripts/process-fsm/model_selection.py` para este cliente/faixa; parâmetros nativos explícitos ou recusa visível.
Do not copy the runbook here. Use the skill tool.
