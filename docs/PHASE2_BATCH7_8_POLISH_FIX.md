# Phase 2 Batches 7–8 polish fix

Apply this small overlay after the Phase 2 Batches 7–8 templates and outline-approval package.

## Included fixes

- Keeps report section introductions and list items with their following content when printing, preventing orphaned headings and detached list markers.
- Removes near-duplicate sentences from generated abstracts without changing the underlying findings.
- Clarifies outline evidence counts by labelling them as supporting sources rather than all scanned sources.

## Install on Windows

1. Stop the backend and frontend development servers.
2. Extract the overlay into `D:\PaperForge` and replace the matching files.
3. Start the backend:

   ```powershell
   cd D:\PaperForge\backend
   .\.venv\Scripts\Activate.ps1
   uvicorn app.main:app --reload
   ```

4. Start the frontend in a second terminal:

   ```powershell
   cd D:\PaperForge\frontend
   npm run dev
   ```

5. Generate new reports to see the PDF changes. Existing exported PDFs are not rewritten.

## Verification

- Backend: 309 tests passed.
- Frontend: 10 tests passed.
- Production frontend build passed.
- Classic Academic, Modern Research, and IEEE-Inspired Technical A4 output was rendered and visually inspected.

