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
    provider: str = Payment.Provider.SEP,
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
    if payment.status in (Payment.Status.FAILED, Payment.Status.CANCELED):
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


def initiate_sep_payment(
    *,
    user,
    amount: Decimal,
    purpose: str = "",
) -> dict:
    """
    Create a pending SEP Payment and obtain a redirect URL (sandbox or live).
    Returns {payment, redirect_url, provider_ref, sandbox}.
    """
    from django.conf import settings

    from . import sep_gateway

    res_num = sep_gateway.generate_res_num()
    payment = create_payment(
        user=user,
        amount=amount,
        purpose=purpose,
        provider=Payment.Provider.SEP,
        provider_ref=res_num,
        metadata={"sep": {"initiated": True}},
    )

    try:
        token_result = sep_gateway.request_token(
            amount=amount,
            res_num=res_num,
            redirect_url=getattr(settings, "SEP_CALLBACK_URL", ""),
        )
    except sep_gateway.SepGatewayError as exc:
        mark_payment_failed(
            payment=payment,
            metadata={
                "sep_token_error": str(exc),
                "sep_token_error_payload": exc.payload,
            },
        )
        raise FinanceError(str(exc)) from exc

    payment.metadata = {
        **(payment.metadata or {}),
        "sep_token": token_result.token,
        "sep_token_request": token_result.request_payload,
        "sep_token_response": token_result.response_payload,
        "sep_sandbox": token_result.sandbox,
    }
    payment.save(update_fields=["metadata", "updated_at"])

    return {
        "payment": payment,
        "redirect_url": token_result.redirect_url,
        "provider_ref": res_num,
        "sandbox": token_result.sandbox,
    }


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
def handle_sep_callback(*, data: dict) -> Payment:
    """
    Process SEP bank return payload. Idempotent: repeated success callbacks
    do not double-credit the wallet.
    """
    from . import sep_gateway

    res_num = _callback_field(data, "ResNum", "resNum", "RESNUM")
    ref_num = _callback_field(data, "RefNum", "refNum", "REFNUM")
    state = _callback_field(data, "State", "state", "Status", "status")

    if not res_num:
        raise FinanceError("SEP callback missing ResNum.")

    try:
        payment = (
            Payment.objects.select_for_update()
            .filter(provider=Payment.Provider.SEP, provider_ref=res_num)
            .get()
        )
    except Payment.DoesNotExist as exc:
        raise FinanceError("Unknown SEP payment (ResNum).") from exc

    meta = {**(payment.metadata or {}), "sep_callback": dict(data)}

    if payment.status == Payment.Status.SUCCEEDED:
        payment.metadata = meta
        payment.save(update_fields=["metadata", "updated_at"])
        return payment

    # Common SEP cancel/fail indicators
    state_upper = state.upper()
    fail_states = {
        "CANCELED",
        "CANCELLED",
        "FAILED",
        "FAIL",
        "ERROR",
        "NOK",
        "CANCELED_BY_USER",
        "CANCEL",
    }
    if state_upper in fail_states or state_upper.startswith("CANCEL"):
        return mark_payment_failed(payment=payment, metadata=meta)

    try:
        verify = sep_gateway.verify_transaction(
            ref_num=ref_num or f"sandbox-ref-{res_num}",
            expected_amount=payment.amount,
        )
    except sep_gateway.SepGatewayError as exc:
        return mark_payment_failed(
            payment=payment,
            metadata={
                **meta,
                "sep_verify_error": str(exc),
                "sep_verify_error_payload": exc.payload,
            },
        )

    meta["sep_verify_request"] = verify.request_payload
    meta["sep_verify_response"] = verify.response_payload

    if not verify.success:
        return mark_payment_failed(
            payment=payment,
            metadata={**meta, "sep_verify_message": verify.message},
        )

    # Keep merchant ResNum as provider_ref; store bank RefNum in metadata.
    meta["sep_ref_num"] = verify.ref_num
    return confirm_payment(
        payment=payment,
        metadata=meta,
        idempotency_key=f"sep-confirm:{payment.pk}",
    )


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
