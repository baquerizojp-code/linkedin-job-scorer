# Job Scorer

## Purpose
Daily automation that reads LinkedIn job alert emails from Gmail, scrapes each job page, scores each job against a candidate's CV and rubric using Gemini, and writes qualifying matches to a Google Sheet tracker.

## Stack
- Python 3.11+
- Gmail API — fetch job-alert emails by label
- Google Sheets API — write scored results, dedup by URL
- Gemini (`google-genai`) — LLM scoring against your CV + rubric
- BeautifulSoup4 — HTML email parsing
- Playwright — LinkedIn job page scraping
- python-dotenv — environment config

## First-time setup
Run the wizard from the repo root:
```bash
python3 setup.py
```
It installs dependencies, walks you through the Google Cloud OAuth setup, prompts for your Gemini API key and Sheet ID, and copies the `config/*.example.md` templates to `config/*.md` for you to edit.

See `README.md` for the full walkthrough.

## Entry point
`scripts/run_scorer.py`

## Manual run
```bash
# From project root
.venv/bin/python scripts/run_scorer.py

# Or double-click run_job_scorer.command (macOS)
```

## Configuration
- `.env` — API keys, Sheet ID, Gmail label name (gitignored)
- `config/cv_summary.md` — your scoring-optimized CV (gitignored; copied from `cv_summary.example.md`)
- `config/rubric.md` — your 100-point weighted rubric (gitignored; copied from `rubric.example.md`)
- `config/scoring_prompt.md` — Gemini prompt template (gitignored; copied from `scoring_prompt.example.md`)
- `config/HOW_TO_GENERATE_CV_AND_RUBRIC.md` — copy-paste prompt for any LLM to generate your CV + rubric
- `credentials/` — Google OAuth credentials, generated during setup (gitignored)

The `config/*.example.md` files are checked into the repo; the working copies (without `.example`) are gitignored so personal data stays local.

## Logs
Written to `logs/YYYY-MM-DD.log`. Gitignored.

## Tracker spreadsheet columns
A=Date · B=Company · C=Role · D=Location · E=Link · F=Fit Score · G=Match Summary · H=Red Flags · I=Recommend · J=Status (free for the user)

Dedup is automatic via column E. The script reads existing URLs at the start of each run.

## Rate limits
The script defaults to 1.5s spacing between Gemini calls. On the free tier this may not be enough — bump `_MIN_CALL_SPACING` in `scripts/gemini_scorer.py` if you see 429 errors.

## Debugging
Start by reading `scripts/run_scorer.py` to understand the pipeline, then read the relevant config file in `config/` for scoring context. Check `logs/YYYY-MM-DD.log` for runtime errors.

## Rules for working in this folder

- DO NOT modify anything in `scripts/` unless the project owner explicitly asks
- DO NOT modify `.env`, `credentials/`, or `.venv/`
- DO modify `config/*.md` files when iterating on CV, rubric, or scoring prompt
- DO NOT commit personal CV content or real Sheet IDs — gitignore covers this by default
