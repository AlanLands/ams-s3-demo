# AMS console — web UI

React 19 + TypeScript + Vite. The screen the presenter drives. The FastAPI
backend it talks to is next door in [`../api/`](../api); the two ship as one
process in production (`npm run build` emits `dist/`, which
`apps.console.api.main` serves with an SPA history fallback).

```bash
npm install
npm run dev       # :5173, proxies /api to the backend on :8000
npm run build     # tsc -b && vite build -> dist/
npm run lint      # oxlint
```

Normally you don't run either by hand — `apps/run-console.sh` starts the
backend and this dev server together.

## Pages

| Route | File | Who sees it |
|---|---|---|
| `/login` | `pages/Login.tsx` | everyone — fictional roster login (`common/roster.py`) |
| `/` | `pages/Home.tsx` | everyone |
| `/s3/{board,target,generate,design-doc,tests,release}` | `pages/s3/` | one route per pipeline stage, gated by the stage's unlock rules |
| `/admin` | `pages/Admin.tsx` + `pages/admin/` | **managers only** — the API enforces it with `require_manager`, this is not a client-side gate |

The admin page is four cards: reset demo state by scope, clear logs, see and
start/stop the target apps, and onboard a repo by writing its
`.s3targets.json`. It shows what a reset would restore and delete before it
runs, reports a source reset as blocked while the tree is dirty, and has no
control for the console itself — it cannot restart the process serving the
request.

## Artifacts open in a modal, not inline

Long AI-produced artifacts — release notes, the deployment plan, the design
doc, the scenario table, the generated and executed test checklists, the
mutation diff, the traceability matrix — render inside `Modal`
(`pages/s3/components.tsx`) rather than expanding down the page. What stays in
the main flow is the part a presenter narrates: the action buttons, the
verdict line, and the token-cost line. The left-hand stage rail is unchanged.

This came from client feedback that there was too much on screen at once, so
resist putting a new artifact back inline. `Modal` is mount-to-open — the
caller renders `{open && <Modal …/>}` — which keeps focus handling and the
escape key in one place.

## Configuration

Vite bakes `VITE_*` values in at **build** time. Copy `.env.example` to
`.env.local`, edit, and rebuild; every value defaults to the previous
hard-coded localhost one, so a plain local run needs none of them. Only
`VITE_`-prefixed names reach the browser, which is also why no secret belongs
in that file.

## State

Per-ticket pipeline state persists in `localStorage` under
`ams-s3:ticket:{key}`, so a tester logging in separately resumes mid-flight.
`GET /s3/reset-marker` changes only on a demo reset, and the SPA drops that
cached state when it does rather than showing results for a ticket the server
no longer has any record of.
