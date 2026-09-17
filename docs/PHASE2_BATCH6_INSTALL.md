# Phase 2 Batch 6 — Install and verify

This overlay upgrades PaperForge to the schema-v2 configurable report model.
It is designed to be extracted over the repository after Phase 1 commit
`deb0498` (or a branch containing that commit).

## 1. Confirm the target branch

```powershell
cd D:\PaperForge
git status --short
git branch --show-current
```

The worktree should be clean. Use the Phase 2 feature branch:

```powershell
git switch -c phase2/configurable-report-model
```

If that branch already exists, use:

```powershell
git switch phase2/configurable-report-model
```

## 2. Apply the overlay

Extract `paperforge-phase2-batch6-configurable-model.zip` directly into
`D:\PaperForge` and allow it to replace matching files. No environment files,
API keys, database files, uploaded PDFs, or generated reports are included.

## 3. Verify the backend

```powershell
cd D:\PaperForge\backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests -q
```

Expected result: `301 passed` (a Starlette/httpx deprecation warning is safe).

## 4. Verify the frontend

```powershell
cd D:\PaperForge\frontend
npm test -- --run
npm run typecheck
npm run build
```

Expected: 9 tests pass, TypeScript succeeds, and Vite creates the production
bundle.

## 5. Product smoke test

Restart backend and frontend, then create one report through all seven wizard
steps. Confirm:

- Step 1 accepts purpose and intended audience.
- Step 3 accepts structure, writing tone, and citation style.
- Step 5 accepts subtitle, university, department, organisation, and
  publication type.
- The generated cover shows the supplied metadata.
- Version information shows the selected structure, template, and citation
  style.
- An older Phase 1 report still opens and can be regenerated.

## 6. Commit

```powershell
cd D:\PaperForge
git status --short
git add README.md docs backend frontend
git diff --cached --check
git commit -m "feat: add configurable report model"
git push -u origin phase2/configurable-report-model
```
