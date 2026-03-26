from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .providers import AssetSnapshot, MarketDataService


HORIZONS = {
    "quarter": {"label": "Quarter", "days": 90},
    "six_months": {"label": "Six Months", "days": 180},
    "year": {"label": "One Year", "days": 365},
}

DEFAULT_STOCK_UNIVERSE = [
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("AAPL", "Apple"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("GOOGL", "Alphabet"),
    ("AVGO", "Broadcom"),
    ("LLY", "Eli Lilly"),
    ("JPM", "JPMorgan Chase"),
    ("V", "Visa"),
    ("COST", "Costco"),
    ("XOM", "Exxon Mobil"),
    ("SPY", "SPDR S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust"),
]

STABLECOIN_NAMES = {
    "tether",
    "usd coin",
    "dai",
    "ethena usde",
    "usds",
    "paypal usd",
    "trueusd",
    "first digital usd",
}

STABLECOIN_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "USDS", "PYUSD", "TUSD", "FDUSD"}


@dataclass(slots=True)
class Signal:
    score: float
    text: str


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def safe_mean(values: list[float | None], default: float = 0.0) -> float:
    usable = [value for value in values if value is not None]
    if not usable:
        return default
    return sum(usable) / len(usable)


def first_available(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def scale_linear(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 50.0
    if math.isclose(low, high):
        return 50.0
    return clamp((value - low) / (high - low), 0.0, 1.0) * 100.0


def scale_inverse(value: float | None, low: float, high: float) -> float:
    return 100.0 - scale_linear(value, low, high)


def returns_from_history(history: list[dict[str, Any]], lookback_days: int) -> float | None:
    if len(history) < 2:
        return None
    latest = history[-1]["close"]
    if latest in {None, 0}:
        return None

    target_index = max(0, len(history) - lookback_days - 1)
    start = history[target_index]["close"]
    if start in {None, 0}:
        return None
    return ((latest / start) - 1.0) * 100.0


def moving_average(history: list[dict[str, Any]], window: int) -> float | None:
    closes = [row["close"] for row in history if row.get("close") is not None]
    if len(closes) < window:
        return None
    relevant = closes[-window:]
    return sum(relevant) / len(relevant)


def annualized_volatility(history: list[dict[str, Any]]) -> float | None:
    closes = [row["close"] for row in history if row.get("close") is not None]
    if len(closes) < 20:
        return None
    daily_returns = []
    for previous, current in zip(closes, closes[1:], strict=False):
        if previous and current:
            daily_returns.append((current / previous) - 1.0)
    if len(daily_returns) < 10:
        return None
    average = sum(daily_returns) / len(daily_returns)
    variance = sum((value - average) ** 2 for value in daily_returns) / len(daily_returns)
    return math.sqrt(variance) * math.sqrt(252) * 100.0


def max_drawdown(history: list[dict[str, Any]]) -> float | None:
    closes = [row["close"] for row in history if row.get("close") is not None]
    if len(closes) < 2:
        return None
    peak = closes[0]
    deepest = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = ((close / peak) - 1.0) * 100.0
        deepest = min(deepest, drawdown)
    return abs(deepest)


def enrich_snapshot(snapshot: AssetSnapshot) -> AssetSnapshot:
    enriched = deepcopy(snapshot)
    history = enriched.history
    current_price = enriched.current_price
    ma_50 = moving_average(history, 50)
    ma_200 = moving_average(history, 200)
    enriched.metrics.update(
        {
            "return30d": returns_from_history(history, 30),
            "return90d": returns_from_history(history, 90),
            "return180d": returns_from_history(history, 180),
            "return365d": returns_from_history(history, 365),
            "volatilityAnnualized": annualized_volatility(history),
            "maxDrawdown": max_drawdown(history),
            "ma50": ma_50,
            "ma200": ma_200,
            "priceVsMa50": ((current_price / ma_50) - 1.0) * 100.0
            if current_price and ma_50
            else None,
            "priceVsMa200": ((current_price / ma_200) - 1.0) * 100.0
            if current_price and ma_200
            else None,
        }
    )
    return enriched


def horizon_days(horizon: str) -> int:
    if horizon not in HORIZONS:
        return HORIZONS["quarter"]["days"]
    return HORIZONS[horizon]["days"]


def summarize_verdict(score: float) -> tuple[str, str]:
    if score >= 75:
        return "Bullish", "Strong fit for the chosen horizon"
    if score >= 63:
        return "Constructive", "Worth a closer look, but not without caveats"
    if score >= 50:
        return "Mixed", "Some support exists, though conviction is not high"
    return "Cautious", "Risk-reward looks weak for the selected horizon"


def component_labels_for(asset_type: str) -> dict[str, str]:
    if asset_type == "stock":
        return {
            "momentum": "Price momentum",
            "quality": "Business quality",
            "growth": "Growth profile",
            "valuation": "Valuation setup",
            "risk": "Risk control",
            "analyst": "External analyst view",
        }
    return {
        "momentum": "Trend strength",
        "liquidity": "Liquidity and size",
        "risk": "Risk control",
        "supply": "Token supply setup",
        "longTerm": "Long-term market position",
    }


def component_explanation(asset_type: str, key: str, score: float) -> str:
    strength = "strong" if score >= 70 else "mixed" if score >= 45 else "weak"
    stock_descriptions = {
        "momentum": f"Recent price action and moving averages are {strength} for this horizon.",
        "quality": f"The quality-style signals used by the model read as {strength}.",
        "growth": f"Growth-oriented signals come through as {strength}.",
        "valuation": f"The valuation inputs land in {strength} territory.",
        "risk": f"Volatility, drawdown, and support-based risk signals are {strength}.",
        "analyst": f"Target prices and recommendation signals are {strength}.",
    }
    crypto_descriptions = {
        "momentum": f"Momentum and trend signals are {strength} for this time window.",
        "liquidity": f"Market-cap depth and trading liquidity are {strength}.",
        "risk": f"Volatility and drawdown controls are {strength}.",
        "supply": f"Dilution and circulating-supply conditions are {strength}.",
        "longTerm": f"Longer-term market position reads as {strength}.",
    }
    return (
        stock_descriptions.get(key, "This factor contributes to the final score.")
        if asset_type == "stock"
        else crypto_descriptions.get(key, "This factor contributes to the final score.")
    )


def build_score_breakdown(
    asset_type: str, components: dict[str, float], weights: dict[str, float]
) -> list[dict[str, Any]]:
    labels = component_labels_for(asset_type)
    breakdown = []
    for key, component_score in components.items():
        weight_key = "long_term" if key == "longTerm" else key
        weight = weights.get(weight_key, 0.0)
        contribution = round(component_score * weight, 1)
        breakdown.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "componentScore": component_score,
                "weightPercent": round(weight * 100, 1),
                "contribution": contribution,
                "explanation": component_explanation(asset_type, key, component_score),
            }
        )
    breakdown.sort(key=lambda item: item["contribution"], reverse=True)
    return breakdown


def pick_top_signals(signals: list[Signal], *, count: int = 3) -> list[str]:
    ordered = sorted(signals, key=lambda item: item.score, reverse=True)
    return [item.text for item in ordered[:count] if item.text]


def score_stock(snapshot: AssetSnapshot, horizon: str) -> dict[str, Any]:
    metrics = snapshot.metrics

    momentum = safe_mean(
        [
            scale_linear(metrics.get("return90d"), -20, 30),
            scale_linear(metrics.get("return180d"), -25, 40),
            scale_linear(metrics.get("priceVsMa50"), -10, 15),
            scale_linear(metrics.get("priceVsMa200"), -20, 25),
            scale_linear(metrics.get("fiftyTwoWeekRangePosition"), 30, 90),
        ]
    )
    quality = safe_mean(
        [
            scale_linear(first_available(metrics.get("profitMargins"), metrics.get("companyEarningsReports")), 0.02, 0.9),
            scale_linear(first_available(metrics.get("operatingMargins"), metrics.get("companyInnovativeness")), 0.05, 0.95),
            scale_linear(first_available(metrics.get("returnOnEquity"), metrics.get("companyHiring")), 0.08, 0.95),
        ]
    )
    growth = safe_mean(
        [
            scale_linear(first_available(metrics.get("revenueGrowth"), metrics.get("companyInnovativeness")), -0.05, 0.95),
            scale_linear(first_available(metrics.get("earningsGrowth"), metrics.get("companyEarningsReports")), -0.1, 0.95),
        ]
    )
    valuation = safe_mean(
        [
            scale_inverse(metrics.get("forwardPe"), 14, 35),
            scale_inverse(metrics.get("trailingPe"), 16, 40),
            scale_inverse(metrics.get("pegRatio"), 1.0, 3.0),
            scale_linear(metrics.get("valuationDiscount"), -10, 15),
        ]
    )
    risk = safe_mean(
        [
            scale_inverse(metrics.get("volatilityAnnualized"), 18, 55),
            scale_inverse(metrics.get("maxDrawdown"), 10, 45),
            scale_inverse(metrics.get("debtToEquity"), 20, 180),
            scale_inverse(metrics.get("beta"), 0.8, 1.8),
            scale_linear(distance_to_support(snapshot.current_price, metrics.get("support")), 0, 12),
        ]
    )
    analyst = safe_mean(
        [
            scale_linear(
                upside_to_target(snapshot.current_price, metrics.get("targetMeanPrice")),
                -5,
                20,
            ),
            scale_inverse(metrics.get("recommendationMean"), 1.8, 3.2),
            rating_score(metrics.get("recommendationRating")),
        ]
    )

    if horizon == "quarter":
        weights = {
            "momentum": 0.34,
            "quality": 0.16,
            "growth": 0.16,
            "valuation": 0.10,
            "risk": 0.12,
            "analyst": 0.12,
        }
    elif horizon == "six_months":
        weights = {
            "momentum": 0.25,
            "quality": 0.22,
            "growth": 0.20,
            "valuation": 0.12,
            "risk": 0.14,
            "analyst": 0.07,
        }
    else:
        weights = {
            "momentum": 0.18,
            "quality": 0.27,
            "growth": 0.20,
            "valuation": 0.18,
            "risk": 0.12,
            "analyst": 0.05,
        }

    components = {
        "momentum": round(momentum, 1),
        "quality": round(quality, 1),
        "growth": round(growth, 1),
        "valuation": round(valuation, 1),
        "risk": round(risk, 1),
        "analyst": round(analyst, 1),
    }
    total = round(sum(components[key] * weight for key, weight in weights.items()), 1)
    verdict, summary = summarize_verdict(total)

    positives = []
    negatives = []
    if (value := metrics.get("return90d")) and value > 8:
        positives.append(Signal(value, "Recent 90-day momentum is working in its favor."))
    if (value := metrics.get("revenueGrowth")) and value > 0.1:
        positives.append(Signal(value * 100, "Revenue growth still looks healthy."))
    if (value := metrics.get("profitMargins")) and value > 0.12:
        positives.append(Signal(value * 100, "Margins suggest durable operating quality."))
    if (value := metrics.get("companyInnovativeness")) and value > 0.8:
        positives.append(Signal(value * 100, "Innovation and product momentum remain a strength."))
    if (value := upside_to_target(snapshot.current_price, metrics.get("targetMeanPrice"))) and value > 8:
        positives.append(Signal(value, "Analyst targets still imply upside from current levels."))
    if (value := metrics.get("priceVsMa200")) and value > 5:
        positives.append(Signal(value, "The price remains above its long-term trend."))
    if (value := metrics.get("valuationDiscount")) and value > 5:
        positives.append(Signal(value, "The free valuation feed suggests the stock is not stretched."))

    if (value := metrics.get("trailingPe")) and value > 35:
        negatives.append(Signal(value, "Valuation is rich relative to many large caps."))
    if (value := metrics.get("debtToEquity")) and value > 150:
        negatives.append(Signal(value, "Leverage is elevated and can amplify downside."))
    if (value := metrics.get("maxDrawdown")) and value > 30:
        negatives.append(Signal(value, "The stock has suffered deep drawdowns over the last year."))
    if (value := metrics.get("return90d")) and value < -8:
        negatives.append(Signal(abs(value), "Momentum has weakened over the last quarter."))
    if (value := metrics.get("volatilityAnnualized")) and value > 45:
        negatives.append(Signal(value, "Volatility is high for this holding period."))
    if (trend := metrics.get("technicalLongTerm")) == "down":
        negatives.append(Signal(50, "The long-term technical trend is still pointing down."))
    if (value := distance_to_support(snapshot.current_price, metrics.get("support"))) and value < 2:
        negatives.append(Signal(60 - value, "Price is trading close to support, leaving less room for error."))

    return {
        "score": total,
        "verdict": verdict,
        "summary": summary,
        "components": components,
        "weights": weights,
        "scoreBreakdown": build_score_breakdown("stock", components, weights),
        "scoreMethod": "Final score = weighted sum of normalized component scores.",
        "positives": pick_top_signals(positives),
        "risks": pick_top_signals(negatives),
    }


def score_crypto(snapshot: AssetSnapshot, horizon: str) -> dict[str, Any]:
    metrics = snapshot.metrics

    momentum = safe_mean(
        [
            scale_linear(metrics.get("return30d"), -25, 40),
            scale_linear(metrics.get("return90d"), -35, 70),
            scale_linear(metrics.get("priceVsMa50"), -15, 25),
            scale_linear(metrics.get("priceVsMa200"), -25, 40),
        ]
    )
    liquidity = safe_mean(
        [
            scale_inverse(metrics.get("marketCapRank"), 1, 40),
            scale_linear(metrics.get("volumeToMarketCap"), 0.015, 0.18),
            scale_linear(snapshot.market_cap, 5_000_000_000, 1_000_000_000_000),
        ]
    )
    risk = safe_mean(
        [
            scale_inverse(metrics.get("volatilityAnnualized"), 35, 120),
            scale_inverse(metrics.get("maxDrawdown"), 20, 75),
        ]
    )
    supply = safe_mean(
        [
            scale_inverse(fdv_premium(metrics), 0.0, 1.0),
            scale_linear(supply_coverage(metrics), 0.5, 1.0),
        ]
    )
    long_term = safe_mean(
        [
            scale_linear(metrics.get("return365d"), -30, 120),
            scale_inverse(metrics.get("marketCapRank"), 1, 25),
        ]
    )

    if horizon == "quarter":
        weights = {
            "momentum": 0.42,
            "liquidity": 0.22,
            "risk": 0.16,
            "supply": 0.10,
            "long_term": 0.10,
        }
    elif horizon == "six_months":
        weights = {
            "momentum": 0.28,
            "liquidity": 0.24,
            "risk": 0.20,
            "supply": 0.14,
            "long_term": 0.14,
        }
    else:
        weights = {
            "momentum": 0.18,
            "liquidity": 0.24,
            "risk": 0.22,
            "supply": 0.18,
            "long_term": 0.18,
        }

    components = {
        "momentum": round(momentum, 1),
        "liquidity": round(liquidity, 1),
        "risk": round(risk, 1),
        "supply": round(supply, 1),
        "longTerm": round(long_term, 1),
    }
    total = round(
        components["momentum"] * weights["momentum"]
        + components["liquidity"] * weights["liquidity"]
        + components["risk"] * weights["risk"]
        + components["supply"] * weights["supply"]
        + components["longTerm"] * weights["long_term"],
        1,
    )
    verdict, summary = summarize_verdict(total)

    positives = []
    negatives = []
    if (value := metrics.get("return90d")) and value > 18:
        positives.append(Signal(value, "Momentum is strong across the last quarter."))
    if (value := metrics.get("marketCapRank")) and value <= 10:
        positives.append(Signal(100 - value, "Large-cap positioning improves liquidity and survivability."))
    if (value := metrics.get("volumeToMarketCap")) and value > 0.05:
        positives.append(Signal(value * 100, "Trading activity is healthy relative to market cap."))
    if (value := supply_coverage(metrics)) and value > 0.85:
        positives.append(Signal(value * 100, "Most supply is already circulating, which reduces dilution risk."))
    if (value := metrics.get("return365d")) and value > 35:
        positives.append(Signal(value, "The one-year trend still points higher."))

    if (value := metrics.get("maxDrawdown")) and value > 55:
        negatives.append(Signal(value, "Historical drawdowns have been severe."))
    if (value := metrics.get("volatilityAnnualized")) and value > 85:
        negatives.append(Signal(value, "Volatility is high even by crypto standards."))
    if (value := fdv_premium(metrics)) and value > 0.4:
        negatives.append(Signal(value * 100, "Fully diluted valuation is far above current market cap."))
    if (value := metrics.get("return30d")) and value < -15:
        negatives.append(Signal(abs(value), "Near-term trend has rolled over."))
    if (value := metrics.get("marketCapRank")) and value > 25:
        negatives.append(Signal(value, "Smaller market-cap assets usually carry more execution risk."))

    return {
        "score": total,
        "verdict": verdict,
        "summary": summary,
        "components": components,
        "weights": weights,
        "scoreBreakdown": build_score_breakdown("crypto", components, weights),
        "scoreMethod": "Final score = weighted sum of normalized component scores.",
        "positives": pick_top_signals(positives),
        "risks": pick_top_signals(negatives),
    }


def upside_to_target(current_price: float | None, target_price: float | None) -> float | None:
    if not current_price or not target_price:
        return None
    return ((target_price / current_price) - 1.0) * 100.0


def distance_to_support(current_price: float | None, support_price: float | None) -> float | None:
    if not current_price or not support_price:
        return None
    return ((current_price / support_price) - 1.0) * 100.0


def rating_score(rating: str | None) -> float | None:
    if not rating:
        return None
    normalized = rating.strip().lower()
    mapping = {
        "strong buy": 92.0,
        "buy": 84.0,
        "outperform": 78.0,
        "overweight": 75.0,
        "hold": 52.0,
        "neutral": 50.0,
        "underperform": 26.0,
        "sell": 12.0,
    }
    return mapping.get(normalized, 50.0)


def fdv_premium(metrics: dict[str, Any]) -> float | None:
    fdv = metrics.get("fullyDilutedValuation")
    market_cap = metrics.get("marketCap")
    if not fdv or not market_cap or market_cap <= 0:
        return None
    return max(0.0, (fdv / market_cap) - 1.0)


def supply_coverage(metrics: dict[str, Any]) -> float | None:
    circulating = metrics.get("circulatingSupply")
    max_supply = metrics.get("maxSupply")
    if not circulating or not max_supply or max_supply <= 0:
        return None
    return clamp(circulating / max_supply, 0.0, 1.0)


def build_scorecard(snapshot: AssetSnapshot, horizon: str) -> dict[str, Any]:
    enriched = enrich_snapshot(snapshot)
    if enriched.asset_type == "stock":
        scorecard = score_stock(enriched, horizon)
    else:
        scorecard = score_crypto(enriched, horizon)
    scorecard["horizon"] = horizon
    scorecard["horizonLabel"] = HORIZONS.get(horizon, HORIZONS["quarter"])["label"]
    return {"snapshot": enriched, "scorecard": scorecard}


def build_recommendation_analysis(
    snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
) -> dict[str, Any]:
    components = scorecard.get("components", {})
    ordered = sorted(components.items(), key=lambda item: item[1], reverse=True)
    best_components = ordered[:3]
    weakest_components = ordered[-2:]
    labels = {
        key: value.lower()
        for key, value in component_labels_for(
            "stock" if snapshot.asset_type == "stock" else "crypto"
        ).items()
    }
    horizon_label = HORIZONS.get(horizon, HORIZONS["quarter"])["label"].lower()

    if scorecard["score"] >= 75:
        headline = f"Why {snapshot.symbol} stands out for the {horizon_label}"
        fit = f"{snapshot.symbol} grades well for this timeframe because its strongest signals line up with the holding period rather than fighting it."
    elif scorecard["score"] >= 63:
        headline = f"Why {snapshot.symbol} makes the shortlist"
        fit = f"The recommendation is more selective than aggressive: there is enough support to keep {snapshot.symbol} on the shortlist for a {horizon_label} position, but not enough to ignore the risks."
    elif scorecard["score"] >= 50:
        headline = f"Why {snapshot.symbol} is only a watchlist idea"
        fit = f"The case is mixed. Some factors are attractive, but the weaker signals mean this is better treated as a watchlist candidate for the {horizon_label}."
    else:
        headline = f"Why {snapshot.symbol} is not a high-conviction pick"
        fit = f"The model does not see enough evidence to recommend {snapshot.symbol} strongly for the {horizon_label}. The upside case exists, but the risk-reward looks thin."

    key_drivers = scorecard.get("positives")[:3]
    if not key_drivers:
        key_drivers = [
            f"Its best scoring area is {labels.get(name, name)}." for name, _ in best_components
        ]

    watch_items = scorecard.get("risks")[:3]
    if not watch_items:
        watch_items = [
            f"The weakest area is {labels.get(name, name)}, which limits conviction."
            for name, _ in weakest_components
        ]

    return {
        "headline": headline,
        "fit": fit,
        "keyDrivers": key_drivers,
        "watchItems": watch_items,
        "timeframeReason": f"The recommendation is specifically tuned for a {horizon_label} horizon, so shorter or longer holding periods may lead to a different conclusion.",
        "scoreMethod": scorecard.get("scoreMethod"),
        "scoreBreakdown": scorecard.get("scoreBreakdown", []),
    }


def build_stock_suggestions(
    service: MarketDataService, *, top_n: int = 4
) -> dict[str, Any]:
    snapshots: list[AssetSnapshot] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(service.stocks.get_snapshot, symbol): (symbol, label)
            for symbol, label in DEFAULT_STOCK_UNIVERSE
        }
        for future in as_completed(futures):
            symbol, _ = futures[future]
            try:
                snapshots.append(enrich_snapshot(future.result()))
            except Exception:
                continue

    horizons = {
        name: rank_snapshots(snapshots, name, top_n=top_n)
        for name in ("quarter", "six_months", "year")
    }
    return {
        "assetType": "stock",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "requestedLimit": top_n,
        "horizons": horizons,
    }


def build_crypto_suggestions(
    service: MarketDataService, *, top_n: int = 4
) -> dict[str, Any]:
    raw_markets = service.crypto.top_markets(per_page=20)
    snapshots: list[AssetSnapshot] = []
    for item in raw_markets:
        name = (item.get("name") or "").lower()
        symbol = (item.get("symbol") or "").upper()
        if name in STABLECOIN_NAMES or symbol in STABLECOIN_SYMBOLS:
            continue
        market_cap = item.get("market_cap")
        total_volume = item.get("total_volume")
        snapshot = AssetSnapshot(
            asset_type="crypto",
            identifier=item.get("id"),
            symbol=symbol,
            name=item.get("name") or symbol,
            currency="USD",
            current_price=item.get("current_price"),
            market_cap=market_cap,
            summary=None,
            history=[],
            metrics={
                "marketCap": market_cap,
                "marketCapRank": item.get("market_cap_rank"),
                "totalVolume": total_volume,
                "volumeToMarketCap": (total_volume / market_cap) if total_volume and market_cap else None,
                "return30d": item.get("price_change_percentage_30d_in_currency"),
                "return90d": item.get("price_change_percentage_30d_in_currency"),
                "return365d": item.get("price_change_percentage_1y_in_currency"),
                "fullyDilutedValuation": item.get("fully_diluted_valuation"),
                "circulatingSupply": item.get("circulating_supply"),
                "maxSupply": item.get("max_supply"),
                "volatilityAnnualized": None,
                "maxDrawdown": None,
                "priceVsMa50": None,
                "priceVsMa200": None,
            },
            context={},
            source="CoinGecko",
        )
        snapshots.append(snapshot)

    horizons = {
        name: rank_snapshots(snapshots, name, top_n=top_n)
        for name in ("quarter", "six_months", "year")
    }
    return {
        "assetType": "crypto",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "requestedLimit": top_n,
        "horizons": horizons,
    }


def rank_snapshots(
    snapshots: list[AssetSnapshot], horizon: str, *, top_n: int = 4
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for snapshot in snapshots:
        scored = build_scorecard(snapshot, horizon)
        scorecard = scored["scorecard"]
        ranked.append(
            (
                scorecard["score"],
                {
                    "identifier": snapshot.identifier,
                    "symbol": snapshot.symbol,
                    "name": snapshot.name,
                    "currentPrice": snapshot.current_price,
                    "marketCap": snapshot.market_cap,
                    "score": scorecard["score"],
                    "verdict": scorecard["verdict"],
                    "summary": scorecard["summary"],
                    "positives": scorecard["positives"],
                    "risks": scorecard["risks"],
                },
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:top_n]]
