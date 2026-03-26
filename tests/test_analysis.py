from __future__ import annotations

import unittest

from stock_analyser.analysis import build_recommendation_analysis, build_scorecard
from stock_analyser.debate import normalize_conviction
from stock_analyser.providers import AssetSnapshot, CoinGeckoClient


class AnalysisTests(unittest.TestCase):
    def test_build_recommendation_analysis_includes_reasoning(self) -> None:
        snapshot = AssetSnapshot(
            asset_type="stock",
            identifier="MSFT",
            symbol="MSFT",
            name="Microsoft Corporation",
            currency="USD",
            current_price=400.0,
            market_cap=None,
            summary=None,
            history=[
                {"date": "2026-01-01", "close": 350.0},
                {"date": "2026-02-01", "close": 370.0},
                {"date": "2026-03-01", "close": 390.0},
                {"date": "2026-03-25", "close": 400.0},
            ],
            metrics={
                "targetMeanPrice": 470.0,
                "recommendationRating": "BUY",
                "valuationDiscount": 10.0,
                "companyInnovativeness": 0.9,
                "companyHiring": 0.86,
                "companyEarningsReports": 0.81,
                "support": 370.0,
                "technicalLongTerm": "up",
                "fiftyTwoWeekRangePosition": 72.0,
            },
            context={},
            source="test",
        )
        scored = build_scorecard(snapshot, "quarter")
        explanation = build_recommendation_analysis(
            scored["snapshot"], "quarter", scored["scorecard"]
        )

        self.assertIn("headline", explanation)
        self.assertTrue(explanation["keyDrivers"])
        self.assertIn("quarter", explanation["timeframeReason"])
        self.assertTrue(explanation["scoreBreakdown"])

    def test_coin_lookup_prefers_real_bitcoin(self) -> None:
        actual = CoinGeckoClient._lookup_score("bitcoin", "BTC", "Bitcoin", 1)
        meme = CoinGeckoClient._lookup_score(
            "bitcoin", "BITCOIN", "HarryPotterObamaSonic10Inu (ETH)", 860
        )

        self.assertGreater(actual, meme)

    def test_crypto_scorecard_contains_expected_fields(self) -> None:
        snapshot = AssetSnapshot(
            asset_type="crypto",
            identifier="bitcoin",
            symbol="BTC",
            name="Bitcoin",
            currency="USD",
            current_price=70000.0,
            market_cap=1_300_000_000_000,
            summary=None,
            history=[
                {"date": "2025-01-01", "close": 42000.0},
                {"date": "2025-06-01", "close": 62000.0},
                {"date": "2025-12-01", "close": 68000.0},
                {"date": "2026-03-25", "close": 70000.0},
            ],
            metrics={
                "marketCap": 1_300_000_000_000,
                "marketCapRank": 1,
                "fullyDilutedValuation": 1_350_000_000_000,
                "circulatingSupply": 20_000_000,
                "maxSupply": 21_000_000,
                "volumeToMarketCap": 0.03,
            },
            context={},
            source="test",
        )
        scored = build_scorecard(snapshot, "year")["scorecard"]

        self.assertIn("score", scored)
        self.assertIn("verdict", scored)
        self.assertIn("components", scored)

    def test_llm_conviction_is_normalized_to_percent_scale(self) -> None:
        self.assertEqual(normalize_conviction(0.72), 72)
        self.assertEqual(normalize_conviction("0.8"), 80)
        self.assertEqual(normalize_conviction(84), 84)


if __name__ == "__main__":
    unittest.main()
