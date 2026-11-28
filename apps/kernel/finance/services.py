import logging
import re
from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .checkout import CheckoutNotFulfillable, handler_for
from .models import LedgerEntry, Payment, PaymentEvent, Wallet, WithdrawalRequest

logger = logging.getLogger(__name__)

_RETURN_PATH = re.compile(r"/[a-z0-9/_-]*")
OPEN_CHECKOUT_STATUSES = (
    Payment.Status.CREATED,
    Payment.Status.PENDING,
    Payment.Status.INDETERMINATE,
)


class FinanceError(Exception):
    """Base finance domain error."""


class InsufficientFunds(FinanceError):
    pass


class IdempotencyConflict(FinanceError):
    pass


RESERVED_PURPOSE_PREFIXES = (
    "shop.order:",
    "lms.course:",
    "booking.appointment:",
    "psy.order:",
    "psy.workshop:",
    "psy.appointment:",
    "psy.ticket:",
    "finance.payment:",
    "vandar:",
)

SHOP_ORDER_PURPOSE_PREFIXES = ("shop.order:",)


def assert_public_purpose(purpose: str) -> None:
    """Public top-up input cannot claim a module or provider reference."""
    if any((purpose or "").startswith(prefix) for prefix in RESERVED_PURPOSE_PREFIXES):
        raise FinanceError("This payment purpose is reserved.")


def get_or_create_wallet(user) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _assert_same_entry(
    existing: LedgerEntry,
    *,
    wallet: Wallet,
    direction: str,
    amount: Decimal,
    entry_type: str,
) -> LedgerEntry:
    if (
        existing.wallet_id != wallet.pk
        or existing.direction != direction
        or existing.amount != amount
        or existing.entry_type != entry_type
    ):
        raise IdempotencyConflict(
            "Idempotency key is already used for a different ledger entry."
        )
    return existing


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
    institute=None,
    payment: Payment | None = None,
) -> LedgerEntry:
    if amount <= 0:
        raise FinanceError("Amount must be positive.")

    with transaction.atomic():
        locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
        existing = LedgerEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return _assert_same_entry(
                existing,
                wallet=locked,
                direction=direction,
                amount=amount,
                entry_type=entry_type,
            )
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
        try:
            with transaction.atomic():
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
                    institute=institute,
                    payment=payment,
                )
        except IntegrityError:
            if direction == LedgerEntry.Direction.CREDIT:
                locked.balance = locked.balance - amount
            else:
                locked.balance = locked.balance + amount
            locked.save(update_fields=["balance", "updated_at"])
            existing = LedgerEntry.objects.get(idempotency_key=idempotency_key)
            return _assert_same_entry(
                existing,
                wallet=locked,
                direction=direction,
                amount=amount,
                entry_type=entry_type,
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
    institute=None,
    payment: Payment | None = None,
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
        institute=institute,
        payment=payment,
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
    institute=None,
    payment: Payment | None = None,
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
        institute=institute,
        payment=payment,
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
    institute=None,
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
        institute=institute,
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

    now = timezone.now()
    entry = None
    if payment.kind == Payment.Kind.CHECKOUT:
        pair = handler_for(payment.purpose or "")
        if pair is None:
            raise FinanceError("No checkout handler is registered for this payment.")
        fulfill, _release = pair
        try:
            with transaction.atomic():
                fulfill(payment)
        except CheckoutNotFulfillable:
            entry = credit_wallet(
                user=payment.user,
                amount=payment.amount,
                entry_type=LedgerEntry.EntryType.REFUND,
                idempotency_key=f"payment-refund:{payment.pk}",
                reference=f"finance.payment:{payment.pk}",
                description="Checkout could not be fulfilled",
                institute=payment.institute,
                payment=payment,
            )
            payment.fulfillment_status = Payment.FulfillmentStatus.REFUNDED_TO_WALLET
        else:
            payment.fulfillment_status = Payment.FulfillmentStatus.FULFILLED
            payment.fulfilled_at = now
    else:
        key = idempotency_key or f"payment:{payment.pk}"
        entry = credit_wallet(
            user=payment.user,
            amount=payment.amount,
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            idempotency_key=key,
            reference=f"finance.payment:{payment.pk}",
            description=payment.purpose or "Payment deposit",
            institute=payment.institute,
            payment=payment,
        )
        payment.fulfillment_status = Payment.FulfillmentStatus.FULFILLED
        payment.fulfilled_at = now

    if entry is not None:
        payment.ledger_entry = entry
    if not payment.verified_at:
        payment.verified_at = now
    payment.transition(Payment.Status.SUCCEEDED)
    if provider_ref:
        payment.provider_ref = provider_ref
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.save()
    from .signals import payment_succeeded

    try:
        payment_succeeded.send(sender=Payment, payment=payment)
    except Exception:
        logger.exception("payment_succeeded listener failed for payment %s", payment.pk)
    return payment


@transaction.atomic
def mark_payment_failed(
    *,
    payment: Payment,
    metadata: dict | None = None,
    reason: str = "",
) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status in (
        Payment.Status.SUCCEEDED,
        Payment.Status.FAILED,
        Payment.Status.CANCELED,
    ):
        return payment
    payment.transition(Payment.Status.FAILED)
    if reason:
        payment.failure_reason = reason
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.save(update_fields=["status", "failure_reason", "metadata", "updated_at"])
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
        Payment.Status.INDETERMINATE,
    ):
        return payment
    payment.transition(Payment.Status.INDETERMINATE)
    if metadata:
        payment.metadata = {**(payment.metadata or {}), **metadata}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    return payment


def _event(payment: Payment, kind: str, payload: dict | None) -> None:
    hidden = {"api_key", "cardnumber", "card_number", "card"}
    safe = {}
    for key, value in (payload or {}).items():
        safe[key] = "***" if str(key).lower() in hidden else value
    PaymentEvent.objects.create(payment=payment, kind=kind, payload=safe)


def _validate_return_path(return_path: str) -> str:
    path = return_path or ""
    if path and not _RETURN_PATH.fullmatch(path):
        raise FinanceError("Return path is invalid.")
    return path


def resolve_return_host(*, institute, request_host: str) -> str:
    from apps.kernel.tenancy.domains import DomainError, normalize_hostname
    from apps.kernel.tenancy.hosts import neutral_hosts
    from apps.kernel.tenancy.models import InstituteDomain

    host = ""
    if request_host:
        try:
            host = normalize_hostname(request_host, allow_dev_port=settings.DEBUG)
        except DomainError:
            host = ""
    origin = (getattr(settings, "PLATFORM_FRONTEND_ORIGIN", "") or "").rstrip("/")
    platform = (urlparse(origin).hostname or "").lower() if origin else ""
    allowed_platform = {platform, *neutral_hosts()} - {""}

    if institute is None:
        if host and host in allowed_platform:
            return host
        if platform:
            return platform
        if host:
            return host
        raise FinanceError("No return host is configured.")

    domains = set(
        InstituteDomain.objects.filter(institute=institute, is_active=True).values_list(
            "hostname", flat=True
        )
    )
    if host and (host in domains or host in allowed_platform):
        return host
    canonical = (
        InstituteDomain.objects.filter(
            institute=institute, is_active=True, is_canonical=True
        )
        .order_by("id")
        .first()
    )
    if canonical is not None:
        return canonical.hostname
    if platform:
        return platform
    raise FinanceError("No return host is configured.")


def _minimum_rial() -> Decimal:
    return Decimal(int(getattr(settings, "VANDAR_MIN_AMOUNT_IRR", 1000)))


def _payment_result(payment: Payment, *, sandbox: bool | None = None) -> dict:
    from . import vandar_gateway

    if sandbox is None:
        sandbox = vandar_gateway.is_sandbox()
    return {
        "payment": payment,
        "redirect_url": vandar_gateway.build_redirect_url(payment.provider_ref),
        "provider_ref": payment.provider_ref,
        "sandbox": sandbox,
    }


def _issue_token(payment: Payment) -> dict:
    from . import vandar_gateway

    try:
        token_result = vandar_gateway.request_token(
            amount=payment.amount,
            factor_number=str(payment.public_id),
        )
    except vandar_gateway.VandarGatewayError as exc:
        payment.transition(Payment.Status.CANCELED)
        payment.failure_reason = str(exc)
        payment.metadata = {
            **(payment.metadata or {}),
            "vandar_token_error": str(exc),
            "vandar_token_error_payload": exc.payload,
        }
        payment.save()
        _event(payment, PaymentEvent.Kind.INITIATE, {"error": str(exc)})
        raise FinanceError(str(exc)) from exc

    payment.provider_ref = token_result.token
    payment.transition(Payment.Status.PENDING)
    payment.metadata = {
        **(payment.metadata or {}),
        "vandar_token": token_result.token,
        "vandar_token_request": token_result.request_payload,
        "vandar_token_response": token_result.response_payload,
        "vandar_sandbox": token_result.sandbox,
    }
    payment.save()
    _event(
        payment,
        PaymentEvent.Kind.INITIATE,
        {"token": token_result.token, "sandbox": token_result.sandbox},
    )
    return _payment_result(payment, sandbox=token_result.sandbox)


def start_topup(
    *,
    user,
    amount: Decimal,
    purpose: str = "wallet.topup",
    institute=None,
    return_path: str = "/patient/wallet",
    request_host: str = "",
) -> dict:
    """Create a wallet top-up. ``amount`` is toman. This is the only ×10 conversion."""
    assert_public_purpose(purpose)
    path = _validate_return_path(return_path)
    if amount != amount.to_integral_value() or amount <= 0:
        raise FinanceError("Toman amount must be a positive whole number.")
    amount_rial = Decimal(int(amount) * 10)
    if amount_rial < _minimum_rial():
        raise FinanceError(f"Amount must be at least {_minimum_rial()} rials.")
    host = resolve_return_host(institute=institute, request_host=request_host)
    if not path:
        path = "/patient/wallet" if institute is not None else "/payment/result"
    with transaction.atomic():
        payment = Payment.objects.create(
            user=user,
            amount=amount_rial,
            purpose=purpose or "wallet.topup",
            provider=Payment.Provider.VANDAR,
            kind=Payment.Kind.TOPUP,
            status=Payment.Status.CREATED,
            institute=institute,
            return_host=host,
            return_path=path,
            metadata={"vandar": {"initiated": True, "amount_toman": int(amount)}},
        )
    return _issue_token(payment)


def start_checkout(
    *,
    user,
    purpose: str,
    amount_irr: Decimal,
    institute,
    return_path: str,
    request_host: str = "",
) -> dict:
    """Charge ``amount_irr`` for one purpose. Reuses an open checkout for that purpose."""
    if institute is None:
        raise FinanceError("Checkout requires an institute.")
    if not purpose:
        raise FinanceError("Checkout purpose is required.")
    path = _validate_return_path(return_path)
    amount = Decimal(amount_irr)
    if amount != amount.to_integral_value() or amount <= 0:
        raise FinanceError("Amount must be a positive whole number of rials.")
    if amount < _minimum_rial():
        raise FinanceError(f"Amount must be at least {_minimum_rial()} rials.")
    host = resolve_return_host(institute=institute, request_host=request_host)

    with transaction.atomic():
        existing = (
            Payment.objects.select_for_update()
            .filter(
                purpose=purpose,
                kind=Payment.Kind.CHECKOUT,
                status__in=OPEN_CHECKOUT_STATUSES,
            )
            .order_by("-id")
            .first()
        )
        if existing is not None and existing.provider_ref:
            payment = existing
            reuse = True
        elif existing is not None:
            existing.amount = amount
            existing.return_host = host
            existing.return_path = path
            existing.user = user
            existing.save(
                update_fields=["amount", "return_host", "return_path", "user", "updated_at"]
            )
            payment = existing
            reuse = False
        else:
            payment = Payment.objects.create(
                user=user,
                amount=amount,
                purpose=purpose,
                provider=Payment.Provider.VANDAR,
                kind=Payment.Kind.CHECKOUT,
                status=Payment.Status.CREATED,
                institute=institute,
                return_host=host,
                return_path=path,
            )
            reuse = False
    if reuse:
        return _payment_result(payment)
    return _issue_token(payment)


def _callback_field(data: dict, *names: str) -> str:
    for name in names:
        value = data.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    lower_map = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _reject_verification(payment: Payment, result, *, stage: str) -> Payment | None:
    """Return a settled payment, or None when the caller should keep asking Vandar."""
    if result.confirm_required:
        return None
    if result.indeterminate:
        return None
    if not result.success:
        _event(payment, stage, {"message": result.message, "amount": str(result.amount or "")})
        return mark_payment_failed(payment=payment, reason=result.message or "Vandar payment was not successful")

    expected_factor = str(payment.public_id)
    if result.factor_number != expected_factor:
        return mark_payment_failed(payment=payment, reason="factor mismatch")
    if result.amount != payment.amount:
        return mark_payment_failed(payment=payment, reason="amount mismatch")
    if not result.trans_id:
        return mark_payment_failed(payment=payment, reason="missing transaction id")
    if (
        Payment.objects.exclude(pk=payment.pk)
        .filter(trans_id=result.trans_id)
        .exists()
    ):
        return mark_payment_failed(payment=payment, reason="transaction id already used")

    payment.trans_id = result.trans_id
    payment.card_masked = (result.card_number or "")[:32]
    payment.verified_at = timezone.now()
    payment.save(update_fields=["trans_id", "card_masked", "verified_at", "updated_at"])
    _event(
        payment,
        stage,
        {
            "trans_id": result.trans_id,
            "factor_number": result.factor_number,
            "amount": str(result.amount),
        },
    )
    return confirm_payment(payment=payment)


@transaction.atomic
def handle_vandar_callback(*, data: dict) -> Payment:
    """Verify a Vandar return. The browser's payment_status is never trusted."""
    from . import vandar_gateway

    token = _callback_field(data, "token")
    if not token:
        raise FinanceError("Vandar callback missing token.")
    try:
        payment = (
            Payment.objects.select_for_update()
            .select_related("institute")
            .get(provider=Payment.Provider.VANDAR, provider_ref=token)
        )
    except Payment.DoesNotExist as exc:
        raise FinanceError("Unknown Vandar payment (token).") from exc

    _event(payment, PaymentEvent.Kind.CALLBACK, dict(data))
    if payment.status in (
        Payment.Status.SUCCEEDED,
        Payment.Status.FAILED,
        Payment.Status.CANCELED,
    ):
        return payment
    if payment.status == Payment.Status.CREATED:
        payment.transition(Payment.Status.PENDING)
        payment.save(update_fields=["status", "updated_at"])

    factor = str(payment.public_id)

    def _call(fn, stage: str):
        try:
            result = fn(token=token, expected_amount=payment.amount, expected_factor=factor)
        except vandar_gateway.VandarGatewayError as exc:
            _event(payment, stage, {"error": str(exc), "indeterminate": exc.indeterminate})
            if exc.indeterminate:
                return None
            return mark_payment_failed(payment=payment, reason=str(exc))
        return _reject_verification(payment, result, stage=stage)

    settled = _call(vandar_gateway.verify_transaction, PaymentEvent.Kind.VERIFY)
    if settled is not None:
        return settled
    settled = _call(vandar_gateway.inquire_transaction, PaymentEvent.Kind.INQUIRY)
    if settled is not None:
        return settled
    settled = _call(vandar_gateway.verify_transaction, PaymentEvent.Kind.VERIFY)
    if settled is not None:
        return settled
    return mark_payment_indeterminate(payment=payment)


@transaction.atomic
def create_withdrawal(
    *,
    user,
    amount: Decimal,
    bank_details: dict,
    ticket_reference: str = "",
    idempotency_key: str,
    institute=None,
) -> WithdrawalRequest:
    wallet = get_or_create_wallet(user)
    hold = debit_wallet(
        user=user,
        amount=amount,
        entry_type=LedgerEntry.EntryType.WITHDRAWAL,
        idempotency_key=idempotency_key,
        reference=ticket_reference,
        description="Withdrawal hold",
        institute=institute,
    )
    return WithdrawalRequest.objects.create(
        wallet=wallet,
        amount=amount,
        bank_details=bank_details,
        ticket_reference=ticket_reference,
        status=WithdrawalRequest.Status.PENDING,
        ledger_hold_entry=hold,
        institute=institute,
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
        institute=withdrawal.institute,
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
