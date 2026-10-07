# Tripartite web

The React + Vite + TypeScript UI for Tripartite (`ARCHITECTURE.md` D8). It is a thin layer
over the API: every component calls an endpoint that exists on `main`, and there is no mock
data.

Milestone **W1**: the query picker, a searchable list of the validation queries from
`GET /api/queries`.

## Requirements

Node.js as pinned in [`.nvmrc`](.nvmrc). `make setup` in the repository root runs `npm ci` here.

## Development

The dev server proxies `/api` to the API on `127.0.0.1:8000`. Run the API in fake mode on a
synthetic data set written outside the repository, then start the dev server:

```bash
export TRIPARTITE_DATA_DIR="$(uv run tripartite data synthetic --out "$(mktemp -d)/syn")"
TRIPARTITE_LLM=fake TRIPARTITE_EVAL_BRIDGE=fake make api   # terminal 1, repository root
make web                                                   # terminal 2, repository root
```

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint, no warnings allowed |
| `npm run test` | Vitest unit and component tests (`fetch` is stubbed) |
| `npm run build` | production build into `dist/` |
| `npm run types` | regenerates `src/api/types.gen.ts` from `../api-contract/openapi.json` |

`src/api/types.gen.ts` is generated and never edited by hand. CI regenerates it and fails if
the committed file differs, so run `npm run types` whenever the API contract changes.
