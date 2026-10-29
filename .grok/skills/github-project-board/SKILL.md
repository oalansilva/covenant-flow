---
name: github-project-board
description: "Operar GitHub Projects v2 a partir do contexto correto do workspace: detectar o board pela pasta atual e AGENTS.md, ou por URL explícita, antes de listar itens, localizar cards e ler campos/status; movimento de Status só por `process_event` (o agente não move nem adiciona)."
---

# github-project-board

Cliente: Grok Build. MUST Read `.cursor/skills/github-project-board/SKILL.md` and follow it as the runbook.
No Grok, `spawn_subagent` passa `model` da captura local do resolver para este cliente/faixa. Sem esforço não suportado, herança ou fallback. Do not copy the runbook here.
