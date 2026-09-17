# DECISIONS.md

One line per decision, chronological: `<decision> — <reason>`.

## Phase 0 — Scaffold

- Repo root is the working directory itself (not a nested `visual-campus/` folder) — the spec tree only names the root; the project directory was opened as the repo.
- The spec was supplied as `SPEC.pdf`; `SPEC.md` was generated from its text layer with `pdftotext -enc UTF-8` and section headers restored — Section 4 requires `SPEC.md` in the repo root; `SPEC.pdf` is kept as the original.
- Several long lines are clipped inside the PDF itself (Commons `iiextmetadatafilter` list after `Obj`, Flickr `extras` after `descrip`, the Commons exclusion regex after `\.t`, `VISION_SYSTEM` after "You receive N", two `//` comments in the vision header, the description prompt, the spelling prompt) — each reconstruction is recorded in the phase that implements it.
- Local development uses a Python 3.12 venv (`.venv`, git-ignored) because Python 3.11 is not installed on the build machine; the Docker image stays `python:3.11-slim` as fixed by Section 16.1 — every pin was resolved for `--python-version 3.11` on manylinux with `pip download` to confirm cp311 wheels exist.
- `numpy==2.4.6` is pinned (not the newest 2.5.x) — numpy 2.5 ships no Python 3.11 wheels, which would break the Docker build.
- Runtime pins live in `backend/requirements.txt`; dev/test pins (`pytest`, `pytest-asyncio`, `respx`, `ruff`) in `backend/requirements-dev.txt` which includes the runtime file — keeps the Docker image free of test tooling while every version stays pinned with `==`.
- Docker is not installed on the build machine, so the `docker build` / `docker run` gate is substituted by an equivalent local check: pip resolution for py3.11/linux, `npm ci && npm run build`, uvicorn started from `backend/` with the built SPA copied to `app/static`, `curl /api/health` — the Dockerfile is Section 16.1 verbatim, so the steps are the same ones the image runs.
- Added `.dockerignore` (node_modules, dist, .venv, data, .git) — the spec Dockerfile does `COPY frontend/ ./` and `COPY backend/ ./`, which would otherwise copy local build artefacts into the image.
- `react-router-dom` 6.x is used for the two routes `/` and `/u/:qid` — it is a router, not a component library, and the spec's `:qid` notation is react-router syntax.
- Frontend pinned to Vite 7.3.6 / TypeScript 5.9.3 / `@vitejs/plugin-react` 5.2.0 rather than the newest Vite 8 / TypeScript 7 majors — stability during the hackathon; Vite 7 needs Node ≥ 20.19, which `node:20-alpine` provides.
- `react-leaflet` pinned to 4.2.1 — 5.x requires React 19 while the spec fixes React 18.
- Tailwind CSS 4.x via the `@tailwindcss/vite` plugin — no PostCSS config needed; one `@import "tailwindcss"` in the stylesheet.
- `Settings` reads `.env` from both the repo root (`../.env` relative to `backend/`) and `backend/.env`, environment variables always win — `docker compose` passes the root `.env`, while `uvicorn` is started from `backend/` locally.
- Empty-string environment values (`TEXT_MODEL=`, `ANTHROPIC_API_KEY=`) are treated as unset — `.env.example` ships every variable, and an empty key must not be sent to the SDK.
- `/api/health` `version` is `GIT_SHA` env if set, else `git rev-parse --short HEAD` at startup, else `dev` — the spec Dockerfile has no build-arg, and there is no `.git` inside the image.
- Retry policy treats `httpx.NetworkError`, `httpx.ConnectTimeout` and `httpx.RemoteProtocolError` as "connection errors"; read timeouts are not retried — a retried read timeout would silently double a stage's time inside the 27 s budget.
- SPA fallback is a catch-all route registered after `/api`; unknown `/api/*` paths return the JSON error envelope, never `index.html` — Section 12 error format must hold for every API path.
- `Warning` model keeps the spec's name although it shadows the Python builtin — the frontend `types.ts` mirrors names exactly.
