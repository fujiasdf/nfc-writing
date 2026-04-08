from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    message: str = ""
    tag_id: str | None = None


class NfcWriter:
    """
    Backend interface.
    A real backend should block until a tag is presented (or timeout),
    then write NDEF and return result.
    """

    def write_uri(self, uri: str, *, timeout_s: float | None = None) -> WriteResult:  # pragma: no cover
        raise NotImplementedError

    def write_text(self, text: str, *, timeout_s: float | None = None) -> WriteResult:  # pragma: no cover
        raise NotImplementedError

