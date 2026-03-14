# Workflow: Scrape Job Listings

## Objective
Scrape product design job listings from 19 sources (global + India), deduplicate, tag AI-skill requirements, and persist to the local SQLite database. Keep the job feed fresh and accurate.

## Inputs Required
- `FIRECRAWL_API_KEY` set in `.env`
- Sources to scrape (default: all 19)

## Tool
`tools/scrape_jobs.py`

## Procedure

### Step 1 — Run initial scrape
```bash
python tools/scrape_jobs.py
```
This scrapes all 19 sources. For selective sources:
```bash
python tools/scrape_jobs.py --sources linkedin naukri dribbble
```

### Step 2 — Validate stale listings (run every 12h)
```bash
python tools/scrape_jobs.py --validate-stale
```
Re-checks job detail pages for listings seen in the last 7 days. Marks confirmed-closed jobs with `closed_at` timestamp.

### Step 3 — Verify results
Check the DB for new entries:
```bash
sqlite3 .tmp/jobs.db "SELECT source, COUNT(*) as count FROM jobs WHERE is_archived=0 GROUP BY source ORDER BY count DESC;"
```
Verify no duplicate fingerprints:
```bash
sqlite3 .tmp/jobs.db "SELECT fingerprint, COUNT(*) c FROM jobs GROUP BY fingerprint HAVING c > 1;"
```

## Deduplication Logic
- Fingerprint = `MD5(company_lower + title_lower + location_lower)`
- If fingerprint exists → update `last_seen_at` only (no duplicate insert)
- If fingerprint is new → full insert with AI skills detection

## AI Skills Tagging
Strong signals (always tag): LLM, generative AI, prompt engineering, AI/ML, RAG, fine-tuning, GPT, Claude, DALL-E, diffusion model
Weak signals (tag if 2+ present): automation, AI tools, data-driven, intelligent, NLP

Tooltip text stored in `ai_skills_tags` JSON column shows exact triggering terms.

## Scheduling (optional)
Set up a cron to run every 4h:
```bash
python tools/scrape_jobs.py          # every 4h — full scrape
python tools/scrape_jobs.py --validate-stale  # every 12h — freshness check
```

## Error Handling
- Rate limit (429/503): exponential backoff 2s → 4s → 8s, max 3 retries
- Zero jobs extracted: logged to `scrape_errors` table, scraper continues to next source
- Network failure: logged, no crash
- Check errors: `sqlite3 .tmp/jobs.db "SELECT * FROM scrape_errors ORDER BY occurred_at DESC LIMIT 20;"`

## Known Constraints
- LinkedIn actively blocks scrapers — if 403 errors persist, consider LinkedIn RSS or job email alerts as fallback
- Indeed may require JavaScript rendering — Firecrawl handles this via its built-in browser
- Salary parsing handles both USD ($) and INR (₹, LPA) formats
- For India sources (Naukri, Foundit, TimesJobs), salary is often in LPA — displayed as ₹

## Outputs
- New jobs inserted into `jobs` table in `.tmp/jobs.db`
- Job feed immediately available via `GET /api/jobs`
