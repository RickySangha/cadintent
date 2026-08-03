"""Core spec schemas: 2020-12 validity, golden samples, and generated types."""

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from cadintent.generated import commands, envelope, refusal, submission

SPEC_VERSION = "0.1.0"
SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "spec" / "schemas"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

SCHEMA_PATHS = sorted(SCHEMAS_DIR.glob("*.json"))
GOLDEN_PATHS = sorted(GOLDEN_DIR.glob("*.json"))

REGISTRY = Registry().with_resources(
    (path.name, Resource.from_contents(json.loads(path.read_text())))
    for path in SCHEMA_PATHS
)


@pytest.mark.parametrize("schema_path", SCHEMA_PATHS, ids=lambda p: p.name)
def test_schema_is_valid_2020_12(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("schema_path", SCHEMA_PATHS, ids=lambda p: p.name)
def test_schema_carries_spec_version(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    assert schema["x-cadintent-spec-version"] == SPEC_VERSION


def test_every_schema_has_golden_valid_and_invalid_samples() -> None:
    covered = {
        (json.loads(p.read_text())["schema"], json.loads(p.read_text())["valid"])
        for p in GOLDEN_PATHS
    }
    for schema_path in SCHEMA_PATHS:
        assert (schema_path.name, True) in covered, f"no valid golden for {schema_path.name}"
        assert (schema_path.name, False) in covered, f"no invalid golden for {schema_path.name}"


@pytest.mark.parametrize("golden_path", GOLDEN_PATHS, ids=lambda p: p.name)
def test_golden_sample(golden_path: Path) -> None:
    case = json.loads(golden_path.read_text())
    validator = jsonschema.Draft202012Validator(
        {"$ref": f"{case['schema']}{case['ref']}"}, registry=REGISTRY
    )
    errors = list(validator.iter_errors(case["document"]))
    if case["valid"]:
        assert not errors, f"expected valid, got: {[e.message for e in errors]}"
    else:
        assert errors, "expected the document to fail validation, but it passed"


def test_generated_envelope_round_trips() -> None:
    doc = json.loads((GOLDEN_DIR / "envelope.valid.json").read_text())["document"]
    model = envelope.Envelope.model_validate(doc)
    assert envelope.Envelope.model_validate(
        json.loads(model.model_dump_json())
    ) == model


def test_generated_envelope_forbids_extras() -> None:
    doc = json.loads((GOLDEN_DIR / "envelope.valid.json").read_text())["document"]
    with pytest.raises(Exception):
        envelope.Envelope.model_validate({**doc, "extra_field": 1})


def test_generated_submission_accepts_golden() -> None:
    doc = json.loads((GOLDEN_DIR / "submission.valid.json").read_text())["document"]
    model = submission.Submission.model_validate(doc)
    assert model.head == 0
    assert len(model.commands) == 2


def test_generated_refusal_accepts_golden() -> None:
    doc = json.loads((GOLDEN_DIR / "refusal.valid.json").read_text())["document"]
    model = refusal.Refusal.model_validate(doc)
    assert model.errors[0].code == refusal.RefusalCode.stale_head
    assert model.errors[0].command is None


def test_refusal_code_list_is_the_closed_thirteen() -> None:
    assert {c.value for c in refusal.RefusalCode} == {
        "stale_head",
        "schema_violation",
        "unknown_kind",
        "author_role_violation",
        "id_collision",
        "unknown_reference",
        "name_collision",
        "missing_basis",
        "scope_violation",
        "spec_unsupported",
        "dangling_reference",
        "missing_declaration",
        "immutable_declaration",
    }


def test_generated_discriminated_payloads() -> None:
    units = commands.ProjectUnitsPayload.model_validate(
        {"system": {"kind": "imperial", "foot": "us_survey"}}
    )
    assert units.system.root.kind == "imperial"
    with pytest.raises(Exception):
        commands.ProjectUnitsPayload.model_validate({"system": {"kind": "imperial"}})
