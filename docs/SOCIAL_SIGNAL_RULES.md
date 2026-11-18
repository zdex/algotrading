# Social signal agent rules

The social signal agent turns recent X posts into one buy, sell, or flat signal. It does not place an order. The decision agent in `AGENT_FLOW.md` is the step that can trade.

Code:

- Collection: `collect_social` in `agents/agno/trading_desk.py`, using `SocialAgent` in `agents/agno/research_agents.py`
- Per-post scoring: `SentimentAnalysis.analyze` in `agents/agno/analysis_agents.py`
- Signal node: `TradingDesk._node_social_signal` in `agents/agno/trading_desk.py`

## What the social agent sends

`SocialAgent` searches recent English posts that are not retweets:

```text
($SYMBOL OR "Company Name") -is:retweet lang:en
```

The lookup uses `X_BEARER_TOKEN`, or `TWITTER_BEARER_TOKEN` if that is the name set in the environment. Without a token, the packet is empty and the signal is flat, with the summary `Social lookup skipped: set X_BEARER_TOKEN to read posts from X.`

Each post is scored on its own with the same word lists as the web signal agent. The post record keeps that score. The signal agent does not score the posts again. It averages the scores already on the packet. At most 10 posts are kept.

If the score list is empty, the signal is flat.

| Field | Empty packet |
| --- | --- |
| Stance | `flat` |
| Score | `0.00` |
| Summary | The collector error, or `No social posts were returned.` |
| Metadata | `items: 0` |

## Per-post score

Matching is case-insensitive. A word counts once if it appears anywhere in that post, including inside a longer word.

Positive words: strong, optimistic, positive, excited, confidence, ahead, robust, upbeat, excellent, healthy, surge, beat, accelerating.

Negative words: weak, concern, negative, risk, worry, pessimistic, decline, miss, soft, challenge, pressure, uncertain, volatility.

```text
post score = (positive hits − negative hits) / (positive hits + negative hits + 1)
```

The post score is clamped to `-1.0` … `1.0` and rounded to three decimals. A post above `0.05` is labeled positive, below `-0.05` negative, and otherwise mixed. That label is stored on the post. The signal uses the numeric average, not the labels.

## Signal score

```text
score = round(sum(post scores) / number of posts, 3)
```

| Score | Stance |
| --- | --- |
| Greater than `0.05` | buy |
| Less than `-0.05` | sell |
| From `-0.05` through `0.05` | flat |

Summary: `{n} posts, average sentiment {score:+.2f}.`

Metadata:

- `items`: number of post scores
- `key_points`: `Average of {n} post scores.`

## Example

Two posts:

```text
Strong beat and healthy demand
Robust and excellent results ahead
```

First post hits strong, beat, and healthy. Score `(3 − 0) / 4 = 0.75`.

Second post hits robust, excellent, and ahead. Score `(3 − 0) / 4 = 0.75`.

```text
score = (0.75 + 0.75) / 2 = 0.750
stance = buy
```

Signal:

| Field | Value |
| --- | --- |
| Agent | Social signal agent |
| Stance | buy |
| Score | +0.75 |
| Summary | 2 posts, average sentiment +0.75. |
| Key point | Average of 2 post scores. |
| Metadata | `items: 2` |

This buy is one of four inputs. A trade still needs at least two sources to agree, and no source to oppose. See `AGENT_FLOW.md`.
