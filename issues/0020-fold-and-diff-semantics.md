---
status: open
type: grilling
labels: [wayfinder:grilling]
assignee:
blocked_by: [0017]
---
## Question
Fold + diff semantics. Decide: fold determinism guarantees and rejection behavior
(invalid command mid-log: halt vs skip-and-record); snapshot representation; diff output
shape (per-object created/modified/deleted with field-level detail?); equality rules
(ties to tolerance policy from geometry ticket); what invariants hypothesis should enforce
(seed list for the fog item). Consult /codebase-design — fold is the deepest module.
