# cadintent workspace targets. Requires uv (https://docs.astral.sh/uv/).

CODEGEN_FLAGS = --input spec/schemas --input-file-type jsonschema \
	--output-model-type pydantic_v2.BaseModel \
	--target-python-version 3.12 --use-annotated --enum-field-as-literal one \
	--formatters black --disable-timestamp

.PHONY: sync codegen codegen-check test

sync:
	uv sync --all-packages

# Regenerate pydantic types from spec/schemas (output is committed).
codegen:
	uv run datamodel-codegen $(CODEGEN_FLAGS) --output kernel/src/cadintent/generated

# Fail if committed generated code is out of date with spec/schemas (for CI).
codegen-check:
	rm -rf .codegen-check
	uv run datamodel-codegen $(CODEGEN_FLAGS) --output .codegen-check
	diff -r .codegen-check kernel/src/cadintent/generated
	rm -rf .codegen-check

test:
	uv run pytest -q
