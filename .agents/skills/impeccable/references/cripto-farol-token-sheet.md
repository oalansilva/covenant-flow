# Folha de tokens — Cripto Farol (agente)

Recorte operacional para clone+delta. **Não** é o YAML visual. Autoridade humana/visual: `DESIGN.md`. **Não reescreva** `DESIGN.md`.

Use esta folha + a tela/rota atual (shell, nav, densidade). Tela nova: shell autenticado, não landing genérica.

## Shell

- Sidebar: `--app-sidebar-width` = `224px`
- Header workspace: `--app-header-desktop` = `80px`; `--app-header-mobile` = `72px`
- Superfície autenticada: sidebar + header + conteúdo; não inventar layout de marketing

## Tokens CSS (produto)

Do `frontend/src/index.css` / `DESIGN.md` (não duplicar o YAML):

- Fundo: `--bg-primary`, `--bg-secondary`, `--bg-elevated`, `--bg-input`, `--bg-overlay`
- Acento: `--accent-primary`, `--accent-primary-hover`
- Texto: `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-muted`
- Borda: `--border-default`, `--border-subtle`

## Tipo e densidade

- Família: Inter (`--font-family`)
- Corpo típico: `--text-base` 14px; labels `--text-sm` 12px
- Espaçamento: `--space-xs` 4px … `--space-md` 16px; densidade compacta do workspace, não landing

## Nav autenticada real (`AppNav`)

- Principal: Favoritos `/favorites`, Monitor `/monitor`
- Estratégia (admin): Descoberta `/combo/discovery`, Combo `/combo/select`
- Conta: Carteira `/external/balances`, Ajuda `/help`
- Admin: Preferências do sistema `/system/preferences`, Usuários `/admin/users`

Clone a nav real. Não inventar itens.
