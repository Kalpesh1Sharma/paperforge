# PaperForge deployment

## Local Docker deployment

Copy `backend/.env.example` to `backend/.env`, add only the provider keys you
intend to use, and run:

```bash
docker compose up --build
```

Open `http://localhost:5173`. The backend health endpoint is available at
`http://localhost:8000/health`. Report sources, SQLite state, and generated
exports are stored in the named `paperforge-data` volume.

## Public demo without API keys

The public demo profile uses deterministic processing, so no source document is
sent to an external AI provider:

```bash
PAPERFORGE_ENV_FILE=./backend/demo.env docker compose up --build
```

On PowerShell:

```powershell
$env:PAPERFORGE_ENV_FILE = "./backend/demo.env"
docker compose up --build
```

This workflow supports upload, outline approval, background processing,
quality checks, all three templates, PDF/HTML/Markdown/DOCX export, editing,
and deletion. SuperDocs review remains unavailable until its key is configured.

## Hosted deployment

Deploy the backend container with a persistent volume mounted at
`/data/reports`. Set `REPORT_STORAGE_DIR=/data/reports`, configure the allowed
frontend origin in `CORS_ORIGINS`, and store provider keys only in the hosting
platform's secret manager.

Build the frontend with `VITE_API_BASE_URL` set to the public HTTPS backend URL.
Both services must use HTTPS in production. Do not place provider keys in
frontend build arguments, browser storage, repository files, or screenshots.

Before sharing a public demo:

1. Run both automated test suites and the frontend production build.
2. Generate and download one report in every template.
3. Confirm the quality panel and editable DOCX export.
4. Delete the test project and confirm its report folder is removed.
5. Apply platform upload limits, request timeouts, HTTPS, and basic abuse
   protection appropriate to the expected audience.

The current SQLite and in-process worker architecture is intended for a
single-instance demo. Multi-instance production deployment requires shared
object storage, a managed database, authentication, and a distributed job
queue.
