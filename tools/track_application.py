"""
track_application.py — Application CRUD with duplicate guard, flexible status tags,
rejection timeline tracking, and Superfolio link management.

Status system:
  Preset tags: Applied | Interviewing – R1 | Interviewing – R2 | HR Round |
               Assignment | Offer | Rejected | Ghosted
  User can also provide any custom string as status.

Usage:
    python tools/track_application.py apply --job-id 42 --resume-id 3
    python tools/track_application.py update --app-id 7 --status "Interviewing – R1"
    python tools/track_application.py feedback --app-id 7 --text "Portfolio was weak" --channel email
    python tools/track_application.py list
    python tools/track_application.py superfolio --app-id 7 --url https://superfolio.co/u/xyz/job123
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from db_init import get_connection, init_db

# ------------------------------------------------------------------
# Preset status tags — shown as suggestions in the UI
# ------------------------------------------------------------------
PRESET_STATUSES = [
    "Applied",
    "Interviewing – R1",
    "Interviewing – R2",
    "HR Round",
    "Assignment",
    "Offer",
    "Rejected",
    "Ghosted",
]

TERMINAL_STATUSES = {"Offer", "Rejected", "Ghosted", "Withdrawn"}


# ------------------------------------------------------------------
# Apply to a job (with duplicate guard)
# ------------------------------------------------------------------
def apply_to_job(
    job_id: int,
    resume_id: Optional[int] = None,
    superfolio_url: Optional[str] = None,
) -> dict:
    """
    Log a new application. Raises ValueError if already applied.
    Returns the new application record as dict.
    """
    init_db()
    conn = get_connection()

    # Duplicate guard
    existing = conn.execute(
        "SELECT id, status FROM applications WHERE job_id = ?",
        (job_id,),
    ).fetchone()

    if existing:
        conn.close()
        raise ValueError(
            f"Already applied to job {job_id} "
            f"(application #{existing['id']}, status: {existing['status']}). "
            "Use `update` to change status."
        )

    # Verify job exists
    job = conn.execute(
        "SELECT id, title, company FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not job:
        conn.close()
        raise ValueError(f"Job ID {job_id} not found in database.")

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO applications
            (job_id, resume_id, status, superfolio_url, applied_at, updated_at)
        VALUES (?, ?, 'Applied', ?, ?, ?)
        """,
        (job_id, resume_id, superfolio_url, now, now),
    )
    app_id = cursor.lastrowid
    conn.commit()

    record = dict(conn.execute(
        "SELECT * FROM applications WHERE id = ?", (app_id,)
    ).fetchone())
    conn.close()

    print(f"[apply] Applied to '{job['title']}' @ {job['company']} — App #{app_id}")
    return record


# ------------------------------------------------------------------
# Update application status
# ------------------------------------------------------------------
def update_status(app_id: int, new_status: str) -> dict:
    """
    Update the status of an application.
    Automatically calculates days_to_outcome when status is terminal.
    """
    conn = get_connection()

    app = conn.execute(
        "SELECT id, applied_at, status FROM applications WHERE id = ?", (app_id,)
    ).fetchone()
    if not app:
        conn.close()
        raise ValueError(f"Application #{app_id} not found.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    days_to_outcome = None
    if new_status in TERMINAL_STATUSES:
        applied_at = datetime.fromisoformat(app["applied_at"])
        days_to_outcome = (now - applied_at).days

    conn.execute(
        """
        UPDATE applications
        SET status = ?, updated_at = ?, days_to_outcome = ?
        WHERE id = ?
        """,
        (new_status, now_iso, days_to_outcome, app_id),
    )
    conn.commit()

    record = dict(conn.execute(
        "SELECT * FROM applications WHERE id = ?", (app_id,)
    ).fetchone())
    conn.close()

    outcome_str = f" (after {days_to_outcome} days)" if days_to_outcome is not None else ""
    print(f"[update] App #{app_id} → {new_status}{outcome_str}")
    return record


# ------------------------------------------------------------------
# Add feedback / rejection note
# ------------------------------------------------------------------
def add_feedback(
    app_id: int,
    feedback_text: str,
    feedback_channel: str = "none",
) -> dict:
    """
    Log rejection or interview feedback for an application.
    Also triggers status update if current status suggests rejection.
    """
    conn = get_connection()

    app = conn.execute(
        "SELECT id, status FROM applications WHERE id = ?", (app_id,)
    ).fetchone()
    if not app:
        conn.close()
        raise ValueError(f"Application #{app_id} not found.")

    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO application_notes
            (application_id, feedback_text, feedback_channel, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (app_id, feedback_text, feedback_channel, now),
    )
    note_id = cursor.lastrowid
    conn.commit()
    conn.close()

    print(f"[feedback] Note #{note_id} added to App #{app_id} via {feedback_channel}")
    return {"note_id": note_id, "app_id": app_id, "feedback_text": feedback_text}


# ------------------------------------------------------------------
# Set or update Superfolio link
# ------------------------------------------------------------------
def set_superfolio_url(app_id: int, url: str) -> dict:
    """Attach a Superfolio custom URL to an application."""
    conn = get_connection()

    app = conn.execute("SELECT id FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not app:
        conn.close()
        raise ValueError(f"Application #{app_id} not found.")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE applications SET superfolio_url = ?, updated_at = ? WHERE id = ?",
        (url, now, app_id),
    )
    conn.commit()
    conn.close()

    print(f"[superfolio] App #{app_id} → {url}")
    return {"app_id": app_id, "superfolio_url": url}


# ------------------------------------------------------------------
# List all applications with job details
# ------------------------------------------------------------------
def list_applications(
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Return applications with enriched job info, optionally filtered by status."""
    conn = get_connection()

    query = """
        SELECT
            a.id            AS app_id,
            a.status,
            a.applied_at,
            a.updated_at,
            a.days_to_outcome,
            a.superfolio_url,
            a.resume_id,
            j.id            AS job_id,
            j.title,
            j.company,
            j.location,
            j.source,
            j.url           AS job_url,
            j.ai_skills_needed,
            j.ai_skills_tags
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
    """
    params: list = []

    if status_filter:
        query += " WHERE a.status = ?"
        params.append(status_filter)

    query += " ORDER BY a.applied_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        if d.get("ai_skills_tags"):
            d["ai_skills_tags"] = json.loads(d["ai_skills_tags"])
        results.append(d)

    return results


# ------------------------------------------------------------------
# Get rejection analytics
# ------------------------------------------------------------------
def rejection_analytics() -> dict:
    """Compute statistics on rejections and feedback themes."""
    conn = get_connection()

    # Days-to-rejection stats
    rejected = conn.execute(
        """
        SELECT days_to_outcome FROM applications
        WHERE status IN ('Rejected', 'Ghosted') AND days_to_outcome IS NOT NULL
        """
    ).fetchall()

    days_list = [r["days_to_outcome"] for r in rejected]
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else None
    min_days = min(days_list) if days_list else None
    max_days = max(days_list) if days_list else None

    # Feedback channel breakdown
    channels = conn.execute(
        """
        SELECT feedback_channel, COUNT(*) as count
        FROM application_notes
        GROUP BY feedback_channel
        """
    ).fetchall()

    # All feedback text for theme analysis
    all_feedback = conn.execute(
        "SELECT feedback_text FROM application_notes WHERE feedback_text IS NOT NULL"
    ).fetchall()

    # Status distribution
    status_dist = conn.execute(
        "SELECT status, COUNT(*) as count FROM applications GROUP BY status ORDER BY count DESC"
    ).fetchall()

    conn.close()

    return {
        "total_applications": sum(r["count"] for r in status_dist),
        "status_distribution": [dict(r) for r in status_dist],
        "rejection_stats": {
            "count": len(days_list),
            "avg_days_to_rejection": avg_days,
            "fastest_days": min_days,
            "slowest_days": max_days,
        },
        "feedback_channels": [dict(r) for r in channels],
        "feedback_texts": [r["feedback_text"] for r in all_feedback],
    }


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Track job applications")
    subparsers = parser.add_subparsers(dest="command")

    # apply
    apply_p = subparsers.add_parser("apply", help="Log a new application")
    apply_p.add_argument("--job-id", type=int, required=True)
    apply_p.add_argument("--resume-id", type=int)
    apply_p.add_argument("--superfolio-url")

    # update
    update_p = subparsers.add_parser("update", help="Update application status")
    update_p.add_argument("--app-id", type=int, required=True)
    update_p.add_argument(
        "--status", required=True,
        help=f"Status. Presets: {', '.join(PRESET_STATUSES)}"
    )

    # feedback
    fb_p = subparsers.add_parser("feedback", help="Add rejection/interview feedback")
    fb_p.add_argument("--app-id", type=int, required=True)
    fb_p.add_argument("--text", required=True)
    fb_p.add_argument("--channel", default="none", choices=["email", "call", "none"])

    # superfolio
    sf_p = subparsers.add_parser("superfolio", help="Set Superfolio URL")
    sf_p.add_argument("--app-id", type=int, required=True)
    sf_p.add_argument("--url", required=True)

    # list
    list_p = subparsers.add_parser("list", help="List all applications")
    list_p.add_argument("--status", help="Filter by status")
    list_p.add_argument("--limit", type=int, default=50)

    # analytics
    subparsers.add_parser("analytics", help="Show rejection analytics")

    # statuses
    subparsers.add_parser("statuses", help="List preset status tags")

    args = parser.parse_args()

    if args.command == "apply":
        result = apply_to_job(args.job_id, args.resume_id, args.superfolio_url)
        print(json.dumps(result, indent=2))

    elif args.command == "update":
        result = update_status(args.app_id, args.status)
        print(json.dumps(result, indent=2))

    elif args.command == "feedback":
        result = add_feedback(args.app_id, args.text, args.channel)
        print(json.dumps(result, indent=2))

    elif args.command == "superfolio":
        result = set_superfolio_url(args.app_id, args.url)
        print(json.dumps(result, indent=2))

    elif args.command == "list":
        apps = list_applications(args.status, args.limit)
        print(f"{'#':<6} {'Company':<22} {'Title':<30} {'Status':<22} {'Applied':<12} {'Days'}")
        print("-" * 100)
        for a in apps:
            days = str(a.get("days_to_outcome") or "–")
            date = (a["applied_at"] or "")[:10]
            print(
                f"{a['app_id']:<6} {a['company'][:21]:<22} {a['title'][:29]:<30} "
                f"{a['status'][:21]:<22} {date:<12} {days}"
            )

    elif args.command == "analytics":
        stats = rejection_analytics()
        print(json.dumps(stats, indent=2))

    elif args.command == "statuses":
        print("Preset status tags:")
        for s in PRESET_STATUSES:
            print(f"  • {s}")
        print("  + any custom string")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
