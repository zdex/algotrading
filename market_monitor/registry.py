"""Canonical panels and the 20 event categories.

Category 18 is owned by Markets. The Decision Log is a cross-panel workflow
and does not own a category.
"""

from __future__ import annotations

from market_monitor.model import Category, Panel


def _types(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split("|"))


PANELS: tuple[Panel, ...] = (
    Panel("macro", "Global Macro", "Growth, inflation, central banks, fiscal policy, and regional cycles."),
    Panel("markets", "Markets", "Equity price action, liquidity, commodities, currencies, and alternatives."),
    Panel("corporate", "Corporate Events", "Earnings, guidance, capital actions, and governance or legal risk."),
    Panel("risk", "Risk Alerts", "Geopolitics, credit stress, disasters, and other portfolio-relevant incidents."),
    Panel("sector", "Sector Rotation", "Industry signals, revisions, valuation, and structural themes."),
    Panel("portfolio", "Portfolio Health", "Holdings, funds, allocation, factors, concentration, and drawdowns."),
    Panel("catalysts", "Upcoming Catalysts", "Scheduled releases, elections, earnings, and market-mechanics dates."),
    Panel("decisions", "Decision Log", "Research decisions across every category, with an audit trail."),
)

_FIELDS = (
    "event time",
    "geography",
    "actual",
    "consensus",
    "prior",
    "source",
    "as-of",
    "verification",
    "severity",
)

CATEGORIES: tuple[Category, ...] = (
    Category(
        1, "macro", "Macroeconomic Events & Economic Indicators",
        "Scheduled growth, inflation, and labor releases, plus revision and nowcast checks.",
        "Weekly, monthly, or quarterly, depending on the series.",
        "Broad equities, cyclicals and defensives, duration, the dollar, and commodities. Read the surprise against expectations.",
        ("country", "release time", "period", "actual", "consensus", "prior", "revised prior", "surprise", "historical percentile", "next release"),
        _types(
            "GDP and revisions|CPI|Core CPI|PPI|PCE|Core PCE|Nonfarm payrolls|Unemployment rate|"
            "Labor force participation|Wage growth|Initial jobless claims|Continuing jobless claims|"
            "Retail sales|Consumer confidence|Consumer sentiment|ISM manufacturing PMI|ISM services PMI|"
            "Industrial production|Durable goods orders|Housing starts|Building permits|Home sales|"
            "Productivity|Unit labor costs|Recession nowcast|Leading indicators|Yield-curve recession signal"
        ),
    ),
    Category(
        2, "macro", "Central Bank Policies & Interest Rates",
        "Policy decisions, guidance, balance sheets, and the rate path implied by futures.",
        "Scheduled meetings plus daily rate-market monitoring.",
        "Bond duration, growth-stock valuation, bank margins, FX, liquidity, and emerging-market flows.",
        _FIELDS,
        _types(
            "FOMC rate decision|FOMC minutes|Fed dot plot|Fed speech|Fed testimony|ECB policy decision|"
            "BOE policy decision|BOJ policy decision|RBI policy decision|PBOC policy decision|Policy-rate path|"
            "Futures-implied policy rate|QE / QT pace|Central bank balance sheet|Real policy rate|"
            "Nominal sovereign yields|Yield curve|Policy guidance"
        ),
    ),
    Category(
        3, "corporate", "Corporate Earnings & Company Announcements",
        "Results, guidance, capital actions, and filing events for held and watched companies.",
        "Event-driven, around quarterly reporting and filing calendars.",
        "The company thesis, valuation, sector peers, and credit quality.",
        _FIELDS,
        _types(
            "Quarterly results|Annual results|Revenue|EPS|EBITDA|Margins|Cash flow|Capex|Segment performance|"
            "Earnings beat or miss|Company guidance|Analyst estimate revisions|Earnings call|Dividend|Buyback|"
            "Stock split|Secondary offering|Debt issuance or refinancing|M&A|Executive change|"
            "Insider transaction|Institutional filing|Restatement|Bankruptcy or restructuring"
        ),
    ),
    Category(
        4, "risk", "Geopolitical & International Events",
        "Conflict, sanctions, trade restrictions, and supply-route disruptions.",
        "Continuous headline surveillance. Confirm with a named source before acting.",
        "Oil and gas, defense, gold, shipping, semiconductors, country risk, and FX.",
        _FIELDS,
        _types(
            "War or escalation|Ceasefire|US-China trade tension|Taiwan tension|Middle East conflict|"
            "Russia-Ukraine development|Sanctions|Tariffs|Export controls|Diplomatic agreement|"
            "Shipping chokepoint|Supply-chain disruption|National security incident|Political instability"
        ),
    ),
    Category(
        5, "macro", "Government Fiscal Policy & Regulatory Events",
        "Budgets, taxes, regulation, and other government actions that change sector economics.",
        "Legislative calendars and event-driven.",
        "Sector earnings, discount rates, fiscal risk, and policy winners or losers.",
        _FIELDS,
        _types(
            "Government budget|Corporate tax|Capital gains tax|Fiscal stimulus|Infrastructure spending|"
            "Defense spending|Healthcare regulation|Banking regulation|Antitrust action|AI regulation|"
            "Climate regulation|Labor regulation|Subsidy program|Debt ceiling|Government shutdown|"
            "Court decision|Import and export policy"
        ),
    ),
    Category(
        6, "markets", "Market Liquidity & Financial Conditions",
        "Funding, reserves, issuance, and flow gauges for risk appetite.",
        "Daily, weekly, or monthly, depending on the series.",
        "Risk appetite, funding costs, leveraged positions, and high-beta assets.",
        _FIELDS,
        _types(
            "Money supply|Central-bank reserves|Treasury General Account|Reverse repo|Repo funding stress|"
            "Bank lending standards|Credit growth|Financial conditions index|Margin debt|Corporate issuance|"
            "Cross-currency basis|ETF fund flows|Mutual fund flows|Institutional foreign flows"
        ),
    ),
    Category(
        7, "markets", "Equity Market Technicals & Sentiment",
        "Trend, breadth, volatility, and positioning for major equity benchmarks.",
        "Intraday or daily, with slower positioning series when published.",
        "Trend, crowding, volatility, breadth, and reversal risk. These are descriptions, not timing calls.",
        _FIELDS,
        _types(
            "S&P 500 trend|Nasdaq trend|Russell 2000 trend|Global benchmark trend|20-day moving average|"
            "50-day moving average|200-day moving average|RSI|MACD|Advance-decline line|New highs and lows|"
            "Percent above moving averages|Market concentration|VIX|Volatility curve|Put/call ratio|Option skew|"
            "Short interest|Investor sentiment survey|Sector relative strength|Volume|CFTC positioning"
        ),
    ),
    Category(
        8, "sector", "Sector-Specific Developments",
        "Industry news and fundamental signals used for relative sector work.",
        "Daily news, weekly signals, and monthly or quarterly fundamentals.",
        "Sector allocation, relative performance, and the earnings outlook.",
        _FIELDS,
        _types(
            "Technology cloud and AI spending|Semiconductor demand inventory and exports|"
            "Financials deposits and credit|Healthcare FDA trials and patents|Energy OPEC and inventories|"
            "Consumer discretionary retail and credit|Consumer staples input costs and pricing|"
            "Industrials orders and capex|Real estate mortgages and occupancy|Utilities power demand and rates|"
            "Materials metals and construction|Communications ads and subscribers|Defense procurement|"
            "Transportation freight and fuel|Renewables subsidies and project pipelines"
        ),
    ),
    Category(
        9, "markets", "Commodity & Natural Resource Events",
        "Energy, metals, and agriculture supply, inventory, and policy items.",
        "Daily pricing context, scheduled inventories, and event-driven supply shocks.",
        "Inflation, producers and consumers, energy, miners, airlines, and industrials.",
        _FIELDS,
        _types(
            "Oil and OPEC+|EIA crude inventories|Oil supply outage|Natural gas storage|Weather-driven gas demand|"
            "LNG flows|Gold and real yields|Central-bank gold purchases|Silver industrial demand|"
            "Copper and China demand|Copper mining supply|Lithium and EV supply-demand|Uranium and nuclear policy|"
            "Iron ore and steel|Agriculture weather|Harvest progress|Agriculture export restrictions|"
            "Rare earths and export controls"
        ),
    ),
    Category(
        10, "markets", "Currency & Foreign Exchange Events",
        "Dollar indexes, major pairs, reserves, and carry positioning.",
        "Intraday or daily, plus periodic reserve releases.",
        "International returns, exporter and importer margins, hedged funds, and sovereign stress.",
        _FIELDS,
        _types(
            "DXY|EUR/USD|USD/JPY|GBP/USD|USD/INR|USD/CNY|Emerging-market FX|Central-bank FX intervention|"
            "FX reserves|Rate differentials|Real effective exchange rate|FX hedging costs|Capital controls|"
            "Carry-trade positioning|Carry-trade unwind"
        ),
    ),
    Category(
        11, "macro", "Global & Emerging Market Events",
        "Regional growth, policy, and flow items used for country allocation.",
        "Daily regional headlines, scheduled macro data, and quarterly reviews.",
        "Country allocation, currency, and sovereign credit risk.",
        _FIELDS,
        _types(
            "US growth inflation and earnings|Europe energy and fiscal|China property|China stimulus|"
            "China industrial activity|India rates earnings and flows|Japan policy yen and governance|"
            "Southeast Asia manufacturing and FDI|Latin America commodities and fiscal|"
            "Middle East oil and sovereign investment|Africa FX debt and commodities|Sovereign rating action|"
            "External debt|Country FX reserves|Cross-border flows"
        ),
    ),
    Category(
        12, "risk", "Bond Market & Credit Events",
        "Curves, spreads, auctions, ratings, and refinancing pressure.",
        "Daily prices and spreads, scheduled auctions and ratings, quarterly defaults.",
        "Bond funds, credit-sensitive equities, discount rates, and refinancing risk.",
        _FIELDS,
        _types(
            "Sovereign yield curve|Real yields|Inflation breakevens|Investment-grade spreads|High-yield spreads|"
            "Corporate defaults|Recovery rates|Ratings actions|Government bond auction|Refinancing wall|"
            "Municipal debt stress|EM sovereign spreads|Bank credit stress|Nonbank credit stress"
        ),
    ),
    Category(
        13, "portfolio", "ETF, Mutual Fund & Fund Management Events",
        "Fund pricing, flows, holdings, and how closely a fund still matches its mandate.",
        "Daily pricing and flows where a file exists; holdings and documents on their own calendar.",
        "Investment costs, liquidity, unintended exposure, and manager risk.",
        _FIELDS,
        _types(
            "Fund NAV|ETF premium or discount|Tracking difference|Tracking error|Expense ratio|Holdings disclosure|"
            "Manager change|Style drift|Fund inflows|Fund outflows|Distribution|Fund merger or closure|"
            "Fund leverage|Fund concentration|Benchmark change|Index reconstitution|Redemption restriction|"
            "Rolling alpha|Rolling beta|Information ratio|Downside capture"
        ),
    ),
    Category(
        14, "corporate", "Corporate Governance, Legal & ESG Risks",
        "Accounting, legal, cyber, labor, and board events that can break a thesis.",
        "Event-driven, with a periodic governance review.",
        "Thesis invalidation, fines, reputation, cost of capital, and tail risk.",
        _FIELDS,
        _types(
            "Accounting allegation|Regulatory probe|Whistleblower report|Cyber breach|Lawsuit|"
            "Shareholder activism|Related-party transaction|Executive pay|Board change|Environmental liability|"
            "Labor dispute|Financial restatement|Auditor change"
        ),
    ),
    Category(
        15, "sector", "Technology Disruption & Structural Trends",
        "Adoption, spending, and valuation context for long-running technology themes.",
        "Ongoing industry news and quarterly fundamentals.",
        "Secular sector mix, disruption risk, and thematic valuation. Not a return forecast.",
        _FIELDS,
        _types(
            "AI and automation|GPUs and data centers|Quantum computing|Robotics and autonomy|Cybersecurity|"
            "EVs and batteries|Biotech and gene editing|Space industry|Nuclear and grid|Digital payments|"
            "Blockchain and tokenization|Cloud and edge computing"
        ),
    ),
    Category(
        16, "risk", "Climate, Natural Disasters & Physical Risks",
        "Weather, disaster, and physical-supply events with sector consequences.",
        "Alerts when relevant, plus seasonal risk notes.",
        "Insurance, agriculture, energy, real estate, utilities, and transportation.",
        _FIELDS,
        _types(
            "Hurricane|Flood|Drought|Wildfire|Extreme temperature|Earthquake|Water shortage|"
            "Disease outbreak|Climate legislation|Physical supply-chain impact"
        ),
    ),
    Category(
        17, "catalysts", "Political Elections & Major Policy Transitions",
        "Election dates, government formation, and the gap between proposals and enacted policy.",
        "Event-driven, with calendar countdowns.",
        "Fiscal and tax outlook, regulated sectors, country risk, and currencies. No partisan direction is assumed.",
        _FIELDS,
        _types(
            "Election calendar|Polling snapshot|Election outcome|Government formation|Legislation|"
            "Trade negotiation|Policy proposal|Enacted measure|Implementation milestone"
        ),
    ),
    Category(
        18, "markets", "Alternative Assets & Cryptocurrency Markets",
        "Liquid crypto context and slower private-market reporting. Category 18 is owned by Markets.",
        "Daily for liquid crypto; monthly or quarterly for private markets; event-driven risk notes.",
        "Alternative exposure, liquidity, and counterparty risk.",
        _FIELDS,
        _types(
            "Bitcoin liquidity and price|Ether liquidity and price|Spot crypto ETF flows|Stablecoin issuance|"
            "Stablecoin redemption|Crypto regulation|Exchange solvency|Custody solvency|Token unlock|"
            "Protocol change|DeFi lending stress|Private equity exit|Private equity valuation|"
            "Private credit default|Private credit nonaccrual|Real estate cap rates|Real estate transactions|"
            "Infrastructure fundraising|Venture fundraising|Redemption gate|Valuation lag"
        ),
    ),
    Category(
        19, "catalysts", "Market Calendar & Mechanical Events",
        "Expiries, index changes, offerings, and session mechanics that can distort prices for a short time.",
        "A forward calendar, with intraday notes only when a scheduled item is in force.",
        "Temporary flows, liquidity, volatility, and price distortions.",
        _FIELDS,
        _types(
            "Monthly options expiry|Quarterly options expiry|Triple witching|Index rebalance|MSCI review|"
            "FTSE review|ETF reconstitution|IPO|Lockup expiration|Secondary offering|Ex-dividend date|"
            "Tax-loss harvesting window|Quarter-end rebalancing|Futures roll|Market holiday|Shortened session|"
            "Trading halt|Circuit breaker|Settlement disruption"
        ),
    ),
    Category(
        20, "portfolio", "Portfolio-Specific Risks & Investment Triggers",
        "Allocation, concentration, drawdown, and thesis checks against the selected book.",
        "Daily exposures and P&L context; weekly risk review; monthly or quarterly rebalance review.",
        "Research prompts to hold, review, hedge, or rebalance. Nothing here is an order.",
        _FIELDS,
        _types(
            "Target versus actual allocation|Single-name concentration|Sector concentration|Country concentration|"
            "Currency concentration|Portfolio beta|Portfolio volatility|Max drawdown|Value at risk|"
            "Expected shortfall|Correlation|Factor exposure|Position liquidity|Leverage and margin|"
            "Profit and loss|Tax lots|Dividend income|Cash flows|Benchmark deviation|Thesis check|Stress scenario"
        ),
    ),
)


def panel(panel_id: str) -> Panel:
    for item in PANELS:
        if item.id == panel_id:
            return item
    raise KeyError(panel_id)


def category(category_id: int) -> Category:
    for item in CATEGORIES:
        if item.id == category_id:
            return item
    raise KeyError(category_id)


def categories_for(panel_id: str) -> tuple[Category, ...]:
    return tuple(item for item in CATEGORIES if item.panel_id == panel_id)


def ownership_counts() -> dict[str, int]:
    counts = {item.id: 0 for item in PANELS}
    for item in CATEGORIES:
        counts[item.panel_id] += 1
    return counts
