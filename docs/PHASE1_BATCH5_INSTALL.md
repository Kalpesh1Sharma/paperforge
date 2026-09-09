# PaperForge Phase 1 — Batch 5

This overlay completes the product-level report workspace.

## Included

- Real report outline with anchored section navigation
- Reloadable embedded publication preview and full-page HTML access
- Source inspector with page and word metadata
- PDF, Markdown, and HTML export controls
- Evidence-confidence and report-version information
- Safe regeneration from persisted sources and wizard settings
- Single- and multi-source regeneration through persistent background jobs
- Clear preview, outline, regeneration, and job error states
- Lightweight SQLite job polling that does not initialize AI providers

## Install on Windows

1. Stop the frontend and backend terminals with `Ctrl+C`.
2. Extract this ZIP directly over `D:\PaperForge` and allow files to be replaced.
3. Start the backend:

```powershell
cd D:\PaperForge\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

4. Start the frontend in a second terminal:

```powershell
cd D:\PaperForge\frontend
npm install
npm run dev
```

No database reset or environment-key change is required.

## Verify

1. Open an existing report from **Projects**.
2. Select entries in **Document outline** and confirm the preview moves to those sections.
3. Test PDF, Markdown, and HTML exports.
4. Check the source, confidence, structure, template, provider, and creation metadata.
5. Select **Regenerate from saved sources**, read the confirmation, and choose **Regenerate**.
6. Confirm PaperForge opens the background processing view and the original report remains available.
7. Select **Work on something else**, then return using the progress banner.

## Automated verification

- Backend: 298 tests passed
- Frontend: 9 interaction tests passed
- TypeScript typecheck passed
- Production Vite build passed
