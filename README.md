# cadintent

An open intermediate representation for engineering design intent — typed commands
in, deterministic drawings out. Pre-v0.

Planning happens in the open: the wayfinder map and all decision tickets live in
[GitHub Issues](../../issues) (map = issue #1). Research findings live in [research/](research/).

## Layout

- [spec/](spec/) — JSON Schema (draft 2020-12) source of truth (CC-BY-4.0)
- [kernel/](kernel/) — `cadintent` Python package: validate / fold / diff, generated types
- [conformance/](conformance/) — `cadintent-conformance`: checks for implementations
- [backends/dxf/](backends/dxf/) — `cadintent-dxf`: DXF emission via ezdxf
- [examples/](examples/) — runnable end-to-end examples

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```
make sync           # install the workspace
make codegen        # regenerate pydantic types from spec/schemas (output committed)
make codegen-check  # fail if committed generated code is stale
make test           # run all tests
```

Code is Apache-2.0 ([LICENSE](LICENSE)); spec text and schemas are CC-BY-4.0
([spec/README.md](spec/README.md)).
