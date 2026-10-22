# Market Monitor

Sidebar section in the Streamlit app. It is the phase-1 dashboard from the investment-dashboard instructions: eight panels, all 20 event categories, and a local decision log. Quotes and macro prints are a **simulated batch** dated 2026-10-16. They are not live.

## Layout

```text
market_monitor/          domain, no Streamlit
  registry.py            8 panels, 20 categories, event-type catalog
  catalog.py             one simulated event per type, plus one duplicate CPI wire
  scoring.py             priority score; missing exposure stays unknown
  query.py               filters, calendar, book exposure, alert matching
  workflow.py            JSON store for decisions, watches, snoozes, rules
  adapters.py            provider protocols and the API contract
  series.py              chart tables for the panels
ui/market_monitor/       page layout
ui/views/monitor_*.py    one sidebar page each
```

Category 18 (alternatives and crypto) belongs to **Markets**. The Decision Log does not own a category. It stores decisions that point at event ids, and each revision appends an audit row.

Risk Alerts lists its own categories and also high or critical events owned by other panels, marked as references.

## Run

From the repo root, with the project environment:

```text
streamlit run ui/app.py
```

Open **Market Monitor** in the sidebar. Choose a book in the top bar:

- Demo book — fixed $1,000,000 mix used for exposure examples
- Paper book — positions already stored for paper trading
- Manual book — symbols and values typed on Portfolio Health
- No holdings — exposure is shown as unknown, not zero

## Tests

```text
pytest tests/test_market_monitor.py
```

## Not built yet

- Licensed feeds (FRED, BLS, BEA, EDGAR, EIA, exchange calendars, news). Adapters in `adapters.py` are the seam. Keys stay on a server; this UI does not call them.
- The HTTP routes listed on Data Sources are a contract only. They are not mounted.
- No orders. Acknowledge, snooze, and the decision log never go to a broker.
- Permissions, multi-user audit storage, and production alerting.
