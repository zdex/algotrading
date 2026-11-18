# Web signal agent rules

The web signal agent turns recent headlines into one buy, sell, or flat signal. It does not place an order. The decision agent in `AGENT_FLOW.md` is the step that can trade.

Code:

- Collection: `collect_web` in `agents/agno/trading_desk.py`, using `NewsAgent` in `agents/agno/research_agents.py`
- Scoring: `SentimentAnalysis.analyze` in `agents/agno/analysis_agents.py`
- Signal node: `TradingDesk._node_web_signal` in `agents/agno/trading_desk.py`

## What the web agent sends

`NewsAgent` reads a Google News RSS search for `{symbol} when:90d` and keeps up to 12 items. Each headline is one line:

```text
published_at | source | title | summary
```

The signal agent joins those lines with newlines and scores them as one block of text. It does not score each headline separately.

If the headline list is empty, the signal is flat.

| Field | Empty packet |
| --- | --- |
| Stance | `flat` |
| Score | `0.00` |
| Summary | The collector error, or `No web items were returned.` |
| Metadata | `items: 0` |

## Word lists

Matching is case-insensitive. A word counts once if it appears anywhere in the joined text, including inside a longer word. `beat` matches both `beat` and `upbeat`.

Positive words:

- strong
- optimistic
- positive
- excited
- confidence
- ahead
- robust
- upbeat
- excellent
- healthy
- surge
- beat
- accelerating

Negative words:

- weak
- concern
- negative
- risk
- worry
- pessimistic
- decline
- miss
- soft
- challenge
- pressure
- uncertain
- volatility

## Score

```text
score = (positive hits − negative hits) / (positive hits + negative hits + 1)
```

The score is clamped to `-1.0` … `1.0` and rounded to three decimals.

| Score | Stance |
| --- | --- |
| Greater than `0.05` | buy |
| Less than `-0.05` | sell |
| From `-0.05` through `0.05` | flat |

The written summary says positive when the score is above `0`, mixed when it is `0`, and negative when it is below `0`. Stance still uses the `0.05` band, so a tiny positive score can be described as positive and still be a flat signal.

Key points on the signal:

- Positive hits: `Positive sentiment terms dominate the narrative.`
- Negative hits: `Negative risk and caution language is present.`
- No hits: `Tone appears broadly neutral.`

Metadata stored with the signal:

- `items`: number of headlines
- `key_points`: the lines above

## Example

Headlines:

```text
2026-11-01 | Reuters | Apple posts a strong beat and healthy demand
2026-11-02 | Bloomberg | Robust outlook and excellent results ahead
```

Hits across both lines: strong, beat, healthy, robust, excellent, ahead. That is 6 positive and 0 negative.

```text
score = (6 − 0) / (6 + 0 + 1) = 0.857
stance = buy
```

Signal:

| Field | Value |
| --- | --- |
| Agent | Web signal agent |
| Stance | buy |
| Score | +0.86 |
| Summary | Sentiment is positive based on tone analysis of the supplied text. |
| Key point | Positive sentiment terms dominate the narrative. |
| Metadata | `items: 2` |

This buy is one of four inputs. A trade still needs at least two sources to agree, and no source to oppose. See `AGENT_FLOW.md`.
