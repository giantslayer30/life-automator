# Workflow: Apply to a Job

## Objective
Generate a tailored PDF resume, get AI improvement suggestions, and submit a tracked application — without accidentally applying twice.

## Inputs Required
- Active resume HTML uploaded via UI (or `tools/generate_pdf_resume.py`)
- Job ID from the database
- `ANTHROPIC_API_KEY` set in `.env` for AI suggestions

## Procedure

### Path A — Via Web UI (recommended)
1. Open `http://localhost:8000`
2. Select a job card from the feed
3. Click **Apply** → Apply modal opens
4. Review AI match score and suggestion chips (loaded automatically)
5. Accept any suggestions you want to apply (click chips to toggle)
6. Optionally paste your Superfolio URL for this application
7. Confirm the resume version shown — click **Preview PDF ↗** to verify
8. Click **Apply Now** → application logged, card shows ✓ Applied

### Path B — Via CLI (for batch / scripted use)

**Step 1 — Ensure resume exists**
```bash
sqlite3 .tmp/jobs.db "SELECT id, version, label, is_active FROM resumes ORDER BY version DESC;"
```
If none, generate one first:
```bash
python tools/generate_pdf_resume.py --html path/to/resume.html --version 1 --label "UX Senior"
```

**Step 2 — Get AI suggestions for a job**
```bash
python tools/ai_suggest.py --job-id 42
```
Review match score and suggestions. Apply changes to your resume HTML manually if needed.

**Step 3 — Regenerate PDF if resume was edited**
```bash
python tools/generate_pdf_resume.py --html path/to/resume.html --version 2
```

**Step 4 — Log the application**
```bash
python tools/track_application.py apply --job-id 42 --resume-id 2
```
Optionally with Superfolio:
```bash
python tools/track_application.py apply --job-id 42 --resume-id 2 --superfolio-url https://superfolio.co/u/you/company-jobid
```

**Step 5 — Apply to multiple jobs (Apply All)**
Via UI: Click "Apply to all N listed jobs" button at top of job list → confirm in modal.
Via API:
```bash
curl -X POST http://localhost:8000/api/apply/bulk \
  -H "Content-Type: application/json" \
  -d '{"job_ids": [42, 43, 44], "resume_id": 2}'
```
Returns: `{"applied": [...], "skipped": [...], "errors": [...]}`

## Duplicate Application Guard
Before every application, the system checks `applications` table for existing record with same `job_id`. If found:
- Via UI: "Apply" button replaced by "✓ Applied" badge — click redirects to application history
- Via CLI: `ValueError` raised with application ID and current status
- Via API: `409 Conflict` returned with detail message

## PDF Quality Check
When generating a new resume version, the tool runs a pixel diff against the last baseline:
- diff < 5%: OK, proceed
- diff ≥ 5%: Warning shown — preview the PDF before submitting to verify layout didn't break

## Superfolio Integration
Superfolio creates a trackable custom link for each application. Usage:
1. Create a link on superfolio.co for the company/role
2. Paste the URL into the Superfolio field in the apply modal
3. The URL is stored on the application record
4. In Application History, each card with a Superfolio URL shows an "Open Superfolio ↗" link

## Outputs
- Application record in `applications` table with `status = 'Applied'`
- PDF stored in `.tmp/resumes/`
- Resume version ID linked to the application for full traceability
