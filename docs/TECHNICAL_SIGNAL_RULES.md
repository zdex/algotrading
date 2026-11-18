# Technical signal agent rules

The technical signal agent turns daily price bars into one buy, sell, or flat signal. It does not place an order. The decision agent in `AGENT_FLOW.md` is the step that can trade.

Code:

- Collection: `collect_technical` in `agents/agno/trading_desk.py`, using `PriceActionAgent` in `agents/agno/price_action.py`
- Scoring: `score_technical` in `agents/agno/trading_desk.py`
- Signal node: `TradingDesk._node_technical_signal` in `agents/agno/trading_desk.py`

## What the technical agent sends

`PriceActionAgent` downloads about a year of daily bars (420 calendar days) from Yahoo Finance and computes a price-action packet. The signal uses these fields:

| Field | How it is set |
| --- | --- |
| `bars` | Number of daily bars with a close |
| `trend` | `uptrend`, `downtrend`, or `range` from the last two swing highs and last two swing lows. A swing is a high or low that is the unique extreme of the two bars on each side. Both the latest high and the latest low must be higher for an uptrend, and both lower for a downtrend. Fewer than two highs or two lows is `range`. |
| `breakout` | `above_prior_range` when the last close is above the high of the previous 20 bars, `below_prior_range` when it is below the low of those bars, otherwise `none`. Fewer than 21 bars is `none`. |
| `gap_pct` | Latest open versus the prior close, in percent. A move smaller than 0.5% is stored as `0.0`. |
| `volume_vs_average` | Latest volume divided by the mean of the previous 20 bars. |
| `last_close`, `support`, `resistance` | Stored on the signal as context. They do not change the score. |

If `bars` is 0, the signal is flat.

| Field | Empty packet |
| --- | --- |
| Stance | `flat` |
| Score | `0.00` |
| Summary | The collector error, or `No price bars were returned.` |
| Metadata | `items: 0`, plus the packet's `trend` and `breakout` |

## Score

The score starts at `0` and adds the points below. It is then clamped to `-1.0` … `1.0` and rounded to three decimals.

| Condition | Points |
| --- | --- |
| Trend is `uptrend` | +0.45 |
| Trend is `downtrend` | −0.45 |
| Trend is anything else | 0 |
| Breakout is `above_prior_range` | +0.35 |
| Breakout is `below_prior_range` | −0.35 |
| Volume is at least `1.2` times the 20-bar average, and the breakout is above the prior range | +0.10 |
| Volume is at least `1.2` times the 20-bar average, and the breakout is below the prior range | −0.10 |
| Volume is high while the breakout is `none` | 0 |
| Gap is at least `+0.50%` | +0.10 |
| Gap is at most `−0.50%` | −0.10 |

| Score | Stance |
| --- | --- |
| Greater than `0.05` | buy |
| Less than `-0.05` | sell |
| From `-0.05` through `0.05` | flat |

Summary: `Technical view from {bars} bars: trend {trend}, breakout {breakout}.`

Metadata:

- `items`: bar count
- `trend`, `breakout`, `last_close`, `support`, `resistance`
- `key_points`: one line for the trend, one for the breakout, and a line each for volume and gap when those points are applied

## Example

Packet:

| Field | Value |
| --- | --- |
| Bars | 252 |
| Trend | `uptrend` |
| Breakout | `above_prior_range` |
| Volume vs average | 1.50 |
| Gap | +0.80% |
| Last close | 190 |

```text
score = 0.45 + 0.35 + 0.10 + 0.10 = 1.000
stance = buy
```

Key points:

- Swing highs and lows are an uptrend.
- Close is above the prior 20-bar range.
- Volume is 1.50x the 20-bar average.
- Latest gap is 0.80%.

Signal:

| Field | Value |
| --- | --- |
| Agent | Technical signal agent |
| Stance | buy |
| Score | +1.00 |
| Summary | Technical view from 252 bars: trend uptrend, breakout above_prior_range. |

This buy is one of four inputs. A trade still needs at least two sources to agree, and no source to oppose. See `AGENT_FLOW.md`.
