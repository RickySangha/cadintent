---
status: open
type: grilling
labels: [wayfinder:grilling]
assignee:
blocked_by: [0017]
---
## Question
Core geometry + units representation. Decide: 2D vs 2.5D vs 3D for v0 primitives; units
policy (SI-only in the model with presentation-side conversion? explicit unit fields?);
coordinate reference — project-local coordinates with optional CRS metadata, or CRS-aware?;
which primitives are core (point, polyline, arc?) vs pack-level; numeric precision/tolerance
policy (matters for diff equality and conformance expected-values).
