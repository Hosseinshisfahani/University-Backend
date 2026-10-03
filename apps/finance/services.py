from decimal import Decimal

from django.db import transaction

from .models import LedgerEntry, Payment, Wallet, WithdrawalRequest


class FinanceError(Exception):
    """Base finance domain error."""


class InsufficientFunds(FinanceError):
    pass


class IdempotencyConflict(FinanceError):
    pass


def get_or_create_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _apply_entry(
    *,
    wallet: Wallet,
    direction: str,
    amount: Decimal,
    entry_type: str,
    idempotency_key: str,
    reference: str = "",
    description: str = "",
    created_by=None,
) -> LedgerEntry:
    if amount <= 0:
        raise FinanceError("Amount must be positive.")

    existing = LedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
        if not locked.is_active:
            raise FinanceError("Wallet is inactive.")

        if direction == LedgerEntry.Direction.CREDIT:
            new_balance = locked.balance + amount
        elif direction == LedgerEntry.Direction.DEBIT:
            if locked.balance < amount:
                raise InsufficientFunds("Insufficient wallet balance.")
            new_balance = locked.balance - amount
        else:
            raise FinanceError(f"Unknown direction: {direction}")

        locked.balance = new_balance
        locked.save(update_fields=["balance", "updated_at"])

        return LedgerEntry.objects.create(
            wallet=locked,
            direction=direction,
            amount=amount,
            balance_after=new_balance,
            entry_type=entry_type,
            reference=reference,
            idempotency_key=idempotency_key,
            description=description,
            created_by=created_by,
        )


def credit_wallet(
    *,
    user,
    amount: Decimal,
    entry_type: str,
    idempotency_key: str,
    reference: str = "",
    description: str = "",
    created_by=None,
) -> LedgerEntry:
    wallet = get_or_create_wallet(user)
    return _apply_entry(
        wallet=wallet,
        direction=LedgerEntry.Direction.CREDIT,
        amount=amount,
        entry_type=entry_type,
        idempotency_key=idempotency_key,
        reference=reference,
        description=description,
        created_by=created_by,
    )


def debit_wallet(
    *,
    user,
    amount: Decimal,
    entry_type: str,
    idempotency_key: str,
    reference: str = "",
    description: str = "",
    created_by=None,
) -> LedgerEntry:
    wallet = get_or_create_wallet(user)
    return _apply_entry(
        wallet=wallet,
        direction=LedgerEntry.Direction.DEBIT,
        amount=amount,
        entry_type=entry_type,
        idempotency_key=idempotency_key,
        reference=reference,
        description=description,
        created_by=created_by,
    )


@transaction.atomic
def create_payment(
    *,
    user,
    amount: Decimal,
    purpose: str = "",
    provider: str = Payment.Provider.VANDAR,
    provider_ref: str = "",
    metadata: dict | None = None,
) -> Payment:
    if amount <= 0:
        raise FinanceError("Payment amount must be positive.")
    get_or_create_wallet(user)
    return Payment.objects.create(
        user=user,
        amount=amount,
        purpose=purpose,
        provider=provider,
        provider_ref=provider_ref,
        metadata=metadata or {},
        status=Payment.Status.PENDING,
    )


@transaction.atomic
def confirm_payment(
    *,
    payment: Payment,
    provider_ref: str = "",
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCEEDED:
        return payment
    if payment.status not in (
        Payment.Status.PENDING,
        Payment.Status.INDETERMINATE,
    ):
        raise FinanceError(f"Cannot confirm payment in status {payment.status}.")

    key = idempotency_key or f"payment-confirm:{payment.pk}"
    entry = credit_wallet(
        user=payment.user,
        amount=payment.amount,
        entry_type=LedgerEntry.EntryType.DEPOSIT,
        idempotency_key=key,
        reference=f"finance.payment:{payment.pk}",
        description=payment.purpose or "Payment deposit",
    )
    payment.status = Payment.Status.SUCCEEDED
    if provider_ref:
        payment.provider_ref = provider_ref
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.ledger_entry = entry
    payment.save()
    return payment


@transaction.atomic
def mark_payment_failed(
    *,
    payment: Payment,
    metadata: dict | None = None,
) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCEEDED:
        return payment
    payment.status = Payment.Status.FAILED
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    return payment


@transaction.atomic
def mark_payment_indeterminate(
    *,
    payment: Payment,
    metadata: dict | None = None,
) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status in (
        Payment.Status.SUCCEEDED,
        Payment.Status.FAILED,
        Payment.Status.CANCELED,
    ):
        return payment
    payment.status = Payment.Status.INDETERMINATE
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    return payment


def initiate_vandar_payment(*, user, amount: Decimal, purpose: str = "") -> dict:
    """
    Create a pending Vandar payment from a toman amount.
    Returns {payment, redirect_url, provider_ref, sandbox}.
    """
    from . import vandar_gateway

    if amount != amount.to_integral_value() or amount <= 0:
        raise FinanceError("Toman amount must be a positive whole number.")

    amount_rial = Decimal(int(amount) * 10)
    if amount_rial < 1000:
        raise FinanceError("Amount must be at least 1000 rials (100 toman).")

    payment = create_payment(
        user=user,
        amount=amount_rial,
        purpose=purpose,
        provider=Payment.Provider.VANDAR,
        metadata={"vandar": {"initiated": True, "amount_toman": int(amount)}},
    )
    try:
        token_result = vandar_gateway.request_token(
            amount=amount_rial,
            factor_number=str(payment.pk),
        )
    except vandar_gateway.VandarGatewayError as exc:
        mark_payment_failed(
            payment=payment,
            metadata={
                "vandar_token_error": str(exc),
                "vandar_token_error_payload": exc.payload,
            },
        )
        raise FinanceError(str(exc)) from exc

    payment.provider_ref = token_result.token
    payment.metadata = {
        **(payment.metadata or {}),
        "vandar_token": token_result.token,
        "vandar_token_request": token_result.request_payload,
        "vandar_token_response": token_result.response_payload,
        "vandar_sandbox": token_result.sandbox,
    }
    payment.save(update_fields=["provider_ref", "metadata", "updated_at"])
    return {
        "payment": payment,
        "redirect_url": token_result.redirect_url,
        "provider_ref": token_result.token,
        "sandbox": token_result.sandbox,
    }


def _record_vandar_result(meta: dict, result, prefix: str) -> dict:
    meta[f"{prefix}_request"] = result.request_payload
    meta[f"{prefix}_response"] = result.response_payload
    meta[f"{prefix}_message"] = result.message
    if result.trans_id:
        meta["vandar_trans_id"] = result.trans_id
    if result.card_number:
        meta["vandar_card_number"] = result.card_number
    return meta


def _confirm_vandar(payment: Payment, meta: dict) -> Payment:
    return confirm_payment(
        payment=payment,
        metadata=meta,
        idempotency_key=f"vandar-confirm:{payment.pk}",
    )


@transaction.atomic
def handle_vandar_callback(*, data: dict) -> Payment:
    """
    Process the Vandar return. The row lock serializes duplicate callbacks
    so the wallet is credited once.
    """
    from . import vandar_gateway

    token = _callback_field(data, "token")
    payment_status = _callback_field(data, "payment_status").upper()
    if not token:
        raise FinanceError("Vandar callback missing token.")

    try:
        payment = (
            Payment.objects.select_for_update()
            .filter(provider=Payment.Provider.VANDAR, provider_ref=token)
            .get()
        )
    except Payment.DoesNotExist as exc:
        raise FinanceError("Unknown Vandar payment (token).") from exc

    meta = {**(payment.metadata or {}), "vandar_callback": dict(data)}

    if payment.status == Payment.Status.SUCCEEDED:
        payment.metadata = meta
        payment.save(update_fields=["metadata", "updated_at"])
        return payment

    if payment.status in (Payment.Status.FAILED, Payment.Status.CANCELED):
        return payment

    if payment_status == "FAILED":
        return mark_payment_failed(payment=payment, metadata=meta)

    if payment_status != "OK":
        return mark_payment_indeterminate(payment=payment, metadata=meta)

    try:
        verified = vandar_gateway.verify_transaction(
            token=token,
            expected_amount=payment.amount,
        )
    except vandar_gateway.VandarGatewayError as exc:
        meta["vandar_verify_error"] = str(exc)
        meta["vandar_verify_error_payload"] = exc.payload
        if not exc.indeterminate:
            return mark_payment_failed(payment=payment, metadata=meta)
        verified = None

    if verified is not None:
        meta = _record_vandar_result(meta, verified, "vandar_verify")
        if verified.success:
            return _confirm_vandar(payment, meta)
        if not verified.indeterminate and not verified.confirm_required:
            return mark_payment_failed(payment=payment, metadata=meta)

    try:
        inquiry = vandar_gateway.inquire_transaction(
            token=token,
            expected_amount=payment.amount,
        )
    except vandar_gateway.VandarGatewayError as exc:
        meta["vandar_inquiry_error"] = str(exc)
        meta["vandar_inquiry_error_payload"] = exc.payload
        if exc.indeterminate:
            return mark_payment_indeterminate(payment=payment, metadata=meta)
        return mark_payment_failed(payment=payment, metadata=meta)

    meta = _record_vandar_result(meta, inquiry, "vandar_inquiry")
    if inquiry.success:
        return _confirm_vandar(payment, meta)
    if inquiry.indeterminate:
        return mark_payment_indeterminate(payment=payment, metadata=meta)
    if not inquiry.confirm_required:
        return mark_payment_failed(payment=payment, metadata=meta)

    try:
        retried = vandar_gateway.verify_transaction(
            token=token,
            expected_amount=payment.amount,
        )
    except vandar_gateway.VandarGatewayError as exc:
        meta["vandar_verify_retry_error"] = str(exc)
        meta["vandar_verify_retry_error_payload"] = exc.payload
        if exc.indeterminate:
            return mark_payment_indeterminate(payment=payment, metadata=meta)
        return mark_payment_failed(payment=payment, metadata=meta)

    meta = _record_vandar_result(meta, retried, "vandar_verify_retry")
    if retried.success:
        return _confirm_vandar(payment, meta)
    if retried.indeterminate or retried.confirm_required:
        return mark_payment_indeterminate(payment=payment, metadata=meta)
    return mark_payment_failed(payment=payment, metadata=meta)


def _callback_field(data: dict, *names: str) -> str:
    for name in names:
        value = data.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    # case-insensitive fallback
    lower_map = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


@transaction.atomic
def create_withdrawal(
    *,
    user,
    amount: Decimal,
    bank_details: dict,
    ticket_reference: str = "",
    idempotency_key: str,
) -> WithdrawalRequest:
    wallet = get_or_create_wallet(user)
    hold = debit_wallet(
        user=user,
        amount=amount,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL,
        idempotency_key=idempotency_key,
        reference=ticket_reference,
        description="Withdrawal hold",
    )
    return WithdrawalRequest.objects.create(
        wallet=wallet,
        amount=amount,
        bank_details=bank_details,
        ticket_reference=ticket_reference,
        status=WithdrawalRequest.Status.PENDING,
        ledger_hold_entry=hold,
    )


@transaction.atomic
def approve_withdrawal(*, withdrawal: WithdrawalRequest, processed_by) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        raise FinanceError("Only pending withdrawals can be approved.")
    withdrawal.status = WithdrawalRequest.Status.APPROVED
    withdrawal.processed_by = processed_by
    withdrawal.save(update_fields=["status", "processed_by", "updated_at"])
    return withdrawal


@transaction.atomic
def mark_withdrawal_paid(*, withdrawal: WithdrawalRequest, processed_by) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    if withdrawal.status not in (
        WithdrawalRequest.Status.PENDING,
        WithdrawalRequest.Status.APPROVED,
    ):
        raise FinanceError("Withdrawal cannot be marked paid.")
    withdrawal.status = WithdrawalRequest.Status.PAID
    withdrawal.processed_by = processed_by
    withdrawal.ledger_finalize_entry = withdrawal.ledger_hold_entry
    withdrawal.save(
        update_fields=[
            "status",
            "processed_by",
            "ledger_finalize_entry",
            "updated_at",
        ]
    )
    return withdrawal


@transaction.atomic
def reject_withdrawal(
    *,
    withdrawal: WithdrawalRequest,
    processed_by,
    reason: str = "",
) -> WithdrawalRequest:
    withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal.pk)
    if withdrawal.status != WithdrawalRequest.Status.PENDING:
        raise FinanceError("Only pending withdrawals can be rejected.")

    reversal = credit_wallet(
        user=withdrawal.wallet.user,
        amount=withdrawal.amount,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL_REVERSAL,
        idempotency_key=f"withdrawal-reject:{withdrawal.pk}",
        reference=f"finance.withdrawal:{withdrawal.pk}",
        description=reason or "Withdrawal rejected — funds returned",
        created_by=processed_by,
    )
    withdrawal.status = WithdrawalRequest.Status.REJECTED
    withdrawal.processed_by = processed_by
    withdrawal.rejection_reason = reason
    withdrawal.ledger_finalize_entry = reversal
    withdrawal.save(
        update_fields=[
            "status",
            "processed_by",
            "rejection_reason",
            "ledger_finalize_entry",
            "updated_at",
        ]
    )
    return withdrawal
