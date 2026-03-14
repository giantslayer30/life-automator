"""
generate_pdf_resume.py — Convert an HTML resume template to a pixel-perfect PDF
using Playwright headless Chrome. Supports versioning and baseline visual diff checks.

Usage:
    python tools/generate_pdf_resume.py --html path/to/resume.html --output resume_v1.pdf
    python tools/generate_pdf_resume.py --html path/to/resume.html --version 2

The generated PDF is saved to .tmp/ and the path returned for upload to Google Drive.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from playwright.sync_api import sync_playwright

TMP_DIR = Path(__file__).parent.parent / ".tmp" / "resumes"
BASELINE_DIR = Path(__file__).parent.parent / ".tmp" / "baselines"

# ------------------------------------------------------------------
# Locked CSS wrapper — ensures consistent A4 rendering
# ------------------------------------------------------------------
LOCKED_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  @page {
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
  }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #111;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* Prevent sections from splitting across pages */
  section, .section, .experience-item, .education-item {
    page-break-inside: avoid;
  }

  h1 { font-size: 20pt; font-weight: 700; }
  h2 { font-size: 11pt; font-weight: 600; margin-top: 14pt; margin-bottom: 4pt;
       border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
  h3 { font-size: 10pt; font-weight: 600; }

  a { color: #1a56db; text-decoration: none; }

  .header         { margin-bottom: 12pt; }
  .contact-line   { font-size: 9pt; color: #555; margin-top: 2pt; }
  .tag            { display: inline-block; background: #f0f4ff; border-radius: 3px;
                    padding: 1px 6px; font-size: 8.5pt; margin: 2px 2px 2px 0; }
</style>
"""


def inject_css(html: str) -> str:
    """Inject the locked CSS into an HTML document before </head> or at top."""
    if "</head>" in html:
        return html.replace("</head>", f"{LOCKED_CSS}\n</head>", 1)
    return LOCKED_CSS + html


def generate_pdf(
    html_content: str,
    output_path: Union[str, Path],
    inject_locked_css: bool = True,
) -> Path:
    """
    Render HTML to PDF via Playwright headless Chrome.

    Args:
        html_content: Full HTML string.
        output_path:  Destination path for the PDF file.
        inject_locked_css: Whether to inject the locked print CSS.

    Returns:
        Path to the generated PDF.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if inject_locked_css:
        html_content = inject_css(html_content)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={
                "top": "18mm",
                "bottom": "18mm",
                "left": "16mm",
                "right": "16mm",
            },
        )
        browser.close()

    return output_path


# ------------------------------------------------------------------
# Visual baseline diff check
# ------------------------------------------------------------------
def render_page_thumbnail(html_content: str) -> str:
    """Render first page of HTML to a base64 PNG for visual diffing."""
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 794, "height": 1123})  # A4 @ 96dpi
        page.set_content(html_content, wait_until="networkidle")
        png_bytes = page.screenshot(clip={"x": 0, "y": 0, "width": 794, "height": 1123})
        browser.close()
    return base64.b64encode(png_bytes).decode()


def pixel_hash(png_b64: str) -> str:
    return hashlib.md5(base64.b64decode(png_b64)).hexdigest()


def check_visual_diff(html_content: str, resume_version: int, threshold: float = 0.05) -> dict:
    """
    Compare rendered thumbnail to stored baseline.
    Returns {"ok": bool, "diff_ratio": float, "message": str}
    """
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    baseline_file = BASELINE_DIR / f"resume_v{resume_version}_baseline.json"

    current_thumb = render_page_thumbnail(html_content)
    current_hash = pixel_hash(current_thumb)

    if not baseline_file.exists():
        # First run — save as baseline
        baseline_file.write_text(json.dumps({
            "hash": current_hash,
            "thumbnail": current_thumb,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        return {"ok": True, "diff_ratio": 0.0, "message": "Baseline saved (first run)."}

    baseline = json.loads(baseline_file.read_text())
    if baseline["hash"] == current_hash:
        return {"ok": True, "diff_ratio": 0.0, "message": "Pixel-perfect match."}

    # Rough pixel diff using byte comparison
    current_bytes = base64.b64decode(current_thumb)
    baseline_bytes = base64.b64decode(baseline["thumbnail"])
    diff_bytes = sum(a != b for a, b in zip(current_bytes, baseline_bytes))
    diff_ratio = diff_bytes / max(len(baseline_bytes), 1)

    ok = diff_ratio <= threshold
    return {
        "ok": ok,
        "diff_ratio": round(diff_ratio, 4),
        "message": (
            f"Layout matches baseline (diff={diff_ratio:.1%})" if ok
            else f"WARNING: Layout drift detected ({diff_ratio:.1%} > {threshold:.0%} threshold). Check PDF preview."
        ),
    }


# ------------------------------------------------------------------
# Version-aware generation
# ------------------------------------------------------------------
def generate_versioned_resume(
    html_content: str,
    version: Optional[int] = None,
    label: Optional[str] = None,
    skip_diff_check: bool = False,
) -> dict:
    """
    Generate a versioned PDF resume and store metadata.

    Returns a dict with: version, pdf_path, diff_result, created_at
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-increment version if not provided
    if version is None:
        existing = sorted(TMP_DIR.glob("resume_v*.pdf"))
        version = len(existing) + 1

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"resume_v{version}_{date_str}.pdf"
    output_path = TMP_DIR / filename

    pdf_path = generate_pdf(html_content, output_path)

    diff_result = {"ok": True, "message": "Diff check skipped."}
    if not skip_diff_check:
        diff_result = check_visual_diff(html_content, version)

    result = {
        "version": version,
        "label": label,
        "pdf_path": str(pdf_path),
        "filename": filename,
        "diff_result": diff_result,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"[pdf] Resume v{version} → {pdf_path}")
    print(f"[pdf] Visual check: {diff_result['message']}")

    return result


# ------------------------------------------------------------------
# Default resume HTML template (used when no custom HTML provided)
# ------------------------------------------------------------------
DEFAULT_RESUME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Resume</title>
</head>
<body>
  <div class="header">
    <h1>{{NAME}}</h1>
    <p class="contact-line">{{EMAIL}} · {{PHONE}} · {{LOCATION}} · <a href="{{PORTFOLIO}}">Portfolio</a></p>
  </div>

  <section>
    <h2>Summary</h2>
    <p>{{SUMMARY}}</p>
  </section>

  <section>
    <h2>Experience</h2>
    {{EXPERIENCE}}
  </section>

  <section>
    <h2>Skills</h2>
    {{SKILLS}}
  </section>

  <section>
    <h2>Education</h2>
    {{EDUCATION}}
  </section>
</body>
</html>"""


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate PDF resume from HTML")
    parser.add_argument("--html", help="Path to HTML resume file")
    parser.add_argument("--output", help="Output PDF path (optional)")
    parser.add_argument("--version", type=int, help="Resume version number")
    parser.add_argument("--label", help="Human label for this version (e.g. 'Senior UX compact')")
    parser.add_argument("--skip-diff", action="store_true", help="Skip visual diff check")
    args = parser.parse_args()

    if args.html:
        html = Path(args.html).read_text()
    else:
        print("[info] No --html provided. Using default template placeholder.")
        html = DEFAULT_RESUME_TEMPLATE

    if args.output:
        pdf = generate_pdf(html, args.output)
        print(f"[done] PDF saved to: {pdf}")
    else:
        result = generate_versioned_resume(
            html,
            version=args.version,
            label=args.label,
            skip_diff_check=args.skip_diff,
        )
        print(f"[done] {result}")
