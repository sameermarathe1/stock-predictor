from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from .config import Settings
from .http_client import ApiError, build_url, request_json


def raw_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")
    return value


def to_iso_date(timestamp: int | float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_percentage_text(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip().replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


@dataclass(slots=True)
class LookupResult:
    identifier: str
    asset_type: str
    symbol: str
    name: str
    subtitle: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assetType": self.asset_type,
            "symbol": self.symbol,
            "name": self.name,
            "subtitle": self.subtitle,
        }


@dataclass(slots=True)
class AssetSnapshot:
    asset_type: str
    identifier: str
    symbol: str
    name: str
    currency: str
    current_price: float | None
    market_cap: float | None
    summary: str | None
    history: list[dict[str, Any]]
    metrics: dict[str, Any]
    context: dict[str, Any]
    source: str

    def to_dict(self, *, include_history: bool = True) -> dict[str, Any]:
        data = {
            "assetType": self.asset_type,
            "identifier": self.identifier,
            "symbol": self.symbol,
            "name": self.name,
            "currency": self.currency,
            "currentPrice": self.current_price,
            "marketCap": self.market_cap,
            "summary": self.summary,
            "metrics": self.metrics,
            "context": self.context,
            "source": self.source,
        }
        if include_history:
            data["history"] = self.history
        return data


class TTLCache:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if now > expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> Any:
        with self._lock:
            self._store[key] = (time.time() + self.ttl_seconds, value)
        return value


class YahooFinanceClient:
    BASE_URL = "https://query1.finance.yahoo.com"

    def __init__(self, settings: Settings) -> None:
        self.timeout = settings.request_timeout_seconds
        self.cache = TTLCache(ttl_seconds=600)

    def search(self, query: str) -> list[LookupResult]:
        cache_key = f"stock-search:{query.strip().lower()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = build_url(
            f"{self.BASE_URL}/v1/finance/search",
            {"q": query, "quotesCount": 8, "newsCount": 0},
        )
        payload = request_json(url, timeout=self.timeout)
        results: list[LookupResult] = []
        for item in payload.get("quotes", []):
            quote_type = (item.get("quoteType") or "").upper()
            if quote_type not in {"EQUITY", "ETF", "MUTUALFUND"}:
                continue
            symbol = item.get("symbol")
            if not symbol:
                continue
            name = item.get("longname") or item.get("shortname") or symbol
            exchange = item.get("exchDisp") or item.get("exchange")
            score = self._lookup_score(query, symbol, name)
            results.append(
                LookupResult(
                    identifier=symbol,
                    asset_type="stock",
                    symbol=symbol,
                    name=name,
                    subtitle=exchange,
                    score=score,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return self.cache.set(cache_key, results)

    def get_snapshot(self, symbol: str) -> AssetSnapshot:
        cache_key = f"stock-snapshot:{symbol.upper()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        safe_symbol = quote(symbol, safe="")
        chart_url = build_url(
            f"{self.BASE_URL}/v8/finance/chart/{safe_symbol}",
            {"interval": "1d", "range": "1y"},
        )
        insights_url = build_url(
            f"{self.BASE_URL}/ws/insights/v1/finance/insights",
            {"symbol": symbol.upper()},
        )

        chart_payload = request_json(chart_url, timeout=self.timeout)
        insights_payload = request_json(insights_url, timeout=self.timeout)

        chart_result = (chart_payload.get("chart", {}).get("result") or [{}])[0]
        meta = chart_result.get("meta", {})
        insight_result = insights_payload.get("finance", {}).get("result", {}) or {}
        instrument_info = insight_result.get("instrumentInfo", {}) or {}
        company_snapshot = insight_result.get("companySnapshot", {}) or {}
        company_scores = company_snapshot.get("company", {}) or {}
        valuation = instrument_info.get("valuation", {}) or {}
        recommendation = instrument_info.get("recommendation", {}) or {}
        technical_events = instrument_info.get("technicalEvents", {}) or {}
        key_technicals = instrument_info.get("keyTechnicals", {}) or {}

        timestamps = chart_result.get("timestamp") or []
        quote_data = ((chart_result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote_data.get("close") or []
        history = [
            {"date": to_iso_date(timestamp), "close": close}
            for timestamp, close in zip(timestamps, closes, strict=False)
            if close is not None
        ]

        symbol_value = meta.get("symbol") or symbol.upper()
        name = meta.get("longName") or meta.get("shortName") or symbol_value
        valuation_description = valuation.get("description")
        recommendation_rating = recommendation.get("rating")
        target_price = recommendation.get("targetPrice")
        long_term_trend = technical_events.get("longTerm")

        summary_parts = []
        if valuation_description:
            summary_parts.append(f"Trading Central currently tags the stock as {valuation_description.lower()}.")
        if recommendation_rating:
            summary_parts.append(f"Argus Research's latest recommendation is {recommendation_rating.upper()}.")
        if target_price:
            summary_parts.append(f"The published target price is {target_price:.2f} USD.")
        if long_term_trend:
            summary_parts.append(f"Yahoo's long-term technical trend reads {long_term_trend}.")
        summary = " ".join(summary_parts) if summary_parts else None

        current_price = raw_value(meta.get("regularMarketPrice"))
        fifty_two_week_high = raw_value(meta.get("fiftyTwoWeekHigh"))
        fifty_two_week_low = raw_value(meta.get("fiftyTwoWeekLow"))
        range_position = None
        if (
            current_price is not None
            and fifty_two_week_high is not None
            and fifty_two_week_low is not None
            and fifty_two_week_high > fifty_two_week_low
        ):
            range_position = (
                (current_price - fifty_two_week_low)
                / (fifty_two_week_high - fifty_two_week_low)
            ) * 100.0

        metrics = {
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
            "quoteType": meta.get("instrumentType"),
            "sector": company_snapshot.get("sectorInfo"),
            "beta": None,
            "trailingPe": None,
            "forwardPe": None,
            "pegRatio": None,
            "dividendYield": None,
            "profitMargins": None,
            "operatingMargins": None,
            "grossMargins": None,
            "revenueGrowth": None,
            "earningsGrowth": None,
            "returnOnEquity": None,
            "returnOnAssets": None,
            "freeCashflow": None,
            "operatingCashflow": None,
            "debtToEquity": None,
            "currentRatio": None,
            "targetMeanPrice": target_price,
            "targetMedianPrice": target_price,
            "recommendationMean": None,
            "recommendationKey": recommendation_rating.lower() if recommendation_rating else None,
            "recommendationRating": recommendation_rating,
            "valuationDescription": valuation_description,
            "valuationDiscount": parse_percentage_text(valuation.get("discount")),
            "support": key_technicals.get("support"),
            "resistance": key_technicals.get("resistance"),
            "stopLoss": key_technicals.get("stopLoss"),
            "technicalShortTerm": technical_events.get("shortTerm"),
            "technicalMidTerm": technical_events.get("midTerm"),
            "technicalLongTerm": long_term_trend,
            "companyInnovativeness": company_scores.get("innovativeness"),
            "companyHiring": company_scores.get("hiring"),
            "companyInsiderSentiments": company_scores.get("insiderSentiments"),
            "companyEarningsReports": company_scores.get("earningsReports"),
            "companyDividends": company_scores.get("dividends"),
            "fiftyTwoWeekHigh": fifty_two_week_high,
            "fiftyTwoWeekLow": fifty_two_week_low,
            "fiftyTwoWeekRangePosition": range_position,
            "marketCap": None,
            "averageDailyVolume3Month": raw_value(meta.get("regularMarketVolume")),
        }

        snapshot = AssetSnapshot(
            asset_type="stock",
            identifier=symbol_value,
            symbol=symbol_value,
            name=name,
            currency=meta.get("currency") or "USD",
            current_price=current_price,
            market_cap=None,
            summary=summary,
            history=history,
            metrics=metrics,
            context={
                "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                "sector": company_snapshot.get("sectorInfo"),
                "support": key_technicals.get("support"),
                "resistance": key_technicals.get("resistance"),
                "valuation": valuation_description,
            },
            source="Yahoo Finance",
        )
        return self.cache.set(cache_key, snapshot)

    @staticmethod
    def _lookup_score(query: str, symbol: str, name: str) -> float:
        query_lower = query.strip().lower()
        score = 0.0
        if symbol.lower() == query_lower:
            score += 100
        if name.lower() == query_lower:
            score += 95
        if symbol.lower().startswith(query_lower):
            score += 55
        if query_lower in name.lower():
            score += 35
        return score


class CoinGeckoClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, settings: Settings) -> None:
        self.timeout = settings.request_timeout_seconds
        self.cache = TTLCache(ttl_seconds=600)

    def search(self, query: str) -> list[LookupResult]:
        cache_key = f"crypto-search:{query.strip().lower()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = build_url(f"{self.BASE_URL}/search", {"query": query})
        payload = request_json(url, timeout=self.timeout)
        results: list[LookupResult] = []
        for item in payload.get("coins", [])[:8]:
            name = item.get("name")
            symbol = (item.get("symbol") or "").upper()
            identifier = item.get("id")
            if not name or not symbol or not identifier:
                continue
            rank = item.get("market_cap_rank")
            subtitle = f"CoinGecko rank #{rank}" if rank else "CoinGecko"
            score = self._lookup_score(query, symbol, name, rank)
            results.append(
                LookupResult(
                    identifier=identifier,
                    asset_type="crypto",
                    symbol=symbol,
                    name=name,
                    subtitle=subtitle,
                    score=score,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return self.cache.set(cache_key, results)

    def get_snapshot(self, coin_id: str) -> AssetSnapshot:
        cache_key = f"crypto-snapshot:{coin_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        details_url = build_url(
            f"{self.BASE_URL}/coins/{quote(coin_id, safe='')}",
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )
        chart_url = build_url(
            f"{self.BASE_URL}/coins/{quote(coin_id, safe='')}/market_chart",
            {"vs_currency": "usd", "days": 365, "interval": "daily"},
        )

        details = request_json(details_url, timeout=self.timeout)
        chart = request_json(chart_url, timeout=self.timeout)
        market_data = details.get("market_data", {})

        prices = chart.get("prices") or []
        history = [
            {"date": to_iso_date(point[0] / 1000), "close": point[1]}
            for point in prices
            if len(point) == 2 and point[1] is not None
        ]

        volume = market_data.get("total_volume", {}).get("usd")
        market_cap = market_data.get("market_cap", {}).get("usd")

        snapshot = AssetSnapshot(
            asset_type="crypto",
            identifier=details.get("id") or coin_id,
            symbol=(details.get("symbol") or coin_id).upper(),
            name=details.get("name") or coin_id,
            currency="USD",
            current_price=market_data.get("current_price", {}).get("usd"),
            market_cap=market_cap,
            summary=clean_text((details.get("description") or {}).get("en")),
            history=history,
            metrics={
                "marketCap": market_cap,
                "marketCapRank": details.get("market_cap_rank"),
                "fullyDilutedValuation": market_data.get("fully_diluted_valuation", {}).get("usd"),
                "totalVolume": volume,
                "volumeToMarketCap": (volume / market_cap) if volume and market_cap else None,
                "priceChange24h": market_data.get("price_change_percentage_24h"),
                "priceChange7d": market_data.get("price_change_percentage_7d"),
                "priceChange30d": market_data.get("price_change_percentage_30d"),
                "priceChange1y": market_data.get("price_change_percentage_1y"),
                "athChangePercentage": market_data.get("ath_change_percentage", {}).get("usd"),
                "circulatingSupply": market_data.get("circulating_supply"),
                "maxSupply": market_data.get("max_supply"),
            },
            context={
                "categories": details.get("categories", [])[:4],
                "homepage": (details.get("links") or {}).get("homepage", [""])[0] or None,
            },
            source="CoinGecko",
        )
        return self.cache.set(cache_key, snapshot)

    def top_markets(self, *, per_page: int = 20) -> list[dict[str, Any]]:
        cache_key = f"crypto-top-markets:{per_page}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = build_url(
            f"{self.BASE_URL}/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h,7d,30d,1y",
            },
        )
        payload = request_json(url, timeout=self.timeout)
        return self.cache.set(cache_key, payload)

    @staticmethod
    def _lookup_score(query: str, symbol: str, name: str, rank: int | None) -> float:
        query_lower = query.strip().lower()
        score = 0.0
        if name.lower() == query_lower:
            score += 140
        if symbol.lower() == query_lower:
            score += 100 if len(query_lower) <= 5 else 18
        if name.lower().startswith(query_lower):
            score += 70
        if symbol.lower().startswith(query_lower):
            score += 28 if len(query_lower) <= 5 else 8
        if query_lower in name.lower():
            score += 35
        if rank:
            score += max(0.0, 30 - min(rank, 30))
        return score


class MarketDataService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stocks = YahooFinanceClient(settings)
        self.crypto = CoinGeckoClient(settings)

    def lookup(self, query: str, asset_type: str = "auto") -> list[LookupResult]:
        query = query.strip()
        if not query:
            return []

        results: list[LookupResult] = []
        if asset_type in {"auto", "stock"}:
            try:
                results.extend(self.stocks.search(query))
            except ApiError:
                pass
        if asset_type in {"auto", "crypto"}:
            try:
                results.extend(self.crypto.search(query))
            except ApiError:
                pass

        results.sort(key=lambda item: item.score, reverse=True)
        seen: set[tuple[str, str]] = set()
        deduped: list[LookupResult] = []
        for result in results:
            key = (result.asset_type, result.identifier)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped[:8]

    def resolve_and_fetch(
        self,
        *,
        query: str | None = None,
        asset_type: str = "auto",
        identifier: str | None = None,
    ) -> AssetSnapshot:
        if asset_type == "stock":
            return self._resolve_stock(query=query, identifier=identifier)
        if asset_type == "crypto":
            return self._resolve_crypto(query=query, identifier=identifier)

        if identifier:
            if "-" in identifier and not identifier.isupper():
                try:
                    return self.crypto.get_snapshot(identifier)
                except ApiError:
                    return self.stocks.get_snapshot(identifier)
            return self.stocks.get_snapshot(identifier)

        if query:
            direct_symbol = query.strip().upper()
            try:
                return self.stocks.get_snapshot(direct_symbol)
            except ApiError:
                pass

            results = self.lookup(query, "auto")
            if not results:
                raise ApiError(f"No asset matched query '{query}'.")
            best = results[0]
            return self.resolve_and_fetch(
                query=query, asset_type=best.asset_type, identifier=best.identifier
            )

        raise ApiError("Either query or identifier is required.")

    def _resolve_stock(
        self, *, query: str | None = None, identifier: str | None = None
    ) -> AssetSnapshot:
        if identifier:
            return self.stocks.get_snapshot(identifier)
        if query:
            symbol = query.strip().upper()
            try:
                return self.stocks.get_snapshot(symbol)
            except ApiError:
                results = self.stocks.search(query)
                if not results:
                    raise ApiError(f"No stock matched query '{query}'.")
                return self.stocks.get_snapshot(results[0].identifier)
        raise ApiError("Stock resolution requires a symbol or query.")

    def _resolve_crypto(
        self, *, query: str | None = None, identifier: str | None = None
    ) -> AssetSnapshot:
        if identifier:
            return self.crypto.get_snapshot(identifier)
        if query:
            results = self.crypto.search(query)
            if not results:
                raise ApiError(f"No crypto asset matched query '{query}'.")
            return self.crypto.get_snapshot(results[0].identifier)
        raise ApiError("Crypto resolution requires an identifier or query.")
