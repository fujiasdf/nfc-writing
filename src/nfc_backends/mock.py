from __future__ import annotations

import time
import uuid

from .base import NfcWriter, WriteResult


class MockWriter(NfcWriter):
    """
    Simulates "tap to write" by waiting a short moment.
    Useful for validating CSV/flow/auto-advance without hardware.
    """

    def __init__(self, tap_delay_s: float = 0.6, fail_every: int = 0):
        self._tap_delay_s = tap_delay_s
        self._fail_every = fail_every
        self._count = 0

    def _write(self, payload: str, timeout_s: float | None) -> WriteResult:
        self._count += 1
        time.sleep(self._tap_delay_s)
        if self._fail_every and (self._count % self._fail_every == 0):
            return WriteResult(ok=False, message="Mock failure (configured).")
        return WriteResult(ok=True, message=f"Written: {payload[:32]}", tag_id=str(uuid.uuid4()))

    def write_uri(self, uri: str, *, timeout_s: float | None = None) -> WriteResult:
        return self._write(uri, timeout_s)

    def write_text(self, text: str, *, timeout_s: float | None = None) -> WriteResult:
        return self._write(text, timeout_s)

