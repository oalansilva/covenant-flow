# Reconciliação do diagnóstico dedicado — 18/10/2026

O pai executou o ciclo real bootstrap → contexto → probes → qualificação da rota, com principal TUI gravável e coordenador exec read-only, sem alternância manual de permissões. Este Apply inspecionou somente receipts/qualificações sanitizados; não abriu sessões, não refez o ensaio, não leu marcadores/prompts dos traces e não realizou revisão de produto ou QA. Resultados dos comandos vivos foram informados pelo pai e corroborados pelos artefatos sanitizados persistidos.

## Escopo e procedência

- Card/worktree: #1098, `card-1098-codex-agentes-nativos`.
- Principal: `codex-tui`, thread `01a14a14-8ad0-78b2-8278-c14aec2b4bf8`.
- Coordenador: `codex_exec/0.163.0`, thread `01a14c6d-8e42-79d3-bd0e-db78be7c3aca`.
- Adapter integrado e revisado por Alan, informado pelo pai: `0d57a079ced29582fe4df656e05a718451af01ddd39d527524864e3eb78be669`.
- Design aprovado preservado: SHA-256 `685305bec5e7664246b6304cfb9b24ee0f930ab53db45a7c171fc4124677d9b3`.
- `internal_context_attestation=unavailable`; sem atestação interna completa ou suporte universal.

Paths privados abaixo são relativos a `.cursor/tmp/codex-evidence/`. Digests de integridade são os selos dos envelopes, não SHA-256 bruto dos arquivos. Fontes nativas e hashes permanecem referenciados pelos envelopes originais, sem reescrita.

| Fase | Artefato sanitizado | Resultado e limite |
| --- | --- | --- |
| Bootstrap | `dedicated-bootstrap-14a3b73dc84ce61043d5823a.package.json` | Lançamento exit0 e binding PASS. Selo do pacote `fde540ef51e335b68ad0781f97168def62120b73e1860ed9ba5f38bf8453193e`. |
| Recusa anterior ao probe | `refusal_source` na qualificação de rota | `route-check`: exit1, `review_route_unqualified`; origem nativa do principal ordinal4524, hash `1eaf62230ba3277c5e601224a7e1f0009d17b11846fb7e9e63a1991a00fefd31`. Não é recusa de outra superfície. |
| Contexto próprio | `dedicated-context-1590e5187b731d46646cbe32.package.json`; `context-qualification-e5fef58078181ab0-3029674d-411d-4468-9cd5-7933914440f4.json` | `codex_context qualify` PASS; contrato/binário, chamada real `fork_turns=none`, ensaio complementar `passed`. Birth `3029674d-411d-4468-9cd5-7933914440f4`; child `01a14c6e-1cc2-7af2-bfa8-3dddcba9723d`. Integridade `015cda677284e0d05829a41d6f53db3b4b9e2de0ab247976c76fcca321075434`, escopo `c331646a3c61969e68be843f9ff0b10c65a85987f73b7e79e97337e23b033826`. Sem cópia da qualificação TUI. |
| Probe dedicado | `dedicated-probe-27277be14d3f503c4e8fad16.package.json` | Selo do pacote `1dce3f030712cdef6849fae20a91986275cd371a726258f4cce0a36f74b63bcd`; ambos perfis nomeados, filhos distintos no mesmo turno do coordenador. |
| Perfis/probes | `review-probe-qualification-df3836865a3bed4c656b2d9492c70859b2df9ee1303d92c284bc9703d27fa8a6.json` | `codex_review_probe qualify` PASS no coordenador exec observado. |
| Rota TUI → exec | `dedicated-route-3a8f19dc25fb945216b47c306c7172a809ba9344e6c5bb976cf903b4a9036886.json` | `qualify-route` PASS; integridade `3a8f19dc25fb945216b47c306c7172a809ba9344e6c5bb976cf903b4a9036886`; cadeia de lançamento/retorno, contexto próprio, dois perfis/probes e continuidade somente leitura. Não qualifica principal exec/App/IDE ou outra sessão coordenadora. |

## Dois reviewers diagnósticos

| Papel nativo | Evidência | Child ID | Integridade do envelope |
| --- | --- | --- | --- |
| `diff-reviewer` | `6852663f-12a4-4d5c-9fc9-7750c921f963.evidence.json` | `01a14c6e-cdfd-7130-95b1-98a4cbaad574` | `8281c5765e97e75fbe7a8e5e1907efa4dfd90e1423e48dff76b664b9be275a6c` |
| `code-reviewer` | `f07c1233-796b-4483-8722-873f7c17b51d.evidence.json` | `01a14c6e-e72b-7d91-86b2-559222325548` | `650389c2de8769da38ca026b273d061f164166e6d7d4e9f74d60e771f325d310` |

Ambos envelopes: `validation=verified`, `status=completed`, `payload_returned=true`, `qualification=true`; argumentos nativos `gpt-6.1-sol/high`, `fork_turns=none`, papel nomeado correto. Observações `diff_read` e `write_denial_readback`: `verified`. Mesmo arquivo diagnóstico `.cursor/tmp/card-1098-readonly-diagnostic.patch`, SHA-256 `6dc533221f012f63bfb4f10befe58aee343efaeefb5fb7a95fd21e9851466383`. Não é o intervalo de produto a revisar. Probes descartáveis não concedem escrita em produto.

## Tasks e limites dos aceites

Concluídas nesta reconciliação: **3.2, 6.1, 6.2**. Implementação integrada/ensaiada cobre coleta/permissões/probes, envelopes pendentes/cadeia autoritativa e ambos perfis nomeados. Negativos são testes de contrato registrados nas entregas de [automação](apply-automatic-review-20261017.md), [settings](coordinator-settings-fix-20261017.md) e [retomada](coordinator-resume-fix-20261018.md), não negativos vivos de todas as superfícies. Última regressão candidata registrada: 288 testes PASS; não reexecutada nesta reconciliação documental.

Progresso real: **23/35**, com 12 pendentes:

- **3.3 e 5.4:** automação implementada e rota diagnóstica qualificada; falta onda de produto sobre diff final, dois pareceres, coleta/proxies, `verify-wave` e checklist. A fase `review` exige Status=Code Review. 3.3 conserva seu checkbox pendente; nenhuma anotação de fase foi acrescentada retroativamente.
- **4.5 e 6.4:** integração local/testes/trust pertinentes informados pelo pai, docs atualizadas; distribuição canônica do novo delta nucleus → consumidor continua incompleta. Recusa anterior `target_outside_binding` não contornada. Integração 4.4 e manifesto local não provam essa distribuição nova.
- **6.3:** TUI → coordenador exec comprovada neste diagnóstico; principal exec → exec e App/IDE → exec não ensaiados. Não generalizar.
- **5.1:** lifecycle/contexto reais parciais existem; falta ensaio completo de lista/estado/inspeção/interação/retorno do operador no mesmo chat.
- **5.2:** existe recusa real de rota não qualificada; não substitui toda a demonstração de limitação do host e seus estados exigida no aceite.
- **5.3:** fixtures Guard e deny/readback de sandbox não substituem ensaio Guard vivo de autorização por card/etapa e denies com readback.
- **5.5 e 5.6:** matriz integral e refinamento interativo autorizado do início ao retorno sem os aceites completos.
- **5.7:** novo positivo exec diagnóstico existe; conjunto de recusas reais de evidência/vínculo/modelo/esforço/contexto ainda incompleto.
- **5.8:** App/IDE sem sessão/origem autoritativa reais; documentação de schema/limitação não conclui positivo.

## Gates para o pai

A capacidade de rota antes ausente está qualificada no escopo acima. Depois de fechar este diff documental, o pai pode preparar `codex_review_session.py prepare --phase review --bootstrap <bootstrap-acima> --diff <diff-final-exato>`, sem iniciar trabalho de review. `principal_preflight` exige esse pacote novo do principal correto, seleção vigente, Status/binding vivos e revalidação de rota/contexto/probes. Só o pai conduz `pedir_review`; este Apply não executou o evento nem seu dry-run e não afirma T9 PASS. I4/digest, hooks/trust e demais gates continuam vigentes.

Bloqueio concreto remanescente do fechamento do Apply: 4.5/6.4 exigem distribuição fora do binding atual já recusada; nenhuma ação documental a completa. Há dependência de fase em 3.3, que inclui retornos de review de produto. O checklist canônico precommit rejeita `tasks.md pending` para 3.3/4.5/6.3/6.4 sem fase explícita, mesmo que a capacidade de `pedir_review` passe. É bloqueio de checklist/commit, não prova de que a FSM impede T9. Não se declara checklist verde nem se alteram anotações para evitá-lo. Tasks 5.x conservam suas anotações after-qa originais.

Só documentação, tasks e evidência foram alteradas nesta reconciliação. Adapter, manifesto, skills, código e Design aprovado permanecem byte a byte. Nenhum novo trust, transição, review, QA, commit ou push realizado.

## Verificação documental desta reconciliação

`openspec validate card-1098-codex-agentes-nativos --strict` e `git diff --check`: PASS. Parser: 35 tasks, 23 completas, 12 pendentes. Chamada somente leitura a `_check_tasks(change, 'precommit')`: `tasks.md pending`, coerente com as quatro tasks sem anotação; não é execução da onda ou do checklist completo.

Sete selos JSON conferidos localmente com `check_seal`: bootstrap, contexto, probe package, qualificação dos probes, rota e ambos envelopes de reviewer. SHA-256 do diff diagnóstico confere. Isso confere integridade dos artefatos sanitizados, sem alegar nova revalidação das fontes nativas pelo Apply. A origem foi revalidada pelos comandos vivos do pai.

Comparação antes/depois de 167 arquivos de código, skills, perfis, manifesto e Design: zero alterações. SHA-256 bruto do manifesto preservado `67acca6f2c659329b3af14214812ac088f0cecbdb90964e76e38c2dfad2306b8`. Não houve alteração que exigisse novo trust nesta reconciliação.
