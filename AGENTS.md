# AGENTS.md — always-on curto

Board: (overlay `board.owner` / `board.number`)

Resolva `(q, bound_card, q_git)`; não invente aresta.
Texto livre é wording; comando exato capturado fora do agente é evento do Alan. NLU ≠ δ. `implemente` ∉ δ.
`Em Refinamento` é a entrada. Não pular Design / Aprovação de Design.
`Todo` não é código; próxima = `iniciar_design` via `process_event`.
Código / `/opsx:apply` só após `Status=Pronto para Dev` (T8).
Portões do Alan: T1, T2, T6, T7, T15, T18 (board ou comando exato). Agent não move Status: pede pelo `process_event`. T16 = `process_event fechar_release`.
Clientes: Cursor Agent (cooperativo); Codex CLI (cooperativo; hooks só após trust review); Grok Build, OpenCode e dsh (cooperativos até ensaio deny na branch de integração).
Não reivindique modo Auto no Cursor, no Codex, no Grok, no OpenCode nem no dsh.
Skills canônicas: `.cursor/skills/` neste repo. Overlay on-demand; runbook = skill `covenant-flow`.

Quando a tarefa precisar de portas/URLs, Drive, banco ou release/lote/PROD:

`Read` o path em overlay `overlay_doc` (`.covenant-flow/overlay.yaml`).

Fora desses tópicos, não carregue o overlay.
