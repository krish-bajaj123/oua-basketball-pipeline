"""Polite HTTP client: per-host throttle + retries."""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "usports-pipeline/1.0 "
    "(educational data pipeline for OUA basketball dashboard; contact: pipeline@example.com)"
)


class ThrottledClient:
    def __init__(self, min_delay: float = 1.0, jitter: float = 0.4, timeout: float = 20.0):
        self.min_delay = min_delay
        self.jitter = jitter
        self.timeout = timeout
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _sleep_if_needed(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.min_delay - elapsed + random.uniform(0, self.jitter)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, params: dict | None = None, max_attempts: int = 4) -> str:
        if params:
            url = f"{url}?{urlencode(params)}"
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            self._sleep_if_needed()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request = time.monotonic()
                if resp.status_code == 404:
                    log.warning("404: %s", url)
                    return ""
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                last_err = e
                backoff = min(30.0, (2 ** attempt) + random.uniform(0, 1))
                log.warning("attempt %d failed for %s: %s — sleeping %.1fs", attempt, url, e, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"GET failed after {max_attempts} attempts: {url}") from last_err
