---
status: open
type: research
labels: [wayfinder:research]
assignee:
blocked_by: []
---
## Question
What toolchain should generate Python (pydantic v2) types from JSON Schema draft 2020-12?
Evaluate datamodel-code-generator fitness and known quirks ($defs/$ref graphs, oneOf/
discriminated unions, const, additionalProperties, recursive schemas, 2020-12 support);
alternatives (quicktype, LinkML, hand-rolled thin generator, writing pydantic first and
emitting JSON Schema FROM it — note this inverts source-of-truth and assess honestly).
Recommend one approach with rationale. Findings → research/codegen-tooling.md.
