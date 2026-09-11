---
name: design-critic
description: "Crítica de Design com teto de rodadas: sem-tela fecha em 1 autor + 1 crítico + 1 rework, com-tela em autor + dupla + 1 rework; só produto/escopo/contrato visível gera P0/P1, detalhe de implementação é P3 aceito resolvido no Apply; o primeiro autor já entrega os tokens parseáveis do gate. Use durante Status=Design, antes de solicitar Aprovação de Design."
---

# Design Critic (canónico)

Canónico: `.cursor/skills/design-critic/` no git do consumidor. Vale nos clientes via MUST Read (Cursor / Grok / dsh) — sem fork da lei por cliente, sem dual-write em `.dsh/` nem `.grok/`. Não ressuscitar `.agents/skills/` como canónico.

## Classificação

Só produto/escopo/contrato visível (tela, estados, acessibilidade, escopo furado) gera P0/P1. Detalhe de implementação (ORM, nomes internos, polish) é P3 "detalhe de Apply": registado como aceito em `design.md` e resolvido no Apply — o crítico nunca o reabre como P0/P1.

## Teto

Sem-tela: 1 autor + 1 crítico + 1 rework. Com-tela: autor + dupla + 1 rework. Segundo rework só com P0 novo de produto justificado no prompt; fora disso o pai publica a seção de crítica com os P3 aceitos e submete.

Validação: o pai justifica o P0 novo no prompt; sem justificativa, o segundo rework não é spawnado.

## Gate no autor

O primeiro autor já entrega `UI impact` / `live_route` / `surface` em linha própria parseável. Sem-tela declara ausência + justificativa curta (nunca rota de catálogo emprestada). Com-tela marca só as regiões clonadas. O crítico/dupla verifica esses tokens como item da rubrica — nenhuma rodada extra nasce só para o parser.

## Bloco D4 (texto exacto — vale para skill e prompts)

> **Design fecha em 1+1+1 (teto):** sem-tela = 1 autor + 1 crítico + 1 rework; com-tela = autor + dupla + 1 rework. Segundo rework só com P0 novo de produto justificado no prompt; fora disso o pai publica a seção de crítica com os P3 aceitos e submete. **Classificação:** só produto/escopo/contrato visível (tela, estados, acessibilidade, escopo furado) gera P0/P1; detalhe de implementação é P3 "detalhe de Apply", aceito em `design.md` e resolvido no Apply — nunca reaberto como P0/P1. **Gate no autor:** o primeiro autor já entrega `UI impact` / `live_route` / `surface` em linha própria parseável; sem-tela declara ausência + justificativa curta (nunca rota de catálogo emprestada); com-tela marca só as regiões clonadas. O crítico/dupla verifica esses tokens como item da rubrica.
