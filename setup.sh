#!/bin/bash
# ──────────────────────────────────────────────────────
# JobFlow Setup Script
# Run once: bash setup.sh
# ──────────────────────────────────────────────────────

set -e

echo "==> Creating virtual environment…"
python3 -m venv .venv
source .venv/bin/activate

echo "==> Installing Python dependencies…"
pip install -r requirements.txt

echo "==> Installing Playwright browser (Chromium for PDF generation)…"
playwright install chromium

echo "==> Initialising database…"
python tools/db_init.py

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add your API keys to .env:"
echo "       FIRECRAWL_API_KEY=your_key_here"
echo "       ANTHROPIC_API_KEY=your_key_here"
echo ""
echo "  2. Start the server:"
echo "       source .venv/bin/activate"
echo "       uvicorn app:app --reload --port 8000"
echo ""
echo "  3. Open http://localhost:8000 in your browser"
echo ""
echo "  4. Scrape your first batch of jobs:"
echo "       python tools/scrape_jobs.py --sources dribbble indeed"
