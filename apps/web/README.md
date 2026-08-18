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

## API base URL

The client resolves the API root from `VITE_API_BASE_URL` (see
[`.env.example`](./.env.example)). Default is `/api`.

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
