#!/usr/bin/env python3
"""Interactive first-time setup for job-scorer.

Walks a new user through:
  1. Python + macOS preflight checks
  2. Creating .venv and installing dependencies
  3. Google Cloud OAuth credential setup (with browser hand-holding)
  4. Gemini API key + Google Sheet ID + Gmail label configuration
  5. Copying config templates to working files
  6. Running the OAuth flow once to verify everything

Re-runnable safely: detects what's already configured and asks before overwriting.

Uses only the Python standard library so it can run before the venv exists.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import textwrap
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / ".venv"
CREDENTIALS_DIR = REPO_ROOT / "credentials"
CONFIG_DIR = REPO_ROOT / "config"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
GOOGLE_CREDS_PATH = CREDENTIALS_DIR / "google_oauth.json"
GOOGLE_TOKEN_PATH = CREDENTIALS_DIR / "token.json"

CONFIG_TEMPLATES = [
    ("cv_summary.example.md", "cv_summary.md"),
    ("rubric.example.md", "rubric.md"),
    ("scoring_prompt.example.md", "scoring_prompt.md"),
]

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def color(s: str, c: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"{c}{s}{RESET}"


def heading(s: str) -> None:
    print()
    print(color(f"━━━ {s} ━━━", BOLD + BLUE))


def ok(s: str) -> None:
    print(color(f"✓ {s}", GREEN))


def warn(s: str) -> None:
    print(color(f"! {s}", YELLOW))


def fail(s: str) -> None:
    print(color(f"✗ {s}", RED))


def info(s: str) -> None:
    print(color(s, DIM))


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if answer:
            return answer
        if default is not None:
            return default
        print("  (a value is required)")


def confirm(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{prompt} {suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def open_url(url: str) -> None:
    info(f"  Opening {url}")
    try:
        webbrowser.open(url)
    except Exception:
        info("  (could not auto-open — copy the URL manually)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Preflight checks
# ─────────────────────────────────────────────────────────────────────────────
def step_preflight() -> None:
    heading("Preflight checks")

    if platform.system() != "Darwin":
        warn(f"Detected OS: {platform.system()}. This setup script targets macOS.")
        warn("It may still work on Linux. On Windows, follow the manual steps in README.md.")
        if not confirm("Continue anyway?", default=False):
            sys.exit(1)
    else:
        ok(f"macOS {platform.mac_ver()[0]}")

    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        fail(f"Python {major}.{minor} detected. This project requires Python 3.11 or newer.")
        info("  Install via:  brew install python@3.13   or visit  https://www.python.org/downloads/")
        sys.exit(1)
    ok(f"Python {major}.{minor}.{sys.version_info[2]}")

    try:
        subprocess.run(
            [sys.executable, "-m", "venv", "--help"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        fail("Python venv module is not available. On Debian/Ubuntu try:  sudo apt install python3-venv")
        sys.exit(1)
    ok("venv module available")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Create venv and install dependencies
# ─────────────────────────────────────────────────────────────────────────────
def venv_python() -> Path:
    return VENV_DIR / "bin" / "python"


def step_create_venv() -> None:
    heading("Python virtual environment")

    if VENV_DIR.exists():
        ok(f".venv already exists at {VENV_DIR.relative_to(REPO_ROOT)}")
        if confirm("Reinstall dependencies from requirements.txt?", default=True):
            install_dependencies()
        return

    info(f"  Creating venv at {VENV_DIR.relative_to(REPO_ROOT)}/ ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    ok("Virtual environment created")
    install_dependencies()


def install_dependencies() -> None:
    pip = VENV_DIR / "bin" / "pip"
    info("  Upgrading pip ...")
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    info("  Installing requirements.txt ...")
    subprocess.run([str(pip), "install", "-r", str(REPO_ROOT / "requirements.txt")], check=True)
    ok("Python dependencies installed")
    info("  Installing Playwright Chromium browser (this may take a minute) ...")
    subprocess.run(
        [str(venv_python()), "-m", "playwright", "install", "chromium"],
        check=True,
    )
    ok("Playwright Chromium installed")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Google Cloud OAuth credentials
# ─────────────────────────────────────────────────────────────────────────────
def step_oauth_credentials() -> None:
    heading("Google Cloud OAuth credentials")

    CREDENTIALS_DIR.mkdir(exist_ok=True)

    if GOOGLE_CREDS_PATH.exists():
        ok(f"OAuth credentials already at credentials/google_oauth.json")
        if not confirm("Replace with a new credential file?", default=False):
            return

    print()
    print(textwrap.dedent("""
        The scorer needs permission to read your Gmail and write to a Google Sheet.
        You'll create your own Google Cloud OAuth client (free, takes ~10 minutes).

        I'll open each Google Cloud Console page in your browser. Follow these steps:

          1. Create a project (any name, e.g. "job-scorer")
          2. Enable the Gmail API
          3. Enable the Google Sheets API
          4. Configure the OAuth consent screen:
               • User type: External
               • Publishing status: Testing
               • Add YOUR OWN Gmail address as a Test user
          5. Create an OAuth client ID:
               • Application type: Desktop app
               • Click DOWNLOAD JSON when done
    """).strip())
    print()

    if confirm("Open the Google Cloud Console pages now?", default=True):
        open_url("https://console.cloud.google.com/projectcreate")
        input("  Press Enter once your project is created and selected ...")
        open_url("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
        input("  Press Enter once the Gmail API is enabled ...")
        open_url("https://console.cloud.google.com/apis/library/sheets.googleapis.com")
        input("  Press Enter once the Google Sheets API is enabled ...")
        open_url("https://console.cloud.google.com/apis/credentials/consent")
        input("  Press Enter once the OAuth consent screen is configured (External / Testing / your email as Test user) ...")
        open_url("https://console.cloud.google.com/apis/credentials")
        print()
        info("  In Credentials → CREATE CREDENTIALS → OAuth client ID → Desktop app → DOWNLOAD JSON")
        input("  Press Enter once you have the downloaded JSON file on your Mac ...")

    print()
    while True:
        path_str = ask("Paste the full path to the downloaded JSON file (e.g. /Users/you/Downloads/client_secret_xxx.json)")
        path = Path(path_str.strip().strip('"').strip("'")).expanduser()
        if not path.exists():
            fail(f"  Not found: {path}")
            continue
        if not path.is_file():
            fail(f"  Not a file: {path}")
            continue
        try:
            shutil.copy(path, GOOGLE_CREDS_PATH)
            ok(f"Copied to credentials/google_oauth.json")
            break
        except Exception as e:
            fail(f"  Could not copy: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Gemini API key, Sheet ID, Gmail label → .env
# ─────────────────────────────────────────────────────────────────────────────
def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def write_env(env: dict[str, str]) -> None:
    lines = [
        "# Generated by setup.py. You can re-run setup.py to update.",
        "",
        f"GEMINI_API_KEY={env.get('GEMINI_API_KEY', '')}",
        f"SHEET_ID={env.get('SHEET_ID', '')}",
        f"GMAIL_LABEL={env.get('GMAIL_LABEL', 'LinkedIn Jobs')}",
        f"GOOGLE_CREDS_PATH={env.get('GOOGLE_CREDS_PATH', './credentials/google_oauth.json')}",
        f"GOOGLE_TOKEN_PATH={env.get('GOOGLE_TOKEN_PATH', './credentials/token.json')}",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines))


def step_env_config() -> None:
    heading("Configuration: API key, Sheet ID, Gmail label")
    env = read_env()

    # ── Gemini API key ──
    current_key = env.get("GEMINI_API_KEY", "")
    has_real_key = bool(current_key) and current_key != "your-gemini-api-key-here"
    if has_real_key:
        masked = current_key[:6] + "…" + current_key[-4:] if len(current_key) > 10 else "(set)"
        ok(f"Gemini API key already set: {masked}")
        if confirm("Replace it?", default=False):
            has_real_key = False
    if not has_real_key:
        print()
        info("  Get a Gemini API key at https://aistudio.google.com/apikey")
        if confirm("Open the Gemini API key page?", default=True):
            open_url("https://aistudio.google.com/apikey")
        env["GEMINI_API_KEY"] = ask("Paste your Gemini API key")
        ok("Gemini API key saved")

    # ── Sheet ID ──
    current_sheet = env.get("SHEET_ID", "")
    if current_sheet:
        ok(f"Google Sheet ID already set: {current_sheet}")
        if not confirm("Replace it?", default=False):
            pass
        else:
            current_sheet = ""
    if not current_sheet:
        print()
        print("  Two options for the tracker spreadsheet:")
        print("    1) Paste an existing Sheet ID")
        print("    2) Let setup create a new sheet for you (after we run OAuth)")
        choice = ask("  Choice (1 or 2)", default="1")
        if choice.strip() == "2":
            env["SHEET_ID"] = "__CREATE_AFTER_OAUTH__"
            info("  Will create a new sheet after OAuth verification.")
        else:
            print()
            info("  The Sheet ID is the long string in the sheet URL:")
            info("    https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit")
            info("  Make sure your sheet has the header row in row 1:")
            info("    Date | Company | Role | Location | Link | Fit Score | Match Summary | Red Flags | Recommend | Status")
            env["SHEET_ID"] = ask("Paste your Google Sheet ID")
        ok("Sheet ID saved")

    # ── Gmail label ──
    current_label = env.get("GMAIL_LABEL", "")
    if current_label and current_label != "LinkedIn Jobs":
        ok(f"Gmail label: {current_label}")
        if confirm("Change it?", default=False):
            current_label = ""
    if not current_label or current_label == "LinkedIn Jobs":
        print()
        info("  This is the Gmail label you apply to LinkedIn job-alert emails.")
        info("  In Gmail, create a filter (e.g. from:jobalerts-noreply@linkedin.com) that applies this label.")
        env["GMAIL_LABEL"] = ask("  Gmail label name", default="LinkedIn Jobs")

    env.setdefault("GOOGLE_CREDS_PATH", "./credentials/google_oauth.json")
    env.setdefault("GOOGLE_TOKEN_PATH", "./credentials/token.json")

    write_env(env)
    ok(".env written")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Copy config templates
# ─────────────────────────────────────────────────────────────────────────────
def step_config_templates() -> None:
    heading("Config templates (CV, rubric, scoring prompt)")
    for example_name, target_name in CONFIG_TEMPLATES:
        example = CONFIG_DIR / example_name
        target = CONFIG_DIR / target_name
        if not example.exists():
            warn(f"Template missing: {example.relative_to(REPO_ROOT)} (skipping)")
            continue
        if target.exists():
            ok(f"{target.relative_to(REPO_ROOT)} already exists (keeping yours)")
            continue
        shutil.copy(example, target)
        ok(f"Created {target.relative_to(REPO_ROOT)} from template")

    print()
    info("  Edit config/cv_summary.md and config/rubric.md before running the scorer.")
    info("  See config/HOW_TO_GENERATE_CV_AND_RUBRIC.md for a copy-paste prompt that")
    info("  generates both files using any LLM (ChatGPT, Claude, Gemini).")


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: OAuth verification + (optional) sheet creation
# ─────────────────────────────────────────────────────────────────────────────
OAUTH_VERIFY_SCRIPT = r"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/spreadsheets',
]

creds_path = Path(sys.argv[1])
token_path = Path(sys.argv[2])
create_sheet = (sys.argv[3] == "create")

creds = None
if token_path.exists():
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())

# Verify Gmail access
gmail = build('gmail', 'v1', credentials=creds)
profile = gmail.users().getProfile(userId='me').execute()
print(f"GMAIL_OK:{profile.get('emailAddress', '?')}")

# Verify Sheets access (and optionally create a sheet)
sheets = build('sheets', 'v4', credentials=creds)
if create_sheet:
    spreadsheet = sheets.spreadsheets().create(body={
        'properties': {'title': 'Job Scorer Tracker'},
        'sheets': [{'properties': {'title': 'Jobs'}}],
    }).execute()
    sid = spreadsheet['spreadsheetId']
    headers = [['Date', 'Company', 'Role', 'Location', 'Link', 'Fit Score',
                'Match Summary', 'Red Flags', 'Recommend', 'Status']]
    sheets.spreadsheets().values().update(
        spreadsheetId=sid,
        range='Jobs!A1:J1',
        valueInputOption='RAW',
        body={'values': headers},
    ).execute()
    print(f"SHEET_CREATED:{sid}")
else:
    print("SHEETS_OK")
"""


def step_oauth_verify_and_maybe_create_sheet() -> None:
    heading("Verify OAuth (and create sheet if requested)")

    env = read_env()
    create_sheet = env.get("SHEET_ID") == "__CREATE_AFTER_OAUTH__"

    if not GOOGLE_CREDS_PATH.exists():
        fail("credentials/google_oauth.json missing — re-run the OAuth credentials step")
        return

    info("  A browser window will open asking you to grant Gmail + Sheets access.")
    info("  You may see an 'unverified app' warning — click Advanced → Go to (project) (unsafe).")
    info("  This is normal because you're running your own private OAuth client.")
    print()

    cmd = [
        str(venv_python()),
        "-c", OAUTH_VERIFY_SCRIPT,
        str(GOOGLE_CREDS_PATH),
        str(GOOGLE_TOKEN_PATH),
        "create" if create_sheet else "verify",
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        fail("OAuth verification failed.")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        info("  Common fixes:")
        info("    • Ensure your email is added as a Test user on the OAuth consent screen")
        info("    • Ensure both Gmail API and Sheets API are enabled")
        info("    • Delete credentials/token.json and re-run setup.py to re-auth")
        return

    output = result.stdout.strip()
    for line in output.splitlines():
        if line.startswith("GMAIL_OK:"):
            ok(f"Gmail access verified for {line.split(':', 1)[1]}")
        elif line.startswith("SHEET_CREATED:"):
            sid = line.split(":", 1)[1]
            env["SHEET_ID"] = sid
            write_env(env)
            ok(f"Created tracker sheet — Sheet ID: {sid}")
            info(f"  https://docs.google.com/spreadsheets/d/{sid}/edit")
        elif line == "SHEETS_OK":
            ok("Sheets access verified")


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Ensure run_job_scorer.command exists
# ─────────────────────────────────────────────────────────────────────────────
def step_launcher() -> None:
    heading("macOS double-click launcher")
    cmd_file = REPO_ROOT / "run_job_scorer.command"
    contents = textwrap.dedent("""\
        #!/bin/bash
        # Double-click runner for the job scorer (macOS).
        # Resolves its own directory so this works regardless of where the project is installed.
        set -e
        cd "$(dirname "$0")"
        exec ./.venv/bin/python scripts/run_scorer.py
    """)
    cmd_file.write_text(contents)
    cmd_file.chmod(0o755)
    ok(f"{cmd_file.name} ready (double-click to run)")


# ─────────────────────────────────────────────────────────────────────────────
# Final summary
# ─────────────────────────────────────────────────────────────────────────────
def final_summary() -> None:
    heading("Setup complete")
    env = read_env()
    print()
    print(color("  Next steps:", BOLD))
    print()
    print("  1. Edit your CV summary and rubric:")
    print(f"     {color('config/cv_summary.md', BLUE)}")
    print(f"     {color('config/rubric.md', BLUE)}")
    print(f"     (See {color('config/HOW_TO_GENERATE_CV_AND_RUBRIC.md', BLUE)} for an LLM prompt that")
    print("      generates both files for you.)")
    print()
    print("  2. Set up a Gmail filter that applies the label")
    print(f"     {color(env.get('GMAIL_LABEL', 'LinkedIn Jobs'), BLUE)} to LinkedIn job-alert emails.")
    print(f"     Suggested filter:  {color('from:jobalerts-noreply@linkedin.com', BLUE)}")
    print()
    print("  3. Run the scorer:")
    print(f"     • Double-click {color('run_job_scorer.command', BLUE)} in Finder")
    print(f"     • Or:  {color('.venv/bin/python scripts/run_scorer.py', BLUE)}")
    print()
    sid = env.get("SHEET_ID", "")
    if sid and sid != "__CREATE_AFTER_OAUTH__":
        print(f"  Your tracker:  {color(f'https://docs.google.com/spreadsheets/d/{sid}/edit', BLUE)}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(color("\n  Job Scorer — first-time setup\n", BOLD))
    info("  This wizard is re-runnable. Press Ctrl-C any time to bail out.")

    try:
        step_preflight()
        step_create_venv()
        step_oauth_credentials()
        step_env_config()
        step_config_templates()
        step_launcher()
        step_oauth_verify_and_maybe_create_sheet()
        final_summary()
    except KeyboardInterrupt:
        print()
        warn("Setup interrupted. Re-run python3 setup.py to continue.")
        sys.exit(1)


if __name__ == "__main__":
    main()
