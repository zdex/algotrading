# Fundamental signal agent rules

The fundamental signal agent turns filing text into one buy, sell, or flat signal. It does not place an order. The decision agent in `AGENT_FLOW.md` is the step that can trade.

Code:

- Collection: `collect_fundamental` in `agents/agno/trading_desk.py`
- Scoring: `FundamentalAnalysis.analyze` in `agents/agno/analysis_agents.py`
- Signal node: `TradingDesk._node_fundamental_signal` in `agents/agno/trading_desk.py`

## What the fundamental agent sends

`FilingsAgent` loads the company's recent filings. The packet keeps up to eight filing labels, shaped like:

```text
10-Q period 2026-06-30 filed 2026-08-01 (SEC EDGAR)
```

It also reads excerpt text from two filings when they exist:

- the latest `10-Q`, or `6-K` if there is no `10-Q`
- the latest `10-K`, or `20-F` if there is no `10-K`

Each excerpt is capped at 1600 characters. The signal agent scores the filing labels and the excerpts as one block of text.

If that text is empty, the signal is flat.

| Field | Empty packet |
| --- | --- |
| Stance | `flat` |
| Score | `0.00` |
| Summary | The collector error, or `No quarterly report or P&L text was returned.` |
| Metadata | `items: 0`, `excerpt_found: false` |

## Phrase lists

Matching is case-insensitive and looks for the whole phrase inside the text. Each phrase counts once, even if it appears many times.

Bullish phrases:

- revenue growth
- earnings beat
- margin expansion
- cash flow
- guidance upgrade
- strong demand
- profitability
- operational leverage

Bearish phrases:

- margin pressure
- guidance cut
- demand slowdown
- legal risk
- inventory issue
- cost inflation
- revenue miss
- weak outlook

## Score

```text
score = (bullish hits − bearish hits) / (bullish hits + bearish hits + 1)
```

The score is clamped to `-1.0` … `1.0` and rounded to three decimals.

| Score | Stance |
| --- | --- |
| Greater than `0.05` | buy |
| Less than `-0.05` | sell |
| From `-0.05` through `0.05` | flat |

The written summary says bullish when the score is above `0`, neutral-to-cautious when it is `0`, and bearish when it is below `0`. Stance still uses the `0.05` band above, so a tiny positive score can be described as bullish and still be a flat signal.

Key points on the signal:

- Bullish hits: `Positive operating signals detected from the document.`
- Bearish hits: `Negative risk factors or weaker guidance are noted.`
- No hits: `No explicit fundamental signal keywords were identified.`

Metadata stored with the signal:

- `items`: number of filing labels in the packet
- `excerpt_found`: whether any 10-Q / 10-K excerpt text was read
- `key_points`: the lines above

## Example

Filing excerpt:

```text
The company reported revenue growth and an earnings beat, with margin expansion and stronger cash flow. Management cited strong demand.
```

Hits: revenue growth, earnings beat, margin expansion, cash flow, strong demand. That is 5 bullish and 0 bearish.

```text
score = (5 − 0) / (5 + 0 + 1) = 0.833
stance = buy
```

Signal:

| Field | Value |
| --- | --- |
| Agent | Fundamental signal agent |
| Stance | buy |
| Score | +0.83 |
| Summary | Fundamental analysis suggests a bullish bias based on the language in the supplied company and earnings context. |
| Key point | Positive operating signals detected from the document. |

This buy is one of four inputs. A trade still needs at least two sources to agree, and no source to oppose. See `AGENT_FLOW.md`.
