# Codegen tooling: JSON Schema 2020-12 → Python (pydantic v2)

- **Date:** 2026-08-02
- **Resolves:** `issues/0012-research-codegen-tooling.md`

## Question

The project defines its data format as JSON Schema draft 2020-12 (source of truth) and
needs pydantic v2 models generated from those schemas. Schemas will use: shared `$defs`
referenced across files, `oneOf` unions of command payloads discriminated by a `kind`
const, enums, nested objects, `additionalProperties: false`, and possibly recursive
references. What toolchain should generate the Python types?

## TL;DR

Use **datamodel-code-generator** (pinned version, fixed flag set, regen-check in CI). A
smoke test against a representative schema set (cross-file `$defs`, `kind`-const
discriminated `oneOf`, enum, `additionalProperties: false`, recursion) produced clean,
correct pydantic v2 output with v0.71.0. One spec-authoring constraint: put an
OpenAPI-3.1-style `discriminator: {"propertyName": "kind"}` next to each `oneOf` — pure
`oneOf` + `const` generates a plain (slower, worse-errors) union. Fallback: a hand-rolled
thin generator; do **not** invert to pydantic-first.

---

## 1. datamodel-code-generator (dcg)

Actively maintained (koxudaxi/datamodel-code-generator, v0.71.0 as of Aug 2026), and it is
the codegen tool the pydantic project itself documents as the integration for
schema-to-model generation ([pydantic docs page](https://pydantic.dev/docs/validation/latest/integrations/dev-tools/datamodel_code_generator/)).
Input support explicitly covers JSON Schema drafts 04/06/07, 2019-09, and **2020-12**
([project README](https://github.com/koxudaxi/datamodel-code-generator/)); output
`pydantic_v2.BaseModel` is a first-class target.

### Smoke test (v0.71.0, this session)

Two files: `common.json` (a `$defs`-only file with `Point` and a `Unit` enum) and
`commands.json` (top-level `oneOf` of `MoveCommand`/`GroupCommand`, each with
`kind: {const: ...}`, `additionalProperties: false`, cross-file `$ref
"common.json#/$defs/Point"`, and `GroupCommand.children` recursively referencing the
union via `$ref: "#"`). Command:

```
datamodel-codegen --input schemas --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel --output out \
  --target-python-version 3.12 --use-annotated --enum-field-as-literal one
```

Results — all of the hard requirements worked:

| Feature | Output |
|---|---|
| Cross-file `$ref` | One module per schema file, proper `from . import common` imports — no duplicated classes |
| `const: "move"` | `kind: Literal['move']` |
| `additionalProperties: false` | `model_config = ConfigDict(extra='forbid')` (verified rejecting extras at runtime) |
| `enum` | `class Unit(Enum)` (or `Literal` with `--enum-field-as-literal all`) |
| Discriminated `oneOf` (with `discriminator` keyword) | `class Command(RootModel[MoveCommand \| GroupCommand])` with `Annotated[..., Field(discriminator='kind')]` — real pydantic discriminated union, verified at runtime |
| Recursion (`$ref: "#"`) | `children: list[Command]` + `GroupCommand.model_rebuild()` — validates nested payloads correctly |

### Quirks and known issues

1. **The discriminator must be declared with the OpenAPI-3.1 `discriminator` keyword.**
   Verified directly: deleting `"discriminator": {"propertyName": "kind"}` from the
   schema and regenerating yields a plain `MoveCommand | Union` with no
   `Field(discriminator=...)` — dcg does not *infer* discrimination from `const` fields.
   `discriminator` is not a 2020-12 validation keyword (it comes from OpenAPI 3.1), but
   2020-12 validators ignore unknown keywords, so carrying it in our schemas is harmless
   and costs nothing. This is the main spec-authoring constraint.
2. **Discriminator handling has a bug history — pin the version.** Older releases put the
   discriminator annotation on a `list` instead of the union
   ([#1937](https://github.com/koxudaxi/datamodel-code-generator/issues/1937)), crashed
   with "Discriminator type is not found"
   ([#1832](https://github.com/koxudaxi/datamodel-code-generator/issues/1832)), and used
   the wrong property name under aliasing
   ([#1769](https://github.com/koxudaxi/datamodel-code-generator/issues/1769)). All fixed
   in the current line (our list-of-discriminated-union case generated correctly), and
   recent releases added a sane fallback to plain unions when a discriminator can't be
   resolved ([releases](https://github.com/koxudaxi/datamodel-code-generator/releases)).
3. **`const` history.** `const` support arrived late
   ([#658](https://github.com/koxudaxi/datamodel-code-generator/issues/658)), pydantic-v2
   output initially emitted the removed `const=` field kwarg
   ([#1463](https://github.com/koxudaxi/datamodel-code-generator/issues/1463)), and
   `const` inside `$defs` was mis-detected
   ([#1951](https://github.com/koxudaxi/datamodel-code-generator/issues/1951)). Current
   output is correct (`Literal[...]`, including for `const` inside `anyOf/oneOf` as of
   v0.51.0), but this is another pin-the-version argument.
4. **Union type aliases become `RootModel` wrappers.** `Command` is
   `RootModel[MoveCommand | GroupCommand]`, so nested access is `cmd.root.children[0].root`.
   `--collapse-root-models` inlines the union everywhere but then the named `Command`
   type disappears entirely (observed in the smoke test) — and it has its own bug history
   ([#2120](https://github.com/koxudaxi/datamodel-code-generator/issues/2120)). Keep the
   RootModel; it is also the natural top-level `model_validate` entry point.
5. **Cosmetic junk:** a `$defs`-only file gets a stray `class Model(RootModel[Any])`.
   Harmless; ignorable or strippable in a post-gen lint.
6. **Features to avoid in the spec** because dcg mangles or ignores them:
   `patternProperties` (silently not generated,
   [#1851](https://github.com/koxudaxi/datamodel-code-generator/issues/1851)); typed
   `additionalProperties` mixed with declared `properties` on the same object
   ([#1751](https://github.com/koxudaxi/datamodel-code-generator/issues/1751));
   and anything with no pydantic equivalent (`if/then/else`, `unevaluatedProperties`,
   cross-property constraints) — those can't round-trip into static types with *any*
   generator, so keep them out of the wire format or enforce them only at the
   jsonschema-validation layer.

## 2. Alternatives

### quicktype

quicktype grew a `pydantic` renderer option for its Python target (requested in
[glideapps/quicktype#1474](https://github.com/glideapps/quicktype/issues/1474)), but the
tool is fundamentally inference-oriented (its headline use is samples→types) and its
JSON-Schema fidelity is the weak spot: types get nondeterministically renamed with
2020-12 `$defs` ([#2778](https://github.com/glideapps/quicktype/issues/2778)), string
formats get coerced to types the schema didn't ask for
([#2219](https://github.com/glideapps/quicktype/issues/2219)), and strictness features
like `additionalProperties: false` and pydantic discriminated unions are not faithfully
honored. It also drags a Node toolchain into a Python project's codegen path. Its real
value to us is later, as *one candidate* for the TypeScript path. **Rejected for Python.**

### LinkML

LinkML is a full modeling framework: author schemas in LinkML YAML, then `gen-pydantic`,
`gen-json-schema`, `gen-typescript`, etc. ([linkml.io generators docs](https://linkml.io/linkml/generators/)).
The multi-target story is attractive, but adopting it means the source of truth becomes
LinkML YAML, not JSON Schema — the ticket's premise (and charter) is that JSON Schema
2020-12 *is* the spec. LinkML's class/slot/mixin semantics are a whole modeling layer to
learn, its generated JSON Schema is an artifact we don't fully control, and its pydantic
generator has its own fidelity gaps for exactly our features (discriminated unions,
strict `additionalProperties`). Worth it for ontology-heavy scientific data models;
overkill and a sovereignty loss here. **Rejected.**

### Hand-rolled thin generator

A few hundred lines walking the schemas with `referencing`/`jsonschema` and emitting
pydantic classes. Full control, zero upstream surprises — but we would re-implement
precisely the hard parts dcg already solved (cross-file ref graphs, recursion +
`model_rebuild`, discriminated-union emission, enum/Literal policy) and own the bug tail
forever. Not justified while dcg passes our tests. **Rejected as first choice; this is
the fallback.**

### Inverted approach: author pydantic, emit JSON Schema

Pydantic v2's `model_json_schema()` emits schemas "compliant with JSON Schema Draft
2020-12 and OpenAPI Specification v3.1.0"
([pydantic JSON Schema docs](https://pydantic.dev/docs/validation/latest/concepts/json_schema/)),
and discriminated unions even emit an OpenAPI `discriminator`. Honest assessment:

**Gained:** perfect Python fidelity by construction; zero codegen pipeline; validators,
computed fields, and custom types are just... written; refactoring is ordinary Python.

**Lost — and this is decisive for an open spec:**

- The spec is no longer a language-neutral artifact anyone can author or review. A
  third-party implementer (or the future TS side) must consume *emitted* schemas whose
  shape is whatever pydantic's generator decides: auto-generated `$defs` names, `title`
  noise, `anyOf: [T, {type: null}]` for optionals, `allOf` wrappers around refs with
  sibling keys. Emitted output can also shift across pydantic releases, churning the
  "spec" without any intended semantic change.
- Python-isms leak into the wire format (field naming conventions, enum classes, default
  representations), and spec review becomes code review of Python.
- The failure mode is subtle: the schemas stop being the contract and become
  documentation of whatever the Python code does — the exact inversion the charter
  forbids. The TS generator then chases pydantic's emission quirks instead of a
  hand-authored, stable schema.

**Rejected** as the primary approach. It remains a legitimate *escape hatch* for internal
(non-spec) types, and a last-resort fallback if schema-first codegen proves untenable.

## 3. Recommendation

**Primary: datamodel-code-generator**, pinned exactly (e.g. `datamodel-code-generator==0.71.0`
as a dev dependency), invoked with a fixed flag set:

```
datamodel-codegen --input spec/schemas --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel --output src/<pkg>/generated \
  --target-python-version 3.12 --use-annotated --enum-field-as-literal one \
  --formatters black
```

plus a CI check that regenerating produces no diff (generated code is committed), and a
conformance layer that *also* validates payloads against the schemas with the `jsonschema`
library — so the schemas stay the enforced contract even where static types are lossy.

**Fallback:** if a dcg release regression or an unfixable generation bug blocks us, write
the thin hand-rolled generator (we'd already have the committed dcg output as its
reference/golden files, which de-risks it substantially). Only if schema-first itself
fails would the pydantic-first inversion be reconsidered.

**Spec-authoring constraints imposed by this choice:**

1. Every discriminated `oneOf` carries `"discriminator": {"propertyName": "kind"}`
   (OpenAPI 3.1 keyword; ignored by pure 2020-12 validators) and every variant declares
   `"kind": {"const": "..."}` in `required`.
2. Cross-file references use relative file paths (`"common.json#/$defs/Point"`), not
   remote `$id` URLs; generate from the schema *directory* so dcg maps files → modules.
3. No `patternProperties`; no typed `additionalProperties` on objects that also declare
   `properties`; no `if/then/else` or `unevaluatedProperties` in the wire format.
4. Named union aliases surface as pydantic `RootModel`s (`.root` access) — accept this;
   don't use `--collapse-root-models` (it erases the named alias and has open bugs).
5. Treat generator upgrades as reviewed changes: bump the pin, regenerate, read the diff.

## Sources

- https://github.com/koxudaxi/datamodel-code-generator/ (README: supported input drafts incl. 2020-12; output types)
- https://github.com/koxudaxi/datamodel-code-generator/releases
- https://pydantic.dev/docs/validation/latest/integrations/dev-tools/datamodel_code_generator/
- https://pydantic.dev/docs/validation/latest/concepts/json_schema/ (2020-12 / OpenAPI 3.1 compliance of emitted schemas)
- dcg issues: [#658](https://github.com/koxudaxi/datamodel-code-generator/issues/658), [#1463](https://github.com/koxudaxi/datamodel-code-generator/issues/1463), [#1751](https://github.com/koxudaxi/datamodel-code-generator/issues/1751), [#1769](https://github.com/koxudaxi/datamodel-code-generator/issues/1769), [#1832](https://github.com/koxudaxi/datamodel-code-generator/issues/1832), [#1851](https://github.com/koxudaxi/datamodel-code-generator/issues/1851), [#1937](https://github.com/koxudaxi/datamodel-code-generator/issues/1937), [#1951](https://github.com/koxudaxi/datamodel-code-generator/issues/1951), [#2120](https://github.com/koxudaxi/datamodel-code-generator/issues/2120), [#2368](https://github.com/koxudaxi/datamodel-code-generator/issues/2368)
- quicktype: [#1474](https://github.com/glideapps/quicktype/issues/1474), [#2219](https://github.com/glideapps/quicktype/issues/2219), [#2778](https://github.com/glideapps/quicktype/issues/2778)
- LinkML generators: https://linkml.io/linkml/generators/
- Smoke test: datamodel-code-generator 0.71.0 + pydantic 2.13.4, run 2026-08-02 (schemas and generated output exercised at runtime: discriminated validation, extra='forbid' rejection, recursive nesting).
