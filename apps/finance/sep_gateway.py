"""
SEP (Saman Electronic Payment) gateway client.

Sandbox mode (SEP_SANDBOX_MODE=True, default) never calls the bank — it
returns mock tokens and successful verifies so local/CI flows work offline.
Flip to production by setting SEP_SANDBOX_MODE=False and a real TerminalId.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib import error, parse, request

from django.conf import settings


class SepGatewayError(Exception):
    """Raised when SEP token/verify fails (or config is invalid)."""

    def __init__(self, message: str, *, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


@dataclass
class SepTokenResult:
    token: str
    redirect_url: str
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    sandbox: bool = True


@dataclass
class SepVerifyResult:
    success: bool
    ref_num: str
    amount: Decimal | None = None
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    sandbox: bool = True
    message: str = ""


def is_sandbox() -> bool:
    return bool(getattr(settings, "SEP_SANDBOX_MODE", True))


def generate_res_num() -> str:
    """Unique merchant invoice number (ResNum / Payment.provider_ref)."""
    return f"SEP-{uuid.uuid4().hex[:24].upper()}"


def build_redirect_url(token: str) -> str:
    base = getattr(settings, "SEP_REDIRECT_BASE_URL", "").rstrip("/")
    return f"{base}?Token={parse.quote(token)}"


def _json_post(url: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        raise SepGatewayError(
            f"SEP HTTP {exc.code}: {data.get('errorDesc') or data.get('resultDescription') or raw}",
            payload=data,
        ) from exc
    except error.URLError as exc:
        raise SepGatewayError(f"SEP network error: {exc.reason}") from exc

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise SepGatewayError("SEP returned non-JSON response", payload={"raw": raw}) from exc


def request_token(
    *,
    amount: Decimal | int,
    res_num: str,
    redirect_url: str | None = None,
    cell_number: str = "",
) -> SepTokenResult:
    amount_int = int(amount)
    if amount_int <= 0:
        raise SepGatewayError("Amount must be positive.")

    callback = redirect_url or getattr(settings, "SEP_CALLBACK_URL", "")
    terminal_id = getattr(settings, "SEP_TERMINAL_ID", "") or ""

    request_payload = {
        "action": "token",
        "TerminalId": terminal_id,
        "Amount": amount_int,
        "ResNum": res_num,
        "RedirectUrl": callback,
        "CellNumber": cell_number or "",
    }

    if is_sandbox():
        token = f"sandbox-token-{res_num}"
        response_payload = {
            "status": 1,
            "token": token,
            "errorCode": "0",
            "errorDesc": "Sandbox mock token",
            "sandbox": True,
        }
        return SepTokenResult(
            token=token,
            redirect_url=build_redirect_url(token),
            request_payload=request_payload,
            response_payload=response_payload,
            sandbox=True,
        )

    if not terminal_id:
        raise SepGatewayError("SEP_TERMINAL_ID is required when SEP_SANDBOX_MODE is False.")

    token_url = getattr(settings, "SEP_TOKEN_URL")
    response_payload = _json_post(token_url, request_payload)
    token = response_payload.get("token") or response_payload.get("Token")
    # SEP success is typically status==1 or presence of token with errorCode 0
    status = response_payload.get("status")
    error_code = str(response_payload.get("errorCode", ""))
    if not token or (status is not None and int(status) != 1 and error_code not in ("", "0")):
        raise SepGatewayError(
            response_payload.get("errorDesc")
            or response_payload.get("resultDescription")
            or "SEP token request failed",
            payload=response_payload,
        )

    return SepTokenResult(
        token=str(token),
        redirect_url=build_redirect_url(str(token)),
        request_payload=request_payload,
        response_payload=response_payload,
        sandbox=False,
    )


def verify_transaction(
    *,
    ref_num: str,
    expected_amount: Decimal | int,
) -> SepVerifyResult:
    if not ref_num:
        return SepVerifyResult(
            success=False,
            ref_num="",
            message="Missing RefNum",
            sandbox=is_sandbox(),
        )

    expected = Decimal(expected_amount)
    terminal_id = getattr(settings, "SEP_TERMINAL_ID", "") or ""
    request_payload = {
        "RefNum": ref_num,
        "TerminalNumber": int(terminal_id) if terminal_id.isdigit() else terminal_id,
    }

    if is_sandbox():
        response_payload = {
            "ResultCode": 0,
            "ResultDescription": "Sandbox mock verify",
            "Success": True,
            "TransactionDetail": {
                "RefNum": ref_num,
                "Amount": int(expected),
            },
            "sandbox": True,
        }
        return SepVerifyResult(
            success=True,
            ref_num=ref_num,
            amount=expected,
            request_payload=request_payload,
            response_payload=response_payload,
            sandbox=True,
            message="Sandbox verified",
        )

    if not terminal_id:
        raise SepGatewayError("SEP_TERMINAL_ID is required when SEP_SANDBOX_MODE is False.")

    verify_url = getattr(settings, "SEP_VERIFY_URL")
    response_payload = _json_post(verify_url, request_payload)

    success_flag = bool(response_payload.get("Success")) or str(
        response_payload.get("ResultCode", "")
    ) in ("0", "00")
    detail = response_payload.get("TransactionDetail") or {}
    verified_amount = detail.get("Amount") or response_payload.get("Amount")
    amount_ok = True
    parsed_amount: Decimal | None = None
    if verified_amount is not None:
        parsed_amount = Decimal(str(verified_amount))
        amount_ok = parsed_amount == expected

    ok = success_flag and amount_ok
    message = response_payload.get("ResultDescription") or (
        "Amount mismatch" if success_flag and not amount_ok else ""
    )

    return SepVerifyResult(
        success=ok,
        ref_num=ref_num,
        amount=parsed_amount if parsed_amount is not None else expected,
        request_payload=request_payload,
        response_payload=response_payload,
        sandbox=False,
        message=message or ("OK" if ok else "Verify failed"),
    )
