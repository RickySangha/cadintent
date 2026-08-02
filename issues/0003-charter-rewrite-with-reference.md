---
status: closed
type: grilling
labels: [wayfinder:grilling, charter]
---
## Question
How does this repo relate to civil-platform's code — literal extraction, pure greenfield,
or rewrite-with-reference?

## Resolution
Rewrite-with-reference. Civil-platform stays the design oracle: schemas generalize its real
command shapes, kernel behavior is checked against what its engine does, dogfood pain points
become spec requirements. No code, tests, or data are copied — this repo's history never
descends from private files, so no pre-publish audit is ever needed. Fresh implementation
against the spec doubles as a completeness test of the spec.
