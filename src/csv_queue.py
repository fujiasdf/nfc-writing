from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class WriteItem:
    index: int
    type: str  # "uri" | "text"
    payload: str


def load_csv(path: str | Path) -> List[WriteItem]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV header is required (url) or (payload) or (type,payload).")

        fields = [c.strip().lower() for c in reader.fieldnames if c]
        has_type = "type" in fields
        has_payload = "payload" in fields
        has_url = "url" in fields

        items: List[WriteItem] = []
        for i, row in enumerate(reader):
            if has_url:
                payload = (row.get("url") or "").strip()
                if not payload:
                    continue
                items.append(WriteItem(index=len(items), type="uri", payload=payload))
                continue

            payload = (row.get("payload") or "").strip() if has_payload else ""
            if not payload:
                continue

            if has_type:
                t = (row.get("type") or "").strip().lower()
                if not t:
                    # default to URL-only behavior if type is blank
                    t = "uri"
                if t not in ("uri", "text"):
                    raise ValueError(f"Unsupported type at row {i+2}: {t!r}")
                items.append(WriteItem(index=len(items), type=t, payload=payload))
            else:
                # URL-only CSV: payload column treated as URI
                items.append(WriteItem(index=len(items), type="uri", payload=payload))

    if not items:
        raise ValueError("No valid rows found in CSV.")
    return items

