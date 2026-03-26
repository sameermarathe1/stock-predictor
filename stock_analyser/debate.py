from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .config import Settings
from .http_client import ApiError, request_json
from .providers import AssetSnapshot


def compact_snapshot(snapshot: AssetSnapshot) -> dict[str, Any]:
    metric_subset = {
        key: value
        for key, value in snapshot.metrics.items()
        if key
        in {
            "return30d",
            "return90d",
            "return180d",
            "return365d",
            "volatilityAnnualized",
            "maxDrawdown",
            "priceVsMa50",
            "priceVsMa200",
            "revenueGrowth",
            "earningsGrowth",
            "profitMargins",
            "operatingMargins",
            "forwardPe",
            "trailingPe",
            "debtToEquity",
            "beta",
            "targetMeanPrice",
            "recommendationMean",
            "marketCapRank",
            "volumeToMarketCap",
            "fullyDilutedValuation",
            "circulatingSupply",
            "maxSupply",
        }
    }
    return {
        "assetType": snapshot.asset_type,
        "symbol": snapshot.symbol,
        "name": snapshot.name,
        "currentPrice": snapshot.current_price,
        "marketCap": snapshot.market_cap,
        "summary": snapshot.summary,
        "context": snapshot.context,
        "metrics": metric_subset,
    }


class RulesDebateEngine:
    def debate(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        bull = self._bull_case(snapshot, horizon, scorecard)
        bear = self._bear_case(snapshot, horizon, scorecard)
        quant = self._quant_case(snapshot, horizon, scorecard)
        moderator = self._moderator(snapshot, horizon, scorecard, [bull, bear, quant])
        return {
            "mode": "rules",
            "analysts": [bull, bear, quant],
            "moderator": moderator,
        }

    def _bull_case(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        conviction = min(95, int(scorecard["score"] + 10))
        stance = "Buy" if scorecard["score"] >= 63 else "Speculative Buy"
        evidence = scorecard["positives"] or [
            "There are enough supporting signals to keep the upside case alive."
        ]
        risks = scorecard["risks"][:1] or ["Upside depends on execution staying on track."]
        return {
            "name": "Bull Analyst",
            "stance": stance,
            "conviction": conviction,
            "summary": f"The bullish case says {snapshot.symbol} still has enough tailwinds for a {horizon.replace('_', ' ')} holding period.",
            "evidence": evidence,
            "risks": risks,
        }

    def _bear_case(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        risk_penalty = max(0, 100 - int(scorecard["score"]))
        stance = "Avoid" if scorecard["score"] < 52 else "Hold Off"
        evidence = scorecard["risks"] or [
            "The setup does not create enough margin of safety."
        ]
        counterpoints = scorecard["positives"][:1] or ["Momentum could improve if conditions change."]
        return {
            "name": "Bear Analyst",
            "stance": stance,
            "conviction": min(95, 45 + risk_penalty),
            "summary": f"The bearish case argues the current setup does not justify new capital over the next {horizon.replace('_', ' ')}.",
            "evidence": evidence,
            "risks": counterpoints,
        }

    def _quant_case(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        components = scorecard["components"]
        momentum = components.get("momentum", 50)
        risk = components.get("risk", components.get("liquidity", 50))
        if momentum >= 60 and risk >= 50:
            stance = "Trend Favours Entry"
        elif momentum >= 55:
            stance = "Watch Momentum"
        else:
            stance = "Weak Setup"
        evidence = [
            f"Momentum component: {momentum}/100.",
            f"Risk or liquidity profile: {risk}/100.",
            f"Overall score: {scorecard['score']}/100 for the chosen horizon.",
        ]
        return {
            "name": "Quant Analyst",
            "stance": stance,
            "conviction": min(95, int((momentum * 0.6) + (risk * 0.4))),
            "summary": f"The quant view focuses on trend strength, drawdown profile, and consistency for the {horizon.replace('_', ' ')} window.",
            "evidence": evidence,
            "risks": scorecard["risks"][:2] or ["The signal quality is average rather than decisive."],
        }

    def _moderator(
        self,
        snapshot: AssetSnapshot,
        horizon: str,
        scorecard: dict[str, Any],
        analysts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        favorable = sum(1 for analyst in analysts if analyst["stance"] in {"Buy", "Speculative Buy", "Trend Favours Entry"})
        if scorecard["score"] >= 72:
            action = "Consider building a position"
        elif scorecard["score"] >= 60:
            action = "Keep on the watchlist"
        else:
            action = "Wait for a better setup"
        return {
            "name": "Moderator",
            "stance": scorecard["verdict"],
            "summary": f"{favorable} of 3 analysts see enough support to stay constructive on {snapshot.symbol}, but the final call depends on how much downside you can tolerate.",
            "decision": action,
            "keyTakeaways": [
                scorecard["summary"],
                *(scorecard["positives"][:2] or ["No single factor dominates the case."]),
                *(scorecard["risks"][:1] or ["Risk remains manageable but not trivial."]),
            ],
        }


class OpenAIDebateEngine:
    PERSONAS = {
        "Bull Analyst": "Argue the upside case. Be concrete about catalysts, growth, momentum, and reasons this asset can outperform over the selected horizon.",
        "Bear Analyst": "Argue the downside case. Focus on valuation, macro, drawdowns, dilution, leverage, competition, and reasons the market may be overestimating upside.",
        "Quant Analyst": "Focus on signals, trend strength, volatility, drawdown profile, and whether the price action supports taking risk over the selected horizon.",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def debate(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.settings.llm_enabled:
            raise ApiError("OpenAI debate requested without OPENAI_API_KEY and OPENAI_MODEL.")

        analysis_packet = {
            "asset": compact_snapshot(snapshot),
            "horizon": horizon,
            "scorecard": scorecard,
        }

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(self._run_persona, name, instruction, analysis_packet)
                for name, instruction in self.PERSONAS.items()
            ]
            analysts = [future.result() for future in futures]

        moderator = self._run_moderator(snapshot, horizon, scorecard, analysts)
        return {"mode": "llm", "analysts": analysts, "moderator": moderator}

    def _run_persona(
        self, name: str, instruction: str, analysis_packet: dict[str, Any]
    ) -> dict[str, Any]:
        system_prompt = (
            "You are part of an investment debate panel. "
            "Respond as valid JSON with keys: name, stance, conviction, summary, evidence, risks. "
            "conviction must be an integer from 0 to 100. "
            "Keep evidence and risks to 2-3 short strings each."
        )
        user_prompt = (
            f"Persona: {name}\n"
            f"Instructions: {instruction}\n"
            f"Analysis packet:\n{json.dumps(analysis_packet, indent=2)}"
        )
        return normalize_analyst_payload(self._chat_json(system_prompt, user_prompt), name)

    def _run_moderator(
        self,
        snapshot: AssetSnapshot,
        horizon: str,
        scorecard: dict[str, Any],
        analysts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are the moderator of an investment debate. "
            "Return valid JSON with keys: name, stance, summary, decision, keyTakeaways. "
            "keyTakeaways should be 3 short strings."
        )
        user_prompt = json.dumps(
            {
                "asset": compact_snapshot(snapshot),
                "horizon": horizon,
                "scorecard": scorecard,
                "analysts": analysts,
            },
            indent=2,
        )
        return self._chat_json(system_prompt, user_prompt)

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        response = request_json(
            f"{self.settings.openai_base_url}/chat/completions",
            method="POST",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            payload=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        content = ((response.get("choices") or [{}])[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise ApiError("OpenAI returned an unexpected chat completion shape.")
        return json.loads(content)


def normalize_analyst_payload(payload: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["name"] = normalized.get("name") or fallback_name
    normalized["conviction"] = normalize_conviction(normalized.get("conviction"))
    normalized["evidence"] = normalize_list_field(normalized.get("evidence"))
    normalized["risks"] = normalize_list_field(normalized.get("risks"))
    return normalized


def normalize_conviction(value: Any) -> int:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return 50
    if isinstance(value, (int, float)):
        numeric = float(value)
        if 0.0 <= numeric <= 1.0:
            numeric *= 100.0
        return max(0, min(100, int(round(numeric))))
    return 50


def normalize_list_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class DebateOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.rules = RulesDebateEngine()
        self.llm = OpenAIDebateEngine(settings)

    def debate(
        self, snapshot: AssetSnapshot, horizon: str, scorecard: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.llm.settings.llm_enabled:
            return self.rules.debate(snapshot, horizon, scorecard)
        try:
            return self.llm.debate(snapshot, horizon, scorecard)
        except Exception as exc:
            fallback = self.rules.debate(snapshot, horizon, scorecard)
            fallback["warning"] = f"LLM debate fell back to rules mode: {exc}"
            return fallback
