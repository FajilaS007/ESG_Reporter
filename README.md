# ESG Auditor

A FastAPI-backed ESG audit application that helps identify potential greenwashing in sustainability claims by cross-referencing company reports with news coverage. The app is focused on India and supports state-level audit scoping.

## Project structure

- `app/` - Python backend application
  - `main.py` - FastAPI entry point
  - `orchestrator.py` - audit workflow and cache handling
  - `models.py` - Pydantic models for requests and responses
  - `tools/` - helper modules for news, report fetching, scoring, location lookup, and cross-referencing
  - `cache/` - generated cache files for audit results
- `frontend/` - static browser UI served from `/`
- `src/` - TypeScript source files and utility definitions
- `requirements.txt` - Python dependencies for the backend
- `package.json` - Node/TypeScript dependencies and scripts
- `tsconfig.json` - TypeScript compiler configuration
- `Dockerfile` - container image definition
- `Procfile` - production startup command for platform deployments
- `runtime.txt` - Python runtime version hint for hosted deploys
- `jest.config.js` - frontend/test runner configuration

## Key behavior

- Serves a single-page frontend at `/`
- Provides API endpoints:
  - `POST /locations` - resolve company location options
  - `POST /audit` - run ESG audit for a company and optional state location
  - `GET /company/{company}/audits` - return cached audits grouped by country and state
- Caches audit output in `app/cache/`

## Requirements

- Python 3.11
- `pip`
- Node.js / npm if you want to run TypeScript tooling or tests

## Local setup

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

2. (Optional) Install Node dependencies for frontend tooling or tests:

```bash
npm install
```

3. Start the backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open the app in your browser:

```text
http://localhost:8000
```

## Running tests

- Python tests:

```bash
pytest
```

- TypeScript / Jest tests:

```bash
npm test
```

## Docker

Build the container image:

```bash
docker build -t esg-auditor .
```

Run the container:

```bash
docker run -p 8000:8000 esg-auditor
```

## Deployment

The project includes a `Procfile` for Heroku-style deployments:

```text
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Notes

- `app/cache/` is generated runtime data and should not be committed to GitHub.
- If the app needs external API keys or service credentials, store them in a local `.env` file and never commit it.
- Add a `.gitignore` file if one is missing. Recommended entries include:

```text
app/cache/
node_modules/
__pycache__/
*.pyc
.env
.DS_Store
```

## Recommended GitHub files

Include these in your repository:
- `app/`
- `frontend/`
- `requirements.txt`
- `package.json`
- `tsconfig.json`
- `jest.config.js`
- `Dockerfile`
- `Procfile`
- `runtime.txt`
- `README.md`
- any source/test config files

Exclude generated or secret files like:
- `app/cache/`
- `node_modules/`
- `__pycache__/`
- `.env`
