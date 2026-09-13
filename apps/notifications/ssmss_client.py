from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib import error, parse, request

from django.conf import settings


class SsmssError(Exception):
    def __init__(self, message: str, *, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


@dataclass
class SsmssSendResult:
    sms_ids: list[str]
    sandbox: bool = False
    response_payload: dict[str, Any] = field(default_factory=dict)


def is_sandbox() -> bool:
    return bool(getattr(settings, "SMS_SANDBOX_MODE", True))


# Persian ۰-۹ and Arabic-Indic ٠-٩ → ASCII 0-9 (Persian keyboards).
_ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_ascii_digits(raw: str) -> str:
    return (raw or "").translate(_ASCII_DIGITS)


def normalize_phone(raw: str) -> str:
    ascii_raw = to_ascii_digits(raw)
    digits = "".join(ch for ch in ascii_raw if "0" <= ch <= "9")
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits


def is_iranian_mobile(phone: str) -> bool:
    return phone.startswith("09") and len(phone) == 11


def send(*, receiver: str, note: str, unique_id: str = "0") -> SsmssSendResult:
    phone = normalize_phone(receiver)
    if not is_iranian_mobile(phone):
        raise SsmssError("فرمت شماره گیرنده نامعتبر است.")
    if is_sandbox():
        sms_id = f"sandbox-{phone[-4:]}-{unique_id or '0'}"
        return SsmssSendResult(
            sms_ids=[sms_id],
            sandbox=True,
            response_payload={"result": True, "list": [sms_id]},
        )
    api_key = getattr(settings, "SSMSS_API_KEY", "") or ""
    sender = getattr(settings, "SSMSS_SENDER_NUMBER", "") or ""
    if not api_key or not sender:
        raise SsmssError(
            "SSMSS_API_KEY and SSMSS_SENDER_NUMBER are required when SMS_SANDBOX_MODE is False."
        )
    base = getattr(settings, "SSMSS_BASE_URL", "").rstrip("/")
    payload = {
        "api_key": api_key,
        "receiver_number": phone,
        "sender_number": sender,
        "note_arr[]": note,
        "date": "0",
        "request_uniqueid": unique_id or "0",
        "flash": "no",
        "onlysend": "no",
    }
    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        f"{base}/sms_send",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SsmssError(f"SSMSS HTTP {exc.code}: {raw}") from exc
    except error.URLError as exc:
        raise SsmssError(f"SSMSS network error: {exc.reason}") from exc
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise SsmssError("SSMSS returned non-JSON", payload={"raw": raw}) from exc
    if not data.get("result"):
        raise SsmssError(str(data.get("error") or "send failed"), payload=data)
    sms_ids = [str(x) for x in (data.get("list") or [])]
    return SsmssSendResult(sms_ids=sms_ids, sandbox=False, response_payload=data)
