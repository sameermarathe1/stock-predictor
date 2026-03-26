from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "stock-analyser/1.0",
}


class ApiError(RuntimeError):
    """Raised when an upstream API request fails."""


def build_url(base: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return base
    return f"{base}?{urlencode(params, doseq=True)}"


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 18,
) -> Any:
    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=request_headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        message = body_text[:400] or exc.reason
        raise ApiError(f"{exc.code} from upstream API at {url}: {message}") from exc
    except URLError as exc:
        raise ApiError(f"Network error while calling {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ApiError(f"Upstream API returned invalid JSON for {url}") from exc
