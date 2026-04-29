import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))

from gmail_client import GmailClient, GmailAuthError
from linkedin_scraper import extract_job_ids_from_email, fetch_with_retry
from gemini_scorer import GeminiScorer, ScoreParseError, ScoreValidationError, RateLimitExceededError
from sheets_client import SheetsClient

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _setup_logging() -> None:
    log_dir = PROJECT_ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(stdout_handler)
    root.addHandler(file_handler)


def _load_file(path: Path) -> str:
    if not path.exists():
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    return path.read_text(encoding='utf-8')


def main() -> None:
    _setup_logging()
    load_dotenv(PROJECT_ROOT / '.env')

    required_vars = [
        'GEMINI_API_KEY', 'SHEET_ID', 'GMAIL_LABEL',
        'GOOGLE_CREDS_PATH', 'GOOGLE_TOKEN_PATH',
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error("Missing required environment variables: %s", ', '.join(missing))
        sys.exit(1)

    gemini_api_key  = os.environ['GEMINI_API_KEY']
    sheet_id        = os.environ['SHEET_ID']
    gmail_label     = os.environ['GMAIL_LABEL']
    creds_path      = os.environ['GOOGLE_CREDS_PATH']
    token_path      = os.environ['GOOGLE_TOKEN_PATH']

    cv_summary      = _load_file(PROJECT_ROOT / 'config' / 'cv_summary.md')
    rubric          = _load_file(PROJECT_ROOT / 'config' / 'rubric.md')
    prompt_template = _load_file(PROJECT_ROOT / 'config' / 'scoring_prompt.md')

    gmail_client = GmailClient(
        creds_path=creds_path,
        token_path=token_path,
        label_name=gmail_label,
    )
    gmail_client.authenticate()

    scorer = GeminiScorer(
        api_key=gemini_api_key,
        cv_summary=cv_summary,
        rubric=rubric,
        prompt_template=prompt_template,
    )

    sheets_client = SheetsClient(
        credentials=gmail_client.credentials,
        sheet_id=sheet_id,
    )

    # ── Pipeline ──────────────────────────────────────────────────────────────
    try:
        seen_urls: set[str] = sheets_client.get_existing_urls()
        threads = gmail_client.get_unread_threads()

        if not threads:
            logger.info("0 emails to process — nothing to do")
            return

        threads_attempted         = 0
        emails_marked_read        = 0
        jobs_attempted            = 0
        jobs_scored               = 0
        jobs_written              = 0
        jobs_skipped_low          = 0
        jobs_skipped_dup          = 0
        jobs_skipped_rate_limited = 0
        threads_rate_limited      = 0
        scrape_failures           = 0
        score_failures            = 0
        rows_to_write: list[list] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for thread in threads:
                    thread_id = thread['id']
                    threads_attempted += 1
                    try:
                        body = gmail_client.get_thread_body(thread_id)
                        job_ids = extract_job_ids_from_email(body)
                        logger.info("Thread %s: %d job ID(s)", thread_id, len(job_ids))

                        thread_rate_limited = False

                        for job_id in job_ids:
                            jobs_attempted += 1
                            url = f"https://www.linkedin.com/jobs/view/{job_id}"

                            if url in seen_urls:
                                jobs_skipped_dup += 1
                                logger.debug("Duplicate, skipping: %s", url)
                                continue

                            scrape = fetch_with_retry(job_id, browser)
                            if not scrape['success']:
                                scrape_failures += 1
                                logger.warning(
                                    "Scrape failed for job %s: %s", job_id, scrape['error']
                                )
                                continue

                            try:
                                score = scorer.score_job(scrape['raw_text'])
                                jobs_scored += 1
                            except RateLimitExceededError as e:
                                jobs_skipped_rate_limited += 1
                                thread_rate_limited = True
                                logger.warning("Rate limit exceeded for job %s: %s", job_id, e)
                                continue
                            except (ScoreParseError, ScoreValidationError) as e:
                                score_failures += 1
                                logger.warning("Score failed for job %s: %s", job_id, e)
                                continue

                            if score['total'] < 50:
                                jobs_skipped_low += 1
                                logger.info(
                                    "Skipped %s | %s | score=%d",
                                    score['company'], score['role'], score['total'],
                                )
                                continue

                            rows_to_write.append([
                                datetime.now().strftime("%Y-%m-%d"),
                                score['company'],
                                score['role'],
                                score['location'],
                                url,
                                score['total'],
                                score['match_summary'],
                                score['red_flags'],
                                score['verdict'],
                            ])
                            seen_urls.add(url)
                            logger.info(
                                "Scored %s | %s | %d | %s",
                                score['company'], score['role'],
                                score['total'], score['verdict'],
                            )

                        if thread_rate_limited:
                            threads_rate_limited += 1
                            logger.warning(
                                "Thread %s kept unread due to rate limiting", thread_id
                            )
                        else:
                            gmail_client.mark_thread_read(thread_id)
                            emails_marked_read += 1

                    except Exception:
                        logger.error(
                            "Unhandled error in thread %s — thread NOT marked read:\n%s",
                            thread_id, traceback.format_exc(),
                        )
            finally:
                browser.close()

        jobs_written = sheets_client.append_rows(rows_to_write)

        divider = "═" * 44
        logger.info(divider)
        logger.info("Run Summary")
        logger.info(divider)
        logger.info("Threads attempted:               %d", threads_attempted)
        logger.info("Emails marked as read:           %d", emails_marked_read)
        logger.info("Threads kept unread (rate limit):%d", threads_rate_limited)
        logger.info("Jobs attempted:                  %d", jobs_attempted)
        logger.info("Jobs scored:                     %d", jobs_scored)
        logger.info("Jobs written to sheet:           %d", jobs_written)
        logger.info("Skipped (already in sheet):      %d", jobs_skipped_dup)
        logger.info("Skipped (score < 50):            %d", jobs_skipped_low)
        logger.info("Skipped (rate limited):          %d", jobs_skipped_rate_limited)
        logger.info("Scrape failures:                 %d", scrape_failures)
        logger.info("Score failures:                  %d", score_failures)
        logger.info(divider)

    except Exception:
        logger.critical("Uncaught exception:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
