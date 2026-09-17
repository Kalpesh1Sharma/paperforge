# Phase 2 — Batches 7 and 8 installation

This overlay adds three production report themes and an evidence-aware outline
approval gate. Apply it on top of the Phase 2 Batch 6 codebase.

## Install

1. Stop the backend and frontend development servers.
2. Extract the overlay into the PaperForge repository root and allow matching
   files to be replaced.
3. From `backend`, activate the virtual environment and run:

   ```powershell
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

4. In a second terminal, run:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

## Acceptance check

Create a new report and verify the following flow:

1. Complete project information and upload one to five PDFs.
2. Choose a report structure.
3. Select **Classic Academic**, **Modern Research**, or
   **IEEE-Inspired Technical**.
4. Complete the publication details.
5. Wait for the outline evidence scan.
6. Rename and reorder at least one section; remove or add a section if useful.
7. Confirm that each section displays an evidence level and source count.
8. Select **Approve outline & continue**.
9. Review the exact approved order, then select **Generate approved report**.
10. Export the PDF and confirm that the chosen visual template is applied.

Going back and changing the report configuration invalidates the current
approval. PaperForge requires approval again before generation.

## Verification completed for this overlay

- Backend: 308 tests passed.
- Frontend: 10 tests passed.
- Frontend production build completed.
- All three template fixtures rendered as readable two-page A4 PDFs for visual
  quality assurance.
