# Chart Snapshot Standard — Post-Hackathon

This standard applies whenever the user says **"tạo chart snapshot"**.

## Design rule: three information layers

1. **Identity** — one header only: symbol, timeframe, and Binance Spot.
2. **Decision levels** — at most two active labels: the nearest supply/invalidation level and the BOS/confirmation level.
3. **Conditional path** — at most one arrow with a label of no more than two words, such as `IF BREAK`.

## Visual constraints

- Reserve visible space to the right of the latest candle for the future scenario.
- Extend the conditional arrow into that future space so it does not end inside the current candle cluster.
- Do not display paragraphs, conclusions, confidence explanations, or trade instructions inside the chart.
- Do not display every pivot. Internal pivots remain calculation inputs only.
- Show no more than two active zones.
- Keep labels to three words or fewer, excluding price values.
- Use pastel mint for bullish candles, pastel coral for bearish candles, pastel cyan for BOS/demand, and pastel red for supply.
- Keep the background charcoal and grid lines subdued.
- Do not add a personal signature or watermark; Binance Square adds account attribution.
- The written post carries the full thesis, confirmation, invalidation, and risk explanation.

## Fail-closed behavior

- A projected path is conditional, never a prediction.
- If price is between confirmation and invalidation, the post must say `NO TRADE` or `WAIT`.
- For Spot mode, a bearish signal maps to `AVOID_BUY`, not a Futures short.
- Only closed candles may generate levels or labels.

## Output contract

The renderer returns the output file, closed-candle count, latest close, bias, nearest swing high, and nearest swing low. These values must match the accompanying post.