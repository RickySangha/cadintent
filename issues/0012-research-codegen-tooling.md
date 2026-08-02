---
status: closed
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

## Resolution
Use datamodel-code-generator (pinned version, fixed flags, committed output with a regen-diff CI check) to generate pydantic v2 models from the 2020-12 schemas. Smoke-tested dcg 0.71.0 + pydantic 2.13.4 on cross-file $defs, kind-const discriminated oneOf, enums, additionalProperties:false, recursion — all clean. Spec constraints: add OpenAPI-3.1-style discriminator beside each oneOf; avoid patternProperties, typed-additionalProperties+properties mixes, if/then/else. Fallback: thin hand-rolled generator with dcg output as goldens. Full report: research/codegen-tooling.md
