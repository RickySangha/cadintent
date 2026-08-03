"""The external DXFIN oracle — an opt-in local hook, never claimed in CI.

Per #24 decision 5, the real-AutoCAD DXFIN round-trip (accoreconsole) is
specified as an opt-in local verification step. The contract here is
could-not-run visibility: when the hook is not configured it reports
``skipped`` with the reason; when configured but the run fails it reports
``could_not_run`` — never a pass. CI never invokes this with the env var
set, so CI never claims more than the ezdxf library round-trip proves.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any

ENV_VAR = "CADINTENT_ACCORECONSOLE"

_SCRIPT = "DXFIN\n{path}\nQUIT\nY\n"


def external_oracle(dxf_path: str, timeout: float = 120.0) -> dict[str, Any]:
    """Attempt the accoreconsole DXFIN round-trip on ``dxf_path``.

    Returns {status: skipped | ran | could_not_run, ...}. ``skipped`` carries
    the opt-in reason; ``could_not_run`` is reported visibly, never a pass.
    """
    exe = os.environ.get(ENV_VAR)
    if not exe:
        return {
            "status": "skipped",
            "reason": (
                f"external DXFIN oracle not configured: set {ENV_VAR} to the "
                "accoreconsole executable to opt in (local only; never "
                "claimed in CI)"
            ),
        }
    script = tempfile.NamedTemporaryFile(
        "w", suffix=".scr", delete=False, encoding="utf-8"
    )
    try:
        script.write(_SCRIPT.format(path=os.path.abspath(dxf_path)))
        script.close()
        proc = subprocess.run(
            [exe, "/s", script.name],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "could_not_run",
            "reason": f"accoreconsole invocation failed: {exc}",
        }
    finally:
        try:
            os.unlink(script.name)
        except OSError:
            pass
    return {
        "status": "ran",
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout.decode(errors="replace")[-2000:],
    }
