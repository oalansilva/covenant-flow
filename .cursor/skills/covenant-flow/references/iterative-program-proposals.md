# Iterative program/proposal docs for Alan

Use this reference when Alan is building a training plan, strategic proposal, curriculum, workshop, internal program, or similar artifact through iterative chat/voice brainstorming.

## Operating pattern

1. Treat the canonical Markdown in the Second Brain/GitHub as the source of truth.
2. After each meaningful refinement, update the document directly, validate the diff, commit, push, and report the commit hash.
3. Do not leave important changes only in chat. If the proposal needs to survive the session, write it to the repo.
4. When Alan says “atualize tudo no GitHub”, verify `git status -sb` and the latest commit before claiming it is updated.
5. If the repo is clean and already synced, report that evidence instead of creating a no-op commit.
6. Keep the final response concise: what changed, file path, commit hash, and any real caveat.

## Proposal structure that worked well

For applied AI/agility training plans, structure the document as:

- thesis and positioning;
- audience and role transition;
- learning objectives;
- macrothemes;
- external benchmark learnings;
- practical use cases;
- recommended cadence;
- theory/practice split;
- group challenge model;
- mentorship/padrinho model;
- detailed weekly plan;
- labs and challenge templates;
- final pitch/evaluation criteria.

## External benchmark incorporation

When Alan asks to review a course/site and see what to include:

1. Extract actual themes from the source.
2. Separate:
   - what the source says;
   - what makes sense to adapt;
   - what not to copy;
   - concrete changes to the proposal.
3. Add a dedicated “Aprendizados aproveitáveis de <fonte>” section instead of scattering vague notes.
4. Link the external source in the header or reference section.
5. Update the weekly plan and lab templates only when the benchmark changes the operating design, not for every keyword.
6. Keep the filter tight to the program context. For this session, the filter was **IA aplicada à agilidade**, not generic AI training.

## Useful curriculum concepts captured from this session

The following themes proved valuable for an AI-for-Agile-Masters curriculum:

- AI First applied to agility.
- Types of LLMs, input/output tokens, context window and multimodality.
- Horizontal vs vertical AI.
- Copilot in daily work and Copilot Studio/Power Automate/Microsoft Graph.
- RAG, embeddings, vector DB and Microsoft stack for corporate RAG.
- RAG vs fine tuning vs context engineering — teach why fine tuning is rarely the first step for internal knowledge.
- Prompt, Context, Harness and Loop Engineering.
- MCP, tools, function calling, APIs and A2A.
- Personal agents and agent operating systems.
- Vibe coding, Cursor, Codex, Claude Code, review/test/spec discipline.
- Spec-driven work, PREVC: Plan → Review → Execute → Validate → Confirm.
- Tool-agnostic AI engineering and fallback plan for tool changes/failures.
- Validation loop, drift, evals, tracing and anti-theater metrics.
- Second brain/team knowledge base before RAG.
- IA for UX/UI and DevOps as adjacent applied examples for Agile Masters in technical squads.
- Capstone/project-integrator framing: final group pitch should be a real operational artifact, not a theory recap.
- Group challenge model: for ~30 people, 6 groups of 5, 6 real challenges, 3 mentors/padrinhos, one agent/workflow/prototype per group.
- Alternating cadence: content week followed by mentorship week.
- Load recommendation for a 30-person applied cohort: **24h total** as the healthy recommendation — 12h content/direction + 12h practical mentoring. 18h is an executive minimum; 30h+ is appropriate if the expected output is an actual MVP.

## External benchmark mapping from this session

- **I2A2 Agentes Autônomos**: useful for progressive challenges, group project/capstone logic, LLM reasoning/validation, RAG, multimodal agents, benchmarks, multiagents, privacy and ethics. Do not copy the long academic structure wholesale.
- **Programe.ai**: useful for harness engineering, agentic programming, personal assistants, agent orchestration, second brain, vibe coding, automation, Claude Code/Codex/Agent Skills. Key lesson: maturity is the system around the tool — context, harness, automation, interface, review, safety and maintenance.
- **AI Coders Academy**: useful for “context is the new code”, tool-agnostic method, spec-driven work, PREVC, validation loop, context packaging/DOTCONTEXT, fallback plans and anti-theater metrics. Key lesson: do not make the program dependent on one tool brand.
- **UNIPDS Pós Engenharia de IA Aplicada**: useful for broadening to UX/UI, DevOps/SRE, architecture, data/fine tuning, security/governance and capstone framing. Do not copy the postgraduate depth; adapt only what strengthens IA + agilidade.
- **MIT Professional Education / Global Alumni IA Agêntica**: useful for executive adoption framing: strategic adoption roadmap, weekly miniprojects, sandbox/A-B tests, compliance documentation, crawl-walk-run maturity, centralized vs embedded agent architecture, pilot-to-practice risks, change management, performance monitoring and feedback loops. Adapt as operational adoption discipline for Agile Masters, not as generic executive AI strategy.
- **FIAP MBA AI Leadership: Strategy, Governance & Scale**: useful for executive scale framing: AI as growth infrastructure, Board Operating System for AI, business capabilities, operating models (CoE/hub-and-spoke/distributed squads), investment governance, build-buy-partner decisions, human-agent design, AI PRD/service blueprint, CRISP-DM adapted to GenAI, sourcing/third-party risk, process redesign with agents, ROI and cost-per-decision. Adapt to a light governance/product lens for Agile Masters; do not import MBA breadth.

## Pitfalls

- Do not over-index on tools. Alan valued the move from “tool training” to “method + context + spec + validation + governance”.
- Do not make it lecture-only. Convert theory into labs, field activities, group challenges and mentored delivery.
- Do not measure success by “used AI” or “tokens consumed”. Use value delivered, time saved, rework reduced, decision quality, and reliability of follow-up.
- Do not assume transcribed tool names are correct. Confirm or let Alan correct terms like OpenClaw/NemoClaw, then update the canonical doc.
- Do not treat every external course topic as a required module. First ask: does this help Agile Masters automate, govern, facilitate or improve squads?
- For 1h sessions, do not compress multiple dense technical themes into a single theory-heavy class. Alternate content and mentoria so groups apply between sessions.
