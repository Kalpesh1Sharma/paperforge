# Phase 2 Batches 10–11 installation and verification

## Install

Extract the update at the PaperForge repository root, preserving the existing
folder structure. No API keys belong in committed files.

From `backend`, activate the virtual environment and refresh dependencies:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
python -m pytest tests -q
uvicorn app.main:app --reload
```

From `frontend` in a second terminal:

```powershell
npm install
npm test -- --run
npm run build
npm run dev
```

## Product check

1. Generate a report using APA, IEEE, and Harvard on separate runs.
2. Confirm evidence labels display source pages and the bibliography contains
   one entry per source document.
3. Open the report workspace and inspect the Quality checks card.
4. Download PDF and Editable DOCX; edit text in Word to confirm it is a normal
   document rather than an image.
5. Edit one report section and confirm both PDF and DOCX refresh.
6. Delete the test project and confirm its report directory is removed.

## Docker and public demo

For normal local Docker use, create `backend/.env` and run:

```powershell
docker compose up --build
```

For the keyless deterministic public-demo profile:

```powershell
$env:PAPERFORGE_ENV_FILE = "./backend/demo.env"
docker compose up --build
```

Open `http://localhost:5173`. See `docs/DEPLOYMENT.md` for persistent storage,
hosted-origin, secret-management, HTTPS, and single-instance limitations.
