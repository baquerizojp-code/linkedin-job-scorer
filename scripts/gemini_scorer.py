import json
import logging
import re
import time
from typing import Any, Literal

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3-flash-preview"

_MIN_CALL_SPACING = 1.5    # seconds — Tier 1 paid allows 1000+ RPM. 1.5s spacing is defensive padding only — not needed for rate compliance, but prevents us from accidentally hammering the API in a tight loop if something goes wrong upstream.
_DEFAULT_RETRY_WAIT = 60   # fallback wait when Retry-After is unparseable
_RETRY_DELAY_RE = re.compile(r'retryDelay[^0-9]*(\d+(?:\.\d+)?)s')

_FIELD_RANGES: dict[str, tuple[int, int]] = {
    'skills_overlap': (0, 50),
    'role_fit':       (0, 20),
    'geo_remote':     (0, 5),
    'domain_fit':     (0, 15),
    'company_signal': (0, 10),
    'total':          (0, 100),
}
_INT_FIELDS = tuple(_FIELD_RANGES.keys())
_VALID_VERDICTS = frozenset({'Apply', 'Review', 'Skip'})

_RETRY_PREFIX = (
    "CRITICAL: Your previous response was malformed. "
    "You MUST return ONLY a valid JSON object matching the exact schema. "
    "No markdown fences, no preamble, no commentary.\n\n"
)


class ScoringResult(BaseModel):
    company: str
    role: str
    location: str
    skills_overlap: int
    role_fit: int
    geo_remote: int
    domain_fit: int
    company_signal: int
    total: int
    verdict: Literal["Apply", "Review", "Skip"]
    match_summary: str
    red_flags: str


class ScoreParseError(Exception):
    pass


class ScoreValidationError(Exception):
    pass


class RateLimitExceededError(Exception):
    pass


class GeminiScorer:
    """Scores job descriptions against a candidate rubric using Gemini."""

    def __init__(
        self,
        api_key: str,
        cv_summary: str,
        rubric: str,
        prompt_template: str,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._cv_summary = cv_summary
        self._rubric = rubric
        self._prompt_template = prompt_template
        self._config = self._build_config()
        self._last_call_time: float = 0.0  # monotonic timestamp of last successful call

    def _build_config(self) -> types.GenerateContentConfig:
        try:
            return types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScoringResult,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                ),
            )
        except Exception as e:
            logger.warning(
                "ThinkingConfig not supported by this SDK/model version: %s — falling back", e
            )
            return types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScoringResult,
            )

    def _build_prompt(self, job_description: str) -> str:
        return (
            self._prompt_template
            .replace('{{CV_SUMMARY}}', self._cv_summary)
            .replace('{{RUBRIC}}', self._rubric)
            .replace('{{JOB_DESCRIPTION}}', job_description)
        )

    def _throttle(self) -> None:
        """Sleep if less than _MIN_CALL_SPACING seconds since the last call."""
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < _MIN_CALL_SPACING:
            wait = _MIN_CALL_SPACING - elapsed
            logger.debug("Throttling %.1fs before next Gemini call", wait)
            time.sleep(wait)

    def _is_rate_limit(self, error: ClientError) -> bool:
        s = str(error)
        return '429' in s or 'RESOURCE_EXHAUSTED' in s

    def _extract_retry_delay(self, error: ClientError) -> int:
        match = _RETRY_DELAY_RE.search(str(error))
        if match:
            return max(1, int(float(match.group(1))) + 2)  # round up + 2s buffer
        return _DEFAULT_RETRY_WAIT

    def _call_model(self, prompt: str) -> str:
        """Call Gemini with proactive throttling and reactive 429 handling."""
        self._throttle()

        try:
            self._last_call_time = time.monotonic()  # stamp before the call
            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=self._config,
            )
            return response.text

        except ClientError as e:
            if not self._is_rate_limit(e):
                raise  # not a 429 — surface immediately

            delay = self._extract_retry_delay(e)
            logger.warning("Rate limited. Waiting %ds before retry.", delay)
            time.sleep(delay)

            try:
                self._last_call_time = time.monotonic()  # stamp before the retry
                response = self._client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=self._config,
                )
                return response.text
            except ClientError as e2:
                if self._is_rate_limit(e2):
                    raise RateLimitExceededError(
                        f"Rate limit persisted after {delay}s wait"
                    ) from e2
                raise

    def score_job(self, job_description: str) -> dict:
        """Score a job description; returns a validated score dict."""
        prompt = self._build_prompt(job_description)
        raw = ''
        try:
            raw = self._call_model(prompt)
            parsed = json.loads(raw)
            self._validate_score(parsed)
            return parsed
        except (json.JSONDecodeError, ScoreValidationError) as e:
            logger.warning("Scoring failed on attempt 1: %s — raw: %.500s", e, raw)

        retry_prompt = _RETRY_PREFIX + prompt
        raw = ''
        try:
            raw = self._call_model(retry_prompt)
            parsed = json.loads(raw)
            self._validate_score(parsed)
            return parsed
        except json.JSONDecodeError as e:
            raise ScoreParseError(
                f"JSON parse failed after retry: {e}. Raw: {raw[:300]}"
            ) from e
        except ScoreValidationError:
            raise

    def _validate_score(self, parsed: dict) -> None:
        missing = ScoringResult.model_fields.keys() - parsed.keys()
        if missing:
            raise ScoreValidationError(f"Missing keys: {sorted(missing)}")

        for field in _INT_FIELDS:
            if not isinstance(parsed[field], int):
                raise ScoreValidationError(
                    f"{field!r} must be int, got {type(parsed[field]).__name__}"
                )

        for field, (lo, hi) in _FIELD_RANGES.items():
            val = parsed[field]
            if not (lo <= val <= hi):
                raise ScoreValidationError(
                    f"{field!r} out of range [{lo}, {hi}]: {val}"
                )

        if parsed['verdict'] not in _VALID_VERDICTS:
            raise ScoreValidationError(f"Invalid verdict: {parsed['verdict']!r}")
