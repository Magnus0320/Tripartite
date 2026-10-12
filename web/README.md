# Tripartite web

The React + Vite + TypeScript UI for Tripartite (`ARCHITECTURE.md` D8). It is a thin layer
over the API: every component calls an endpoint that exists on `main`, and there is no mock
data.

Milestones so far:

- **W1**: the query picker, a searchable list of the validation queries from `GET /api/queries`.
- **W2**: the Run button (`POST /api/runs`, seed 0), the live stage from the event stream
  `GET /api/runs/{run_id}/events` with polling `GET /api/runs/{run_id}` as the fallback, and
  the plan as one card per day.

Failed requests follow the web client status rules of `ARCHITECTURE.md` D8: a network failure,
502 or 504 means the API is unreachable; 503 shows the API's message; 409 means the model is
busy; 404 means not found; anything else is a generic error with its status.

## Requirements

Node.js as pinned in [`.nvmrc`](.nvmrc). `make setup` in the repository root runs `npm ci` here.

## Development

The dev server proxies `/api` to the API on `127.0.0.1:8000`. Run the API in fake mode on the
scoreable synthetic data set, written outside the repository, then start the dev server:

```bash
export TRIPARTITE_DATA_DIR="$(uv run tripartite data synthetic --scoreable --out ~/.cache/tripartite/synthetic-scoreable)"
TRIPARTITE_LLM=fake TRIPARTITE_EVAL_BRIDGE=fake make api   # terminal 1, repository root
make web                                                   # terminal 2, repository root
```

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint, no warnings allowed |
| `npm run test` | Vitest unit and component tests (`fetch` and `EventSource` are stubbed) |
| `npm run build` | production build into `dist/` |
| `npm run types` | regenerates `src/api/types.gen.ts` from `../api-contract/openapi.json` |

`src/api/types.gen.ts` is generated and never edited by hand. CI regenerates it and fails if
the committed file differs, so run `npm run types` whenever the API contract changes.
