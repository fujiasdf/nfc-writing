from __future__ import annotations


def _ndef_record_well_known(*, type_char: str, payload: bytes) -> bytes:
    # MB=1 ME=1 CF=0 SR=1 IL=0 TNF=0x01
    header = 0xD1
    t = type_char.encode("ascii")
    if len(t) != 1:
        raise ValueError("type_char must be 1 byte")
    if len(payload) > 255:
        raise ValueError("payload too long for SR record")
    return bytes([header, len(t), len(payload)]) + t + payload


def ndef_uri(uri: str) -> bytes:
    # NFC Forum URI RTD: first byte is prefix code; 0x00 means no prefix.
    payload = bytes([0x00]) + uri.encode("utf-8")
    return _ndef_record_well_known(type_char="U", payload=payload)


def ndef_text(text: str, lang: str = "en") -> bytes:
    lang_b = lang.encode("ascii")
    if len(lang_b) > 63:
        raise ValueError("lang too long")
    status = len(lang_b) & 0x3F  # UTF-8
    payload = bytes([status]) + lang_b + text.encode("utf-8")
    return _ndef_record_well_known(type_char="T", payload=payload)


def ndef_message_single(record: bytes) -> bytes:
    return record


def tlv_ndef(ndef_msg: bytes) -> bytes:
    # NDEF TLV: 0x03 + length + message + 0xFE terminator
    n = len(ndef_msg)
    if n <= 254:
        return bytes([0x03, n]) + ndef_msg + bytes([0xFE])
    if n <= 0xFFFF:
        return bytes([0x03, 0xFF, (n >> 8) & 0xFF, n & 0xFF]) + ndef_msg + bytes([0xFE])
    raise ValueError("NDEF message too long")

