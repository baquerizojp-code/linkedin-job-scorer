import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

_JOB_ID_RE = re.compile(r'(?:/comm)?/jobs/view/(\d+)')


def extract_job_ids_from_email(email_body: str) -> list[str]:
    """Return deduplicated LinkedIn job IDs from email body, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for job_id in _JOB_ID_RE.findall(email_body):
        if job_id not in seen:
            seen.add(job_id)
            result.append(job_id)
    logger.debug("Extracted %d unique job ID(s)", len(result))
    return result


def fetch_job_description(job_id: str, playwright_browser) -> dict:
    """
    Scrape job description text from LinkedIn using an open Playwright browser.

    Never raises — returns success=False with an error string on any failure.
    """
    url = f"https://www.linkedin.com/jobs/view/{job_id}"
    page = None
    try:
        page = playwright_browser.new_page()
        page.set_extra_http_headers({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            )
        })
        page.goto(url, timeout=30_000, wait_until='domcontentloaded')
        page.wait_for_selector('main', timeout=10_000)

        try:
            page.click('button[aria-label*="more"]', timeout=3_000)
        except Exception:
            pass  # best-effort

        page.wait_for_timeout(2_000)
        raw_text: str = page.evaluate("document.querySelector('main')?.innerText || ''")

        if len(raw_text) < 1_500:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3_000)
            raw_text = page.evaluate("document.querySelector('main')?.innerText || ''")

        logger.debug("Fetched job %s: %d chars", job_id, len(raw_text))
        return {
            'job_id': job_id,
            'url': url,
            'raw_text': raw_text,
            'success': True,
            'error': None,
        }
    except Exception as e:
        logger.warning("Scrape failed for job %s: %s", job_id, e)
        return {
            'job_id': job_id,
            'url': url,
            'raw_text': '',
            'success': False,
            'error': str(e),
        }
    finally:
        if page:
            page.close()


def fetch_with_retry(job_id: str, playwright_browser) -> dict:
    """Call fetch_job_description; on failure retry once after a 5-second pause."""
    result = fetch_job_description(job_id, playwright_browser)
    if not result['success']:
        logger.info("Retrying scrape for job %s", job_id)
        time.sleep(5)
        result = fetch_job_description(job_id, playwright_browser)
    return result
