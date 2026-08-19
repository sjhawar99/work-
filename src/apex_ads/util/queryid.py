"""The keyed identifier for a search query (Phase-6 task zero).

A query handle has to satisfy two things at once, and they pull against each other:

    the same normalised query next Friday  →  the same ID   (recurrence is detectable)
    somebody holding findings.json         →  cannot test   (no dictionary confirmation)
                                              likely medical phrases

A plain truncated SHA-256 gives the first and fails the second: anybody with a report can
hash `kidney failure last stage how long to live` and check whether that handle appears.
For healthcare queries the guessable space is small enough that this is a real disclosure,
not a theoretical one.

An HMAC under **one stable local secret** gives both. Not a rotating weekly key — rotation
would break recurrence detection, which is the entire point of the Watchdog comparing one
Friday to the next.

**Operating dependency, stated plainly.** The secret lives in a git-ignored file outside
the repository's tracked tree and never appears in a report, a manifest, a log or a
dashboard. If it is lost, IDs generated afterwards no longer join to historical ones.
That is acceptable and is the documented cost of the property above: back the file up
alongside the workbook, or accept that history stops joining on the day it is lost.

The manifest records a **fingerprint** of the key — a hash of the key, not the key — so a
later reader can tell whether two runs are comparable without being handed the secret.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from apex_ads.util.text import tokenise

KEY_FILENAME = "query_id.key"
KEY_DIRNAME = ".apex_secrets"
"""Git-ignored, and deliberately not inside `config/`.

`config/` is committed. A secret in a committed directory survives only as long as nobody
runs `git add -A` with a stale ignore file, and this project has a person who is not a
developer running the commands.
"""

KEY_BYTES = 32
ID_CHARS = 12
ID_PREFIX = "q"
"""Non-numeric on purpose: an all-digit handle gets masked by `redact()` as phone-shaped,
which silently collapses distinct queries to one string in a log."""

FINGERPRINT_CHARS = 12


class QueryKeyError(Exception):
    """The identifier key could not be read or created."""


def normalise_query(text: str) -> str:
    """The canonical form an ID is computed over.

    Keying is only half of stability — two exports writing `Knee  Replacement` and
    `knee replacement` must produce one handle, or recurrence detection silently misses
    the recurrence it exists to find. Reuses the compiler's tokeniser so the Watchdog and
    the collision engine agree on what "the same term" means.
    """
    return " ".join(tokenise(text))


@dataclass(frozen=True)
class QueryIdKey:
    """A loaded secret, and the two things anybody is allowed to do with it."""

    _secret: bytes
    path: Path

    def identify(self, text: str) -> str:
        """The stable, keyed, non-guessable handle for one query."""
        digest = hmac.new(self._secret, normalise_query(text).encode("utf-8"), hashlib.sha256)
        return ID_PREFIX + digest.hexdigest()[:ID_CHARS]

    @property
    def fingerprint(self) -> str:
        """Identifies the key without disclosing it, so runs can be compared.

        A hash of the secret under a fixed label — safe to print in a manifest, useless
        for computing a query handle.
        """
        digest = hashlib.sha256(b"apex-query-id-key-fingerprint\x00" + self._secret)
        return digest.hexdigest()[:FINGERPRINT_CHARS]

    def __repr__(self) -> str:
        """Never render the secret. This object ends up in tracebacks."""
        return f"QueryIdKey(fingerprint={self.fingerprint!r}, path={str(self.path)!r})"


def default_key_path(repo_root: Path) -> Path:
    return repo_root / KEY_DIRNAME / KEY_FILENAME


def load_or_create(path: Path) -> tuple[QueryIdKey, bool]:
    """Read the secret, creating one on first use. Returns `(key, created)`.

    Created rather than demanded because the alternative is an operator who cannot run the
    Watchdog on Friday until somebody explains key management to them. The run prints a
    one-line notice the first time, naming the file to back up.
    """
    if path.exists():
        raw = path.read_bytes().strip()
        if len(raw) < KEY_BYTES * 2:  # hex of KEY_BYTES
            raise QueryKeyError(
                f"{path} does not contain a usable key (expected {KEY_BYTES * 2} hex "
                "characters). Delete the file to have a new one generated — note that "
                "query IDs generated afterwards will not join to older reports."
            )
        return QueryIdKey(_secret=bytes.fromhex(raw.decode("ascii")), path=path), False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(KEY_BYTES)
        path.write_text(secret.hex(), encoding="ascii")
        # Owner-only. Best-effort: Windows ignores the mode, and a failure here must not
        # stop a Friday review.
        with contextlib.suppress(OSError):
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        raise QueryKeyError(f"cannot create the query-ID key at {path}: {exc}") from exc

    return QueryIdKey(_secret=secret, path=path), True


def key_notice(key: QueryIdKey) -> str:
    """What to tell the operator the first time a key is generated."""
    return (
        f"A new query-ID key was created at {key.path}.\n"
        "  It is not in git, and it is not in any report. Back it up alongside the\n"
        "  workbook. Without it, next week's report cannot be matched to this one —\n"
        "  the same search term would get a different ID."
    )


def has_key_material(text: str, key: QueryIdKey) -> bool:
    """True if a rendered string contains the secret. Used by the guardrail tests."""
    return key._secret.hex() in text


def _env_override() -> str | None:
    """`APEX_QUERY_ID_KEY` — for CI and tests, never for the operator's machine."""
    return os.environ.get("APEX_QUERY_ID_KEY")


def resolve(repo_root: Path, path: Path | None = None) -> tuple[QueryIdKey, bool]:
    """The key this run should use: explicit path, then env, then the default file."""
    override = _env_override()
    if override:
        raw = override.strip()
        if len(raw) < KEY_BYTES * 2:
            raise QueryKeyError(
                f"APEX_QUERY_ID_KEY must be at least {KEY_BYTES * 2} hex characters; got {len(raw)}"
            )
        return QueryIdKey(_secret=bytes.fromhex(raw), path=Path("$APEX_QUERY_ID_KEY")), False
    return load_or_create(path or default_key_path(repo_root))
