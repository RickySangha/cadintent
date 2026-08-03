"""cadintent kernel: validate / fold / diff over design-intent command streams."""

from .canonical import canonical_bytes, extend_log_hash, log_hash
from .checks import run_checks
from .diff import diff_bytes, diff_doc, empty_diff_bytes
from .fold import ApplyError, FoldHalt, Model, fold
from .registry import RegistryError, RegistryStore, ResolvedRule, artifact_hash
from .snapshot import (
    StaleSnapshot,
    fold_from,
    model_from_doc,
    snapshot_bytes,
    snapshot_doc,
    verify_snapshot,
)
from .spec import SPEC_VERSION
from .submit import Accepted, Refused, submit, validate_submission

__version__ = "0.0.1"

__all__ = [
    "Accepted",
    "ApplyError",
    "FoldHalt",
    "Model",
    "Refused",
    "RegistryError",
    "RegistryStore",
    "ResolvedRule",
    "SPEC_VERSION",
    "StaleSnapshot",
    "artifact_hash",
    "canonical_bytes",
    "diff_bytes",
    "diff_doc",
    "empty_diff_bytes",
    "extend_log_hash",
    "fold",
    "fold_from",
    "log_hash",
    "model_from_doc",
    "run_checks",
    "snapshot_bytes",
    "snapshot_doc",
    "submit",
    "validate_submission",
    "verify_snapshot",
]
