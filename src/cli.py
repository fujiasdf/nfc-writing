from __future__ import annotations

import sys
import time

from .csv_queue import load_csv
from .nfc_backends.base import NfcWriter
from .nfc_backends.mock import MockWriter
from .nfc_backends.springcore_pcsc import PcscConfig, SpringCorePcscWriter
from .sound import beep_error, beep_ok


def _make_writer(*, mock: bool, pcsc: bool, reader_contains: str) -> NfcWriter:
    if mock:
        return MockWriter(tap_delay_s=0.1)
    if pcsc:
        return SpringCorePcscWriter(PcscConfig(reader_name_contains=reader_contains))
    raise RuntimeError("実機モードが指定されていません（--pcsc を付けてください）")


def run_cli(*, csv_path: str, mock: bool, pcsc: bool = False, reader_contains: str = "") -> int:
    items = load_csv(csv_path)
    writer = _make_writer(mock=mock, pcsc=pcsc, reader_contains=reader_contains)

    print(f"Loaded {len(items)} rows from {csv_path}")
    if mock:
        print("Enterキーで「タグをかざした」扱い（モック）。Ctrl+Cで終了。")
    else:
        print("タグをかざすと書き込みます。Ctrl+Cで終了。")

    cursor = 0
    while cursor < len(items):
        it = items[cursor]
        if mock:
            try:
                input(f"[{cursor+1}/{len(items)}] {it.type} {it.payload} > tap then press Enter ")
            except (KeyboardInterrupt, EOFError):
                print("\nStopped.")
                return 130
        else:
            print(f"[{cursor+1}/{len(items)}] {it.type} {it.payload} > waiting for tag...")

        try:
            if it.type == "uri":
                res = writer.write_uri(it.payload, timeout_s=None)
            else:
                res = writer.write_text(it.payload, timeout_s=None)
        except Exception as e:
            beep_error()
            print(f"ERROR: {e}", file=sys.stderr)
            time.sleep(0.1)
            continue

        if res.ok:
            beep_ok()
            tid = f" tag={res.tag_id}" if res.tag_id else ""
            print(f"OK: {res.message}{tid}")
            cursor += 1
        else:
            beep_error()
            print(f"NG: {res.message} (retry same row)")

    print("Done.")
    return 0

