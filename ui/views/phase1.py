"""Phase 1 Validation: placeholder until run_phase1.py is connected."""

import streamlit as st

st.title("Phase 1 Validation")
st.info(
    "Not connected yet. `run_phase1.py` (walk-forward, Monte Carlo, benchmark and cost "
    "sensitivity, PROCEED/REFINE verdict) wasn't among the uploaded files.",
    icon=":material/construction:",
)

st.markdown("""
**What this page will show once it's wired up**

- **Walk-forward:** 24-month train / 6-month test windows on a timeline, in-sample vs
  out-of-sample Sharpe per window, and the stitched out-of-sample equity curve.
- **Monte Carlo:** a fan chart of simulated equity paths (5th / 50th / 95th percentile)
  and the distribution of final return and max drawdown.
- **Benchmark:** strategy vs SPY/QQQ with alpha, beta and information ratio
  (single-run versions of these are already on Backtest Results).
- **Cost sensitivity:** Sharpe and CAGR for each cost scenario, showing where the edge disappears.
- **Verdict:** PROCEED / REFINE with the pass/fail criteria as a checklist.

**What's needed:** `run_phase1.py` should call `backtester.runner.run_backtest()` for each
window/scenario and save its outputs (for example with `backtester.results_store.save_result`
plus a small `phase1.json` holding the window table, Monte Carlo percentiles and verdict).
""")

st.caption("Tip: until then, you can approximate cost sensitivity by running the same settings with "
           "different slippage in Backtest Lab and comparing them on Backtest Results → Compare runs.")
