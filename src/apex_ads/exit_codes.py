"""Process exit codes. Part of the contract — see spec §15.1.

CI, schedulers and humans all key off these. `OK` means "importable"; nothing else does.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for every `apex` command."""

    OK = 0
    """Success — a READY build. Warnings may exist."""

    BLOCKER = 2
    """A validation BLOCKER. No deployable output was produced."""

    ERROR = 3
    """Unexpected error. Traceback in logs/<run_id>.log; partial output removed."""

    DRIFT = 4
    """Drift check found CRITICAL drift."""

    BAD_INVOCATION = 5
    """Missing file, unreadable config, unknown argument, unimplemented command."""

    DRAFT = 6
    """No BLOCKERs, but URL validation was incomplete. Quarantined, not deployable."""
