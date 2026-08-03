"""Shared helpers + the fixed hypothesis profile (deterministic in CI)."""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, settings

# Fixed profile per #32: property tests run in CI deterministically.
settings.register_profile(
    "cadintent",
    derandomize=True,
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("cadintent")

SPEC = "0.1.0"
ENGINEER = "engineer:ricky"


def ulid(n: int, tag: str = "") -> str:
    """A deterministic valid ULID from a small integer."""
    from cadintent.ulid import encode

    return encode(n)


def command(
    kind: str,
    payload: dict[str, Any],
    author: str = ENGINEER,
    basis: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "author": author,
        "kind": kind,
        "payload": payload,
        "basis": basis or [],
        "spec": SPEC,
    }


def submission(
    project: str,
    head: int,
    commands: list[dict[str, Any]],
    scope: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "project": project,
        "head": head,
        "scope": scope or [{"kind": "project"}],
        "commands": commands,
    }


def units_command() -> dict[str, Any]:
    return command("project.units", {"system": {"kind": "metric"}})


def create_node(obj: str, x: str = "0.000", y: str = "0.000") -> dict[str, Any]:
    return command(
        "object.create",
        {
            "object": obj,
            "type": "civil.manhole",
            "geometry": {"kind": "point", "point": {"x": x, "y": y}},
        },
    )
