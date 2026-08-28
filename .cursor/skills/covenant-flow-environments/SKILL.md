---
name: covenant-flow-environments
description: "Mapa de ambientes do consumidor a partir do overlay: DEV, PROD opcional, services, URLs, two-path, restart e release. Use quando a tarefa puder afetar DEV, PROD, publicação, release, deploy, banco, serviço ou validação pública."
---

# Covenant Flow Environments

Complementa `covenant-flow`. Decide **onde agir**: `DEV`, `PROD` ou `DEV->PROD`.

Valores de topologia vêm de `.covenant-flow/overlay.yaml`:

- `environments.dev` (obrigatório se o projeto tem runtime DEV): `source`, `url`, `db`, `services[]`
- `environments.prod` (omitir se o projeto é só DEV)
- `canonical_paths` / `forbidden_worktrees` (two-path)
- `release.restart` / `migrate` / `build` / `health_url`

Não trate paths, units systemd ou URLs hardcoded neste ficheiro como o mapa. Leia o overlay do consumidor.

Se Alan não disser `producao`, `prod`, `release`, `publicar`, `subir lote` ou equivalente, assuma **DEV**.

Se `environments.prod` estiver ausente, o projeto é DEV-only: recuse deploy de produção. Se `release.*` estiver vazio, T16 / `release-guard` recusa deploy.

OpenClaw **não** é runtime ativo. Não operar `openclaw-gateway.service` nem a porta `18789` como caminho corrente.

## Two-path

Operar só os paths em `canonical_paths`. Não usar entradas de `forbidden_worktrees` como clone/workspace. Path temporário: inventariar; apagar só com autorização explícita de Alan.

## Restart

- Done técnico DEV: comando em `release.restart` no `environments.dev.source`.
- Validação intermédia: só o unit afetado de `environments.*.services`.
- PROD: só com pedido explícito; units de `environments.prod.services`; evidência em `release.health_url`.

## Release

Fail-closed. Pedido explícito. Evidência mínima: SHA publicado, migrate/build/restart dos hooks de overlay, URL pública validada. Sem hooks preenchidos, não há `Pronto`.
