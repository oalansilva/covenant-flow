---
name: qa-dev
description: "Contrato do filho qa-dev: testa um bloco de critérios do card no DEV, logado, num navegador headless no servidor, e grava o resultado por critério. Use só como filho do teste no DEV, com o plano de `qa_dev.py plan` no prompt, quando `qa_dev` existe no overlay. Não é o qa-gate, não muda Status e não homologa."
---

# qa-dev

Cliente: dsh. MUST Read `.cursor/skills/qa-dev/SKILL.md` and follow it as the runbook.
Resolver local: `scripts/process-fsm/model_selection.py` para este cliente/faixa; parâmetros nativos explícitos ou recusa visível.
Do not copy the runbook here.
