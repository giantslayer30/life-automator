# Workflow: Track Applications & Learn from Feedback

## Objective
Maintain accurate application status, record rejection timelines and feedback, and surface patterns over time.

## Status Tag System

### Preset tags (suggested in UI)
| Tag | When to use |
|-----|-------------|
| `Applied` | Default — just submitted |
| `Interviewing – R1` | First interview scheduled/done |
| `Interviewing – R2` | Second interview |
| `HR Round` | Final HR / culture fit call |
| `Assignment` | Take-home design task |
| `Offer` | Offer received |
| `Rejected` | Formally rejected |
| `Ghosted` | No response after 2+ weeks |

Custom tags: type any string in the "custom status" input (e.g. "Waiting for referral", "Contract negotiation").

## Procedure

### Update an application status (UI)
1. Go to `http://localhost:8000/history`
2. Click the status pill on any application row
3. Select a preset status chip, or type a custom one
4. For Rejected / Ghosted: feedback section appears — enter feedback text and channel
5. Optionally add/update Superfolio URL
6. Click **Save** → status updates, days_to_outcome auto-calculated

### Update an application status (CLI)
```bash
python tools/track_application.py update --app-id 7 --status "Interviewing – R1"
python tools/track_application.py update --app-id 7 --status "Rejected"
```

### Add feedback note
```bash
python tools/track_application.py feedback --app-id 7 \
  --text "Portfolio case studies lacked business impact metrics" \
  --channel email
```

### Add Superfolio URL after the fact
```bash
python tools/track_application.py superfolio --app-id 7 \
  --url https://superfolio.co/u/you/company-role
```

### View all applications
```bash
python tools/track_application.py list
python tools/track_application.py list --status Rejected
```

### View rejection analytics
```bash
python tools/track_application.py analytics
```
Returns:
- Total applications by status
- Average days to rejection
- Fastest / slowest rejection
- Feedback channels used
- All feedback text (for manual theme analysis)

## Days-to-Outcome Calculation
Automatically calculated when status is set to any terminal state (Offer, Rejected, Ghosted):
```
days_to_outcome = today - applied_at (in calendar days)
```

## Identifying Feedback Themes
Run analytics monthly to collect all feedback text, then look for patterns:
```bash
python tools/track_application.py analytics | python -c "
import json, sys
data = json.load(sys.stdin)
print('Feedback themes:')
for t in data['feedback_texts']:
    print(' -', t)
"
```
Common patterns to watch for:
- Portfolio depth / case study quality
- Missing specific skills (Figma, prototyping, research)
- Culture fit / seniority mismatch
- Response speed (ghosting before interview = timing issue)

## Superfolio View Tracking
When you add a Superfolio URL to an application:
- Superfolio tracks: view count, viewer location, browser, time spent
- Check your Superfolio dashboard for engagement signals
- High views + no reply → portfolio viewed but JD fit may be weak
- No views + no reply → application may not have been read

## Outputs
- Updated `applications` table with latest status + days_to_outcome
- Feedback notes in `application_notes` table
- Analytics available via `GET /api/analytics`
- History page at `http://localhost:8000/history` shows all data in table view
