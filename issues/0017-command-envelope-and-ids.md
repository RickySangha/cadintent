---
status: open
type: grilling
labels: [wayfinder:grilling]
assignee:
blocked_by: [0013]
---
## Question
Design the core command envelope + identity scheme (the deepest spec decision; everything
composes around it). Decide: envelope fields (project, seq, author, kind, payload, basis —
what else? timestamps? schema-version stamp?); optimistic-concurrency semantics of seq;
ID format (ULID?) and rules for derived human names; how commands reference objects
(id vs name); error/rejection contract for invalid commands. Consult /domain-modeling;
civil-platform lessons doc is the primary input.
