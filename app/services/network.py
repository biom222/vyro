from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt == max_attempts:
                return response
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else base_delay * 2 ** (attempt - 1)
            logger.warning(
                "HTTP %s from %s; retrying in %.1fs (%s/%s)",
                response.status_code,
                url,
                delay,
                attempt,
                max_attempts,
            )
            time.sleep(min(delay, 10.0))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt == max_attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            logger.warning(
                "Network error calling %s; retrying in %.1fs (%s/%s): %s",
                url,
                delay,
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(delay)
    if last_error:
        raise last_error
    raise RuntimeError("HTTP request exhausted retries without a response")
