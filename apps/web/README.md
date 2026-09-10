# Frontend - agentic-support-guide web

Local prototype UI. React + TypeScript + Vite + Tailwind CSS + Recharts.

Renders four fully implemented pages (Dashboard, Assessments, Supports,
AI Audit) plus a shared PlaceholderPage for the other nav items. The
Supports page shows a live three-agent workflow panel and provider
status, and handles the full set of typed failure states returned by
the backend envelope.

## Setup

```powershell
cd apps/web
npm install
Copy-Item .env.example .env
```

## Run

```powershell
npm run dev
```

The dev server listens on http://127.0.0.1:5173 and proxies `/api` to
http://127.0.0.1:8000 without stripping the prefix.

## Build and test

```powershell
npm run build
npm run test
```

## How the UI reaches the API

There is no sign-in. The browser calls `/api/...` on the web tier's own
origin, and `server.js` forwards it to the API with a shared key
attached server-side.

The key never reaches the browser, because a bundle cannot keep a
secret. That is the whole reason the web tier runs a server instead of
serving static files: `pm2 serve` had nowhere to hold a credential.

```
browser  ──/api/*──▶  web tier (server.js)  ──+ x-api-key──▶  API
```

`VITE_API_BASE_URL` should stay unset. It defaults to a relative `/api`,
which is what routes through the proxy. Pointing it at the API's own
hostname bypasses the proxy, and the API will reject the call because
the browser has no key to send.

Local development already works this way: `vite.config.ts` proxies
`/api` to `http://127.0.0.1:8000`, so the shape is identical and the API
skips the key check when it is not on App Service.

The district list comes from `/api/supports/options`, never from a
constant in the UI. More than one district renders a picker.

Anyone who can open the UI can use it. See
[docs/security-and-privacy.md](../../docs/security-and-privacy.md) for
what that does and does not protect.

## Setup status and error states

The UI reads `/api/health/details` for setup status. The Demo Guide and
Supports pages both render a `SetupStatus` component:

- **Customer demo ready (green):** `active_provider = "azure_foundry"`
  and Azure AI Foundry env vars are populated.
- **Customer demo NOT ready (red):** provider unconfigured or the
  backend is currently wired to a test-double LLM provider (which only
  happens inside `pytest`).

The Supports page renders a distinct error message for each envelope
status returned by the coordinator: `provider_missing`,
`provider_timeout`, `provider_throttling`, `provider_content_filter`,
`provider_error`, `invalid_model_json`, `validation_failed`, and
`orchestration_budget_exhausted`.
