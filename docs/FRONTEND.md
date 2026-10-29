# AgentsMind web app (`frontend/`)

React 19 + TypeScript + Vite 8, Tailwind CSS 4 (design tokens as CSS variables), Radix UI
primitives (dialog, dropdown menu, tabs), TanStack Query, Lucide icons and IBM Plex Sans
(self-hosted through Fontsource, so no font CDN). Versions are pinned exactly in
`frontend/package.json` and recorded in `docs/API_VERIFICATION.md`.

## Run it

Needs Node.js 22 LTS.

```powershell
cd frontend
npm install
npm run build          # type-checks with tsc, then writes frontend\dist
```

The core API serves `frontend\dist` on its own port, so after a build the whole product is at
http://127.0.0.1:8000 (started by `scripts\win\run_all.ps1`). For UI development with hot
reload, run `npm run dev` and open http://127.0.0.1:5173 (it proxies `/api` to port 8000).

## Screens

| Screen | Path | Who |
|---|---|---|
| Sign in, forgot password, reset password | `/login`, `/forgot-password`, `/reset-password` | everyone |
| Hub: departments, approvals waiting, recent conversations, system health (admin) | `/` | all staff |
| Assistant: conversations, live progress (SSE), approval cards, clarifying questions | `/assistant` | all staff |
| Approvals: pending and decided actions, exact arguments, approve or reject | `/approvals` | all staff (own), admin (all) |
| HR: CV screening and candidates board (stages moved by people) | `/hr` | hr |
| IT: raise complaints, follow tickets; IT staff change status and comment | `/it` | all staff (own tickets), it |
| Finance: payroll summary (SQL), people with add, edit, CSV and typed-name delete; payments | `/finance` | finance |
| Documents: Drive search, read, summarise, compare | `/documents` | hr, it, finance |
| Communications: inbox with suspicious-message warnings, compose with review, calendar with conflict check | `/communications` | all staff |
| Admin: users, MCP and queue health, dead tasks, tool calls, audit log, system outbox | `/admin` | admin |
| Settings: account, theme, change password | `/settings` | everyone |
| 403 and 404 pages that say what to do next | any | |

The menu and route guards hide what a role cannot use, but the API enforces every rule on the
server; the UI never decides access.

## Design rules (checked by tests)

- Light and dark themes from the same tokens (`src/styles.css`). Choice: Light, Dark or Match
  system, remembered per browser.
- WCAG AA contrast for every text and control pair in both themes: `node scripts/contrast.mjs`.
- No emoji, no gradients, no glassmorphism (no backdrop blur). Every input has a label, every
  icon-only button has an accessible name, focus is always visible, motion respects
  "reduce motion". Checked on every page in both themes by `e2e/design-rules.spec.ts`.
- Anything produced by a sandbox backend or the sandbox model shows a **Simulated** label.
  Text from emails, CVs and files is shown as outside content.
- Every form that changes data sends an `Idempotency-Key` and disables its button while
  sending, so a double click or a retry never creates a duplicate.

## Tests

`npm run e2e` runs Playwright (Chromium) against a running system. `AGENTSMIND_URL` picks the
server (default http://127.0.0.1:8000). Sign-in details come from `data\local_credentials.txt`
(`scripts\env_setup.py`) and `data\seed_credentials.txt` (`scripts\seed.py`). The phase gate
runs the whole suite against the live sandbox system.

| Spec | Covers |
|---|---|
| `auth-and-rbac.spec.ts` | sign-in errors, redirect back, employee cannot open Finance or Documents, sign out |
| `assistant.spec.ts` | calendar by prompt to approval to read-back, clarification round trip, hostile email, fallback |
| `departments.spec.ts` | IT complaint to ticket number and confirmation page, Finance add and typed-name delete, HR screening flags the hostile CV, Documents summary labeled Simulated, suspicious inbox message |
| `design-rules.spec.ts` | no emoji, gradients or blur, labelled inputs and named buttons on every page in both themes, theme remembered |
