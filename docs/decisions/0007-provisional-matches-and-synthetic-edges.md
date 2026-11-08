# 0007 — Provisional matches stay in the graph, and swaps become SYNTHETIC edges

- **Status:** Proposed (Cameron to confirm). Both were built in Phases 1 and 2 before being written
  down; this records them so the code and the invariants agree.
- **Date:** 2026-11-08

## Context
Two choices were made while building that touch the invariants or the data model.

1. **Invariant 6** says low-confidence matches go to the review queue, not straight into the graph.
   The resolver (docs/architecture.md, "Entity resolution") links a mention at 0.6 to 0.9
   confidence provisionally and also queues it for review.
2. **Leveraged funds.** TSLL holds Tesla mostly through total-return swaps. Counting only a fund's
   equity lines showed Tesla at 8.6% of a portfolio where the fund's own filing implies about 2x.
   Showing that needs an edge type the architecture table does not have.

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| A. Keep 0.6-0.9 matches out of the graph until a reviewer accepts them | Strictly follows invariant 6 | Exposure silently undercounts until the queue is cleared; the queue becomes a blocker | Review time |
| B. Link them provisionally, mark the confidence on the edge, queue for review | Exposure is complete now; every provisional flow is visible and labelled | Some numbers rest on unreviewed matches | A caveat and a `provisional_value` figure |
| C. Link only at 0.9 or above | Simple | Same undercounting as A, no review path for near misses | None |

For swaps: (D) a new `SYNTHETIC` edge type, kept out of funded value; (E) fold swap exposure into
`CONTAINS`; (F) ignore swaps.

## Decision
Proposed: **B** and **D**.
- Provisional matches carry their confidence on the edge (the minimum across a company's lines),
  appear in the exposure result with `provisional` flags and a `provisional_value` total, and are
  queued. A fuzzy match needs a distinctive word in common and a margin over the runner-up, is
  capped at 0.89, and teaches no identifiers until a reviewer accepts it.
- `SYNTHETIC` (fund to company) has weight equal to signed swap notional over net assets. It is not
  money you hold, so it is excluded from funded value and from the reconciliation, and reported as
  economic exposure beside it. Each edge cites the filed swap XML.

## Consequences
- The exposure API and report label provisional value and swap exposure; the documented invariant
  wording is read as "not as certain facts", not "not at all".
- Evidence is enforced by convention in the writers, not by the database. Consider an invariant
  checker rule or a deferred constraint before more edge writers are added.
- Only swaps with a ticker reference are handled. Futures, options, forwards and index swaps are
  stored but not turned into exposure.
- **Revisit if:** the share of provisional value is large, the gold sample shows wrong links at 0.6
  to 0.9, or a reviewer rejects a meaningful share of queued fuzzy matches.
