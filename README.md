# Covenant Flow — portable process product

Private GitHub repository for the 12-column process (nucleus + 20 skills + four client adapters).

## Install

```bash
git clone git@github.com:oalansilva/covenant-flow.git
cd covenant-flow
```

In the **consumer** repository:

```bash
/path/to/covenant-flow/install.sh --init --target /path/to/consumer
# fill .covenant-flow/overlay.yaml (board ids, globs, environments, overlay_doc)
/path/to/covenant-flow/install.sh --pin v1.1.0 --target /path/to/consumer
```

Or follow skill `implantar` in `.cursor/skills/implantar/`.

`--init` writes required keys **empty** and does not guess project values.
`--pin` copies nucleus, `.cursor/` `.grok/` `.opencode/` `.dsh/`, `.agents/skills/` (impeccable, design-critic, playwright-cli), helpers, and a generated `AGENTS.md`. It copies `.dsh/` even when overlay omits `clients.dsh`. It refuses an empty or invalid overlay. The consumer **commits** those trees. It does not overwrite the Markdown at `overlay_doc`.

v1 does **not** install via git submodule, gitignore pointers, marketplace, or template-clone.

## Pin

Overlay field `pin` is a semver tag `vMAJOR.MINOR.PATCH`. A breaking overlay-schema change is a major tag (`v2.0.0`). Bump = re-run `--pin` and commit the diff; project keys are preserved.

## Layout

- Nucleus: `.cursor/process-fsm.yaml`, `scripts/process-fsm/`
- Adapters: `.cursor/`, `.grok/`, `.opencode/`, `.dsh/`
- Overlay machine file (consumer): `.covenant-flow/overlay.yaml`
- Human overlay: path in `overlay_doc`
- Skills: `covenant-flow`, `covenant-flow-environments`, `implantar`, plus OpenSpec, grill, board, kaizen, design-critic, impeccable, playwright-cli
