"""
ai_suggest.py — AI-powered resume analysis using the Claude API.

For each job application, this tool:
1. Strips PII from the resume text before sending to Claude
2. Analyzes resume against job description
3. Returns a match score + prioritized, one-click-style suggestions
4. Tags AI skills requirements with specific tooltip terms

Usage:
    python tools/ai_suggest.py --resume path/to/resume.txt --jd path/to/jd.txt
    python tools/ai_suggest.py --job-id 42  # pulls from DB
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ------------------------------------------------------------------
# PII stripping — remove before sending to Claude API
# ------------------------------------------------------------------
PII_PATTERNS = [
    # Phone numbers (international + Indian formats)
    (r'\+?[\d\s\-\(\)]{7,15}(?=\s|$|[,;])', "[PHONE]"),
    # Email addresses
    (r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b', "[EMAIL]"),
    # Indian PAN (ABCDE1234F)
    (r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', "[PAN]"),
    # Aadhaar (12-digit)
    (r'\b\d{4}\s?\d{4}\s?\d{4}\b', "[AADHAAR]"),
    # Physical address lines (heuristic: comma-separated with PIN/ZIP)
    (r'\b\d{6}\b', "[PINCODE]"),  # Indian PIN codes
    (r'\b\d{5}(?:-\d{4})?\b', "[ZIPCODE]"),  # US ZIP
    # Date of birth patterns
    (r'\bD\.?O\.?B\.?\s*[:\-]?\s*[\d\/\-\.]+', "[DOB]"),
    (r'\bborn\s+(?:on\s+)?[\d\/\-\.]+(?: \d{4})?', "[DOB]", re.IGNORECASE),
]


def strip_pii(text: str) -> str:
    """Remove personal identifiable information from resume text."""
    for pattern_args in PII_PATTERNS:
        if len(pattern_args) == 3:
            pattern, replacement, flags = pattern_args
            text = re.sub(pattern, replacement, text, flags=flags)
        else:
            pattern, replacement = pattern_args
            text = re.sub(pattern, replacement, text)
    return text


# ------------------------------------------------------------------
# Core analysis function
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert resume coach specializing in product design and UX roles.

Analyze the provided resume against a job description and return a JSON object with:
{
  "match_score": <integer 0-100>,
  "match_summary": "<one sentence explaining the score>",
  "suggestions": [
    {
      "id": "<unique string>",
      "section": "<Summary|Skills|Experience|Portfolio|Cover Letter>",
      "type": "<add|strengthen|remove|reorder>",
      "field": "<what to change, e.g. 'Skills section'>",
      "current": "<current wording or null if missing>",
      "suggested": "<exact suggested text>",
      "reason": "<why this matters for THIS specific JD, be specific>",
      "jd_mentions": <number of times this term/skill appears in JD>,
      "impact": "<high|medium|low>"
    }
  ],
  "ai_skills_gap": {
    "required": ["<list of AI skills JD mentions>"],
    "present_in_resume": ["<which ones candidate already has>"],
    "missing": ["<which ones to highlight or gain>"]
  },
  "tone_match": "<formal|startup|creative|technical>",
  "red_flags": ["<anything that might hurt the application>"]
}

Rules:
- Maximum 8 suggestions. Prioritize high-impact ones.
- Make suggestions SPECIFIC and actionable — not generic advice.
- "suggested" field must contain ready-to-use text, not instructions.
- Focus on UX/product design context.
- If a skill is mentioned 3+ times in JD and missing from resume, it MUST be a high-impact suggestion.
- Return ONLY valid JSON. No preamble, no markdown fences."""


def analyze_resume_vs_jd(
    resume_text: str,
    job_description: str,
    job_title: str = "",
    company: str = "",
    strip_pii_before_send: bool = True,
) -> dict:
    """
    Run Claude analysis on resume vs JD.
    Returns parsed JSON dict.
    """
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    if strip_pii_before_send:
        resume_text = strip_pii(resume_text)

    user_message = f"""JOB TITLE: {job_title}
COMPANY: {company}

--- JOB DESCRIPTION ---
{job_description[:4000]}

--- RESUME ---
{resume_text[:4000]}

Analyze this resume against the job description and return the JSON analysis."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wraps in them
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    return json.loads(raw)


# ------------------------------------------------------------------
# Format suggestions for frontend rendering
# ------------------------------------------------------------------
def format_suggestions_for_ui(analysis: dict) -> list[dict]:
    """
    Convert raw analysis into UI-ready suggestion chips.
    Sorted by impact: high → medium → low.
    """
    impact_order = {"high": 0, "medium": 1, "low": 2}
    suggestions = analysis.get("suggestions", [])
    sorted_suggestions = sorted(
        suggestions,
        key=lambda s: impact_order.get(s.get("impact", "low"), 2),
    )

    chips = []
    for s in sorted_suggestions:
        chips.append({
            "id": s.get("id"),
            "label": _make_chip_label(s),
            "section": s.get("section"),
            "type": s.get("type"),
            "suggested_text": s.get("suggested"),
            "reason": s.get("reason"),
            "jd_mentions": s.get("jd_mentions", 0),
            "impact": s.get("impact"),
            "badge_color": {"high": "red", "medium": "amber", "low": "blue"}.get(
                s.get("impact", "low"), "blue"
            ),
        })

    return chips


def _make_chip_label(suggestion: dict) -> str:
    """Generate a short, one-line chip label for the UI."""
    t = suggestion.get("type", "update")
    section = suggestion.get("section", "")
    field = suggestion.get("field", "")
    jd_n = suggestion.get("jd_mentions", 0)

    jd_context = f" (in JD {jd_n}×)" if jd_n >= 2 else ""

    if t == "add":
        suggested_preview = (suggestion.get("suggested") or "")[:40]
        return f"Add to {section}: \"{suggested_preview}…\"{jd_context}"
    elif t == "strengthen":
        return f"Strengthen {field}{jd_context}"
    elif t == "remove":
        return f"Remove from {section}: {field}"
    elif t == "reorder":
        return f"Reorder {section} — put {field} first"
    return f"Update {section}: {field}{jd_context}"


# ------------------------------------------------------------------
# DB-integrated analysis (pulls job + latest resume from DB)
# ------------------------------------------------------------------
def analyze_from_db(job_id: int) -> dict:
    """Load job description from DB, run analysis against active resume."""
    sys.path.insert(0, str(Path(__file__).parent))
    from db_init import get_connection

    conn = get_connection()

    job = conn.execute(
        "SELECT title, company, description FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()

    if not job:
        raise ValueError(f"Job ID {job_id} not found in database")

    resume = conn.execute(
        "SELECT html_content FROM resumes WHERE is_active = 1 ORDER BY version DESC LIMIT 1"
    ).fetchone()

    conn.close()

    if not resume or not resume["html_content"]:
        raise ValueError("No active resume found in database. Upload a resume first.")

    # Strip HTML tags for plain text analysis
    resume_text = re.sub(r"<[^>]+>", " ", resume["html_content"])
    resume_text = re.sub(r"\s+", " ", resume_text).strip()

    return analyze_resume_vs_jd(
        resume_text=resume_text,
        job_description=job["description"] or "",
        job_title=job["title"],
        company=job["company"],
    )


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI resume analysis vs job description")
    parser.add_argument("--resume", help="Path to resume text or HTML file")
    parser.add_argument("--jd", help="Path to job description text file")
    parser.add_argument("--job-id", type=int, help="Pull job from DB by ID")
    parser.add_argument("--no-pii-strip", action="store_true", help="Skip PII stripping")
    args = parser.parse_args()

    if args.job_id:
        result = analyze_from_db(args.job_id)
    elif args.resume and args.jd:
        resume_text = Path(args.resume).read_text()
        jd_text = Path(args.jd).read_text()
        result = analyze_resume_vs_jd(
            resume_text=resume_text,
            job_description=jd_text,
            strip_pii_before_send=not args.no_pii_strip,
        )
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\nMatch Score: {result.get('match_score')}%")
    print(f"Summary: {result.get('match_summary')}")
    print(f"\nSuggestions ({len(result.get('suggestions', []))}):")
    for chip in format_suggestions_for_ui(result):
        print(f"  [{chip['impact'].upper()}] {chip['label']}")

    if result.get("red_flags"):
        print(f"\nRed Flags:")
        for flag in result["red_flags"]:
            print(f"  ⚠ {flag}")

    print(f"\nFull result:\n{json.dumps(result, indent=2)}")
