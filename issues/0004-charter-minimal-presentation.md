---
status: closed
type: grilling
labels: [wayfinder:grilling, charter]
---
## Question
Is the presentation layer in v0, and how much of it?

## Resolution
Minimal presentation spec, naive implementation. Spec gets two schemas — label rules
(template + style ref + preferred offsets) and symbol catalog (type→block mapping with
conditional variants + computed rotation) — because retrofitting them later breaks the spec.
Implementation is deliberately dumb: fixed-offset placement, no collision solving, no
auto-leaders, no pins. Test applied: a second implementer needs label rules and catalogs to
be *compatible*; placement quality may differ between implementations, content correctness may not.
