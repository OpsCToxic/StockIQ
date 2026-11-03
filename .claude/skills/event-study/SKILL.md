---
name: event-study
description: Methodology and honesty rules for StockIQ event studies, typical-trend cards, and signal lead/lag tests (abnormal returns, windows, sample size, conditioning, wording). Use when building the timeline module or evaluating any signal's historical edge.
---

# Event studies and lead/lag tests

## Abnormal returns
- Expected return from a market model: regress the stock's daily return on the market return over an
  estimation window of [-260, -11] trading days relative to the event, ending before the event window.
- AR_t = R_t − (α + β·R_m,t). Event window default [−10, +10]; store CAR over [−1,+1], [0,+5], [0,+10].
- Event day 0 = first trading session the information was *known* (after-close announcements → next day).
- Exclude events whose windows overlap a prior event of the same type for that entity, or note overlap.

## Stored stats (`event_study` table)
`n, mean_ret, median_ret, p25, p75` per (entity, event_type, window), plus `computed_at` and the
as_of used. Compute from events known before as_of only.

## Honesty rules (user-facing)
- Always show n and the spread (IQR) next to any average.
- n < 8 → grey out and label "too few events".
- Wording: "Historically, around past earnings, NVDA moved a median of +1.2% (n = 14, IQR −3.1% to
  +4.0%)." Never "NVDA will" / "expect" / "likely to".
- Show the unconditional pattern next to any conditioned one (v2).

## Lead/lag for signals (sentiment, insider, 13F, congress)
- For each entity and signal type, compare forward abnormal returns after signal days vs. non-signal
  days, using only signals known at the time.
- Report effect, n, and a simple significance measure; correct or caveat for multiple testing across
  many tickers.
- Store the result even when null; display "no measurable edge" where true.
- Ask the `quant-reviewer` subagent to review any new event-study or lead/lag code.
