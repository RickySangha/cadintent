---
status: closed
type: grilling
labels: [wayfinder:grilling, charter]
---
## Question
Language, tooling, and spec format?

## Resolution
Spec source of truth: JSON Schema draft 2020-12; Python types generated, never hand-written.
Kernel: Python 3.12+, uv, pydantic (runtime validation), typer (CLI). Tests: pytest +
hypothesis (property-based fold/diff invariants). DXF backend: ezdxf. Monorepo layout
(spec/, kernel/, conformance/, backends/dxf/, examples/), details owned by the scaffold
ticket. Codegen tool NOT settled — datamodel-code-generator has known quirks; see the
codegen research ticket.
