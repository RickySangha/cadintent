# cadintent spec

JSON Schema (draft 2020-12) is the source of truth for the cadintent wire format.
Schemas live in [schemas/](schemas/); Python types are generated from them (never
hand-written) — see the repo root `Makefile` (`make codegen`).

## Licensing

The specification text and schemas in this directory are licensed under
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/). Code elsewhere in this
repository is licensed under Apache-2.0 (see the root [LICENSE](../LICENSE)).

## Authoring constraints

Imposed by the codegen toolchain decision
([research/codegen-tooling.md](../research/codegen-tooling.md)):

1. Every discriminated `oneOf` carries `"discriminator": {"propertyName": "kind"}`
   (OpenAPI 3.1 keyword, ignored by pure 2020-12 validators), and every variant
   declares `"kind": {"const": "..."}` and lists `kind` in `required`.
2. Cross-file references use relative file paths (`"common.json#/$defs/Point"`),
   never remote `$id` URLs.
3. Forbidden in the wire format: `patternProperties`; typed `additionalProperties`
   on objects that also declare `properties`; `if/then/else`;
   `unevaluatedProperties`.
