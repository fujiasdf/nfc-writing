from __future__ import annotations

import time
import typing
from dataclasses import dataclass, field

from .base import NfcWriter, WriteResult
from ..ndef import ndef_message_single, ndef_text, ndef_uri, tlv_ndef


def _to_hex(b: bytes) -> str:
    return b.hex().upper()


@dataclass
class PcscConfig:
    reader_name_contains: str = ""
    poll_interval_s: float = 0.2
    write_timeout_s: float | None = None
    wait_remove_after_write: bool = True
    remove_poll_interval_s: float = 0.2
    remove_timeout_s: float = 30.0
    forbid_uid_hex: str | None = None
    stop_check: "typing.Callable[[], bool] | None" = None


class SpringCorePcscWriter(NfcWriter):
    """
    PC/SC backend for SpringCard SpringCore readers (e.g., PUCK Base).

    Uses:
    - GET DATA (FF CA) to get NFC Forum tag type + UID
    - READ BINARY (FF B0) / UPDATE BINARY (FF D6) for Type 2 tags (4-byte pages)
    """

    def __init__(self, cfg: PcscConfig | None = None):
        self.cfg = cfg or PcscConfig()

        try:
            from smartcard.System import readers  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "pyscard が必要です。`pip install pyscard` が失敗する場合は "
                "Xcode Command Line Tools / swig / PCSC を整備してください。"
            ) from e

        self._readers_fn = readers

    def _select_reader(self):
        rs = self._readers_fn()
        if not rs:
            raise RuntimeError("PC/SC reader が見つかりません（未接続 or 権限/ドライバ問題）")
        for r in rs:
            if self.cfg.reader_name_contains.lower() in str(r).lower():
                return r
        # fallback to first
        return rs[0]

    def _stopped(self) -> bool:
        return self.cfg.stop_check is not None and self.cfg.stop_check()

    def _connect_wait(self):
        import sys
        from smartcard.scard import SCARD_PROTOCOL_T0, SCARD_PROTOCOL_T1
        reader = self._select_reader()
        print(f"[PCSC] _connect_wait: reader={reader}", file=sys.stderr, flush=True)

        deadline = None if self.cfg.write_timeout_s is None else (time.time() + self.cfg.write_timeout_s)
        attempt = 0
        while True:
            if self._stopped():
                raise RuntimeError("stopped")
            conn = reader.createConnection()
            try:
                conn.connect()
                # Verify the connection works by reading UID
                self._get_uid(conn)
                print(f"[PCSC] connected on attempt {attempt}", file=sys.stderr, flush=True)
                return conn
            except Exception as e:
                if attempt % 10 == 0:
                    print(f"[PCSC] connect attempt {attempt}: {e}", file=sys.stderr, flush=True)
                try:
                    conn.disconnect()
                except Exception:
                    pass
                attempt += 1
                if deadline is not None and time.time() > deadline:
                    raise TimeoutError("タグ待ちがタイムアウトしました")
                time.sleep(self.cfg.poll_interval_s)

    def _tx(self, conn, apdu: list[int]) -> tuple[bytes, int, int]:
        data, sw1, sw2 = conn.transmit(apdu)
        return bytes(data), sw1, sw2

    def _get_uid(self, conn) -> bytes:
        data, sw1, sw2 = self._tx(conn, [0xFF, 0xCA, 0x00, 0x00, 0x00])
        if (sw1, sw2) != (0x90, 0x00):
            raise RuntimeError(f"GET UID failed: {sw1:02X}{sw2:02X}")
        return data

    def _wait_tag_removed_or_changed(self, conn, uid: bytes) -> None:
        """
        Prevent repeated writes/beeps while the same tag stays on the reader.
        Wait until UID read fails (tag removed) or UID changes (different tag).
        """
        if not self.cfg.wait_remove_after_write:
            return

        deadline = None if self.cfg.remove_timeout_s is None else (time.time() + self.cfg.remove_timeout_s)
        while True:
            if self._stopped():
                return
            if deadline is not None and time.time() > deadline:
                return
            try:
                cur = self._get_uid(conn)
            except Exception:
                try:
                    conn.disconnect()
                except Exception:
                    pass
                return
            if cur != uid:
                return
            time.sleep(self.cfg.remove_poll_interval_s)

    def _get_nfc_forum_tag_type(self, conn) -> int:
        # Try SpringCard-specific command first
        data, sw1, sw2 = self._tx(conn, [0xFF, 0xCA, 0xF1, 0x01, 0x00])
        if (sw1, sw2) == (0x90, 0x00) and len(data) >= 1 and data[0] != 0:
            return data[0]
        # Fallback: detect Type 2 tag by reading CC at page 3
        try:
            cc = self._read_page4(conn, 3)
            if cc[0] == 0xE1:  # NDEF magic byte → Type 2 tag
                return 2
        except Exception:
            pass
        return 0

    def _read_page4(self, conn, page: int) -> bytes:
        # READ BINARY: FF B0 00 <page> <Le>
        data, sw1, sw2 = self._tx(conn, [0xFF, 0xB0, 0x00, page & 0xFF, 0x04])
        if (sw1, sw2) != (0x90, 0x00) or len(data) != 4:
            raise RuntimeError(f"READ page {page} failed: {sw1:02X}{sw2:02X}")
        return data

    def _read_pages(self, conn, start_page: int, num_bytes: int) -> bytes:
        """READ BINARY で複数ページ分を一括読み出し"""
        le = min(num_bytes, 0xFF)  # 最大255バイト
        data, sw1, sw2 = self._tx(conn, [0xFF, 0xB0, 0x00, start_page & 0xFF, le])
        if (sw1, sw2) != (0x90, 0x00):
            raise RuntimeError(f"READ pages from {start_page} failed: {sw1:02X}{sw2:02X}")
        return data

    def _write_page4(self, conn, page: int, buf4: bytes) -> None:
        if len(buf4) != 4:
            raise ValueError("buf4 must be 4 bytes")
        apdu = [0xFF, 0xD6, 0x00, page & 0xFF, 0x04] + list(buf4)
        _data, sw1, sw2 = self._tx(conn, apdu)
        if (sw1, sw2) != (0x90, 0x00):
            raise RuntimeError(f"WRITE page {page} failed: {sw1:02X}{sw2:02X}")

    def _type2_capacity(self, conn) -> int:
        # CC is in page 3 bytes 0..3; byte2 is data area size in 8-byte units.
        cc = self._read_page4(conn, 3)
        if cc[0] != 0xE1:
            # Not a formatted Type 2 tag (or unsupported)
            raise RuntimeError(f"Type2 CC missing/invalid (page3={_to_hex(cc)})")
        data_area = cc[2] * 8  # bytes available in data area (starts at page 4)
        return int(data_area)

    def _write_ndef_type2(self, conn, ndef_msg: bytes) -> None:
        tlv = tlv_ndef(ndef_msg)
        cap = self._type2_capacity(conn)
        if len(tlv) > cap:
            raise RuntimeError(f"NDEF too large: need {len(tlv)} bytes, tag capacity {cap} bytes")

        # Write starting at page 4.
        data = tlv
        # Pad to 4-byte boundary with zeros (safe within data area).
        if len(data) % 4:
            data += b"\x00" * (4 - (len(data) % 4))

        start_page = 4
        page_count = len(data) // 4
        for i in range(page_count):
            page = start_page + i
            chunk = data[i * 4 : i * 4 + 4]
            self._write_page4(conn, page, chunk)

        # Verify: read back and compare. If the tag was already removed
        # (all write commands succeeded), treat as OK.
        try:
            actual = self._read_pages(conn, start_page, len(data))
        except Exception:
            return  # tag removed after successful writes — OK
        if actual[:len(data)] != data:
            raise RuntimeError(
                "ベリファイ失敗: 書き込みデータと読み戻しが不一致。"
                "タグを3秒以上かざしたまま保持してください。"
            )

    def write_uri(self, uri: str, *, timeout_s: float | None = None) -> WriteResult:
        if timeout_s is not None:
            self.cfg = PcscConfig(
                reader_name_contains=self.cfg.reader_name_contains,
                poll_interval_s=self.cfg.poll_interval_s,
                write_timeout_s=timeout_s,
            )
        conn = self._connect_wait()
        tag_type = self._get_nfc_forum_tag_type(conn)
        uid = self._get_uid(conn)
        if self.cfg.forbid_uid_hex and _to_hex(uid) == self.cfg.forbid_uid_hex.strip().upper():
            self._wait_tag_removed_or_changed(conn, uid)
            return WriteResult(ok=False, message="SAME_TAG", tag_id=_to_hex(uid))
        if tag_type not in (2,):
            return WriteResult(ok=False, message=f"Unsupported NFC Forum tag type: {tag_type}", tag_id=_to_hex(uid))

        msg = ndef_message_single(ndef_uri(uri))
        self._write_ndef_type2(conn, msg)
        self._wait_tag_removed_or_changed(conn, uid)
        return WriteResult(ok=True, message="Wrote NDEF URI", tag_id=_to_hex(uid))

    def write_text(self, text: str, *, timeout_s: float | None = None) -> WriteResult:
        if timeout_s is not None:
            self.cfg = PcscConfig(
                reader_name_contains=self.cfg.reader_name_contains,
                poll_interval_s=self.cfg.poll_interval_s,
                write_timeout_s=timeout_s,
            )
        conn = self._connect_wait()
        tag_type = self._get_nfc_forum_tag_type(conn)
        uid = self._get_uid(conn)
        if self.cfg.forbid_uid_hex and _to_hex(uid) == self.cfg.forbid_uid_hex.strip().upper():
            self._wait_tag_removed_or_changed(conn, uid)
            return WriteResult(ok=False, message="SAME_TAG", tag_id=_to_hex(uid))
        if tag_type not in (2,):
            return WriteResult(ok=False, message=f"Unsupported NFC Forum tag type: {tag_type}", tag_id=_to_hex(uid))

        msg = ndef_message_single(ndef_text(text))
        self._write_ndef_type2(conn, msg)
        self._wait_tag_removed_or_changed(conn, uid)
        return WriteResult(ok=True, message="Wrote NDEF Text", tag_id=_to_hex(uid))

