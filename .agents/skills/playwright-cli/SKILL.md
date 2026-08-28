---
name: playwright-cli
description: Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from web pages.
allowed-tools: Bash(playwright-cli:*), Bash(playwright-cli-headed:*), Bash(xvfb-run:*), Bash(env:*)
---

# Browser Automation with playwright-cli

## Server-specific rule for this repo

On this server, headed browser runs must use the wrapper `playwright-cli-headed` instead of plain `playwright-cli` because the environment runs as root and has no real X server. The wrapper already applies:

- `xvfb-run -a`
- `PLAYWRIGHT_MCP_SANDBOX=false`

Use this rule of thumb:

- Use `playwright-cli-headed` for headed runs on this server.
- Use plain `playwright-cli` only for non-headed flows that are already known to work in the current environment.
- Do not assume snapshot refs like `e21` or `e35` are stable across runs; capture a fresh snapshot before clicking/checking.
- On this host, do not treat multi-invocation headed sessions as reliable by default.
- Prefer one single `run-code` command that includes `page.goto(...)`, the full interaction flow, and `page.screenshot(...)`.
- Use named sessions with `-s=<name>` only when a task has already proved stable across multiple invocations in the current environment.
- If the wrapper is unavailable in PATH, call the full path `/usr/local/bin/playwright-cli-headed`.
- The wrapper already redirects browser/cache state into project-controlled paths to avoid `/root/.cache/ms-playwright/daemon` permission issues.
- For stable completion in this environment, prefer this pattern:
  - one call to `playwright-cli-headed -s=<name> run-code "async page => { ... }"`
  - include `await page.goto(...)`
  - include all DOM interactions in the same script
  - include `await page.screenshot({ path: ... })` in the same script or follow immediately with an explicit screenshot command only if the session is known-good

## Quick start

```bash
# headed flow on this server
playwright-cli-headed -s=todomvc open https://playwright.dev --headed
playwright-cli-headed -s=todomvc snapshot
playwright-cli-headed -s=todomvc click e15
playwright-cli-headed -s=todomvc type "page.click"
playwright-cli-headed -s=todomvc press Enter
playwright-cli-headed -s=todomvc screenshot
playwright-cli-headed -s=todomvc close
```

## Commands

### Core

```bash
playwright-cli-headed -s=mysession open https://example.com/ --headed
playwright-cli-headed -s=mysession goto https://playwright.dev
playwright-cli-headed -s=mysession type "search query"
playwright-cli-headed -s=mysession click e3
playwright-cli-headed -s=mysession dblclick e7
playwright-cli-headed -s=mysession fill e5 "user@example.com"
playwright-cli-headed -s=mysession drag e2 e8
playwright-cli-headed -s=mysession hover e4
playwright-cli-headed -s=mysession select e9 "option-value"
playwright-cli-headed -s=mysession upload ./document.pdf
playwright-cli-headed -s=mysession check e12
playwright-cli-headed -s=mysession uncheck e12
playwright-cli-headed -s=mysession snapshot
playwright-cli-headed -s=mysession snapshot --filename=after-click.yaml
playwright-cli-headed -s=mysession eval "document.title"
playwright-cli-headed -s=mysession eval "el => el.textContent" e5
playwright-cli-headed -s=mysession dialog-accept
playwright-cli-headed -s=mysession dialog-accept "confirmation text"
playwright-cli-headed -s=mysession dialog-dismiss
playwright-cli-headed -s=mysession resize 1920 1080
playwright-cli-headed -s=mysession close
```

### Navigation

```bash
playwright-cli go-back
playwright-cli go-forward
playwright-cli reload
```

### Keyboard

```bash
playwright-cli press Enter
playwright-cli press ArrowDown
playwright-cli keydown Shift
playwright-cli keyup Shift
```

### Mouse

```bash
playwright-cli mousemove 150 300
playwright-cli mousedown
playwright-cli mousedown right
playwright-cli mouseup
playwright-cli mouseup right
playwright-cli mousewheel 0 100
```

### Save as

```bash
playwright-cli screenshot
playwright-cli screenshot e5
playwright-cli screenshot --filename=page.png
playwright-cli pdf --filename=page.pdf
```

### Tabs

```bash
playwright-cli tab-list
playwright-cli tab-new
playwright-cli tab-new https://example.com/page
playwright-cli tab-close
playwright-cli tab-close 2
playwright-cli tab-select 0
```

### Storage

```bash
playwright-cli state-save
playwright-cli state-save auth.json
playwright-cli state-load auth.json

# Cookies
playwright-cli cookie-list
playwright-cli cookie-list --domain=example.com
playwright-cli cookie-get session_id
playwright-cli cookie-set session_id abc123
playwright-cli cookie-set session_id abc123 --domain=example.com --httpOnly --secure
playwright-cli cookie-delete session_id
playwright-cli cookie-clear

# LocalStorage
playwright-cli localstorage-list
playwright-cli localstorage-get theme
playwright-cli localstorage-set theme dark
playwright-cli localstorage-delete theme
playwright-cli localstorage-clear

# SessionStorage
playwright-cli sessionstorage-list
playwright-cli sessionstorage-get step
playwright-cli sessionstorage-set step 3
playwright-cli sessionstorage-delete step
playwright-cli sessionstorage-clear
```

### Network

```bash
playwright-cli route "**/*.jpg" --status=404
playwright-cli route "https://api.example.com/**" --body='{"mock": true}'
playwright-cli route-list
playwright-cli unroute "**/*.jpg"
playwright-cli unroute
```

### DevTools

```bash
playwright-cli console
playwright-cli console warning
playwright-cli network
playwright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
playwright-cli tracing-start
playwright-cli tracing-stop
playwright-cli video-start
playwright-cli video-stop video.webm
```

## Open parameters
```bash
# Use specific browser when creating session
playwright-cli open --browser=chrome
playwright-cli open --browser=firefox
playwright-cli open --browser=webkit
playwright-cli open --browser=msedge
# Connect to browser via extension
playwright-cli open --extension

# Use persistent profile (by default profile is in-memory)
playwright-cli open --persistent
# Use persistent profile with custom directory
playwright-cli open --profile=/path/to/profile

# Start with config file
playwright-cli open --config=my-config.json

# Close the browser
playwright-cli close
# Delete user data for the default session
playwright-cli delete-data
```

## Snapshots

After each command, playwright-cli provides a snapshot of the current browser state.

```bash
> playwright-cli goto https://example.com
### Page
- Page URL: https://example.com/
- Page Title: Example Domain
### Snapshot
[Snapshot](.playwright-cli/page-2026-02-14T19-22-42-679Z.yml)
```

You can also take a snapshot on demand using `playwright-cli snapshot` command.

If `--filename` is not provided, a new snapshot file is created with a timestamp. Default to automatic file naming, use `--filename=` when artifact is a part of the workflow result.

## Browser Sessions

```bash
# create new browser session named "mysession" with persistent profile
playwright-cli -s=mysession open example.com --persistent
# same with manually specified profile directory (use when requested explicitly)
playwright-cli -s=mysession open example.com --profile=/path/to/profile
playwright-cli -s=mysession click e6
playwright-cli -s=mysession close  # stop a named browser
playwright-cli -s=mysession delete-data  # delete user data for persistent session

playwright-cli list
# Close all browsers
playwright-cli close-all
# Forcefully kill all browser processes
playwright-cli kill-all
```

## Local installation

In some cases user might want to install playwright-cli locally. If running globally available `playwright-cli` binary fails, use `npx playwright-cli` to run the commands. For example:

```bash
npx playwright-cli open https://example.com
npx playwright-cli click e1
```

## Example: Form submission

```bash
playwright-cli open https://example.com/form
playwright-cli snapshot

playwright-cli fill e1 "user@example.com"
playwright-cli fill e2 "password123"
playwright-cli click e3
playwright-cli snapshot
playwright-cli close
```

## Example: Multi-tab workflow

```bash
playwright-cli open https://example.com
playwright-cli tab-new https://example.com/other
playwright-cli tab-list
playwright-cli tab-select 0
playwright-cli snapshot
playwright-cli close
```

## Example: Debugging with DevTools

```bash
playwright-cli open https://example.com
playwright-cli click e4
playwright-cli fill e7 "test"
playwright-cli console
playwright-cli network
playwright-cli close
```

```bash
playwright-cli open https://example.com
playwright-cli tracing-start
playwright-cli click e4
playwright-cli fill e7 "test"
playwright-cli tracing-stop
playwright-cli close
```

## Specific tasks

* **Request mocking** [references/request-mocking.md](references/request-mocking.md)
* **Running Playwright code** [references/running-code.md](references/running-code.md)
* **Browser session management** [references/session-management.md](references/session-management.md)
* **Storage state (cookies, localStorage)** [references/storage-state.md](references/storage-state.md)
* **Test generation** [references/test-generation.md](references/test-generation.md)
* **Tracing** [references/tracing.md](references/tracing.md)
* **Video recording** [references/video-recording.md](references/video-recording.md)
