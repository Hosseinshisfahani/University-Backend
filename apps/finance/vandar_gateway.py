"""
Vandar IPG v4 client.

Sandbox mode (VANDAR_SANDBOX_MODE=True, default) never calls Vandar.
Live mode requires VANDAR_API_KEY and VANDAR_CALLBACK_URL from the environment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib import error, request

from django.conf import settings


class VandarGatewayError(Exception):
    """Token, verify, or inquiry failed, or live config is missing.

    indeterminate=True means a timeout, a connection error, or HTTP 5xx.
    The caller must not treat that as a failed charge.
    """

    def __init__(
        self,
        message: str,
        *,
        payload: dict | None = None,
        indeterminate: bool = False,
    ):
        super().__init__(message)
        self.payload = payload or {}
        self.indeterminate = indeterminate


@dataclass
class VandarTokenResult:
    token: str
    redirect_url: str
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    sandbox: bool = True


@dataclass
class VandarMoneyResult:
    """Result of verify or transaction inquiry."""

    success: bool
    indeterminate: bool
    confirm_required: bool
    amount: Decimal | None = None
    trans_id: str = ""
    card_number: str = ""
    message: str = ""
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    sandbox: bool = True


def is_sandbox() -> bool:
    return bool(getattr(settings, "VANDAR_SANDBOX_MODE", True))


def build_redirect_url(token: str) -> str:
    base = str(getattr(settings, "VANDAR_REDIRECT_BASE_URL", "")).rstrip("/")
    return f"{base}/{token}"


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if "api_key" in redacted:
        redacted["api_key"] = "***"
    return redacted


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
            status_code = getattr(resp, "status", 200)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        if not isinstance(data, dict):
            data = {"raw": data}
        raise VandarGatewayError(
            f"Vandar HTTP {exc.code}",
            payload=data,
            indeterminate=exc.code >= 500,
        ) from exc
    except error.URLError as exc:
        raise VandarGatewayError(
            f"Vandar network error: {exc.reason}",
            indeterminate=True,
        ) from exc
    except TimeoutError as exc:
        raise VandarGatewayError("Vandar timeout", indeterminate=True) from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise VandarGatewayError(
            "Vandar returned non-JSON response",
            payload={"raw": raw},
            indeterminate=status_code >= 500,
        ) from exc
    if not isinstance(data, dict):
        raise VandarGatewayError(
            "Vandar returned a non-object JSON body",
            payload={"raw": data},
        )
    return data


def _require_live_config() -> tuple[str, str]:
    api_key = getattr(settings, "VANDAR_API_KEY", "") or ""
    callback = getattr(settings, "VANDAR_CALLBACK_URL", "") or ""
    if not api_key:
        raise VandarGatewayError(
            "VANDAR_API_KEY is required when VANDAR_SANDBOX_MODE is False."
        )
    if not callback:
        raise VandarGatewayError(
            "VANDAR_CALLBACK_URL is required when VANDAR_SANDBOX_MODE is False."
        )
    return api_key, callback


def _amount_covers(returned: Any, expected: Decimal) -> tuple[bool, Decimal | None]:
    if returned is None or str(returned).strip() == "":
        return False, None
    parsed = Decimal(str(returned)).to_integral_value()
    return parsed >= expected, parsed


def _confirm_required(message: str) -> bool:
    normalized = message.lower().replace(" ", "")
    return "confirmrequierd" in normalized or "confirmrequired" in normalized


def _settled(message: str) -> bool:
    return message.strip().lower() in {"ok", "success", "verified"}


def _interpret(
    response_payload: dict[str, Any],
    *,
    expected: Decimal,
    request_payload: dict[str, Any],
    sandbox: bool,
) -> VandarMoneyResult:
    message = str(response_payload.get("message") or "")
    status = response_payload.get("status")
    amount_ok, parsed = _amount_covers(response_payload.get("amount"), expected)
    common = dict(
        amount=parsed,
        trans_id=str(response_payload.get("transId") or ""),
        card_number=str(response_payload.get("cardNumber") or ""),
        request_payload=request_payload,
        response_payload=response_payload,
        sandbox=sandbox,
    )

    if _confirm_required(message):
        return VandarMoneyResult(
            success=False,
            indeterminate=False,
            confirm_required=True,
            message=message,
            **common,
        )

    if status == 1 and _settled(message) and amount_ok:
        return VandarMoneyResult(
            success=True,
            indeterminate=False,
            confirm_required=False,
            message=message or "ok",
            **common,
        )

    if status == 1 and _settled(message) and not amount_ok:
        return VandarMoneyResult(
            success=False,
            indeterminate=False,
            confirm_required=False,
            message="Amount mismatch",
            **common,
        )

    # status 1 with an unknown message is not proof of failure.
    if status == 1:
        return VandarMoneyResult(
            success=False,
            indeterminate=True,
            confirm_required=False,
            message=message or "Unrecognized Vandar status",
            **common,
        )

    return VandarMoneyResult(
        success=False,
        indeterminate=False,
        confirm_required=False,
        message=message or "Vandar payment was not successful",
        **common,
    )


def request_token(
    *,
    amount: Decimal | int,
    factor_number: str,
    mobile_number: str = "",
) -> VandarTokenResult:
    amount_int = int(amount)
    if amount_int < 1000:
        raise VandarGatewayError("Amount must be at least 1000 rials.")

    api_key = getattr(settings, "VANDAR_API_KEY", "") or ""
    callback = getattr(settings, "VANDAR_CALLBACK_URL", "") or ""
    request_payload: dict[str, Any] = {
        "api_key": api_key,
        "amount": amount_int,
        "callback_url": callback,
        "factorNumber": factor_number,
    }
    if mobile_number:
        request_payload["mobile_number"] = mobile_number

    if is_sandbox():
        token = f"sandbox-{factor_number}"
        return VandarTokenResult(
            token=token,
            redirect_url=build_redirect_url(token),
            request_payload=_redact(request_payload),
            response_payload={"status": 1, "token": token, "sandbox": True},
            sandbox=True,
        )

    api_key, callback = _require_live_config()
    request_payload["api_key"] = api_key
    request_payload["callback_url"] = callback
    response_payload = _json_post(settings.VANDAR_SEND_URL, request_payload)
    token = response_payload.get("token")
    if response_payload.get("status") != 1 or not token:
        raise VandarGatewayError(
            str(response_payload.get("message") or "Vandar token request failed"),
            payload=response_payload,
        )
    return VandarTokenResult(
        token=str(token),
        redirect_url=build_redirect_url(str(token)),
        request_payload=_redact(request_payload),
        response_payload=response_payload,
        sandbox=False,
    )


def verify_transaction(*, token: str, expected_amount: Decimal | int) -> VandarMoneyResult:
    return _money_call(
        url=settings.VANDAR_VERIFY_URL,
        token=token,
        expected_amount=expected_amount,
    )


def inquire_transaction(*, token: str, expected_amount: Decimal | int) -> VandarMoneyResult:
    return _money_call(
        url=settings.VANDAR_TRANSACTION_URL,
        token=token,
        expected_amount=expected_amount,
    )


def _money_call(*, url: str, token: str, expected_amount: Decimal | int) -> VandarMoneyResult:
    expected = Decimal(int(expected_amount))
    api_key = getattr(settings, "VANDAR_API_KEY", "") or ""
    request_payload = {"api_key": api_key, "token": token}

    if is_sandbox():
        return VandarMoneyResult(
            success=True,
            indeterminate=False,
            confirm_required=False,
            amount=expected,
            trans_id=f"sandbox-trans-{token}",
            message="ok",
            request_payload=_redact(request_payload),
            response_payload={
                "status": 1,
                "amount": str(int(expected)),
                "message": "ok",
                "transId": f"sandbox-trans-{token}",
                "sandbox": True,
            },
            sandbox=True,
        )

    if not api_key:
        raise VandarGatewayError(
            "VANDAR_API_KEY is required when VANDAR_SANDBOX_MODE is False."
        )

    response_payload = _json_post(url, request_payload)
    return _interpret(
        response_payload,
        expected=expected,
        request_payload=_redact(request_payload),
        sandbox=False,
    )