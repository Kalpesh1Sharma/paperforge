# Phase 2 Batch 9 installation

This overlay completes report editing for an existing Phase 2 Batch 8
PaperForge checkout.

## Install

1. Stop the backend and frontend development servers.
2. Extract the overlay into the PaperForge repository root and allow matching
   source files to be replaced.
3. Do not copy or replace `backend/.env`; this package contains no credentials.
4. Restart both applications:

   ```powershell
   cd D:\PaperForge\backend
   .\.venv\Scripts\Activate.ps1
   uvicorn app.main:app --reload
   ```

   ```powershell
   cd D:\PaperForge\frontend
   npm run dev
   ```

No database migration command is required. Existing `report.json` files load
with revision 1, generated content, and unlocked sections.

## Verify

1. Open a completed report and select **Edit report**.
2. Select a section, change its text, and select **Save section**. Confirm the
   revision increases and the preview and downloads contain the new text.
3. Try **Rewrite**, **Shorten**, and **Expand** on an unlocked section. The
   configured provider failover chain is used; deterministic behavior remains
   available if every remote provider fails.
4. Select **Lock section** and confirm editing and assisted actions are
   disabled. Unlock it to continue.
5. Change the visual template between Classic Academic, Modern Research, and
   IEEE-Inspired Technical. Confirm the layout changes while edited text stays
   identical.
6. Download PDF, Markdown, and HTML and confirm all three reflect the current
   revision.

## Automated checks

```powershell
cd D:\PaperForge\backend
python -m pytest tests -q

cd D:\PaperForge\frontend
npm test -- --run
npm run build
```

The packaged implementation was verified with 311 backend tests, 11 frontend
tests, and a successful production build.
