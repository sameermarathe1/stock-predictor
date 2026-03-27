from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from stock_analyser.config import load_settings
from stock_analyser.debate import (
    extract_text_and_citations,
    normalize_citations,
    parse_citation_line,
    parse_research_brief_text,
    parse_json_response_text,
)


class ConfigAndDebateTests(unittest.TestCase):
    def test_load_settings_uses_counsel_model_pool_when_present(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-4.1-mini",
                "OPENAI_COUNSEL_MODELS": "gpt-5-mini,gpt-4.1-mini,gpt-4.1",
                "OPENAI_COUNSEL_MAX_MEMBERS": "9",
                "OPENAI_COUNSEL_TIMEOUT_SECONDS": "120",
            },
            clear=False,
        ):
            settings = load_settings()

        self.assertEqual(
            settings.counsel_models,
            ("gpt-5-mini", "gpt-4.1-mini", "gpt-4.1"),
        )
        self.assertEqual(settings.counsel_member_limit(), 5)
        self.assertEqual(settings.counsel_timeout_seconds(), 120)

    def test_pick_counsel_models_randomizes_and_fills_extra_slots(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_COUNSEL_MODELS": "gpt-5-mini,gpt-4.1-mini,gpt-4.1",
            },
            clear=False,
        ):
            settings = load_settings()

        with patch("stock_analyser.config.random.sample", return_value=["gpt-4.1", "gpt-5-mini", "gpt-4.1-mini"]), patch(
            "stock_analyser.config.random.choice",
            return_value="gpt-4.1",
        ):
            self.assertEqual(
                settings.pick_counsel_models(5),
                ["gpt-4.1", "gpt-5-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4.1"],
            )

    def test_normalize_citations_deduplicates_urls(self) -> None:
        citations = normalize_citations(
            [
                {"title": "Example", "url": "https://example.com/a"},
                {"title": "Duplicate", "url": "https://example.com/a"},
                {"title": "", "url": "https://example.com/b"},
            ]
        )

        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[1]["title"], "https://example.com/b")

    def test_extract_text_and_citations_reads_message_annotations(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"verdict":"Buy"}',
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Source One",
                                    "url": "https://example.com/source-1",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        content, citations = extract_text_and_citations(response)

        self.assertEqual(content, '{"verdict":"Buy"}')
        self.assertEqual(citations[0]["url"], "https://example.com/source-1")

    def test_parse_json_response_text_accepts_fenced_json(self) -> None:
        payload = parse_json_response_text(
            """```json
{"verdict":"Buy","confidence":81}
```"""
        )

        self.assertEqual(payload["verdict"], "Buy")
        self.assertEqual(payload["confidence"], 81)

    def test_parse_json_response_text_accepts_extra_prefix_text(self) -> None:
        payload = parse_json_response_text(
            'Here is the JSON you asked for:\n{"verdict":"Watchlist","confidence":55}'
        )

        self.assertEqual(payload["verdict"], "Watchlist")
        self.assertEqual(payload["confidence"], 55)

    def test_parse_research_brief_text_accepts_template_output(self) -> None:
        payload = parse_research_brief_text(
            """
SUMMARY:
Microsoft remains fundamentally strong, but near-term timing is mixed.
MARKET_CONTEXT:
Large-cap tech leadership is still important for sentiment.
CATALYSTS:
- Azure growth resilience
- AI monetization progress
CONCERNS:
- Rich valuation
- Momentum cooling
OPTIONS_CONTEXT:
Defined-risk bullish structures look cleaner than outright chasing.
SOURCES:
- Yahoo Finance | https://finance.yahoo.com/quote/MSFT/
- Finviz | https://finviz.com/quote.ashx?t=MSFT
"""
        )

        self.assertEqual(payload["marketContext"], "Large-cap tech leadership is still important for sentiment.")
        self.assertEqual(payload["catalysts"][0], "Azure growth resilience")
        self.assertEqual(payload["concerns"][1], "Momentum cooling")
        self.assertEqual(len(payload["sources"]), 2)

    def test_parse_citation_line_accepts_title_and_url(self) -> None:
        citation = parse_citation_line(
            "- Yahoo Finance | https://finance.yahoo.com/quote/MSFT/"
        )

        self.assertEqual(
            citation,
            {
                "title": "Yahoo Finance",
                "url": "https://finance.yahoo.com/quote/MSFT/",
            },
        )


if __name__ == "__main__":
    unittest.main()
