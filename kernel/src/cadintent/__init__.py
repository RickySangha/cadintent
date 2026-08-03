"""cadintent kernel: validate / fold / diff over design-intent command streams."""

from .canonical import canonical_bytes, log_hash
from .fold import ApplyError, FoldHalt, Model, fold
from .snapshot import snapshot_bytes, snapshot_doc
from .spec import SPEC_VERSION
from .submit import Accepted, Refused, submit, validate_submission

__version__ = "0.0.1"

__all__ = [
    "Accepted",
    "ApplyError",
    "FoldHalt",
    "Model",
    "Refused",
    "SPEC_VERSION",
    "canonical_bytes",
    "fold",
    "log_hash",
    "snapshot_bytes",
    "snapshot_doc",
    "submit",
    "validate_submission",
]
