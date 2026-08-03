"""The cadintent CLI (#34): validate / submit / fold / diff / check (+ render stub).

The whole surface is one sentence (#30): canonical bytes on stdout, human
prose on stderr, outcomes in the exit code.

- I/O: positional file paths in; the verb's canonical JSON document on stdout
  by default; ``-o <path>`` writes the same bytes to a file instead,
  atomically (temp + rename), and stdout then carries nothing. ``-`` reads any
  read-only argument from stdin (at most one per invocation) — never
  ``submit``'s log, which is extended in place atomically and left
  byte-identical on refusal. No default output directories, no TTY-dependent
  behavior, no ``--format`` flag.
- Exit table: 0 clean; 1 findings (validate errors, check findings incl.
  visible not-run); 2 refusal (submit only — nothing landed); 3 stale /
  could-not-run (with the re-index hint on stderr); 64 usage (click's default
  usage exit of 2 is explicitly overridden — 2 means refusal only); 70
  internal error (one-line summary, no traceback by default).
- stderr: human rendering of every typed outcome — one line per
  error/finding (``code  cmd#N  field.path — message``) plus counts and any
  hint. ``--quiet`` suppresses the stderr summary; nothing suppresses the
  stdout document.

Within-contract choices made here (documented on #34): ``check`` takes a
snapshot (per #30 decision 7 — snapshot-consuming verbs verify schema + spec
stamp, exit 3 on mismatch, and take no log argument); a registry artifact that
fails hash/schema trust (``RegistryError``) is could-not-run (exit 3), while a
file that is not parseable JSON at all is usage (exit 64).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from typing import Any, Optional

import typer

try:  # typer >= 0.16 vendors click as typer._click; raise/catch the one it uses
    from typer._click import exceptions as click_exc
except ImportError:  # pragma: no cover — older typer drives standalone click
    from click import exceptions as click_exc

from . import canonical
from .checks import run_checks
from .diff import diff_bytes
from .fold import FoldHalt
from .registry import RegistryError, RegistryStore
from .snapshot import (
    StaleSnapshot,
    fold_from,
    model_from_doc,
    snapshot_bytes,
    verify_snapshot,
)
from .spec import SPEC_VERSION
from .submit import Refused, submit as kernel_submit, validate_submission

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_REFUSAL = 2
EXIT_STALE = 3
EXIT_USAGE = 64
EXIT_INTERNAL = 70

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)

_OUTPUT_HELP = "Write the canonical output document to this file (atomic) instead of stdout."
_QUIET_HELP = "Suppress the human stderr summary (the stdout document is never suppressed)."


# ---------------------------------------------------------------------------
# Plumbing


class _CouldNotRun(Exception):
    """Exit-3 class: the verb could not legitimately do its job."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class _Stdin:
    """Tracks the at-most-one-'-'-per-invocation rule."""

    def __init__(self) -> None:
        self.used = False

    def read(self) -> bytes:
        if self.used:
            raise click_exc.UsageError(
                "at most one argument may be '-' (stdin) per invocation"
            )
        self.used = True
        return sys.stdin.buffer.read()


def _single_dash(*paths: Optional[str]) -> _Stdin:
    """Enforce at-most-one '-' up front; returns the invocation's stdin guard."""
    if sum(1 for path in paths if path == "-") > 1:
        raise click_exc.UsageError(
            "at most one argument may be '-' (stdin) per invocation"
        )
    return _Stdin()


def _read_bytes(path: str, what: str, stdin: _Stdin) -> bytes:
    if path == "-":
        return stdin.read()
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise click_exc.UsageError(f"cannot read {what} {path!r}: {exc.strerror or exc}")


def _parse_json(raw: bytes, path: str, what: str) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise click_exc.UsageError(f"{what} {path!r} is not parseable JSON: {exc}")


def _read_json(path: str, what: str, stdin: _Stdin) -> Any:
    return _parse_json(_read_bytes(path, what, stdin), path, what)


def _read_log(path: str, stdin: _Stdin) -> list[dict[str, Any]]:
    doc = _read_json(path, "log", stdin)
    if not isinstance(doc, list):
        raise click_exc.UsageError(
            f"log {path!r} must be a JSON array of envelope-complete commands"
        )
    return doc


def _load_snapshot(path: str, what: str, stdin: _Stdin) -> tuple[bytes, dict[str, Any]]:
    """Read + parse a snapshot and verify its spec stamp (#30 decision 7)."""
    raw = _read_bytes(path, what, stdin)
    doc = _parse_json(raw, path, what)
    if not isinstance(doc, dict) or "spec" not in doc:
        raise _CouldNotRun("stale_snapshot", f"{what} {path!r} carries no spec stamp")
    if doc["spec"] != SPEC_VERSION:
        raise _CouldNotRun(
            "stale_snapshot",
            f"{what} {path!r} has spec stamp {doc['spec']!r} but the supported "
            f"spec is {SPEC_VERSION!r}",
        )
    return raw, doc


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cadintent-tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _emit(document_bytes: bytes, output: Optional[str]) -> None:
    if output is None:
        sys.stdout.buffer.write(document_bytes)
        sys.stdout.buffer.flush()
    else:
        _atomic_write(output, document_bytes)


def _say(quiet: bool, line: str) -> None:
    if not quiet:
        sys.stderr.write(line + "\n")


def _render_errors(errors: list[dict[str, Any]], quiet: bool, noun: str = "error") -> None:
    for error in errors:
        where = "-" if error.get("command") is None else f"cmd#{error['command']}"
        _say(
            quiet,
            f"{error['code']}  {where}  {error.get('path') or '/'} — {error['message']}",
        )
    plural = "" if len(errors) == 1 else "s"
    _say(quiet, f"{len(errors)} {noun}{plural}")


@contextmanager
def _typed_failures(quiet: bool, output: Optional[str]):
    """Render exit-3 typed outcomes twice (JSON document + stderr line)."""

    def fail(code: int, error: dict[str, Any], line: str) -> None:
        _emit(canonical.canonical_bytes({"spec": SPEC_VERSION, "error": error}), output)
        _say(quiet, line)
        raise typer.Exit(code)

    try:
        yield
    except FoldHalt as exc:
        fail(
            EXIT_STALE,
            {"code": exc.code, "seq": exc.seq, "message": exc.message},
            f"{exc.code}  seq#{exc.seq} — {exc.message}",
        )
    except StaleSnapshot as exc:
        fail(
            EXIT_STALE,
            {"code": exc.code, "message": exc.message},
            f"{exc.code} — {exc.message}",
        )
    except RegistryError as exc:
        fail(
            EXIT_STALE,
            {"code": exc.code, "message": exc.message},
            f"{exc.code} — {exc.message}",
        )
    except _CouldNotRun as exc:
        fail(
            EXIT_STALE,
            {"code": exc.code, "message": exc.message},
            f"{exc.code} — {exc.message}; re-run `cadintent fold` to regenerate",
        )


# ---------------------------------------------------------------------------
# Verbs


@app.command()
def validate(
    document: str = typer.Argument(..., help="Submission JSON file, or '-' for stdin."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUTPUT_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_QUIET_HELP),
) -> None:
    """Schema-check a submission document without touching any log."""
    doc = _read_json(document, "document", _single_dash(document))
    errors = validate_submission(doc)
    _emit(canonical.canonical_bytes({"spec": SPEC_VERSION, "errors": errors}), output)
    if errors:
        _render_errors(errors, quiet, noun="validation error")
        raise typer.Exit(EXIT_FINDINGS)


@app.command()
def submit(
    log: str = typer.Argument(..., help="Log file (extended in place; never '-')."),
    submission: str = typer.Argument(..., help="Submission JSON file, or '-' for stdin."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUTPUT_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_QUIET_HELP),
) -> None:
    """Apply one submission: extend the log, or refuse totally (exit 2)."""
    if log == "-":
        raise click_exc.UsageError(
            "submit's log must be a real file path (it is rewritten in place), not '-'"
        )
    stdin = _single_dash(submission)
    entries = _read_log(log, stdin)
    doc = _read_json(submission, "submission", stdin)
    with _typed_failures(quiet, output):
        result = kernel_submit(entries, doc)
    if isinstance(result, Refused):
        _emit(
            canonical.canonical_bytes({"spec": SPEC_VERSION, **result.refusal}), output
        )
        _render_errors(result.refusal["errors"], quiet, noun="refusal error")
        _say(quiet, "refused: nothing landed; the log is byte-identical")
        raise typer.Exit(EXIT_REFUSAL)
    _atomic_write(log, canonical.canonical_bytes(result.log))
    receipt = {
        "spec": SPEC_VERSION,
        "project": doc.get("project") if isinstance(doc, dict) else None,
        "batch": result.batch,
        "head": len(result.log),
        "accepted": len(result.log) - len(entries),
    }
    _emit(canonical.canonical_bytes(receipt), output)


@app.command()
def fold(
    log: str = typer.Argument(..., help="Log file, or '-' for stdin."),
    from_snapshot: Optional[str] = typer.Option(
        None,
        "--from-snapshot",
        help="Resume from this snapshot (verified; output byte-equals full replay).",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUTPUT_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_QUIET_HELP),
) -> None:
    """Emit the canonical snapshot of a log."""
    stdin = _single_dash(log, from_snapshot)
    entries = _read_log(log, stdin)
    with _typed_failures(quiet, output):
        if from_snapshot is None:
            document_bytes = snapshot_bytes(entries)
        else:
            raw = _read_bytes(from_snapshot, "snapshot", stdin)
            _parse_json(raw, from_snapshot, "snapshot")  # unparseable JSON is usage
            doc = verify_snapshot(raw, entries)
            document_bytes = fold_from(raw, entries[doc["head"] :])
    _emit(document_bytes, output)


@app.command()
def diff(
    snap_a: str = typer.Argument(..., help="Snapshot A (before), or '-' for stdin."),
    snap_b: str = typer.Argument(..., help="Snapshot B (after), or '-' for stdin."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUTPUT_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_QUIET_HELP),
) -> None:
    """Emit the canonical field-level diff between two snapshots."""
    stdin = _single_dash(snap_a, snap_b)
    with _typed_failures(quiet, output):
        raw_a, _ = _load_snapshot(snap_a, "snapshot A", stdin)
        raw_b, _ = _load_snapshot(snap_b, "snapshot B", stdin)
        document_bytes = diff_bytes(raw_a, raw_b)
    _emit(document_bytes, output)


@app.command()
def check(
    snapshot: str = typer.Argument(..., help="Snapshot file, or '-' for stdin."),
    registry: Optional[list[str]] = typer.Option(
        None,
        "--registry",
        help="Rule-registry artifact JSON to load (repeatable; hash-checked).",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=_OUTPUT_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_QUIET_HELP),
) -> None:
    """Run pack checks over a snapshot; findings (incl. visible not-run) exit 1."""
    stdin = _single_dash(snapshot, *(registry or []))
    with _typed_failures(quiet, output):
        _, doc = _load_snapshot(snapshot, "snapshot", stdin)
        store = RegistryStore()
        for path in registry or []:
            store.add(_read_json(path, "registry artifact", stdin))
        run = run_checks(model_from_doc(doc), store)
    _emit(canonical.canonical_bytes(run), output)
    non_clean = [r for r in run["results"] if r["status"] != "pass"]
    if not non_clean:
        return
    findings = 0
    for result in non_clean:
        line = f"{result['check']}  {result['status']}"
        if result.get("reason"):
            line += f" — {result['reason']}"
        _say(quiet, line)
        for finding in result["findings"]:
            findings += 1
            subjects = ",".join(finding["subjects"]) or "-"
            _say(quiet, f"{finding['check']}  {subjects} — {finding['message']}")
    _say(
        quiet,
        f"{findings} finding{'' if findings == 1 else 's'}; "
        f"{len(non_clean)} of {len(run['results'])} checks not clean",
    )
    raise typer.Exit(EXIT_FINDINGS)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def render(ctx: typer.Context) -> None:
    """Render a snapshot to DXF — not yet implemented (deferred build issue)."""
    raise click_exc.UsageError(
        "render is not yet implemented (deferred to the DXF backend build issue)"
    )


# ---------------------------------------------------------------------------
# Entry point: pin the exit table (usage is 64, never click's default 2)


def main() -> None:
    try:
        code = app(standalone_mode=False)
        raise SystemExit(code if isinstance(code, int) else 0)
    except click_exc.Exit as exc:
        raise SystemExit(exc.exit_code)
    except click_exc.ClickException as exc:  # UsageError included
        sys.stderr.write(f"usage error: {exc.format_message()}\n")
        raise SystemExit(EXIT_USAGE)
    except click_exc.Abort:
        sys.stderr.write("aborted\n")
        raise SystemExit(EXIT_USAGE)
    except Exception as exc:  # noqa: BLE001 — the 70 boundary
        sys.stderr.write(f"internal error: {type(exc).__name__}: {exc}\n")
        raise SystemExit(EXIT_INTERNAL)


if __name__ == "__main__":
    main()
