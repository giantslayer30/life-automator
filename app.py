"""
app.py — FastAPI backend for the Job Application Platform.

Run:
    uvicorn app:app --reload --port 8000

Endpoints:
    GET  /                          → Job board HTML page
    GET  /api/jobs                  → Paginated job listing
    GET  /api/jobs/{id}             → Single job detail
    POST /api/resume/upload         → Upload .docx resume, convert to HTML
    GET  /api/resume/versions       → List resume versions
    GET  /api/resume/{id}/pdf       → Not available in hosted version (no Playwright)
    POST /api/apply/{job_id}        → Apply to a job
    POST /api/apply/bulk            → Apply All (with duplicate guard)
    GET  /api/applications          → Application history
    PUT  /api/applications/{id}/status → Update application status
    POST /api/applications/{id}/feedback → Add feedback note
    PUT  /api/applications/{id}/superfolio → Set Superfolio URL
    POST /api/ai/suggest/{job_id}   → Get AI suggestions for a job
    GET  /api/analytics             → Rejection + application stats
    GET  /api/scrape/run            → Trigger manual scrape (background)
    GET  /api/statuses              → Return preset status tags
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent / "tools"))

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
import io
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel

from db_init import get_connection, init_db, DB_PATH
from track_application import (
    PRESET_STATUSES,
    add_feedback,
    apply_to_job,
    list_applications,
    rejection_analytics,
    set_superfolio_url,
    update_status,
)

# ------------------------------------------------------------------
# App init
# ------------------------------------------------------------------
app = FastAPI(title="Job Application Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
TMP_DIR = Path(__file__).parent / ".tmp"

TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Cache-busting: changes on every server restart so browsers always get fresh assets
CACHE_VERSION = str(int(datetime.now(timezone.utc).timestamp()))
templates.env.globals["v"] = CACHE_VERSION

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Initialize DB on startup
@app.on_event("startup")
def startup():
    init_db()
    _archive_old_jobs()


def _archive_old_jobs():
    """Archive jobs not seen in the last 3 days."""
    from datetime import timedelta
    conn = get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    result = conn.execute(
        "UPDATE jobs SET is_archived = 1 WHERE last_seen_at < ? AND is_archived = 0",
        (cutoff,),
    )
    if result.rowcount:
        print(f"[startup] Archived {result.rowcount} stale job(s) older than 3 days")
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# DOCX → HTML converter
# ------------------------------------------------------------------
def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def docx_to_html(file_bytes: bytes) -> str:
    """Convert .docx bytes to basic HTML suitable for PDF generation and AI analysis."""
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    parts = [
        '<html><body style="font-family:Inter,Arial,sans-serif;max-width:800px;'
        'margin:40px auto;padding:0 24px;line-height:1.6;color:#111827">'
    ]
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name
        if "Heading 1" in style:
            parts.append(f'<h1 style="font-size:22px;margin-bottom:4px">{_esc(text)}</h1>')
        elif "Heading 2" in style:
            parts.append(
                f'<h2 style="font-size:16px;border-bottom:1px solid #e5e7eb;'
                f'padding-bottom:4px;margin-top:20px">{_esc(text)}</h2>'
            )
        elif "Heading" in style:
            parts.append(f'<h3 style="font-size:14px;margin-bottom:2px">{_esc(text)}</h3>')
        elif "List" in style:
            parts.append(f'<li style="margin-left:20px">{_esc(text)}</li>')
        else:
            parts.append(f'<p style="margin:4px 0">{_esc(text)}</p>')
    parts.append("</body></html>")
    return "".join(parts)


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------
class StatusUpdate(BaseModel):
    status: str

class FeedbackNote(BaseModel):
    feedback_text: str
    feedback_channel: str = "none"  # email | call | none

class SuperfolioUpdate(BaseModel):
    url: str

class BulkApplyRequest(BaseModel):
    job_ids: list[int]
    resume_id: Optional[int] = None

class ApplyRequest(BaseModel):
    resume_id: Optional[int] = None
    superfolio_url: Optional[str] = None


# ------------------------------------------------------------------
# Frontend routes
# ------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    return templates.TemplateResponse("history.html", {"request": request})


# ------------------------------------------------------------------
# Jobs API
# ------------------------------------------------------------------
@app.get("/api/jobs")
async def get_jobs(
    page: int = 1,
    per_page: int = 30,
    source: Optional[str] = None,    # comma-separated sources
    location: Optional[str] = None,  # comma-separated city names
    remote: Optional[bool] = None,
    ai_skills: Optional[bool] = None,
    search: Optional[str] = None,
    archived: bool = False,
):
    conn = get_connection()

    conditions = ["is_archived = ?"]
    params: list = [1 if archived else 0]

    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            placeholders = ",".join("?" * len(sources))
            conditions.append(f"source IN ({placeholders})")
            params.extend(sources)
    if location:
        locs = [l.strip() for l in location.split(",") if l.strip()]
        if locs:
            loc_conds = " OR ".join(["location LIKE ?" for _ in locs])
            conditions.append(f"({loc_conds})")
            params.extend([f"%{l}%" for l in locs])
    if remote is not None:
        conditions.append("remote = ?")
        params.append(1 if remote else 0)
    if ai_skills is not None:
        conditions.append("ai_skills_needed = ?")
        params.append(1 if ai_skills else 0)
    if search:
        conditions.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    # Apply saved negative keywords
    neg_rows = conn.execute("SELECT keyword FROM negative_keywords").fetchall()
    for nk in neg_rows:
        conditions.append("title NOT LIKE ?")
        params.append(f"%{nk['keyword']}%")

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT id, title, company, location, remote, employment_type,
               salary_min, salary_max, salary_currency, url, source,
               ai_skills_needed, ai_skills_tags,
               visa_sponsorship, visa_tags,
               scraped_at, last_seen_at, closed_at
        FROM jobs WHERE {where}
        ORDER BY scraped_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()

    conn.close()

    jobs = []
    for row in rows:
        d = dict(row)
        if d.get("ai_skills_tags"):
            d["ai_skills_tags"] = json.loads(d["ai_skills_tags"])
        if d.get("visa_tags"):
            d["visa_tags"] = json.loads(d["visa_tags"])
        # Check if already applied
        conn2 = get_connection()
        app_row = conn2.execute(
            "SELECT status FROM applications WHERE job_id = ?", (d["id"],)
        ).fetchone()
        conn2.close()
        d["application_status"] = app_row["status"] if app_row else None
        jobs.append(d)

    return {
        "jobs": jobs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    d = dict(row)
    if d.get("ai_skills_tags"):
        d["ai_skills_tags"] = json.loads(d["ai_skills_tags"])
    if d.get("visa_tags"):
        d["visa_tags"] = json.loads(d["visa_tags"])
    return d


# ------------------------------------------------------------------
# Resume API
# ------------------------------------------------------------------
@app.post("/api/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
):
    """Upload a .docx resume and convert to HTML. PDF generation not available in hosted version."""
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")

    file_bytes = await file.read()
    html_content = docx_to_html(file_bytes)

    conn = get_connection()
    last = conn.execute("SELECT MAX(version) as v FROM resumes").fetchone()
    version = (last["v"] or 0) + 1
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("UPDATE resumes SET is_active = 0")
    cursor = conn.execute(
        "INSERT INTO resumes (version, label, html_content, created_at, is_active) VALUES (?,?,?,?,1)",
        (version, label, html_content, now),
    )
    resume_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "resume_id": resume_id,
        "version": version,
        "label": label,
    }


@app.get("/api/resume/versions")
async def list_resume_versions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, version, label, local_path, created_at, is_active FROM resumes ORDER BY version DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/resume/{resume_id}/pdf")
async def serve_pdf(resume_id: int):
    """PDF generation is not available in the hosted version (requires Playwright)."""
    raise HTTPException(status_code=501, detail="PDF generation is not available in the hosted version.")


# ------------------------------------------------------------------
# Application API
# ------------------------------------------------------------------
@app.post("/api/apply/{job_id}")
async def apply(job_id: int, body: ApplyRequest):
    try:
        record = apply_to_job(job_id, body.resume_id, body.superfolio_url)
        return record
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/apply/bulk")
async def bulk_apply(request: BulkApplyRequest, background_tasks: BackgroundTasks):
    """
    Apply to multiple jobs. Skips already-applied jobs silently.
    Returns counts of applied, skipped.
    """
    results = {"applied": [], "skipped": [], "errors": []}

    for job_id in request.job_ids:
        try:
            record = apply_to_job(job_id, request.resume_id)
            results["applied"].append({"job_id": job_id, "app_id": record["id"]})
        except ValueError as e:
            if "Already applied" in str(e):
                results["skipped"].append({"job_id": job_id, "reason": str(e)})
            else:
                results["errors"].append({"job_id": job_id, "error": str(e)})

    return results


@app.get("/api/applications")
async def get_applications(status: Optional[str] = None, limit: int = 50):
    return list_applications(status_filter=status, limit=limit)


@app.put("/api/applications/{app_id}/status")
async def update_application_status(app_id: int, body: StatusUpdate):
    try:
        return update_status(app_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/applications/{app_id}/feedback")
async def add_application_feedback(app_id: int, body: FeedbackNote):
    try:
        return add_feedback(app_id, body.feedback_text, body.feedback_channel)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/api/applications/{app_id}/superfolio")
async def update_superfolio(app_id: int, body: SuperfolioUpdate):
    try:
        return set_superfolio_url(app_id, body.url)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ------------------------------------------------------------------
# Analytics
# ------------------------------------------------------------------
@app.get("/api/analytics")
async def analytics():
    return rejection_analytics()


# ------------------------------------------------------------------
# Scrape trigger
# ------------------------------------------------------------------
@app.post("/api/scrape/run")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    sources: Optional[str] = None,  # comma-separated
    tier: int = 1,
):
    """Trigger a background scrape job."""
    def run_scrape(source_list, tier_val):
        from scrape_jobs import scrape
        scrape(sources_to_run=source_list, tier=tier_val)

    source_list = [s.strip() for s in sources.split(",")] if sources else None
    background_tasks.add_task(run_scrape, source_list, tier)
    return {"status": "scraping started", "sources": source_list or f"tier-{tier} defaults"}


# ------------------------------------------------------------------
# Scrape stats
# ------------------------------------------------------------------
@app.get("/api/scrape/stats")
async def scrape_stats():
    """Return per-source job counts and last scraped timestamp."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT source, COUNT(*) as count, MAX(scraped_at) as last_scraped
        FROM jobs WHERE is_archived = 0
        GROUP BY source ORDER BY source
    """).fetchall()
    conn.close()
    return {"sources": [dict(r) for r in rows]}


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------
@app.get("/api/statuses")
async def get_statuses():
    return {"preset_statuses": PRESET_STATUSES}


@app.get("/api/locations")
async def get_locations():
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT location FROM jobs WHERE location IS NOT NULL AND location != '' AND is_archived = 0 ORDER BY location"
    ).fetchall()
    conn.close()
    locs = sorted({r["location"].strip() for r in rows if r["location"] and r["location"].strip()})
    return {"locations": locs}


@app.get("/api/sources")
async def get_sources():
    from scrape_jobs import FIRECRAWL_SOURCES, NATIVE_SOURCES
    all_sources = {**FIRECRAWL_SOURCES, **NATIVE_SOURCES}
    return {
        "sources": [
            {"name": k, "region": v.get("region", "global")}
            for k, v in all_sources.items()
        ]
    }


# ------------------------------------------------------------------
# Negative keywords CRUD
# ------------------------------------------------------------------
@app.get("/api/keywords/negative")
async def get_negative_keywords():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, keyword FROM negative_keywords ORDER BY keyword"
    ).fetchall()
    conn.close()
    return {"keywords": [dict(r) for r in rows]}


class KeywordBody(BaseModel):
    keyword: str


@app.post("/api/keywords/negative")
async def add_negative_keyword(body: KeywordBody):
    kw = body.keyword.strip().lower()
    if not kw:
        raise HTTPException(status_code=400, detail="keyword cannot be empty")
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO negative_keywords (keyword, created_at) VALUES (?, ?)",
            (kw, now),
        )
        conn.commit()
    except Exception:
        raise HTTPException(status_code=409, detail="keyword already exists")
    finally:
        conn.close()
    return {"keyword": kw}


@app.delete("/api/keywords/negative/{keyword_id}")
async def delete_negative_keyword(keyword_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM negative_keywords WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()
    return {"deleted": keyword_id}


@app.get("/health")
async def health():
    return {"status": "ok", "db": str(DB_PATH)}
