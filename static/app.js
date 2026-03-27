const state = {
  lookupTimer: null,
  selectedLookup: null,
  health: {
    llmEnabled: false,
    counselAvailable: false,
    counselMaxMembers: 5,
    counselModels: [],
  },
  suggestions: {
    stocks: null,
    crypto: null,
  },
  suggestionLimit: {
    stocks: 4,
    crypto: 4,
  },
  activeSuggestionType: "stocks",
};

const elements = {
  form: document.querySelector("#analysis-form"),
  query: document.querySelector("#query"),
  assetType: document.querySelector("#asset-type"),
  horizon: document.querySelector("#horizon"),
  aiCounselEnabled: document.querySelector("#ai-counsel-enabled"),
  counselMembers: document.querySelector("#counsel-members"),
  counselMembersField: document.querySelector("#counsel-members-field"),
  counselStatus: document.querySelector("#counsel-status"),
  lookupMenu: document.querySelector("#lookup-menu"),
  analyzeButton: document.querySelector("#analyze-button"),
  homeButton: document.querySelector("#home-button"),
  results: document.querySelector("#analysis-results"),
  analysisWarning: document.querySelector("#analysis-warning"),
  llmStatus: document.querySelector("#llm-status"),
  assetBadge: document.querySelector("#asset-badge"),
  assetTitle: document.querySelector("#asset-title"),
  assetSummary: document.querySelector("#asset-summary"),
  assetPrice: document.querySelector("#asset-price"),
  metricStrip: document.querySelector("#metric-strip"),
  chartChange: document.querySelector("#chart-change"),
  priceChart: document.querySelector("#price-chart"),
  verdictScore: document.querySelector("#verdict-score"),
  verdictTitle: document.querySelector("#verdict-title"),
  verdictSummary: document.querySelector("#verdict-summary"),
  positiveList: document.querySelector("#positive-list"),
  riskList: document.querySelector("#risk-list"),
  recommendationHeadline: document.querySelector("#recommendation-headline"),
  recommendationFit: document.querySelector("#recommendation-fit"),
  timeframeReason: document.querySelector("#timeframe-reason"),
  driverList: document.querySelector("#driver-list"),
  watchList: document.querySelector("#watch-list"),
  scoreMethod: document.querySelector("#score-method"),
  scoreBreakdownList: document.querySelector("#score-breakdown-list"),
  debateMode: document.querySelector("#debate-mode"),
  debateCards: document.querySelector("#debate-cards"),
  moderatorStance: document.querySelector("#moderator-stance"),
  moderatorSummary: document.querySelector("#moderator-summary"),
  moderatorDecision: document.querySelector("#moderator-decision"),
  moderatorPoints: document.querySelector("#moderator-points"),
  counselVerdictShell: document.querySelector("#counsel-verdict-shell"),
  counselInvestable: document.querySelector("#counsel-investable"),
  counselTradeType: document.querySelector("#counsel-trade-type"),
  counselConfidence: document.querySelector("#counsel-confidence"),
  counselEntryPlan: document.querySelector("#counsel-entry-plan"),
  counselExitPlan: document.querySelector("#counsel-exit-plan"),
  counselOptionsIdea: document.querySelector("#counsel-options-idea"),
  counselRiskFlags: document.querySelector("#counsel-risk-flags"),
  counselModelsUsed: document.querySelector("#counsel-models-used"),
  counselSources: document.querySelector("#counsel-sources"),
  counselTranscriptShell: document.querySelector("#counsel-transcript-shell"),
  counselMembersUsed: document.querySelector("#counsel-members-used"),
  counselTranscript: document.querySelector("#counsel-transcript"),
  suggestionsState: document.querySelector("#suggestions-state"),
  suggestionsColumns: document.querySelector("#suggestions-columns"),
  moreSuggestionsButton: document.querySelector("#more-suggestions-button"),
  suggestionTabs: document.querySelectorAll("[data-suggestion-type]"),
  suggestionTemplate: document.querySelector("#suggestion-card-template"),
};

document.addEventListener("DOMContentLoaded", () => {
  wireEvents();
  populateCounselMembers(state.health.counselMaxMembers);
  syncCounselControls();
  loadHealth();
  loadSuggestions();
});

function wireEvents() {
  elements.query.addEventListener("input", onQueryInput);
  elements.query.addEventListener("blur", () => {
    window.setTimeout(hideLookupMenu, 120);
  });
  elements.form.addEventListener("submit", onSubmit);
  elements.homeButton.addEventListener("click", resetHomepage);
  elements.moreSuggestionsButton.addEventListener("click", onShowMoreSuggestions);
  elements.aiCounselEnabled.addEventListener("change", onCounselToggle);
  elements.counselMembers.addEventListener("change", syncAnalyzeButtonLabel);

  document.addEventListener("pointerdown", (event) => {
    if (!elements.lookupMenu.contains(event.target) && event.target !== elements.query) {
      hideLookupMenu();
    }
  });

  elements.suggestionTabs.forEach((button) => {
    button.addEventListener("click", () => {
      state.activeSuggestionType = button.dataset.suggestionType;
      elements.suggestionTabs.forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      renderSuggestions();
    });
  });
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const payload = await response.json();
    state.health = {
      llmEnabled: Boolean(payload.llmEnabled),
      counselAvailable: Boolean(payload.counselAvailable),
      counselMaxMembers: Number(payload.counselMaxMembers) || 5,
      counselModels: Array.isArray(payload.counselModels) ? payload.counselModels : [],
    };

    if (state.health.counselAvailable) {
      elements.llmStatus.textContent = "OpenAI debate + AI counsel ready";
    } else if (state.health.llmEnabled) {
      elements.llmStatus.textContent = "OpenAI debate enabled";
    } else {
      elements.llmStatus.textContent = "Rules-based";
    }
  } catch {
    elements.llmStatus.textContent = "Unavailable";
  }

  populateCounselMembers(state.health.counselMaxMembers);
  syncCounselControls();
}

function populateCounselMembers(maxMembers) {
  const limit = Math.max(2, Math.min(maxMembers || 5, 5));
  const currentValue = Number(elements.counselMembers.value) || 3;
  elements.counselMembers.innerHTML = "";
  for (let count = 2; count <= limit; count += 1) {
    const option = document.createElement("option");
    option.value = String(count);
    option.textContent = `${count} agents`;
    elements.counselMembers.appendChild(option);
  }
  const safeValue = Math.max(2, Math.min(currentValue, limit));
  elements.counselMembers.value = String(safeValue);
}

function syncCounselControls() {
  const available = state.health.counselAvailable;
  elements.aiCounselEnabled.disabled = !available;

  if (!available) {
    elements.aiCounselEnabled.checked = false;
    elements.counselMembersField.classList.add("hidden");
    elements.counselStatus.textContent = state.health.llmEnabled
      ? "AI counsel needs at least one model in OPENAI_COUNSEL_MODELS."
      : "Add OPENAI_API_KEY plus OPENAI_MODEL or OPENAI_COUNSEL_MODELS to unlock AI counsel.";
  } else if (elements.aiCounselEnabled.checked) {
    const pool = state.health.counselModels.length
      ? state.health.counselModels.join(", ")
      : "your configured default model";
    elements.counselMembersField.classList.remove("hidden");
    elements.counselStatus.textContent = `Counsel will randomly draw from: ${pool}.`;
  } else {
    elements.counselMembersField.classList.add("hidden");
    elements.counselStatus.textContent = "Disabled by default because each run launches multiple web-enabled agents.";
  }

  syncAnalyzeButtonLabel();
}

function syncAnalyzeButtonLabel() {
  if (elements.aiCounselEnabled.checked && !elements.aiCounselEnabled.disabled) {
    const members = elements.counselMembers.value || "3";
    elements.analyzeButton.textContent = `Run AI Counsel (${members})`;
    return;
  }
  elements.analyzeButton.textContent = "Run Debate";
}

function onCounselToggle() {
  syncCounselControls();
  if (elements.aiCounselEnabled.checked && !elements.aiCounselEnabled.disabled) {
    elements.counselMembers.focus();
  }
}

function onQueryInput(event) {
  const value = event.target.value.trim();
  state.selectedLookup = null;
  if (state.lookupTimer) {
    clearTimeout(state.lookupTimer);
  }
  if (value.length < 2) {
    hideLookupMenu();
    return;
  }
  state.lookupTimer = window.setTimeout(() => {
    fetchLookup(value, elements.assetType.value);
  }, 220);
}

async function fetchLookup(query, assetType) {
  try {
    const params = new URLSearchParams({ query, assetType });
    const response = await fetch(`/api/lookup?${params.toString()}`);
    const payload = await response.json();
    renderLookupMenu(payload.results || []);
  } catch {
    hideLookupMenu();
  }
}

function renderLookupMenu(results) {
  if (!results.length) {
    hideLookupMenu();
    return;
  }

  elements.lookupMenu.innerHTML = "";
  results.forEach((result) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "lookup-option";
    option.innerHTML = `
      <strong>${escapeHtml(result.name)} <span>(${escapeHtml(result.symbol)})</span></strong>
      <span>${escapeHtml(result.assetType)}${result.subtitle ? ` • ${escapeHtml(result.subtitle)}` : ""}</span>
    `;
    option.addEventListener("click", () => {
      state.selectedLookup = result;
      elements.query.value = `${result.name} (${result.symbol})`;
      elements.assetType.value = result.assetType;
      hideLookupMenu();
    });
    elements.lookupMenu.appendChild(option);
  });
  elements.lookupMenu.classList.remove("hidden");
}

function hideLookupMenu() {
  elements.lookupMenu.classList.add("hidden");
}

function resetHomepage() {
  state.selectedLookup = null;
  elements.form.reset();
  elements.assetType.value = "auto";
  elements.horizon.value = "quarter";
  elements.aiCounselEnabled.checked = false;
  populateCounselMembers(state.health.counselMaxMembers);
  syncCounselControls();
  elements.analysisWarning.classList.add("hidden");
  elements.analysisWarning.textContent = "";
  elements.results.classList.add("hidden");
  elements.homeButton.classList.add("hidden");
  hideLookupMenu();
  elements.query.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function onSubmit(event) {
  event.preventDefault();
  const query = elements.query.value.trim();
  if (!query) {
    return;
  }

  await runAnalysis(buildAnalysisPayload(query));
}

function buildAnalysisPayload(query) {
  const counselEnabled = elements.aiCounselEnabled.checked && !elements.aiCounselEnabled.disabled;
  return {
    query,
    assetType: state.selectedLookup ? state.selectedLookup.assetType : elements.assetType.value,
    identifier: state.selectedLookup ? state.selectedLookup.identifier : null,
    horizon: elements.horizon.value,
    aiCounselEnabled: counselEnabled,
    counselMembers: counselEnabled ? Number(elements.counselMembers.value || 3) : 0,
  };
}

async function runAnalysis(payload) {
  elements.analyzeButton.disabled = true;
  elements.analyzeButton.textContent = payload.aiCounselEnabled ? "Launching council..." : "Running...";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Analysis failed.");
    }
    renderAnalysis(data);
  } catch (error) {
    window.alert(error.message);
  } finally {
    elements.analyzeButton.disabled = false;
    syncAnalyzeButtonLabel();
  }
}

function renderAnalysis(data) {
  const { asset, history, scorecard, recommendation, debate } = data;
  elements.results.classList.remove("hidden");
  elements.homeButton.classList.remove("hidden");

  if (debate.warning) {
    elements.analysisWarning.textContent = debate.warning;
    elements.analysisWarning.classList.remove("hidden");
  } else {
    elements.analysisWarning.textContent = "";
    elements.analysisWarning.classList.add("hidden");
  }

  elements.assetBadge.textContent = `${asset.assetType.toUpperCase()} • ${asset.symbol}`;
  elements.assetTitle.textContent = asset.name;
  elements.assetSummary.textContent =
    asset.summary || "No business summary was available from the free data source.";
  elements.assetPrice.textContent = formatCurrency(asset.currentPrice, asset.currency || "USD");

  const metricMap = buildMetricMap(asset, scorecard);
  elements.metricStrip.innerHTML = "";
  metricMap.forEach((item) => {
    const card = document.createElement("div");
    card.className = "metric-chip";
    card.innerHTML = `<span>${item.label}</span><strong>${item.value}</strong>`;
    elements.metricStrip.appendChild(card);
  });

  elements.verdictScore.textContent = `${Math.round(scorecard.score)}`;
  elements.verdictTitle.textContent = scorecard.verdict;
  elements.verdictSummary.textContent = scorecard.summary;
  renderList(elements.positiveList, scorecard.positives);
  renderList(elements.riskList, scorecard.risks);
  elements.recommendationHeadline.textContent = recommendation.headline;
  elements.recommendationFit.textContent = recommendation.fit;
  elements.timeframeReason.textContent = recommendation.timeframeReason;
  renderList(elements.driverList, recommendation.keyDrivers);
  renderList(elements.watchList, recommendation.watchItems);
  elements.scoreMethod.textContent = recommendation.scoreMethod || "";
  renderScoreBreakdown(recommendation.scoreBreakdown || []);

  elements.debateMode.textContent = buildDebateModeLabel(debate);
  renderDebateCards(debate.analysts || []);
  const moderator = debate.moderator || {};
  elements.moderatorStance.textContent = moderator.stance || "-";
  elements.moderatorSummary.textContent = moderator.summary || "";
  elements.moderatorDecision.textContent = moderator.decision || "";
  renderList(elements.moderatorPoints, moderator.keyTakeaways || []);

  renderCounsel(debate.counsel || null);
  renderChart(history || [], asset.currentPrice, asset.currency || "USD");
  elements.results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function buildDebateModeLabel(debate) {
  if (debate.mode === "counsel") {
    const members = (debate.counsel || {}).memberCount || 0;
    return `Debate mode: AI counsel with ${members} web-enabled agents`;
  }
  if (debate.mode === "llm") {
    return "Debate mode: LLM-backed agents";
  }
  return "Debate mode: Rules-based analysts";
}

function renderScoreBreakdown(items) {
  elements.scoreBreakdownList.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "score-breakdown-item";
    row.innerHTML = `
      <div>
        <h3>${escapeHtml(item.label)}</h3>
        <p>${escapeHtml(item.explanation)}</p>
      </div>
      <div class="score-breakdown-meta">
        <strong>${escapeHtml(String(item.componentScore))} x ${escapeHtml(String(item.weightPercent))}%</strong>
        <span>Contribution ${escapeHtml(String(item.contribution))}</span>
      </div>
    `;
    elements.scoreBreakdownList.appendChild(row);
  });
}

function buildMetricMap(asset, scorecard) {
  const metrics = asset.metrics || {};
  const baseCandidates = [
    {
      label: "Market cap",
      raw: asset.marketCap,
      formatter: (value) => formatCompactCurrency(value, asset.currency || "USD"),
    },
    {
      label: "90d return",
      raw: metrics.return90d,
      formatter: formatPercent,
    },
    {
      label: "1y return",
      raw: metrics.return365d,
      formatter: formatPercent,
    },
    {
      label: "Volatility",
      raw: metrics.volatilityAnnualized,
      formatter: formatPercent,
    },
  ];

  const stockCandidates = [
    {
      label: "Target upside",
      raw: targetUpside(asset.currentPrice, metrics.targetMeanPrice),
      formatter: formatPercent,
    },
    {
      label: "52w range",
      raw: metrics.fiftyTwoWeekRangePosition,
      formatter: formatPercent,
    },
    {
      label: "Valuation discount",
      raw: metrics.valuationDiscount,
      formatter: formatPercent,
    },
    {
      label: "Support",
      raw: metrics.support,
      formatter: (value) => formatCurrency(value, asset.currency || "USD"),
    },
    {
      label: "Resistance",
      raw: metrics.resistance,
      formatter: (value) => formatCurrency(value, asset.currency || "USD"),
    },
    {
      label: "Daily volume",
      raw: metrics.averageDailyVolume3Month,
      formatter: formatCompactNumber,
    },
  ];

  const cryptoCandidates = [
    {
      label: "Market cap rank",
      raw: metrics.marketCapRank,
      formatter: formatNumber,
    },
    {
      label: "30d return",
      raw: metrics.return30d,
      formatter: formatPercent,
    },
    {
      label: "Volume / cap",
      raw: decimalToPercent(metrics.volumeToMarketCap),
      formatter: formatPercent,
    },
  ];

  const candidates = [
    ...baseCandidates,
    ...(asset.assetType === "stock" ? stockCandidates : cryptoCandidates),
    {
      label: "Horizon score",
      raw: Math.round(scorecard.score),
      formatter: (value) => `${value} / 100`,
    },
  ];

  return candidates
    .filter((item) => isPresentValue(item.raw))
    .slice(0, 8)
    .map((item) => ({
      label: item.label,
      value: item.formatter(item.raw),
    }));
}

function renderDebateCards(analysts) {
  elements.debateCards.innerHTML = "";
  analysts.forEach((analyst) => {
    const card = document.createElement("article");
    card.className = "debate-card";
    card.dataset.tone = toneForAnalyst(analyst.name, analyst.specialty);

    const metaBits = [];
    if (analyst.specialty) {
      metaBits.push(analyst.specialty);
    }
    if (analyst.model) {
      metaBits.push(analyst.model);
    }

    const planBits = [analyst.entryPlan, analyst.exitPlan, analyst.optionsIdea]
      .filter((item) => item && item.trim())
      .slice(0, 2);

    card.innerHTML = `
      <div class="debate-card-head">
        <div>
          <h3>${escapeHtml(analyst.name)}</h3>
          <p class="conviction">Conviction ${escapeHtml(String(analyst.conviction || "-"))}/100</p>
          ${metaBits.length ? `<p class="panel-meta">${escapeHtml(metaBits.join(" • "))}</p>` : ""}
        </div>
        <span class="stance-pill">${escapeHtml(analyst.stance || "View")}</span>
      </div>
      <p class="debate-copy">${escapeHtml(analyst.summary || "")}</p>
      <ul class="compact-list">${renderItems([...(analyst.evidence || []).slice(0, 2), ...planBits])}</ul>
    `;
    elements.debateCards.appendChild(card);
  });
}

function renderCounsel(counsel) {
  if (!counsel) {
    elements.counselVerdictShell.classList.add("hidden");
    elements.counselTranscriptShell.classList.add("hidden");
    return;
  }

  elements.counselVerdictShell.classList.remove("hidden");
  elements.counselTranscriptShell.classList.remove("hidden");

  const verdict = counsel.verdict || {};
  elements.counselInvestable.textContent = verdict.investable || "Watchlist";
  elements.counselTradeType.textContent = verdict.tradeType || "No Trade";
  elements.counselConfidence.textContent = `${Number(verdict.confidence || 0)}/100`;
  elements.counselEntryPlan.textContent = verdict.entryPlan || "No entry plan was produced.";
  elements.counselExitPlan.textContent = verdict.exitPlan || "No exit plan was produced.";
  elements.counselOptionsIdea.textContent =
    verdict.optionsIdea || "No options trade was favored over the underlying.";
  elements.counselModelsUsed.textContent = (counsel.modelsUsed || []).join(", ") || "Default model";
  renderList(elements.counselRiskFlags, verdict.riskFlags || []);
  renderCitationLinks(elements.counselSources, verdict.citations || []);

  const members = counsel.memberCount || 0;
  elements.counselMembersUsed.textContent = `${members} agents participated.`;
  renderTranscript(counsel.transcript || []);
}

function renderTranscript(entries) {
  elements.counselTranscript.innerHTML = "";
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "microcopy";
    empty.textContent = "No transcript was captured for this run.";
    elements.counselTranscript.appendChild(empty);
    return;
  }

  entries.forEach((entry) => {
    const card = document.createElement("article");
    card.className = "transcript-card";

    const header = document.createElement("div");
    header.className = "transcript-head";

    const title = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = entry.speaker || "Agent";
    const meta = document.createElement("p");
    meta.className = "panel-meta";
    meta.textContent = [entry.role, entry.model, entry.round].filter(Boolean).join(" • ");
    title.appendChild(heading);
    if (meta.textContent) {
      title.appendChild(meta);
    }

    const stance = document.createElement("span");
    stance.className = "stance-pill";
    stance.textContent = entry.stance || "View";
    header.appendChild(title);
    header.appendChild(stance);

    const message = document.createElement("p");
    message.className = "debate-copy";
    message.textContent = entry.message || "";

    card.appendChild(header);
    card.appendChild(message);
    appendCitationLinks(card, entry.citations || []);
    elements.counselTranscript.appendChild(card);
  });
}

function appendCitationLinks(parent, citations) {
  if (!citations.length) {
    return;
  }
  const shell = document.createElement("div");
  shell.className = "citation-list";

  citations.forEach((citation) => {
    const link = document.createElement("a");
    link.href = citation.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    link.className = "citation-card";

    const title = document.createElement("strong");
    title.textContent = citationDisplayTitle(citation);

    const meta = document.createElement("span");
    meta.className = "citation-url";
    meta.textContent = citationDisplayMeta(citation.url);

    const footer = document.createElement("div");
    footer.className = "citation-footer";

    const ref = document.createElement("span");
    ref.className = "citation-ref";
    ref.textContent = "Reference link";

    const open = document.createElement("span");
    open.className = "citation-open";
    open.textContent = "Open";

    footer.appendChild(ref);
    footer.appendChild(open);

    link.appendChild(title);
    link.appendChild(meta);
    link.appendChild(footer);
    shell.appendChild(link);
  });

  parent.appendChild(shell);
}

function renderCitationLinks(container, citations) {
  container.innerHTML = "";
  appendCitationLinks(container, citations);
}

function citationDisplayTitle(citation) {
  const title = (citation.title || "").trim();
  if (title && !looksLikeUrl(title)) {
    return title;
  }

  const details = parsedUrlDetails(citation.url);
  if (!details) {
    return "Source";
  }

  const pathLabel = details.pathname
    .split("/")
    .filter(Boolean)
    [0];

  if (pathLabel) {
    return `${details.hostname} / ${pathLabel}`;
  }

  return details.hostname;
}

function citationDisplayMeta(url) {
  const details = parsedUrlDetails(url);
  if (!details) {
    return url || "";
  }

  const path = shortenText(details.pathname === "/" ? "" : details.pathname, 40);
  return path ? `${details.hostname}${path}` : details.hostname;
}

function parsedUrlDetails(url) {
  try {
    const parsed = new URL(url);
    return {
      hostname: parsed.hostname.replace(/^www\./, ""),
      pathname: parsed.pathname || "/",
    };
  } catch {
    return null;
  }
}

function looksLikeUrl(value) {
  return /^https?:\/\//i.test(value) || value.includes("www.");
}

function shortenText(value, maxLength) {
  if (!value || value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function renderChart(history, currentPrice, currency) {
  const usable = history.filter((point) => Number.isFinite(point.close));
  if (usable.length < 2) {
    elements.priceChart.innerHTML = "";
    elements.chartChange.textContent = "Not enough history";
    return;
  }

  const values = usable.map((point) => point.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = 640;
  const height = 260;
  const padding = 16;
  const span = Math.max(max - min, 1);

  const points = usable.map((point, index) => {
    const x = padding + (index / (usable.length - 1)) * (width - padding * 2);
    const y = height - padding - ((point.close - min) / span) * (height - padding * 2);
    return `${x},${y}`;
  });

  const areaPoints = [`${padding},${height - padding}`, ...points, `${width - padding},${height - padding}`];
  const latestPoint = usable[usable.length - 1];
  const change = ((latestPoint.close / usable[0].close) - 1) * 100;
  elements.chartChange.textContent = `${formatPercent(change)} over the displayed period`;

  elements.priceChart.innerHTML = `
    <defs>
      <linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="rgba(13,116,103,0.28)"></stop>
        <stop offset="100%" stop-color="rgba(13,116,103,0.02)"></stop>
      </linearGradient>
    </defs>
    <polyline fill="url(#chart-fill)" stroke="none" points="${areaPoints.join(" ")}"></polyline>
    <polyline fill="none" stroke="#0d7467" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${points.join(" ")}"></polyline>
    <circle cx="${points[points.length - 1].split(",")[0]}" cy="${points[points.length - 1].split(",")[1]}" r="5" fill="#bc5d31"></circle>
    <text x="${padding}" y="${padding + 8}" fill="#60594d" font-size="12">${escapeHtml(formatCurrency(max, currency))}</text>
    <text x="${padding}" y="${height - 8}" fill="#60594d" font-size="12">${escapeHtml(formatCurrency(min, currency))}</text>
    <text x="${width - 150}" y="${padding + 8}" fill="#181612" font-size="12">${escapeHtml(formatCurrency(currentPrice, currency))} latest</text>
  `;
}

async function loadSuggestions() {
  try {
    await Promise.all([fetchSuggestions("stocks"), fetchSuggestions("crypto")]);
    elements.suggestionsState.textContent = "Ranked from free market data and the app's scoring model.";
    renderSuggestions();
  } catch {
    elements.suggestionsState.textContent = "Suggestions could not be loaded right now.";
  }
}

async function fetchSuggestions(type) {
  const assetType = type === "stocks" ? "stock" : "crypto";
  const limit = state.suggestionLimit[type];
  const response = await fetch(`/api/suggestions?assetType=${assetType}&limit=${limit}`);
  state.suggestions[type] = await response.json();
}

async function onShowMoreSuggestions() {
  const currentType = state.activeSuggestionType;
  state.suggestionLimit[currentType] = Math.min(state.suggestionLimit[currentType] + 4, 12);
  elements.moreSuggestionsButton.disabled = true;
  elements.moreSuggestionsButton.textContent = "Loading...";
  try {
    await fetchSuggestions(currentType);
    renderSuggestions();
  } catch {
    elements.suggestionsState.textContent = "Could not load more ideas right now.";
  } finally {
    elements.moreSuggestionsButton.disabled = false;
    elements.moreSuggestionsButton.textContent = "Show More Ideas";
  }
}

function renderSuggestions() {
  const payload = state.suggestions[state.activeSuggestionType];
  if (!payload || !payload.horizons) {
    return;
  }

  const horizonLabels = {
    quarter: "Quarter",
    six_months: "Six Months",
    year: "One Year",
  };

  elements.suggestionsColumns.innerHTML = "";
  Object.entries(payload.horizons).forEach(([key, ideas]) => {
    const column = document.createElement("div");
    column.className = "suggestions-column";
    column.innerHTML = `<h3>${horizonLabels[key] || key}</h3>`;
    ideas.forEach((idea) => {
      const fragment = elements.suggestionTemplate.content.cloneNode(true);
      const card = fragment.querySelector(".suggestion-card");
      card.querySelector(".suggestion-symbol").textContent = idea.symbol;
      card.querySelector(".suggestion-name").textContent = idea.name;
      card.querySelector(".suggestion-score").textContent = `${Math.round(idea.score)}/100`;
      card.querySelector(".suggestion-summary").textContent = idea.summary;
      card.querySelector(".suggestion-price").textContent = formatCompactCurrency(
        idea.currentPrice,
        "USD",
        { fallback: "Price unavailable" }
      );
      renderList(
        card.querySelector(".suggestion-points"),
        [...(idea.positives || []).slice(0, 2), ...(idea.risks || []).slice(0, 1)]
      );
      card.addEventListener("click", () => {
        openSuggestionAnalysis(idea, key);
      });
      column.appendChild(fragment);
    });
    elements.suggestionsColumns.appendChild(column);
  });

  const maxReturned = Math.max(...Object.values(payload.horizons).map((ideas) => ideas.length));
  const currentLimit = state.suggestionLimit[state.activeSuggestionType];
  const canShowMore = maxReturned >= currentLimit && currentLimit < 12;
  elements.moreSuggestionsButton.classList.toggle("hidden", !canShowMore);
}

async function openSuggestionAnalysis(idea, horizon) {
  const assetType = state.activeSuggestionType === "stocks" ? "stock" : "crypto";
  state.selectedLookup = {
    identifier: idea.identifier,
    assetType,
  };
  elements.query.value = `${idea.name} (${idea.symbol})`;
  elements.assetType.value = assetType;
  elements.horizon.value = horizon;
  await runAnalysis(
    buildAnalysisPayload(idea.symbol)
  );
}

function renderList(element, items) {
  element.innerHTML = renderItems(items);
}

function renderItems(items) {
  if (!items || !items.length) {
    return "<li>No notable signals were available.</li>";
  }
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function toneForAnalyst(name, specialty = "") {
  const joined = `${name} ${specialty}`.toLowerCase();
  if (joined.includes("bull") || joined.includes("fundamental")) {
    return "bull";
  }
  if (joined.includes("bear") || joined.includes("risk")) {
    return "bear";
  }
  if (joined.includes("option")) {
    return "navy";
  }
  return "quant";
}

function targetUpside(currentPrice, targetPrice) {
  if (!currentPrice || !targetPrice) {
    return null;
  }
  return ((targetPrice / currentPrice) - 1) * 100;
}

function decimalToPercent(value) {
  if (!Number.isFinite(value)) {
    return null;
  }
  return value * 100;
}

function formatCurrency(value, currency = "USD") {
  if (!Number.isFinite(value)) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: value >= 100 ? 2 : 4,
  }).format(value);
}

function formatCompactCurrency(value, currency = "USD", options = {}) {
  if (!Number.isFinite(value)) {
    return options.fallback || "Unavailable";
  }
  const highValue = Math.abs(value) >= 1000;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: highValue ? "compact" : "standard",
    maximumFractionDigits: highValue ? 2 : 4,
  }).format(value);
}

function formatCompactNumber(value) {
  if (!Number.isFinite(value)) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatNumber(value) {
  if (!Number.isFinite(value)) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value) {
  if (!Number.isFinite(value)) {
    return "Unavailable";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function isPresentValue(value) {
  if (typeof value === "number") {
    return Number.isFinite(value);
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  return value !== null && value !== undefined;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
