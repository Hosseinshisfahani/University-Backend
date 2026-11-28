"""Clear disposable finance and commerce rows. Users, catalog, and content stay."""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone


FINANCE_MODELS = (
    ("finance", "PaymentEvent"),
    ("finance", "LedgerEntry"),
    ("finance", "WithdrawalRequest"),
    ("finance", "Payment"),
    ("finance", "Wallet"),
)
COMMERCE_MODELS = (
    ("shop", "CartItem"),
    ("shop", "Cart"),
    ("shop", "OrderItem"),
    ("shop", "CouponRedemption"),
    ("shop", "Order"),
    ("lms", "SessionProgress"),
    ("lms", "Certificate"),
    ("lms", "Enrollment"),
    ("booking", "AppointmentReview"),
    ("booking", "Appointment"),
    ("psy_institute", "WorkshopSessionProgress"),
    ("psy_institute", "WorkshopCertificate"),
    ("psy_institute", "WorkshopEnrollment"),
    ("psy_institute", "TherapistReview"),
    ("psy_institute", "CartItem"),
    ("psy_institute", "Cart"),
    ("psy_institute", "OrderItem"),
    ("psy_institute", "CouponRedemption"),
    ("psy_institute", "Order"),
    ("psy_institute", "Appointment"),
)


class Command(BaseCommand):
    help = "Dry-run by default. Truncate finance and commerce test rows on Postgres."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--database-name", default="")
        parser.add_argument("--allow-real-payments", action="store_true")
        parser.add_argument("--include-dependents", action="store_true")

    def handle(self, *args, **options):
        tables = _existing_tables(_model_tables(FINANCE_MODELS + COMMERCE_MODELS))
        counts = _counts(tables)
        for name, count in counts.items():
            self.stdout.write(f"{name}={count}")

        if not options["execute"]:
            self.stdout.write("dry-run")
            return

        connected = connection.settings_dict.get("NAME") or ""
        if options["database_name"] != connected:
            raise CommandError(
                f"Refusing to execute: --database-name {options['database_name']!r} "
                f"does not match the connected database {connected!r}."
            )
        real = _real_vandar_payments()
        if real and not options["allow_real_payments"]:
            raise CommandError(
                "Refusing to execute: succeeded Vandar payments exist whose token "
                f"is not a sandbox token ({real}). Pass --allow-real-payments to discard them."
            )
        if connection.vendor != "postgresql":
            raise CommandError("reset_commerce_test_data can only execute on PostgreSQL.")

        outside = _outside_foreign_keys(tables)
        if outside and not options["include_dependents"]:
            listed = ", ".join(f"{src} -> {dst}" for src, dst in outside)
            raise CommandError(
                "Other tables reference rows that would be truncated: "
                f"{listed}. Pass --include-dependents to include them."
            )
        if outside and options["include_dependents"]:
            tables = list(dict.fromkeys([src for src, _dst in outside] + tables))

        with transaction.atomic():
            if tables:
                quoted = ", ".join(connection.ops.quote_name(table) for table in tables)
                with connection.cursor() as cursor:
                    cursor.execute(f"TRUNCATE {quoted}")
            _delete_withdrawal_tickets()
            _reset_slots()
            _reset_coupon_counters()
        self.stdout.write("executed")


def _model_tables(pairs) -> list[str]:
    tables = []
    for app_label, model_name in pairs:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        tables.append(model._meta.db_table)
    return tables


def _existing_tables(tables: list[str]) -> list[str]:
    existing = set(connection.introspection.table_names())
    return [table for table in tables if table in existing]


def _counts(tables: list[str]) -> dict[str, int]:
    counts = {}
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            counts[table] = cursor.fetchone()[0]
    return counts


def _real_vandar_payments() -> int:
    try:
        Payment = apps.get_model("finance", "Payment")
    except LookupError:
        return 0
    if Payment._meta.db_table not in set(connection.introspection.table_names()):
        return 0
    return (
        Payment.objects.filter(provider="vandar", status="succeeded")
        .exclude(provider_ref__startswith="sandbox-")
        .count()
    )


def _outside_foreign_keys(tables: list[str]) -> list[tuple[str, str]]:
    if connection.vendor != "postgresql":
        return []
    table_set = set(tables)
    sql = """
        SELECT DISTINCT src.relname, dst.relname
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class dst ON dst.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = src.relnamespace
        WHERE c.contype = 'f'
          AND n.nspname = current_schema()
          AND dst.relname = ANY(%s)
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [list(table_set)])
        rows = cursor.fetchall()
    return [(src, dst) for src, dst in rows if src not in table_set]


def _delete_withdrawal_tickets() -> None:
    try:
        Ticket = apps.get_model("psy_institute", "Ticket")
        TicketMessage = apps.get_model("psy_institute", "TicketMessage")
    except LookupError:
        return
    tickets = Ticket.objects.filter(type="withdrawal")
    TicketMessage.objects.filter(ticket__in=tickets).delete()
    tickets.delete()


def _quoted_table(app_label: str, model_name: str) -> str | None:
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    table = model._meta.db_table
    if table not in set(connection.introspection.table_names()):
        return None
    return connection.ops.quote_name(table)


def _reset_slots() -> None:
    now = timezone.now()
    try:
        Slot = apps.get_model("booking", "Slot")
    except LookupError:
        Slot = None
    if Slot is not None:
        Slot.objects.filter(status__in=["booked", "held"], starts_at__gte=now).update(
            status="open",
            hold_expires_at=None,
        )
        Slot.objects.filter(status__in=["booked", "held"], starts_at__lt=now).update(
            status="blocked",
            hold_expires_at=None,
        )
    # The psychology slot table is frozen. This maintenance reset writes it
    # with SQL instead of the ORM.
    quoted = _quoted_table("psy_institute", "AppointmentSlot")
    if quoted is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {quoted} SET status = %s, hold_expires_at = NULL "
            "WHERE status IN (%s, %s) AND starts_at >= %s",
            ["open", "booked", "held", now],
        )
        cursor.execute(
            f"UPDATE {quoted} SET status = %s, hold_expires_at = NULL "
            "WHERE status IN (%s, %s) AND starts_at < %s",
            ["blocked", "booked", "held", now],
        )


def _reset_coupon_counters() -> None:
    try:
        Coupon = apps.get_model("shop", "Coupon")
    except LookupError:
        pass
    else:
        Coupon.objects.update(used_count=0)
    quoted = _quoted_table("psy_institute", "Coupon")
    if quoted is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {quoted} SET used_count = 0")
