from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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
            "targetMedianPrice",
            "recommendationMean",
            "recommendationRating",
            "marketCapRank",
            "volumeToMarketCap",
            "fullyDilutedValuation",
            "circulatingSupply",
            "maxSupply",
            "support",
            "resistance",
            "stopLoss",
            "valuationDiscount",
            "technicalShortTerm",
            "technicalMidTerm",
            "technicalLongTerm",
            "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow",
            "fiftyTwoWeekRangePosition",
            "averageDailyVolume3Month",
        }
    }
    return {
        "assetType": snapshot.asset_type,
        "symbol": snapshot.symbol,
        "name": snapshot.name,
        "currency": snapshot.currency,
        "currentPrice": snapshot.current_price,
        "marketCap": snapshot.market_cap,
        "summary": snapshot.summary,
        "context": snapshot.context,
        "metrics": metric_subset,
        "historyTail": snapshot.history[-20:],
        "source": snapshot.source,
    }


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
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_text(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or default
    if value is None:
        return default
    return str(value).strip() or default


def merge_unique_strings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            normalized = item.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return merged


def normalize_citations(citations: list[dict[str, str]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for citation in citations or []:
        url = normalize_text(citation.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        normalized.append(
            {
                "title": normalize_text(citation.get("title"), url),
                "url": url,
            }
        )
    return normalized


def extract_text_and_citations(response: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    text_parts: list[str] = []
    citations: list[dict[str, str]] = []

    for item in response.get("output", []) or []:
        if item.get("type") == "web_search_call":
            action = item.get("action") or {}
            for source in action.get("sources", []) or []:
                citations.append(
                    {
                        "title": normalize_text(source.get("title")),
                        "url": normalize_text(source.get("url")),
                    }
                )
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") not in {"output_text", "text"}:
                continue
            text = normalize_text(content.get("text"))
            if text:
                text_parts.append(text)
            for annotation in content.get("annotations", []) or []:
                if annotation.get("type") != "url_citation":
                    continue
                citations.append(
                    {
                        "title": normalize_text(annotation.get("title")),
                        "url": normalize_text(annotation.get("url")),
                    }
                )

    if not text_parts and isinstance(response.get("output_text"), str):
        text_parts.append(response["output_text"])

    return "\n".join(part for part in text_parts if part), normalize_citations(citations)


def parse_json_response_text(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            parsed, end_index = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and not cleaned[index + end_index :].strip():
            return parsed

    raise ApiError("OpenAI counsel returned invalid JSON content.")


def parse_research_brief_text(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()

    sections = {
        "SUMMARY": [],
        "MARKET_CONTEXT": [],
        "CATALYSTS": [],
        "CONCERNS": [],
        "OPTIONS_CONTEXT": [],
        "SOURCES": [],
    }
    current_key = ""

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.rstrip(":")
        if normalized in sections:
            current_key = normalized
            continue

        for key in sections:
            prefix = f"{key}:"
            if line.startswith(prefix):
                current_key = key
                remainder = line[len(prefix) :].strip()
                if remainder:
                    sections[key].append(remainder)
                break
        else:
            if not current_key:
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            sections[current_key].append(line)

    summary = " ".join(sections["SUMMARY"]).strip()
    market_context = " ".join(sections["MARKET_CONTEXT"]).strip()
    options_context = " ".join(sections["OPTIONS_CONTEXT"]).strip()
    catalysts = [item for item in sections["CATALYSTS"] if item]
    concerns = [item for item in sections["CONCERNS"] if item]
    sources = [item for item in sections["SOURCES"] if item]

    if not any([summary, market_context, options_context, catalysts, concerns, sources]):
        raise ApiError("OpenAI counsel returned an invalid research brief.")

    return {
        "summary": summary,
        "marketContext": market_context,
        "catalysts": catalysts,
        "concerns": concerns,
        "optionsContext": options_context,
        "sources": sources,
    }


def parse_citation_line(line: str) -> dict[str, str] | None:
    raw = line.strip()
    if raw.startswith("- "):
        raw = raw[2:].strip()
    if not raw:
        return None

    if "|" in raw:
        title, url = [part.strip() for part in raw.split("|", 1)]
        if url.startswith("http://") or url.startswith("https://"):
            return {"title": title or url, "url": url}

    if raw.startswith("http://") or raw.startswith("https://"):
        return {"title": raw, "url": raw}

    return None


def normalize_analyst_payload(payload: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["name"] = normalized.get("name") or fallback_name
    normalized["conviction"] = normalize_conviction(normalized.get("conviction"))
    normalized["evidence"] = normalize_list_field(normalized.get("evidence"))
    normalized["risks"] = normalize_list_field(normalized.get("risks"))
    normalized["summary"] = normalize_text(normalized.get("summary"))
    normalized["stance"] = normalize_text(normalized.get("stance"), "View")
    return normalized


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
        favorable = sum(
            1
            for analyst in analysts
            if analyst["stance"] in {"Buy", "Speculative Buy", "Trend Favours Entry"}
        )
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


class OpenAICounselEngine:
    PERSONAS = (
        {
            "name": "Fundamental Analyst",
            "specialty": "Business quality",
            "instruction": (
                "Focus on business quality, margins, growth, competitive moat, capital intensity, "
                "and whether the current financial snapshot supports owning the stock."
            ),
        },
        {
            "name": "Technical Analyst",
            "specialty": "Price action",
            "instruction": (
                "Focus on momentum, support and resistance, volatility, drawdowns, trend quality, "
                "and whether the timing for the stated horizon is attractive."
            ),
        },
        {
            "name": "Risk Manager",
            "specialty": "Downside control",
            "instruction": (
                "Focus on position risk, valuation traps, downside scenarios, invalidation levels, "
                "and what would make the thesis break."
            ),
        },
        {
            "name": "Options Strategist",
            "specialty": "Derivatives framing",
            "instruction": (
                "Focus on whether common-stock exposure is better than a call, put, or no-options view. "
                "Only suggest options when the risk-reward is clearly better and explain the conditions."
            ),
        },
        {
            "name": "Macro Analyst",
            "specialty": "Macro and catalysts",
            "instruction": (
                "Focus on rates, sector rotation, regulation, macro catalysts, and newsflow that could "
                "change the thesis over the selected horizon."
            ),
        },
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def debate(
        self,
        snapshot: AssetSnapshot,
        horizon: str,
        scorecard: dict[str, Any],
        member_count: int,
    ) -> dict[str, Any]:
        if not self.settings.counsel_enabled:
            raise ApiError(
                "AI counsel requires OPENAI_API_KEY and at least one counsel model."
            )

        member_count = max(2, min(member_count, self.settings.counsel_member_limit()))
        counsel_packet = {
            "generatedAt": datetime.now(tz=UTC).date().isoformat(),
            "asset": compact_snapshot(snapshot),
            "horizon": horizon,
            "scorecard": scorecard,
        }
        assignments = self._assignments(member_count)
        shared_research_warning = ""
        research_model = self._pick_research_model()
        try:
            shared_research = self._run_shared_research(
                counsel_packet,
                research_model,
            )
        except Exception as exc:
            shared_research = self._run_local_research(
                counsel_packet,
                research_model,
            )
            shared_research_warning = (
                "Shared web research timed out, so the counsel continued with market-data-only research: "
                f"{exc}"
            )

        with ThreadPoolExecutor(max_workers=member_count) as executor:
            opening_futures = [
                executor.submit(
                    self._build_opening_case,
                    assignment,
                    counsel_packet,
                    shared_research,
                )
                for assignment in assignments
            ]
            openings = [future.result() for future in opening_futures]

        moderator = self._build_moderator(
            counsel_packet,
            shared_research,
            openings,
        )

        result = {
            "mode": "counsel",
            "analysts": openings,
            "moderator": moderator,
            "counsel": {
                "enabled": True,
                "memberCount": member_count,
                "maxMembers": self.settings.counsel_member_limit(),
                "modelsUsed": [shared_research["model"]] if shared_research.get("model") else [],
                "verdict": {
                    "investable": moderator["investable"],
                    "tradeType": moderator["tradeType"],
                    "entryPlan": moderator["entryPlan"],
                    "exitPlan": moderator["exitPlan"],
                    "optionsIdea": moderator["optionsIdea"],
                    "confidence": moderator["confidence"],
                    "riskFlags": moderator["riskFlags"],
                    "summary": moderator["discussionSummary"] or moderator["summary"],
                    "citations": moderator["citations"],
                },
                "transcript": self._build_transcript(shared_research, openings, moderator),
            },
        }
        if shared_research_warning:
            result["warning"] = shared_research_warning
        return result

    def _assignments(self, member_count: int) -> list[dict[str, str]]:
        models = self.settings.pick_counsel_models(member_count)
        personas = list(self.PERSONAS[:member_count])
        return [
            {
                **persona,
                "model": models[index],
            }
            for index, persona in enumerate(personas)
        ]

    def _pick_research_model(self) -> str:
        candidates = list(self.settings.counsel_models)
        if not candidates:
            if not self.settings.openai_model:
                raise ApiError("No OpenAI model is configured for shared research.")
            return self.settings.openai_model

        preferred_exact = ("gpt-4.1-mini", "gpt-5-mini")
        for target in preferred_exact:
            for candidate in candidates:
                if candidate == target:
                    return candidate

        for candidate in candidates:
            if "mini" in candidate.lower():
                return candidate

        return candidates[0]

    def _run_opening_case(
        self,
        assignment: dict[str, str],
        counsel_packet: dict[str, Any],
        shared_research: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are a member of an AI investment counsel. Use the supplied financial packet and "
            "shared research brief to form an actionable view. Do not browse for fresh information in this round. "
            "Return JSON only with keys: "
            "name, stance, conviction, summary, message, evidence, risks, entryPlan, exitPlan, optionsIdea. "
            "conviction must be an integer from 0 to 100. summary should be 1-2 sentences. "
            "message should read like an opening argument in 2-4 sentences. evidence and risks must each "
            "contain 2-4 short strings. optionsIdea may be an empty string when no options trade is justified. "
            "Do not wrap the JSON in markdown fences."
        )
        user_prompt = json.dumps(
            {
                "persona": assignment["name"],
                "specialty": assignment["specialty"],
                "instructions": assignment["instruction"],
                "guidance": {
                    "task": "Decide whether the stock looks investible over the selected horizon.",
                    "requiredOutput": [
                        "A clear stance",
                        "An entry framing",
                        "An exit or invalidation plan",
                        "An options idea only if it is genuinely superior to spot exposure",
                    ],
                },
                "sharedResearch": shared_research,
                "analysisPacket": counsel_packet,
            },
            indent=2,
        )
        payload = self._chat_json(
            model=assignment["model"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return {
            "name": normalize_text(payload.get("name"), assignment["name"]),
            "specialty": assignment["specialty"],
            "model": assignment["model"],
            "stance": normalize_text(payload.get("stance"), "Watchlist"),
            "conviction": normalize_conviction(payload.get("conviction")),
            "summary": normalize_text(payload.get("summary")),
            "message": normalize_text(payload.get("message"), normalize_text(payload.get("summary"))),
            "evidence": normalize_list_field(payload.get("evidence"))[:4],
            "risks": normalize_list_field(payload.get("risks"))[:4],
            "entryPlan": normalize_text(payload.get("entryPlan"), "Wait for more confirmation."),
            "exitPlan": normalize_text(payload.get("exitPlan"), "No exit plan was stated."),
            "optionsIdea": normalize_text(payload.get("optionsIdea")),
            "citations": [],
        }

    def _build_opening_case(
        self,
        assignment: dict[str, str],
        counsel_packet: dict[str, Any],
        shared_research: dict[str, Any],
    ) -> dict[str, Any]:
        scorecard = counsel_packet["scorecard"]
        asset = counsel_packet["asset"]
        metrics = asset.get("metrics", {})
        positives = scorecard.get("positives", [])
        risks = scorecard.get("risks", [])
        catalysts = shared_research.get("catalysts", [])
        concerns = shared_research.get("concerns", [])
        score = float(scorecard.get("score", 50))
        symbol = asset.get("symbol", "the asset")
        specialty = assignment["specialty"]

        if specialty == "Business quality":
            stance = "Accumulate" if score >= 66 else "Watchlist" if score >= 55 else "Avoid"
            conviction = min(92, max(35, int(score + 8)))
            summary = (
                f"The business-quality view is {'constructive' if score >= 66 else 'mixed' if score >= 55 else 'cautious'} "
                f"on {symbol} over this horizon."
            )
            evidence = merge_unique_strings(positives[:2], catalysts[:2])[:4]
            risk_items = merge_unique_strings(risks[:2], concerns[:2])[:4]
        elif specialty == "Price action":
            momentum = int(scorecard.get("components", {}).get("momentum", 50))
            stance = (
                "Trend improving" if momentum >= 65 else "Wait for confirmation" if momentum >= 55 else "Weak trend"
            )
            conviction = min(90, max(30, momentum))
            summary = (
                f"The technical view sees {'supportive' if momentum >= 65 else 'uncertain' if momentum >= 55 else 'weak'} "
                f"price action for {symbol} right now."
            )
            evidence = merge_unique_strings(
                [
                    f"Momentum score is {momentum}/100.",
                    self._price_level_note(metrics),
                ],
                catalysts[:1],
            )[:4]
            risk_items = merge_unique_strings(risks[:2], concerns[:2])[:4]
        elif specialty == "Downside control":
            stance = "Size carefully" if score >= 60 else "Capital preservation first"
            conviction = min(90, max(40, int(100 - score + 35)))
            summary = (
                f"The risk view stays focused on protecting downside before pressing upside in {symbol}."
            )
            evidence = merge_unique_strings(
                risks[:2],
                concerns[:2],
                [self._exit_plan_from_metrics(metrics)],
            )[:4]
            risk_items = merge_unique_strings(concerns[:2], risks[:2])[:4]
        elif specialty == "Derivatives framing":
            stance = "Options selective"
            conviction = min(85, max(35, int(score)))
            summary = (
                f"The options view prefers defined-risk structures only if the catalyst path is clean enough."
            )
            evidence = merge_unique_strings(
                catalysts[:2],
                [shared_research.get("optionsContext", "")],
            )[:4]
            risk_items = merge_unique_strings(concerns[:2], risks[:2])[:4]
        else:
            stance = "Macro watch"
            conviction = min(85, max(35, int(score)))
            summary = (
                f"The macro view thinks outside context still matters for whether {symbol} can work this quarter."
            )
            evidence = merge_unique_strings(
                [shared_research.get("marketContext", "")],
                catalysts[:2],
            )[:4]
            risk_items = merge_unique_strings(concerns[:2], risks[:2])[:4]

        return {
            "name": assignment["name"],
            "specialty": assignment["specialty"],
            "model": shared_research.get("model"),
            "stance": stance,
            "conviction": conviction,
            "summary": summary,
            "message": summary,
            "evidence": evidence or positives[:2] or ["The setup has a balanced risk-reward profile."],
            "risks": risk_items or risks[:2] or ["The setup still needs monitoring."],
            "entryPlan": self._entry_plan_from_score(score, metrics),
            "exitPlan": self._exit_plan_from_metrics(metrics),
            "optionsIdea": self._options_idea(score, catalysts, concerns),
            "citations": [],
        }

    def _run_shared_research(
        self, counsel_packet: dict[str, Any], model: str
    ) -> dict[str, Any]:
        system_prompt = (
            "You are the research lead for an AI investment counsel. Use live web search once to collect the most "
            "important context for the room. Return plain text in exactly this format and nothing else:\n"
            "SUMMARY:\n"
            "MARKET_CONTEXT:\n"
            "CATALYSTS:\n"
            "- item\n"
            "CONCERNS:\n"
            "- item\n"
            "OPTIONS_CONTEXT:\n"
            "SOURCES:\n"
            "- Source title | https://example.com\n"
            "Keep SUMMARY to 2-3 sentences. Keep MARKET_CONTEXT and OPTIONS_CONTEXT to one short line each. "
            "Provide 2-4 bullet items each for CATALYSTS and CONCERNS. Do not use JSON. "
            "List 3-6 sources in SOURCES using the exact 'title | url' pattern. "
            "Do not wrap the answer in markdown fences."
        )
        user_prompt = json.dumps(
            {
                "task": (
                    "Gather current web context for this asset so multiple analysts can debate it without "
                    "running separate searches."
                ),
                "analysisPacket": counsel_packet,
            },
            indent=2,
        )
        content, citations = self._response_text(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        payload = parse_research_brief_text(content)
        parsed_citations = normalize_citations(
            [parse_citation_line(line) for line in payload.get("sources", []) if parse_citation_line(line)]
        )
        return {
            "summary": normalize_text(payload.get("summary")),
            "marketContext": normalize_text(payload.get("marketContext")),
            "catalysts": normalize_list_field(payload.get("catalysts"))[:4],
            "concerns": normalize_list_field(payload.get("concerns"))[:4],
            "optionsContext": normalize_text(payload.get("optionsContext")),
            "citations": normalize_citations(parsed_citations + citations),
            "model": model,
            "mode": "web",
        }

    def _run_local_research(
        self, counsel_packet: dict[str, Any], model: str
    ) -> dict[str, Any]:
        system_prompt = (
            "You are the research lead for an AI investment counsel. Use only the supplied market data packet "
            "to create a concise internal research brief. Do not browse for fresh information. Return JSON only "
            "with keys: summary, marketContext, catalysts, concerns, optionsContext. summary should be 2-3 "
            "sentences. marketContext and optionsContext should be short strings. catalysts and concerns should "
            "each contain 2-4 short strings. Do not wrap the JSON in markdown fences."
        )
        user_prompt = json.dumps(
            {
                "task": "Build a fast internal research brief from the existing market-data snapshot only.",
                "analysisPacket": counsel_packet,
            },
            indent=2,
        )
        payload = self._chat_json(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return {
            "summary": normalize_text(payload.get("summary")),
            "marketContext": normalize_text(payload.get("marketContext")),
            "catalysts": normalize_list_field(payload.get("catalysts"))[:4],
            "concerns": normalize_list_field(payload.get("concerns"))[:4],
            "optionsContext": normalize_text(payload.get("optionsContext")),
            "citations": [],
            "model": model,
            "mode": "local",
        }

    def _run_moderator(
        self,
        counsel_packet: dict[str, Any],
        shared_research: dict[str, Any],
        openings: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are the chair of an AI investment counsel. Use the shared research brief and the room's arguments "
            "to reach a concrete action. Do not browse for new information in this round. Return JSON only with keys: "
            "name, stance, summary, decision, "
            "keyTakeaways, investable, tradeType, entryPlan, exitPlan, optionsIdea, confidence, riskFlags, "
            "discussionSummary. confidence must be an integer from 0 to 100. keyTakeaways and riskFlags "
            "must contain 2-4 short strings. investable should be one of Investible, Watchlist, Not investible. "
            "tradeType should be one of Long Equity, Short Equity, Call Option, Put Option, No Trade. "
            "Do not wrap the JSON in markdown fences."
        )
        user_prompt = json.dumps(
            {
                "analysisPacket": counsel_packet,
                "sharedResearch": shared_research,
                "openingRound": openings,
            },
            indent=2,
        )
        payload = self._chat_json(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return {
            "name": normalize_text(payload.get("name"), "Counsel Moderator"),
            "stance": normalize_text(payload.get("stance"), normalize_text(payload.get("investable"), "Watchlist")),
            "summary": normalize_text(payload.get("summary")),
            "decision": normalize_text(payload.get("decision"), "No clear action was produced."),
            "keyTakeaways": normalize_list_field(payload.get("keyTakeaways"))[:4],
            "investable": normalize_text(payload.get("investable"), "Watchlist"),
            "tradeType": normalize_text(payload.get("tradeType"), "No Trade"),
            "entryPlan": normalize_text(payload.get("entryPlan"), "No clear entry plan was produced."),
            "exitPlan": normalize_text(payload.get("exitPlan"), "No clear exit plan was produced."),
            "optionsIdea": normalize_text(payload.get("optionsIdea")),
            "confidence": normalize_conviction(payload.get("confidence")),
            "riskFlags": normalize_list_field(payload.get("riskFlags"))[:4],
            "discussionSummary": normalize_text(payload.get("discussionSummary")),
            "citations": shared_research.get("citations", [])[:8],
            "model": model,
        }

    def _build_moderator(
        self,
        counsel_packet: dict[str, Any],
        shared_research: dict[str, Any],
        openings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scorecard = counsel_packet["scorecard"]
        asset = counsel_packet["asset"]
        score = float(scorecard.get("score", 50))
        symbol = asset.get("symbol", "the asset")
        positive_votes = sum(
            1
            for opening in openings
            if opening["stance"]
            in {"Accumulate", "Trend improving", "Size carefully", "Options selective", "Macro watch"}
        )

        if score >= 68 and positive_votes >= max(2, len(openings) - 1):
            investable = "Investible"
            trade_type = "Long Equity"
            decision = f"Build exposure in {symbol} gradually rather than chase size all at once."
        elif score <= 48:
            investable = "Not investible"
            trade_type = "No Trade"
            decision = f"Avoid new exposure in {symbol} until the setup improves materially."
        else:
            investable = "Watchlist"
            trade_type = "No Trade"
            decision = f"Keep {symbol} on watch and wait for a better entry or stronger trend confirmation."

        return {
            "name": "Counsel Moderator",
            "stance": investable,
            "summary": (
                f"The counsel lands on a {investable.lower()} verdict for {symbol}, balancing the scorecard, "
                f"shared research brief, and the specialist views."
            ),
            "decision": decision,
            "keyTakeaways": merge_unique_strings(
                scorecard.get("positives", [])[:2],
                shared_research.get("catalysts", [])[:2],
            )[:4],
            "investable": investable,
            "tradeType": trade_type,
            "entryPlan": self._entry_plan_from_score(score, asset.get("metrics", {})),
            "exitPlan": self._exit_plan_from_metrics(asset.get("metrics", {})),
            "optionsIdea": self._options_idea(
                score,
                shared_research.get("catalysts", []),
                shared_research.get("concerns", []),
            ),
            "confidence": min(92, max(35, int(score + 5))),
            "riskFlags": merge_unique_strings(
                scorecard.get("risks", [])[:2],
                shared_research.get("concerns", [])[:2],
            )[:4],
            "discussionSummary": (
                "The room found the fundamentals solid, but wanted cleaner timing and downside control before "
                "treating the setup as a high-conviction entry."
            ),
            "citations": shared_research.get("citations", [])[:8],
            "model": shared_research.get("model"),
        }

    def _entry_plan_from_score(self, score: float, metrics: dict[str, Any]) -> str:
        resistance = metrics.get("resistance")
        support = metrics.get("support")
        if score >= 68 and resistance:
            return f"Enter in tranches and add only if price holds strength through resistance near {resistance}."
        if score >= 60 and support:
            return f"Prefer entries near support around {support} instead of chasing short-term strength."
        return "Wait for stronger confirmation before taking fresh risk."

    def _exit_plan_from_metrics(self, metrics: dict[str, Any]) -> str:
        stop_loss = metrics.get("stopLoss")
        support = metrics.get("support")
        resistance = metrics.get("resistance")
        if stop_loss:
            return f"Exit if price breaks the stop-loss area near {stop_loss} or if the thesis weakens."
        if support:
            return f"Exit if price loses support near {support} and fails to reclaim it."
        if resistance:
            return f"Trim into strength near resistance around {resistance} if momentum stalls."
        return "Exit if execution weakens or the trend deteriorates meaningfully."

    def _options_idea(self, score: float, catalysts: list[str], concerns: list[str]) -> str:
        catalyst_text = catalysts[0] if catalysts else ""
        concern_text = concerns[0] if concerns else ""
        if score >= 68:
            return (
                "If you want defined risk instead of stock, consider a bullish call spread around a catalyst window"
                + (f" such as {catalyst_text}." if catalyst_text else ".")
            )
        if score <= 48:
            return (
                "If bearish conviction rises, a put spread is cleaner than a naked directional short"
                + (f", especially if {concern_text.lower()}" if concern_text else ".")
            )
        return "No options structure stands out enough versus waiting."

    def _price_level_note(self, metrics: dict[str, Any]) -> str:
        support = metrics.get("support")
        resistance = metrics.get("resistance")
        if support and resistance:
            return f"Key range is support near {support} and resistance near {resistance}."
        if support:
            return f"Support is near {support}."
        if resistance:
            return f"Resistance is near {resistance}."
        return "No clear support or resistance level was available."

    def _merge_member_views(
        self, opening: dict[str, Any], rebuttal: dict[str, Any]
    ) -> dict[str, Any]:
        final_exit = rebuttal["exitPlan"] or opening["exitPlan"]
        final_options = rebuttal["optionsIdea"] or opening["optionsIdea"]
        evidence = merge_unique_strings(opening["evidence"], rebuttal["agreementPoints"])
        risks = merge_unique_strings(opening["risks"], rebuttal["pushback"])
        return {
            "name": opening["name"],
            "stance": rebuttal["stance"] or opening["stance"],
            "conviction": rebuttal["conviction"] or opening["conviction"],
            "summary": rebuttal["summary"] or opening["summary"],
            "evidence": evidence[:4],
            "risks": risks[:4],
            "entryPlan": opening["entryPlan"],
            "exitPlan": final_exit,
            "optionsIdea": final_options,
            "model": opening["model"],
            "specialty": opening["specialty"],
        }

    def _build_transcript(
        self,
        shared_research: dict[str, Any],
        openings: list[dict[str, Any]],
        moderator: dict[str, Any],
    ) -> list[dict[str, Any]]:
        transcript: list[dict[str, Any]] = [
            {
                "speaker": "Research Lead",
                "role": "Shared web research"
                if shared_research.get("mode") == "web"
                else "Fast internal research",
                "model": shared_research.get("model"),
                "round": "Research brief",
                "stance": "Context",
                "message": shared_research.get("summary") or "No shared research summary was produced.",
                "citations": shared_research.get("citations", []),
            }
        ]
        for opening in openings:
            transcript.append(
                {
                    "speaker": opening["name"],
                    "role": opening["specialty"],
                    "model": opening["model"],
                    "round": "Opening case",
                    "stance": opening["stance"],
                    "message": opening["message"],
                    "citations": opening["citations"],
                }
            )
        transcript.append(
            {
                "speaker": moderator["name"],
                "role": "Moderator",
                "model": moderator["model"],
                "round": "Final verdict",
                "stance": moderator["tradeType"],
                "message": moderator["decision"],
                "citations": moderator["citations"],
            }
        )
        return transcript

    def _response_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        payload = {
            "model": model,
            "tools": [
                {
                    "type": "web_search_preview",
                    "search_context_size": "low",
                }
            ],
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "include": ["web_search_call.action.sources"],
        }
        response = request_json(
            f"{self.settings.openai_base_url}/responses",
            method="POST",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            payload=payload,
            timeout=self.settings.counsel_timeout_seconds(),
        )
        content, citations = extract_text_and_citations(response)
        if not content:
            raise ApiError("OpenAI counsel returned an empty response.")
        return parse_json_response_text(content), citations

    def _response_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, list[dict[str, str]]]:
        payload = {
            "model": model,
            "tools": [
                {
                    "type": "web_search_preview",
                    "search_context_size": "low",
                }
            ],
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "include": ["web_search_call.action.sources"],
        }
        response = request_json(
            f"{self.settings.openai_base_url}/responses",
            method="POST",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            payload=payload,
            timeout=self.settings.counsel_timeout_seconds(),
        )
        content, citations = extract_text_and_citations(response)
        if not content:
            raise ApiError("OpenAI counsel returned an empty response.")
        return content, citations

    def _chat_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
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


class DebateOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.rules = RulesDebateEngine()
        self.llm = OpenAIDebateEngine(settings)
        self.counsel = OpenAICounselEngine(settings)

    def debate(
        self,
        snapshot: AssetSnapshot,
        horizon: str,
        scorecard: dict[str, Any],
        *,
        counsel_enabled: bool = False,
        counsel_members: int = 3,
    ) -> dict[str, Any]:
        if counsel_enabled:
            try:
                return self.counsel.debate(snapshot, horizon, scorecard, counsel_members)
            except Exception as exc:
                fallback = self._standard_debate(snapshot, horizon, scorecard)
                fallback["warning"] = f"AI counsel fell back to the standard panel: {exc}"
                return fallback
        return self._standard_debate(snapshot, horizon, scorecard)

    def _standard_debate(
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
