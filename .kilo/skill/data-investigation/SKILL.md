---
name: data-investigation
description: Rigorous, reproducible data investigations (anomalies, hypothesis tests, one-off analyses). Use for the E3 campaign, sweep outputs in evaluation/, and any result that will be cited.
---

# Data investigation (ArthaAI)

Use this for the E3 evaluation campaign and for any analysis whose result will be recorded.

## Method
1. **Pre-register**: write the hypothesis, the sample, and the pass/fail rule *before* looking at
   results (see `E3_EVALUATION_PROTOCOL.md`).
2. **Declare the sample**: name the frozen manifest hash (`evaluation/frozen_universe.json`) and the window.
3. **Reproduce**: keep the exact command and its raw output (`evaluation/sweep10_*.txt`).
4. **No tuning on the graded window**: parameters come from in-sample data only.
5. **Report everything**: all pre-registered variants, including failures — never select the best.
6. **Separate data from code**: a null result may be a data limit, *and vice versa*. Confirm the
   harness actually routes the signal you think it does — ARTHA-315 was exactly this trap
   (`promote-sweep` silently ran `trend` for several signals).
7. **Record**: results go in `evaluation/e3_results.md` with the commit and the sample hash.

## Red flags
- A result that **reverses on a wider sample** (survivorship / small-sample artifact).
- A "signal" result **identical to a baseline** — the harness may have fallen back silently.
- Any claim that is not reproducible from a recorded command.
