"""Hostname normalization, TXT challenge, and canonical activation.

DNS lookup is optional. Operators can paste the TXT value into the
management command. The plaintext challenge is returned once and only
its hash is stored.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import InstituteDomain, TenancyAuditEvent


class DomainError(Exception):
    pass


def normalize_hostname(value: str, *, allow_dev_port: bool = False) -> str:
    raw = (value or "").strip().lower()
    if not raw or "://" in raw or "@" in raw or "/" in raw or "?" in raw or "#" in raw:
        raise DomainError("invalid hostname")
    if "*" in raw or " " in raw:
        raise DomainError("invalid hostname")
    host = raw
    if allow_dev_port and host.count(":") == 1:
        host, port = host.split(":")
        if not port.isdigit():
            raise DomainError("invalid hostname")
    elif ":" in host:
        raise DomainError("invalid hostname")
    if host.endswith("."):
        host = host[:-1]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainError("invalid hostname") from exc
    if not host or len(host) > 253 or host.startswith(".") or ".." in host:
        raise DomainError("invalid hostname")
    labels = host.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise DomainError("invalid hostname")
    return host


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def begin_verification(*, institute, hostname: str) -> tuple[InstituteDomain, str]:
    hostname = normalize_hostname(hostname)
    token = secrets.token_urlsafe(32)
    domain, _created = InstituteDomain.objects.update_or_create(
        hostname=hostname,
        defaults={
            "institute": institute,
            "is_active": False,
            "is_canonical": False,
            "verification_token_hash": _hash(token),
            "verification_expires_at": timezone.now() + timedelta(hours=48),
            "verified_at": None,
            "tls_ready_at": None,
        },
    )
    return domain, token


@transaction.atomic
def confirm_verification(*, hostname: str, token: str) -> InstituteDomain:
    hostname = normalize_hostname(hostname)
    try:
        domain = InstituteDomain.objects.select_for_update().get(hostname=hostname)
    except InstituteDomain.DoesNotExist as exc:
        raise DomainError("unknown hostname") from exc
    if not domain.verification_token_hash or domain.verification_expires_at is None:
        raise DomainError("no challenge")
    if domain.verification_expires_at < timezone.now():
        raise DomainError("expired challenge")
    if _hash(token) != domain.verification_token_hash:
        raise DomainError("challenge mismatch")
    domain.verified_at = timezone.now()
    domain.verification_token_hash = ""
    domain.verification_expires_at = None
    domain.save(
        update_fields=[
            "verified_at",
            "verification_token_hash",
            "verification_expires_at",
            "updated_at",
        ]
    )
    return domain


@transaction.atomic
def mark_tls_ready(*, hostname: str) -> InstituteDomain:
    hostname = normalize_hostname(hostname)
    domain = InstituteDomain.objects.select_for_update().get(hostname=hostname)
    if domain.verified_at is None:
        raise DomainError("ownership is not verified")
    domain.tls_ready_at = timezone.now()
    domain.save(update_fields=["tls_ready_at", "updated_at"])
    return domain


@transaction.atomic
def activate_canonical(*, hostname: str, actor=None) -> InstituteDomain:
    """Lock the institute and switch the single canonical domain."""
    hostname = normalize_hostname(hostname)
    domain = (
        InstituteDomain.objects.select_for_update()
        .select_related("institute")
        .get(hostname=hostname)
    )
    if domain.verified_at is None or domain.tls_ready_at is None:
        raise DomainError("domain is not ready")
    institute = domain.institute
    InstituteDomain.objects.select_for_update().filter(institute=institute, is_canonical=True).exclude(
        pk=domain.pk
    ).update(is_canonical=False)
    domain.is_active = True
    domain.is_canonical = True
    domain.save(update_fields=["is_active", "is_canonical", "updated_at"])
    TenancyAuditEvent.objects.create(
        actor=actor,
        action="domain.activate",
        hostname=domain.hostname,
        institute=institute,
        detail={"canonical": True},
    )
    return domain


@transaction.atomic
def revoke_domain(*, hostname: str, actor=None) -> InstituteDomain:
    hostname = normalize_hostname(hostname)
    domain = InstituteDomain.objects.select_for_update().get(hostname=hostname)
    domain.is_active = False
    domain.is_canonical = False
    domain.save(update_fields=["is_active", "is_canonical", "updated_at"])
    TenancyAuditEvent.objects.create(
        actor=actor,
        action="domain.revoke",
        hostname=domain.hostname,
        institute=domain.institute,
        detail={},
    )
    return domain
