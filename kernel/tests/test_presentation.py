"""Presentation-pack resolution (#22 decision 8): nearest-first whole-entry
replacement, single-pack attribution, disabled suppression, hash trust."""

from __future__ import annotations

from typing import Any

import pytest

from cadintent.fold import Model
from cadintent.presentation import PackStore, PresentationError, pack_hash


def style(name: str, layer: str = "V-NODE-TEXT") -> dict[str, Any]:
    return {
        "name": name,
        "layer": layer,
        "font": "isocp.shx",
        "height": "2.5",
        "width_factor": "1",
        "justification": "middle_center",
        "rotation": "0",
    }


def pack(pack_id: str, version: str = "1.0.0", **parts: Any) -> dict[str, Any]:
    return {"id": pack_id, "version": version, **parts}


def model_importing(*packs: dict[str, Any]) -> Model:
    """A model whose presentation imports pin ``packs`` in the given log
    order (the last import is nearest)."""
    model = Model(project="0" * 26, head=len(packs))
    for seq, doc in enumerate(packs, start=1):
        model.imports.append(
            {
                "seq": seq,
                "family": "presentation",
                "value": {
                    "id": doc["id"],
                    "version": doc["version"],
                    "content_hash": pack_hash(doc),
                },
            }
        )
    return model


def loaded(*packs: dict[str, Any]) -> PackStore:
    store = PackStore()
    for doc in packs:
        store.add(doc)
    return store


def test_no_import_is_missing_declaration():
    with pytest.raises(PresentationError) as exc:
        PackStore().resolve(Model())
    assert exc.value.code == "missing_declaration"


def test_imported_but_not_loaded_is_unresolvable():
    office = pack("office", text_styles=[style("note")])
    with pytest.raises(PresentationError) as exc:
        PackStore().resolve(model_importing(office))
    assert exc.value.code == "unresolvable_pack"


def test_hash_mismatch_refuses():
    office = pack("office", text_styles=[style("note")])
    model = model_importing(office)
    tampered = pack("office", text_styles=[style("note", layer="OTHER")])
    with pytest.raises(PresentationError) as exc:
        loaded(tampered).resolve(model)
    assert exc.value.code == "pack_hash_mismatch"


def test_invalid_artifact_is_schema_violation():
    with pytest.raises(PresentationError) as exc:
        PackStore().add({"id": "x"})
    assert exc.value.code == "schema_violation"


def test_nearest_entry_wins_whole_entry_and_is_attributed():
    office = pack("office", text_styles=[style("note", layer="OFFICE")])
    project = pack("project", text_styles=[style("note", layer="PROJECT")])
    # office imported first, project last: project is nearest.
    resolved = loaded(office, project).resolve(model_importing(office, project))
    entry = resolved.text_styles["note"]
    assert entry.entry["layer"] == "PROJECT"  # whole-entry replacement
    assert entry.pack.id == "project"  # attributable to exactly one pack
    assert [ref.id for ref in resolved.packs] == ["project", "office"]


def test_farther_entries_survive_where_not_overridden():
    office = pack("office", text_styles=[style("note"), style("title")])
    project = pack("project", text_styles=[style("note", layer="PROJECT")])
    resolved = loaded(office, project).resolve(model_importing(office, project))
    assert resolved.text_styles["title"].pack.id == "office"


def test_disabled_suppresses_farther_entry():
    office = pack("office", text_styles=[style("note")])
    project = pack("project", text_styles=[{"name": "note", "disabled": True}])
    resolved = loaded(office, project).resolve(model_importing(office, project))
    assert "note" not in resolved.text_styles


def test_ordered_lists_resolve_wholesale_nearest_first():
    linework = [{"when": {"kind": "civil.conduit"}, "layer": "OFFICE-PIPE"}]
    office = pack("office", linework=linework)
    project = pack(
        "project",
        linework=[{"when": {"kind": "civil.conduit"}, "layer": "PROJECT-PIPE"}],
    )
    resolved = loaded(office, project).resolve(model_importing(office, project))
    ref, entries = resolved.linework
    assert ref.id == "project" and entries[0]["layer"] == "PROJECT-PIPE"
    # a nearer pack without the list falls through to the farther one
    bare = pack("bare", version="2.0.0")
    resolved = loaded(office, bare).resolve(model_importing(office, bare))
    ref, entries = resolved.linework
    assert ref.id == "office" and entries[0]["layer"] == "OFFICE-PIPE"
