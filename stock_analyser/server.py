from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analysis import (
    build_crypto_suggestions,
    build_recommendation_analysis,
    build_scorecard,
    build_stock_suggestions,
)
from .config import ROOT_DIR, Settings, load_settings
from .debate import DebateOrchestrator
from .http_client import ApiError
from .providers import MarketDataService


STATIC_DIR = ROOT_DIR / "static"


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.market_data = MarketDataService(settings)
        self.debate = DebateOrchestrator(settings)
        self._suggestions_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()

    def health_payload(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "llmEnabled": self.settings.llm_enabled,
        }

    def lookup(self, query: str, asset_type: str) -> dict[str, Any]:
        return {
            "results": [
                result.to_dict()
                for result in self.market_data.lookup(query=query, asset_type=asset_type)
            ]
        }

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = (payload.get("query") or "").strip() or None
        asset_type = payload.get("assetType") or "auto"
        identifier = payload.get("identifier")
        horizon = payload.get("horizon") or "quarter"

        snapshot = self.market_data.resolve_and_fetch(
            query=query, asset_type=asset_type, identifier=identifier
        )
        scored = build_scorecard(snapshot, horizon)
        enriched_snapshot = scored["snapshot"]
        debate = self.debate.debate(enriched_snapshot, horizon, scored["scorecard"])
        recommendation = build_recommendation_analysis(
            enriched_snapshot, horizon, scored["scorecard"]
        )
        return {
            "asset": enriched_snapshot.to_dict(include_history=False),
            "history": enriched_snapshot.history,
            "scorecard": scored["scorecard"],
            "recommendation": recommendation,
            "debate": debate,
            "disclaimer": "For education only, not investment advice.",
        }

    def suggestions(self, asset_type: str, limit: int = 4) -> dict[str, Any]:
        asset_type = asset_type or "all"
        limit = max(1, min(limit, 12))
        if asset_type == "stock":
            return self._cached_suggestions("stock", build_stock_suggestions, limit)
        if asset_type == "crypto":
            return self._cached_suggestions("crypto", build_crypto_suggestions, limit)
        return {
            "stocks": self._cached_suggestions("stock", build_stock_suggestions, limit),
            "crypto": self._cached_suggestions("crypto", build_crypto_suggestions, limit),
        }

    def _cached_suggestions(self, key: str, builder, limit: int) -> dict[str, Any]:
        import time

        now = time.time()
        ttl = self.settings.suggestions_cache_seconds
        cache_key = f"{key}:{limit}"
        with self._cache_lock:
            cached = self._suggestions_cache.get(cache_key)
            if cached and now < cached[0]:
                return cached[1]
        data = builder(self.market_data, top_n=limit)
        with self._cache_lock:
            self._suggestions_cache[cache_key] = (now + ttl, data)
        return data


def build_handler(state: AppState):
    class StockAnalyserHandler(BaseHTTPRequestHandler):
        server_version = "StockAnalyser/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._write_json(HTTPStatus.OK, state.health_payload())
                return
            if parsed.path == "/api/lookup":
                params = parse_qs(parsed.query)
                query = (params.get("query") or [""])[0]
                asset_type = (params.get("assetType") or ["auto"])[0]
                self._handle_api(lambda: state.lookup(query, asset_type))
                return
            if parsed.path == "/api/suggestions":
                params = parse_qs(parsed.query)
                asset_type = (params.get("assetType") or ["all"])[0]
                limit = int((params.get("limit") or ["4"])[0])
                self._handle_api(lambda: state.suggestions(asset_type, limit))
                return
            self._serve_static(parsed.path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/analyze":
                self._handle_api(lambda: state.analyze(self._read_json()))
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle_api(self, fn) -> None:
            try:
                self._write_json(HTTPStatus.OK, fn())
            except ApiError as exc:
                self._write_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            return json.loads(raw_body or "{}")

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, requested_path: str) -> None:
            relative_path = "index.html" if requested_path in {"", "/"} else requested_path.lstrip("/")
            candidate = (STATIC_DIR / relative_path).resolve()
            if STATIC_DIR.resolve() not in candidate.parents and candidate != STATIC_DIR.resolve():
                self._write_json(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
                return
            if not candidate.exists() or not candidate.is_file():
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
                return

            mime_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            body = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return StockAnalyserHandler


def run() -> None:
    settings = load_settings()
    state = AppState(settings)
    handler = build_handler(state)
    httpd = ThreadingHTTPServer((settings.host, settings.port), handler)
    print(f"Serving on http://{settings.host}:{settings.port}")
    httpd.serve_forever()
