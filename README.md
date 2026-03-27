# Signal Forge

Signal Forge is a lightweight web app for researching stocks and crypto with:

- free market-data integrations for stocks and digital assets
- a multi-analyst debate panel that argues the bull, bear, and quant case
- an optional AI counsel mode with 2 to 5 web-enabled agents, rotating models, and a visible discussion log
- ranked ideas for a quarter, six months, and one year
- direct analysis of a ticker, company name, coin, or token symbol
- an explicit "why this is recommended" explanation for every analysis

## Tech stack

- Python 3.13+
- standard-library HTTP server
- static HTML, CSS, and vanilla JavaScript frontend
- free market data from Yahoo Finance and CoinGecko
- optional OpenAI-compatible chat endpoint for LLM-backed debate and AI counsel

## Project layout

- `stock_analyser/app.py`: entrypoint
- `stock_analyser/server.py`: web server and JSON API routes
- `stock_analyser/providers.py`: free data-provider integrations
- `stock_analyser/analysis.py`: scoring, horizon ranking, and recommendation explanations
- `stock_analyser/debate.py`: rules-based and optional LLM-backed debate orchestration
- `static/index.html`: web interface
- `static/styles.css`: UI styling
- `static/app.js`: client-side interactions

## Run locally

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install project requirements:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Copy the sample environment file:

```bash
cp .env.example .env
```

4. Optional: add `OPENAI_API_KEY` and `OPENAI_MODEL` to `.env` if you want real LLM-backed analyst debate.

Optional AI counsel configuration:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
OPENAI_COUNSEL_MODELS=gpt-5,gpt-5-mini,gpt-4.1-mini
OPENAI_COUNSEL_MAX_MEMBERS=5
OPENAI_COUNSEL_TIMEOUT_SECONDS=90
```

The standard debate uses `OPENAI_MODEL`. The optional AI counsel can reuse that model or randomly draw from the comma-separated `OPENAI_COUNSEL_MODELS` pool. `OPENAI_COUNSEL_TIMEOUT_SECONDS` gives the web-enabled counsel extra time for slower search-heavy runs. The UI keeps AI counsel off by default and lets you pick 2 to 5 agents when you enable it.

5. Start the app:

```bash
python -m stock_analyser.app
```

6. Open:

```text
http://127.0.0.1:8000
```

## API endpoints

- `GET /api/health`
- `GET /api/lookup?query=MSFT&assetType=auto`
- `POST /api/analyze`
- `GET /api/suggestions?assetType=stock`
- `GET /api/suggestions?assetType=crypto`

Example analyze payload:

```json
{
  "query": "MSFT",
  "assetType": "stock",
  "horizon": "quarter",
  "aiCounselEnabled": true,
  "counselMembers": 4
}
```

## Notes

- Stock lookups and charts use free Yahoo Finance endpoints.
- Crypto lookups and analytics use CoinGecko.
- The stock fundamentals feed is intentionally lightweight because the app prefers free, low-friction sources over paid APIs.
- The AI counsel path calls the OpenAI Responses API with web search enabled, so it is slower and more expensive than the standard debate.
- `requirements.txt` is intentionally minimal right now because the app runs on the standard library.
- This app is for research support and education, not personal financial advice.

## Tests

Run the small offline test suite with:

```bash
python -m unittest discover -s tests
```
