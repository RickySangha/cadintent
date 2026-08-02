---
status: closed
type: research
labels: [wayfinder:research]
assignee:
blocked_by: []
---
## Question
What does civil-platform (the private reference oracle at /Users/ricky/Desktop/civil-platform)
teach the openintent spec? Read engine/src, docs/PRD.md + SPEC.md, issues/ (especially
dogfood issues #21–#29), standards/conventions. Extract as a requirements document, NOT code:
actual command shapes used in practice; ID/naming approach; check types that earned their
keep; label/attrib/block lessons (attributed blocks #22, attrib-vs-rule #23, STYLE sanitize
#28); pain points that must be structurally impossible in the new spec. Cite civil-platform
paths for traceability but copy no code or data into the findings.
Findings → research/civil-platform-lessons.md.

## Resolution
Civil-platform's field-tested mutation vocabulary is rule-carrying, set-targeting, scope-declaring elements (not bare set-value commands) with a closed no-eval rule registry — the envelope must make rules, selections, derivation records, and declared blast radius first-class. Every shipped check traces to a specific defect; meta-lessons: verification must be structural, vacuous passes must be visibly distinct from real ones, every tolerance needs a typed refusal. Top structural-impossibility list anchored by merge-back/stale-copy disease, coordinate-free annotation, author-restricted existing-conditions writes, surveyed-vs-interpolated tagging. Full report: research/civil-platform-lessons.md
