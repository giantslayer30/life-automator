"""
scrape_jobs.py — Multi-source job scraper.

Two types of sources:
  Firecrawl sources  — use the Firecrawl API (~1 credit each)
  Native sources     — free public APIs / RSS feeds (0 credits)

Usage:
    python tools/scrape_jobs.py                        # tier-1 sources (default)
    python tools/scrape_jobs.py --tier 2               # all sources
    python tools/scrape_jobs.py --sources jsearch remote_ok
    python tools/scrape_jobs.py --validate-stale       # re-check recent listings

Credit budget (3 000 credits/month):
    Tier-1 Firecrawl sources = 5 credits/run
    Run up to 3×/day, 30 days → ~450 credits/month (15 % of budget)
    All native sources cost 0 credits.
"""

import argparse
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests
from dotenv import load_dotenv

from db_init import get_connection, init_db, DB_PATH

load_dotenv(Path(__file__).parent.parent / ".env")

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"

# ------------------------------------------------------------------
# Title relevance filter — only keep design-related jobs
# ------------------------------------------------------------------
DESIGN_TITLE_KEYWORDS = [
    "design", "designer", "ux", "ui/ux", "ui ", " ui,", "user experience",
    "user interface", "product design", "visual", "interaction design",
    "motion", "creative director", "art director", "brand", "graphic",
    "illustration", "figma", "sketch", "service design",
]

# ------------------------------------------------------------------
# Negative keywords — jobs whose titles contain ANY of these are
# dropped even if they match DESIGN_TITLE_KEYWORDS above.
# Edit this list freely; re-run the scraper to apply changes.
# ------------------------------------------------------------------
NEGATIVE_TITLE_KEYWORDS = [
    "graphic designer",
    "graphic design intern",
    "fashion",
    "interior design",
    "game designer",
    "game design",
    "instructional designer",
    "flyer",
    "print designer",
]


def load_negative_keywords() -> list:
    """Load user-managed blocked keywords from DB, falling back to hardcoded list."""
    try:
        conn = get_connection()
        rows = conn.execute("SELECT keyword FROM negative_keywords").fetchall()
        conn.close()
        if rows:
            return [r["keyword"].lower() for r in rows]
    except Exception:
        pass
    return [kw.lower() for kw in NEGATIVE_TITLE_KEYWORDS]


GEO_EXCLUSION_PATTERNS = [
    "us only", "u.s. only", "usa only", "united states only",
    "eu only", "europe only", "european union only",
    "uk only", "united kingdom only",
    "canada only", "australia only",
    "us-based only", "us based only",
    "must be located in the us", "must be based in the us",
    "us citizens only", "us residents only",
]


def is_geo_excluded(text: str) -> bool:
    """Return True if the job is restricted to a region that excludes India."""
    lowered = text.lower()
    return any(pat in lowered for pat in GEO_EXCLUSION_PATTERNS)


def is_design_job(title: str, negative_kws: list = None) -> bool:
    t = title.lower()
    blocklist = negative_kws if negative_kws is not None else NEGATIVE_TITLE_KEYWORDS
    if any(neg in t for neg in blocklist):
        return False
    return any(kw in t for kw in DESIGN_TITLE_KEYWORDS)


# ------------------------------------------------------------------
# Visa / sponsorship / relocation signals
# ------------------------------------------------------------------
VISA_SIGNALS = [
    "visa sponsorship", "sponsor visa", "work authorization", "work visa",
    "h1b", "h-1b", "work permit", "sponsorship available", "we sponsor",
    "relocation assistance", "relocation package", "relocation support",
    "relocation stipend", "open to relocation", "willing to relocate",
    "global hiring", "international candidates",
]

# Phrases that negate visa signals — if found near a visa keyword, skip it
VISA_NEGATIONS = [
    "no visa sponsorship", "not available", "no sponsorship",
    "does not sponsor", "do not sponsor", "will not sponsor",
    "cannot sponsor", "unable to sponsor", "not sponsor",
    "without sponsorship", "no relocation", "not eligible for visa",
    "visa sponsorship is not", "visa sponsorship not",
    "sponsorship not available", "sponsorship is not available",
    "no work visa", "not provide visa", "doesn't sponsor",
    "don't sponsor", "won't sponsor",
]


def detect_visa(text: str) -> tuple:
    """Return (tagged, triggering_terms) for visa/relocation signals.

    Checks for negation phrases first — if the text says
    'no visa sponsorship' or 'does not sponsor', it's not tagged.
    """
    lowered = text.lower()
    # Check negations first
    if any(neg in lowered for neg in VISA_NEGATIONS):
        return False, []
    found = [s for s in VISA_SIGNALS if s in lowered]
    return bool(found), found


# ------------------------------------------------------------------
# AI Skills taxonomy
# ------------------------------------------------------------------
AI_STRONG_SIGNALS = [
    "llm", "large language model", "generative ai", "gen ai", "genai",
    "prompt engineering", "prompt engineer", "ai/ml", "machine learning",
    "rag", "retrieval augmented", "fine-tuning", "fine tuning",
    "diffusion model", "stable diffusion", "midjourney", "dall-e",
    "gpt", "claude", "gemini", "ai researcher", "ai product",
]
AI_WEAK_SIGNALS = [
    "automation", "ai tools", "data-driven", "ai-powered",
    "intelligent", "predictive", "neural", "computer vision",
    "natural language processing", "nlp",
]


def detect_ai_skills(text: str) -> tuple:
    """Return (tagged, triggering_terms) for a job description."""
    lowered = text.lower()
    found_strong = [s for s in AI_STRONG_SIGNALS if s in lowered]
    found_weak   = [s for s in AI_WEAK_SIGNALS   if s in lowered]
    triggering   = found_strong[:]
    if len(found_weak) >= 2:
        triggering.extend(found_weak[:2])
    tagged = bool(found_strong) or len(found_weak) >= 2
    return tagged, triggering


# ------------------------------------------------------------------
# Fingerprint for deduplication
# ------------------------------------------------------------------
def job_fingerprint(company: str, title: str, location: str) -> str:
    raw = f"{company.lower().strip()}{title.lower().strip()}{location.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


# ------------------------------------------------------------------
# Firecrawl wrapper with exponential backoff
# ------------------------------------------------------------------
def firecrawl_scrape(url: str, max_retries: int = 3) -> Optional[dict]:
    """Scrape a URL via Firecrawl API. Returns parsed response or None."""
    if not FIRECRAWL_API_KEY:
        raise EnvironmentError("FIRECRAWL_API_KEY not set in .env")

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": ["extract", "markdown"],
        "actions": [{"type": "wait", "milliseconds": 2000}],
        "extract": {
            "prompt": "Extract all job listings from this page. For each job, capture the FULL description text (not a summary). Pay special attention to any mentions of visa sponsorship, relocation assistance, work authorization, H1B, or international candidates.",
            "schema": {
                "type": "object",
                "properties": {
                    "jobs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title":           {"type": "string"},
                                "company":         {"type": "string"},
                                "location":        {"type": "string"},
                                "remote":          {"type": "boolean"},
                                "employment_type": {"type": "string"},
                                "salary":          {"type": "string"},
                                "description":     {"type": "string", "description": "Full job description including requirements, responsibilities, benefits, and any visa/relocation details. Do NOT summarize."},
                                "url":             {"type": "string"},
                                "visa_sponsorship": {"type": "boolean", "description": "True if the listing mentions visa sponsorship, work authorization, H1B, relocation assistance, relocation package, or hiring international candidates."},
                                "experience_years": {"type": "string", "description": "Years of experience required, e.g. '3+', '5-7'. Empty if not stated."},
                            },
                        },
                    }
                },
            }
        },
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{FIRECRAWL_BASE_URL}/scrape",
                headers=headers,
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (429, 503):
                wait = 2 ** attempt
                print(f"  [rate limit {resp.status_code}] retrying in {wait}s…")
                time.sleep(wait)
            else:
                print(f"  [error {resp.status_code}] {url}")
                return None
        except requests.RequestException as e:
            print(f"  [request error] {e}")
            time.sleep(2 ** attempt)

    return None


# ==================================================================
# Native scrapers — free, no Firecrawl credits
# ==================================================================

def scrape_remoteok() -> list:
    """Remote OK public JSON API. No auth needed."""
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-scraper/1.0)"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # data[0] is a notice object; actual jobs start at index 1
        all_jobs = data[1:] if len(data) > 1 else []

        design_tags = {
            "design", "ux", "ui", "product", "product-design",
            "figma", "sketch", "user-experience", "graphic-design",
        }
        results = []
        for job in all_jobs:
            tags = {t.lower().replace(" ", "-") for t in (job.get("tags") or [])}
            if not tags.intersection(design_tags):
                continue

            lo = job.get("salary_min")
            hi = job.get("salary_max")
            salary = None
            if lo and hi:
                salary = f"${int(lo):,}–${int(hi):,}"
            elif lo:
                salary = f"${int(lo):,}+"

            results.append({
                "title":           job.get("position") or "",
                "company":         job.get("company") or "",
                "location":        job.get("location") or "Remote",
                "remote":          True,
                "employment_type": "full-time",
                "salary":          salary,
                "description":     job.get("description") or "",
                "url":             job.get("url") or f"https://remoteok.com/l/{job.get('slug', '')}",
            })
        return results
    except Exception as e:
        print(f"  [error] {e}")
        return []


def scrape_weworkremotely() -> list:
    """We Work Remotely RSS feed. No auth needed."""
    try:
        resp = requests.get(
            "https://weworkremotely.com/categories/remote-design-jobs.rss",
            timeout=30,
        )
        resp.raise_for_status()
        root    = ET.fromstring(resp.content)
        channel = root.find("channel")
        items   = channel.findall("item") if channel else []

        results = []
        for item in items:
            # Title format: "Company Name: Job Title [Anywhere]"
            title_raw = (item.findtext("title") or "").strip()
            link      = item.findtext("link") or ""
            desc      = item.findtext("description") or ""

            company = ""
            title   = title_raw
            if ": " in title_raw:
                company, title = title_raw.split(": ", 1)
                company = company.strip()
                # Strip trailing "[Anywhere]" bracket
                title = re.sub(r"\s*\[.*?\]\s*$", "", title).strip()

            results.append({
                "title":           title,
                "company":         company,
                "location":        "Remote",
                "remote":          True,
                "employment_type": "full-time",
                "salary":          None,
                "description":     desc,
                "url":             link,
            })
        return results
    except Exception as e:
        print(f"  [error] {e}")
        return []


def scrape_himalayas() -> list:
    """Himalayas public jobs API. No auth needed. Runs multiple queries."""
    queries = [
        {"q": "product designer", "limit": 50},
        {"q": "UX designer India", "limit": 30},
        {"q": "UI designer India", "limit": 30},
    ]
    all_results = []
    for params in queries:
        try:
            resp = requests.get(
                "https://himalayas.app/api/jobs",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data     = resp.json()
            jobs_raw = data.get("jobs") if isinstance(data, dict) else data
            if not isinstance(jobs_raw, list):
                continue

            for job in jobs_raw:
                company_raw = job.get("company") or {}
                company = (
                    company_raw.get("name")
                    if isinstance(company_raw, dict)
                    else str(company_raw)
                )
                loc = job.get("locationRestrictions") or job.get("location") or ""
                is_remote = bool(job.get("remote")) or "remote" in loc.lower()
                all_results.append({
                    "title":           job.get("title") or "",
                    "company":         company or "",
                    "location":        loc or ("Remote" if is_remote else ""),
                    "remote":          is_remote,
                    "employment_type": (job.get("jobType") or "").lower() or "full-time",
                    "salary":          None,
                    "description":     job.get("description") or "",
                    "url":             job.get("applicationUrl") or job.get("url") or "",
                })
        except Exception as e:
            print(f"  [error] {e}")
    return all_results


def _jsearch_query(key: str, query: str, location: str = None, remote_only: bool = False) -> list:
    """Run a single JSearch API query and return normalised job dicts."""
    params = {
        "query":       query,
        "page":        "1",
        "num_pages":   "2",
        "date_posted": "3days",
    }
    if remote_only:
        params["remote_jobs_only"] = "true"

    try:
        resp = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={
                "X-RapidAPI-Key":  key,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            },
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        jobs_raw = resp.json().get("data") or []
    except Exception as e:
        print(f"    [jsearch error] {e}")
        return []

    results = []
    for job in jobs_raw:
        lo = job.get("job_min_salary")
        hi = job.get("job_max_salary")
        salary = None
        if lo and hi:
            period = job.get("job_salary_period") or "year"
            salary = f"${lo:,.0f}–${hi:,.0f}/{period}"

        results.append({
            "title":           job.get("job_title") or "",
            "company":         job.get("employer_name") or "",
            "location":        (
                job.get("job_city")
                or job.get("job_state")
                or job.get("job_country")
                or "Remote"
            ),
            "remote":          bool(job.get("job_is_remote")),
            "employment_type": (job.get("job_employment_type") or "").lower(),
            "salary":          salary,
            "description":     job.get("job_description") or "",
            "url":             job.get("job_apply_link") or job.get("job_google_link") or "",
        })
    return results


def scrape_jsearch() -> list:
    """JSearch API — aggregates LinkedIn + Indeed + Glassdoor.

    Runs multiple queries:
      1. Product designer remote jobs (global)
      2. Product designer jobs in India (not necessarily remote)
      3. UX designer jobs in India
      4. LinkedIn "hiring" posts mentioning product/UX design in India

    Requires RAPIDAPI_KEY in .env.
    Free tier: 500 requests/month.
    Sign up: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
    """
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        print("  [skip] RAPIDAPI_KEY not set in .env — get a free key at rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
        return []

    all_results = []

    queries = [
        # LinkedIn/Indeed jobs in India (including non-remote)
        {"query": "product designer in India", "label": "product designer India"},
        {"query": "UX designer in India", "label": "UX designer India"},
        # Remote jobs globally
        {"query": "product designer", "label": "product designer remote", "remote_only": True},
        # LinkedIn hiring posts — people posting "hiring" for design roles
        {"query": "hiring product designer India", "label": "hiring posts India"},
        {"query": "hiring UX designer India", "label": "hiring UX India"},
        # Visa sponsorship design jobs
        {"query": "product designer visa sponsorship", "label": "visa sponsorship jobs"},
    ]

    for q in queries:
        print(f"    [{q['label']}] querying…")
        results = _jsearch_query(key, q["query"], remote_only=q.get("remote_only", False))
        print(f"    [{q['label']}] {len(results)} results")
        all_results.extend(results)
        time.sleep(0.5)  # respect rate limits

    return all_results


def scrape_visa_search() -> list:
    """Firecrawl web search — discover career pages and job boards
    with visa sponsorship + product design roles.

    Step 1: Search the web for relevant pages (free search credits).
    Step 2: Scrape the top results via Firecrawl extract (~1 credit each).
    """
    if not FIRECRAWL_API_KEY:
        print("  [skip] FIRECRAWL_API_KEY not set")
        return []

    # Target company career pages and individual postings, NOT aggregators
    # (Indeed/ZipRecruiter/LinkedIn block scraping)
    search_queries = [
        'senior product designer visa sponsorship -site:indeed.com -site:ziprecruiter.com -site:linkedin.com -site:glassdoor.com',
        'product designer relocation sponsorship careers -site:indeed.com -site:ziprecruiter.com -site:linkedin.com -site:glassdoor.com',
        '"product designer" "visa sponsorship" site:lever.co OR site:greenhouse.io OR site:ashbyhq.com OR site:jobs.lever.co',
        '"product designer" "relocation" hiring site:lever.co OR site:greenhouse.io OR site:ashbyhq.com OR site:workable.com',
    ]

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    # Step 1: Collect unique URLs from search results
    seen_urls = set()
    urls_to_scrape = []

    for query in search_queries:
        try:
            resp = requests.post(
                f"{FIRECRAWL_BASE_URL}/search",
                headers=headers,
                json={"query": query, "limit": 3},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or []
                for item in data:
                    url = item.get("url") or ""
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        urls_to_scrape.append(url)
                        print(f"    [found] {item.get('title', '')[:60]}")
            else:
                print(f"    [error {resp.status_code}] search: {query[:50]}")
        except Exception as e:
            print(f"    [error] {e}")
        time.sleep(0.5)

    # Cap at 5 pages to limit credit usage
    urls_to_scrape = urls_to_scrape[:5]
    print(f"  [visa search] Scraping {len(urls_to_scrape)} pages…")

    # Step 2: Scrape each URL with Firecrawl extract
    all_jobs = []
    for url in urls_to_scrape:
        print(f"    [scrape] {url[:70]}…")
        result = firecrawl_scrape(url)
        if not result:
            continue
        jobs_raw = []
        if "extract" in result and isinstance(result["extract"], dict):
            jobs_raw = result["extract"].get("jobs") or []
        elif "data" in result and isinstance(result["data"], dict):
            jobs_raw = result["data"].get("extract", {}).get("jobs") or []

        # Tag all jobs from this source with visa by default
        # (they came from a visa sponsorship search)
        for job in jobs_raw:
            if job.get("visa_sponsorship") is None:
                job["visa_sponsorship"] = True
        all_jobs.extend(jobs_raw)
        print(f"    [ok] {len(jobs_raw)} jobs extracted")
        time.sleep(1)

    print(f"  [visa search] {len(all_jobs)} total jobs from {len(urls_to_scrape)} pages")
    return all_jobs


# ------------------------------------------------------------------
# Source registries
# ------------------------------------------------------------------
FIRECRAWL_SOURCES: dict = {
    # ── Tier 1: reliable, design-specific ──
    "wellfound": {
        "url": "https://wellfound.com/role/r/product-designer",
        "region": "global", "tier": 1,
    },
    "naukri": {
        "url": "https://www.naukri.com/product-designer-jobs",
        "region": "india", "tier": 1,
    },
    "arc_dev": {
        "url": "https://arc.dev/remote-jobs/product-designer",
        "region": "global", "tier": 1,
    },
    # ── Tier 2: opt-in, less reliable or lower volume ──
    "glassdoor": {
        "url": "https://www.glassdoor.com/Job/product-designer-jobs-SRCH_KO0,16.htm",
        "region": "global", "tier": 2,
    },
    "behance": {
        "url": "https://www.behance.net/joblist?field=ux-ui-design",
        "region": "global", "tier": 2,
    },
    "coroflot": {
        "url": "https://www.coroflot.com/jobs/listings",
        "region": "global", "tier": 2,
    },
    "aiga": {
        "url": "https://designjobs.aiga.org/#sort=relevancy",
        "region": "global", "tier": 2,
    },
    "foundit": {
        "url": "https://www.foundit.in/srp/results?query=product+designer",
        "region": "india", "tier": 2,
    },
    "shine": {
        "url": "https://www.shine.com/job-search/ux-designer-jobs",
        "region": "india", "tier": 2,
    },
    "timesjobs": {
        "url": "https://www.timesjobs.com/candidate/job-search.html?searchType=personalizedSearch&from=submit&txtKeywords=product+designer",
        "region": "india", "tier": 2,
    },
}

# Native sources cost 0 Firecrawl credits
# jsearch (LinkedIn) is first — always scrape LinkedIn before anything else
NATIVE_SOURCES: dict = {
    "jsearch": {
        "fn": scrape_jsearch,
        "label": "JSearch / LinkedIn + Indeed (RapidAPI free tier)",
        "region": "global", "tier": 1,
    },
    "visa_search": {
        "fn": scrape_visa_search,
        "label": "Visa Sponsorship Search (Firecrawl web search)",
        "region": "global", "tier": 1,
    },
    "remote_ok": {
        "fn": scrape_remoteok,
        "label": "Remote OK (public JSON API, free)",
        "region": "global", "tier": 1,
    },
    "we_work_remotely": {
        "fn": scrape_weworkremotely,
        "label": "We Work Remotely (RSS feed, free)",
        "region": "global", "tier": 1,
    },
    "himalayas": {
        "fn": scrape_himalayas,
        "label": "Himalayas (public JSON API, free)",
        "region": "global", "tier": 1,
    },
}


# ------------------------------------------------------------------
# Parse salary string → (min, max, currency)
# ------------------------------------------------------------------
def parse_salary(salary_str: Optional[str]) -> Tuple[Optional[int], Optional[int], str]:
    if not salary_str:
        return None, None, "USD"
    currency = "INR" if any(c in salary_str for c in ["₹", "INR", "LPA", "lpa"]) else "USD"
    numbers  = re.findall(r"[\d,]+", salary_str.replace(",", ""))
    nums     = [int(n.replace(",", "")) for n in numbers if n]
    if len(nums) >= 2:
        return min(nums), max(nums), currency
    elif len(nums) == 1:
        return nums[0], nums[0], currency
    return None, None, currency


# ------------------------------------------------------------------
# Persist jobs to DB
# ------------------------------------------------------------------
def upsert_jobs(jobs: list, source: str, conn, negative_kws: list = None) -> tuple:
    """Insert new jobs or update last_seen. Returns (inserted, updated)."""
    now = datetime.now(timezone.utc).isoformat()
    inserted = updated = 0

    for job in jobs:
        title   = (job.get("title")   or "").strip()
        company = (job.get("company") or "").strip()
        location = (job.get("location") or "").strip()

        if not title or not company:
            continue

        # Drop irrelevant jobs (e.g. WWR mixing in non-design roles)
        if not is_design_job(title, negative_kws):
            continue

        # Drop jobs geo-restricted to regions excluding India
        description = job.get("description") or ""
        if is_geo_excluded(f"{title} {description} {location}"):
            continue

        fp = job_fingerprint(company, title, location)
        ai_tagged, ai_terms   = detect_ai_skills(description)
        visa_tagged, visa_terms = detect_visa(f"{title} {description}")
        # Also pick up Firecrawl-extracted visa flag as fallback
        if not visa_tagged and job.get("visa_sponsorship"):
            visa_tagged = True
            visa_terms = ["extracted by firecrawl"]
        salary_min, salary_max, currency = parse_salary(job.get("salary"))

        existing = conn.execute(
            "SELECT id FROM jobs WHERE fingerprint = ?", (fp,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE jobs SET last_seen_at = ? WHERE fingerprint = ?",
                (now, fp),
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO jobs
                    (fingerprint, title, company, location, remote,
                     employment_type, salary_min, salary_max, salary_currency,
                     description, url, source,
                     ai_skills_needed, ai_skills_tags,
                     visa_sponsorship, visa_tags,
                     scraped_at, last_seen_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fp, title, company, location,
                    1 if job.get("remote") else 0,
                    job.get("employment_type"),
                    salary_min, salary_max, currency,
                    description,
                    job.get("url") or "",
                    source,
                    1 if ai_tagged else 0,
                    json.dumps(ai_terms) if ai_terms else None,
                    1 if visa_tagged else 0,
                    json.dumps(visa_terms) if visa_terms else None,
                    now, now,
                ),
            )
            inserted += 1

    conn.commit()
    return inserted, updated


# ------------------------------------------------------------------
# Log scrape errors
# ------------------------------------------------------------------
def log_error(source: str, url: str, status_code: Optional[int], message: str, conn) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO scrape_errors (source, url, status_code, error_message, occurred_at) VALUES (?,?,?,?,?)",
        (source, url, status_code, message, now),
    )
    conn.commit()


# ------------------------------------------------------------------
# Archive stale listings
# ------------------------------------------------------------------
def archive_old_jobs(conn, max_age_days: int = 3) -> int:
    """Archive jobs not refreshed within max_age_days. Returns count archived."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    result = conn.execute(
        "UPDATE jobs SET is_archived = 1 WHERE last_seen_at < ? AND is_archived = 0",
        (cutoff,),
    )
    conn.commit()
    return result.rowcount


# ------------------------------------------------------------------
# Validate stale listings (<7d) — check if job page is still live
# ------------------------------------------------------------------
def validate_stale_listings(conn) -> None:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    stale  = conn.execute(
        "SELECT id, url, title, company FROM jobs WHERE last_seen_at > ? AND closed_at IS NULL AND is_archived = 0",
        (cutoff,),
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    print(f"[validate] Checking {len(stale)} active listings…")
    for row in stale:
        try:
            resp = requests.head(row["url"], timeout=10, allow_redirects=True)
            if resp.status_code == 404:
                conn.execute(
                    "UPDATE jobs SET closed_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
                print(f"  [closed] {row['title']} @ {row['company']}")
        except Exception:
            pass
    conn.commit()


# ------------------------------------------------------------------
# Main scrape loop
# ------------------------------------------------------------------
def scrape(sources_to_run: Optional[list] = None, tier: int = 1, validate_stale: bool = False) -> None:
    init_db()
    conn = get_connection()

    # Merge both registries; native sources first (jsearch/LinkedIn runs first)
    all_sources = {}
    for k, v in NATIVE_SOURCES.items():
        all_sources[k] = {**v, "_method": "native"}
    for k, v in FIRECRAWL_SOURCES.items():
        all_sources[k] = {**v, "_method": "firecrawl"}

    if sources_to_run:
        targets = [s for s in sources_to_run if s in all_sources]
        unknown = [s for s in sources_to_run if s not in all_sources]
        for u in unknown:
            print(f"[warning] Unknown source '{u}', skipping")
    else:
        targets = [k for k, v in all_sources.items() if v.get("tier", 1) <= tier]

    fc_count  = sum(1 for k in targets if all_sources[k]["_method"] == "firecrawl")
    nat_count = sum(1 for k in targets if all_sources[k]["_method"] == "native")
    print(
        f"[scrape] {len(targets)} source(s) — "
        f"{fc_count} Firecrawl (~{fc_count} credits), "
        f"{nat_count} native (free)\n"
        f"         sources: {', '.join(targets)}\n"
    )

    total_inserted = total_updated = 0
    negative_kws = load_negative_keywords()
    if negative_kws:
        print(f"[filter] Blocking titles containing: {', '.join(negative_kws)}\n")

    for name in targets:
        src    = all_sources[name]
        method = src["_method"]

        if method == "native":
            print(f"[{name}] {src.get('label', 'Native API')} …")
            jobs_raw = src["fn"]()

        else:  # firecrawl
            print(f"[{name}] Scraping {src['url']} …")
            result = firecrawl_scrape(src["url"])

            if not result:
                log_error(name, src["url"], None, "Firecrawl returned None", conn)
                print("  [failed] No data returned")
                continue

            jobs_raw = []
            if "extract" in result and isinstance(result["extract"], dict):
                jobs_raw = result["extract"].get("jobs") or []
            elif "data" in result and isinstance(result["data"], dict):
                jobs_raw = result["data"].get("extract", {}).get("jobs") or []

        if not jobs_raw:
            print(f"  [empty] No jobs extracted from {name}")
            if method == "firecrawl":
                log_error(name, src.get("url", ""), None, "Zero jobs extracted", conn)
            continue

        ins, upd = upsert_jobs(jobs_raw, name, conn, negative_kws)
        total_inserted += ins
        total_updated  += upd
        print(f"  [ok] +{ins} new, ~{upd} updated")
        time.sleep(1)  # polite delay

    print(f"\n[done] Total: +{total_inserted} new jobs, ~{total_updated} refreshed")

    archived = archive_old_jobs(conn, max_age_days=3)
    if archived:
        print(f"[archive] Removed {archived} stale job(s) older than 3 days")

    if validate_stale:
        validate_stale_listings(conn)

    conn.close()


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    all_names = list(FIRECRAWL_SOURCES.keys()) + list(NATIVE_SOURCES.keys())
    parser = argparse.ArgumentParser(
        description="Scrape job listings via Firecrawl + free native APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available sources: {', '.join(all_names)}",
    )
    parser.add_argument("--sources", nargs="+", metavar="SOURCE",
                        help="Specific sources to scrape")
    parser.add_argument("--tier", type=int, default=1,
                        help="Max source tier (1=default, 2=all). Default: 1")
    parser.add_argument("--validate-stale", action="store_true",
                        help="Re-check recent listings for closure (uses HEAD requests, no credits)")
    args = parser.parse_args()
    scrape(sources_to_run=args.sources, tier=args.tier, validate_stale=args.validate_stale)
