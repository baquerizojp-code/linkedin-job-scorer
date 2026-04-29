# Job Scorer

An automation that reads LinkedIn job-alert emails from your Gmail, scrapes each job description, scores it 0-100 against your CV and a weighted rubric using Gemini, and appends qualifying matches to a Google Sheet — all driven by a single double-click on macOS.

It runs entirely on your machine. Your CV, your Gmail, your Gemini key, your Google Sheet. Nothing leaves your computer except the API calls you make to Google and Gemini.

---

## What you'll need

- **macOS** (Linux/Windows support is on the roadmap)
- **Python 3.11 or newer** — check with `python3 --version`. If you don't have it, install via [python.org](https://www.python.org/downloads/) or `brew install python@3.13`
- **A Gmail account** receiving LinkedIn job alert emails (set up a job alert at [linkedin.com/jobs](https://www.linkedin.com/jobs/) if you haven't)
- **A Google account** for the tracker spreadsheet (can be the same Gmail)
- **A Gemini API key** — free tier works for low volume; paid Tier 1 recommended for daily runs of 50+ jobs. Get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **About 20-30 minutes** for first-time setup, mostly spent clicking through Google Cloud Console

---

## Quick start

```bash
git clone https://github.com/<YOUR-FORK>/job-scorer.git
cd job-scorer
python3 setup.py
```

The setup wizard walks you through everything below. Read on if you want to know what it's doing or to do any step manually.

---

## What the wizard does

1. **Creates a Python virtual environment** in `.venv/` and installs dependencies (`pip install -r requirements.txt`, then `playwright install chromium`)
2. **Walks you through Google Cloud OAuth setup** (see next section — this is the one part the wizard cannot fully automate)
3. **Prompts for your Gemini API key** and writes it to `.env`
4. **Prompts for your Google Sheet ID** (or offers to create a fresh sheet for you)
5. **Prompts for your Gmail label** name
6. **Copies template config files** to your local working copies (`cv_summary.example.md` → `cv_summary.md`, etc.)
7. **Runs the OAuth flow once** to generate `credentials/token.json` and verify everything works
8. **Generates the macOS double-click launcher** (`run_job_scorer.command`)

You can re-run `setup.py` any time. It detects what's already configured and asks before overwriting.

---

## The Google Cloud OAuth step (the painful part)

The script needs permission to read your Gmail and write to your Sheets. Google requires each user to create their own OAuth client to grant this access. There is no way around this — it's how Google's API security works for personal-scope apps.

The wizard will open each page for you and tell you what to click, but here's the full picture:

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a new project (any name)
2. Enable the **Gmail API** at [APIs & Services → Library](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
3. Enable the **Google Sheets API** at [the Sheets library page](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
4. Configure the **OAuth consent screen**:
   - User type: **External**
   - Publishing status: **Testing**
   - Add your own Gmail address as a **Test user** (you must be a test user to use the app while it's unverified)
5. Create an **OAuth client ID** at [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials):
   - Application type: **Desktop app**
   - Download the JSON
6. When the wizard asks, paste the path to that downloaded JSON. The wizard moves it to `credentials/google_oauth.json`.

The first run of the scorer (or the wizard's verification step) will pop a browser window asking you to grant Gmail + Sheets access to your own app. Click through; the consent screen will warn that the app is "unverified" — that's expected because you're running your own private OAuth client.

---

## Set up your Gmail filter

For the scorer to find LinkedIn job emails, you need a Gmail filter that labels them. In Gmail:

1. Click the search bar's filter icon (or paste this query: `from:jobalerts-noreply@linkedin.com`)
2. Click **Create filter**
3. Tick **Apply the label** → choose or create a label (default: `LinkedIn Jobs`)
4. Tick **Also apply to matching conversations** if you have existing alerts
5. Click **Create filter**

Whatever label name you pick, set `GMAIL_LABEL` in `.env` to match (the wizard does this for you).

---

## Set up your tracker sheet

The wizard can create one for you, or you can make one yourself:

1. Create a new Google Sheet
2. In row 1, paste this header (tab-separated, columns A-J):
   `Date | Company | Role | Location | Link | Fit Score | Match Summary | Red Flags | Recommend | Status`
3. Copy the long ID from the sheet's URL — it's the part between `/d/` and `/edit`. That's your `SHEET_ID`.

Column J (`Status`) is yours — the script never writes there. Use it for "Applied", "Interview", "Rejected", whatever fits your workflow.

---

## Generate your CV summary and scoring rubric

The scorer needs two markdown files tuned to you: `config/cv_summary.md` (a condensed CV) and `config/rubric.md` (a 100-point weighted scoring rubric). Writing these by hand is annoying.

**The fastest path:** open [`config/HOW_TO_GENERATE_CV_AND_RUBRIC.md`](config/HOW_TO_GENERATE_CV_AND_RUBRIC.md), copy the prompt at the top, paste it into ChatGPT / Claude / Gemini, append your full CV and a description of your target search, and the LLM will produce both files in the right format. Drop them into `config/`.

You can iterate over time — edit the files directly, the script reads them fresh on every run.

---

## Run it

After setup is complete and your config files are filled in:

**Option A — double-click** the `run_job_scorer.command` file in Finder.

**Option B — from the terminal:**
```bash
.venv/bin/python scripts/run_scorer.py
```

A daily run typically takes 2-3 minutes for 30-50 jobs. Output is logged to `logs/YYYY-MM-DD.log` and printed to your terminal.

To run it on a schedule, add `run_job_scorer.command` to macOS's [`launchd`](https://www.launchd.info/) or a tool like [Cronicle](https://github.com/jhuckaby/Cronicle).

---

## Troubleshooting

**`Token has been expired or revoked` / OAuth errors on first run**
Delete `credentials/token.json` and re-run. The auth flow will open a browser to re-grant access.

**`This app is unverified` warning**
Expected. You're running your own private OAuth client. Click "Advanced" → "Go to (project name) (unsafe)" → grant access.

**`429 RESOURCE_EXHAUSTED` from Gemini**
You're hitting free-tier rate limits. Either wait, run on a smaller batch, or enable billing on your Gemini project (paid Tier 1 is generous and cheap).

**`Insufficient Permission` from Gmail**
The scopes in `scripts/gmail_client.py` need both `gmail.modify` and `spreadsheets`. If you initially granted only one, delete `token.json` and re-auth.

**LinkedIn scrape returns empty for some jobs**
Usually transient (LinkedIn rate-limits aggressive scraping). The script logs the failure and moves on; the next run retries unprocessed emails.

**Wizard says Python version too old**
Install Python 3.11+ via `brew install python@3.13` or [python.org](https://www.python.org/downloads/). Run `python3.13 setup.py` if `python3` still points to an older version.

---

## Project layout

```
job-scorer/
├── setup.py                           # First-time interactive setup wizard
├── run_job_scorer.command             # macOS double-click launcher (path-relative)
├── README.md                          # This file
├── LICENSE                            # MIT
├── requirements.txt
├── .env.example                       # Template — wizard creates your real .env
├── .gitignore
│
├── config/
│   ├── cv_summary.example.md          # Template CV (you customize, copy → cv_summary.md)
│   ├── rubric.example.md              # Template rubric → rubric.md
│   ├── scoring_prompt.example.md      # Gemini prompt template → scoring_prompt.md
│   └── HOW_TO_GENERATE_CV_AND_RUBRIC.md  # Copy-paste prompt for any LLM
│
├── scripts/
│   ├── run_scorer.py                  # Main entry point
│   ├── gmail_client.py                # Gmail API wrapper
│   ├── sheets_client.py               # Google Sheets wrapper
│   ├── gemini_scorer.py               # Gemini scoring
│   └── linkedin_scraper.py            # Playwright job-page scraper
│
├── credentials/                       # Generated during setup (gitignored)
└── logs/                              # Daily run logs (gitignored)
```

---

## Privacy and data

- The scorer never sends your data to any service except the Google APIs (Gmail, Sheets) and Gemini, both authenticated with your own keys.
- Your CV, OAuth tokens, and Sheet ID stay on your machine.
- The `.gitignore` excludes everything personal by default (`.env`, `credentials/`, `config/*.md` working copies). Only the `.example.md` templates and the script code are tracked in git.

---

## Contributing

This is a small personal-scale tool, but PRs welcome — especially Windows / Linux setup paths or improvements to the scoring logic.

## License

[MIT](LICENSE)
