# Trading desk agent flow

The trading desk in `agents/agno/trading_desk.py` is a LangGraph `StateGraph`. One pass scores one company. A scheduled run repeats that pass for every company on the agent.

Orders from the execution agent are paper orders. They are written to `data/agents/paper_orders.json` and are not sent to a broker.

## Outer loop

The Trading Agent page starts a `ScheduledRunner` (`agents/agno/schedule.py`).

```text
Companies on the agent + schedule
    ↓
ScheduledRunner
    ↓
first pass immediately, then every 15 minutes, 30 minutes, 1 hour, 4 hours, daily, monthly on day 1, or quarterly on day 1 of Jan, Apr, Jul, and Oct
    ↓
TradingDesk.run for each company
```

Each running agent keeps the company list and schedule it had when it was started. Starting another agent does not change the ones already running. Each agent card has its own Stop.

## Graph for one company

Research agents start together. Each one hands its packet to its own signal agent. The decision agent waits until all four signals exist. The execution agent runs only after that decision.

```text
                 ┌─ Web agent ──────────────► Web signal agent ──────────────┐
                 ├─ Fundamental agent ──────► Fundamental signal agent ──────┤
Start ───────────┼─ Social agent ───────────► Social signal agent ───────────┼──► Decision agent ──► Execution agent ──► End
                 └─ Technical agent ────────► Technical signal agent ────────┘
```

Node names are the same strings as `AGENT_NAMES` in `agents/agno/trading_desk.py`.

## What each agent does

| Agent | Input | Output |
| --- | --- | --- |
| Web agent | Company symbol and name | Headlines from `NewsAgent` |
| Web signal agent | Those headlines | Buy, sell, or flat from sentiment keywords |
| Fundamental agent | Company symbol and name | Filing list plus 10-Q / 10-K excerpt text from `FilingsAgent` |
| Fundamental signal agent | That filing text | Buy, sell, or flat from fundamental phrases. Rules: `FUNDAMENTAL_SIGNAL_RULES.md` |
| Social agent | Company symbol and name | Posts and scores from `SocialAgent` |
| Social signal agent | Those post scores | Buy, sell, or flat from the average score |
| Technical agent | Daily bars from `PriceActionAgent` | Trend, breakout, gap, and volume |
| Technical signal agent | That price packet | One score from trend, breakout, volume, and gap |
| Decision agent | The four signals | Buy, sell, or hold, plus a quantity |
| Execution agent | The decision | A queued paper order, or no order on hold |

A missing packet becomes a flat signal with score `0.00`. Flat does not count as a vote for or against a trade.

## Decision rule

`combine_signals` trades only when at least two sources agree and none oppose.

| Agreeing sources | Opposing source | Action | Quantity |
| --- | --- | --- | --- |
| 2 or more buy | No sell | buy | 10 for 2 votes, 15 for 3, 20 for 4 |
| 2 or more sell | No buy | sell | 10 for 2 votes, 15 for 3, 20 for 4 |
| Anything else | — | hold | 0 |

A score above `0.05` is buy. A score below `-0.05` is sell. A score from `-0.05` through `0.05` is flat.

## Execution

On buy or sell, the execution agent appends a `PaperOrder` with status `queued` and route `paper blotter`. The reason text includes that the order is not sent to a broker.

On hold, the execution agent writes a log line and does not append an order.

## Where this shows up

`ui/views/trading_agent.py` lists each running agent, who is running now, the agent output, the decisions, and the paper blotter. The page does not draw this graph. The graph above is the LangGraph in `agents/agno/trading_desk.py`.
