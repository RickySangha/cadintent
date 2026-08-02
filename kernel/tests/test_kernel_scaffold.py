"""Scaffold smoke tests: generated types import and validate against the schemas."""

import json
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cadintent.generated import common

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "spec" / "schemas"


def test_schemas_are_valid_2020_12() -> None:
    for schema_path in SCHEMAS_DIR.glob("*.json"):
        schema = json.loads(schema_path.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)


def test_generated_point_round_trips() -> None:
    p = common.Point(x=1.5, y=-2.0)
    assert common.Point.model_validate(p.model_dump()) == p


def test_generated_point_forbids_extras() -> None:
    with pytest.raises(Exception):
        common.Point.model_validate({"x": 0, "y": 0, "z": 0})


@given(x=st.floats(allow_nan=False, allow_infinity=False), y=st.floats(allow_nan=False, allow_infinity=False))
def test_generated_matches_schema(x: float, y: float) -> None:
    """Whatever the generated model accepts, the source schema accepts too."""
    schema = json.loads((SCHEMAS_DIR / "common.json").read_text())
    payload = common.Point(x=x, y=y).model_dump()
    jsonschema.validate(payload, {**schema["$defs"]["Point"], "$defs": schema["$defs"]})
