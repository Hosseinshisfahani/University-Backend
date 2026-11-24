"""Bind a request host to a neutral platform or one active institute."""

from dataclasses import dataclass

from django.conf import settings
from django.http import Http404

from .domains import DomainError, normalize_hostname
from .models import InstituteDomain


@dataclass(frozen=True)
class HostBinding:
    kind: str
    slug: str = ""
    name: str = ""
    frontend_mode: str = ""
    canonical_hostname: str = ""


def neutral_hosts() -> set[str]:
    configured = getattr(settings, "TENANCY_NEUTRAL_HOSTS", None) or [
        "localhost",
        "127.0.0.1",
        "testserver",
    ]
    return {item.strip().lower() for item in configured if item}


def describe_host(raw_host: str) -> HostBinding:
    allow_port = bool(getattr(settings, "DEBUG", False))
    try:
        hostname = normalize_hostname(raw_host, allow_dev_port=allow_port)
    except DomainError:
        return HostBinding(kind="unknown")
    if hostname in neutral_hosts():
        return HostBinding(kind="platform")
    domain = (
        InstituteDomain.objects.filter(hostname=hostname)
        .select_related("institute")
        .first()
    )
    if domain is None:
        if allow_port:
            return HostBinding(kind="platform")
        return HostBinding(kind="unknown")
    if not domain.is_active or not domain.institute.is_active:
        return HostBinding(kind="inactive")
    canonical = (
        domain.institute.domains.filter(is_canonical=True, is_active=True)
        .values_list("hostname", flat=True)
        .first()
        or domain.hostname
    )
    return HostBinding(
        kind="institute",
        slug=domain.institute.slug,
        name=domain.institute.name,
        frontend_mode=domain.institute.frontend_mode,
        canonical_hostname=canonical,
    )


def require_host_agreement(request, institute) -> HostBinding:
    binding = getattr(request, "tenancy_host", None) or describe_host(request.get_host())
    if binding.kind in ("unknown", "inactive"):
        raise Http404("مرکز پیدا نشد.")
    if binding.kind == "institute" and binding.slug != institute.slug:
        raise Http404("مرکز پیدا نشد.")
    return binding


def public_config(institute, binding: HostBinding | None = None) -> dict:
    frontend = (institute.settings or {}).get("frontend") or {}
    branding = {
        key: frontend.get(key)
        for key in ("name", "logo_url", "primary")
        if frontend.get(key)
    }
    navigation = frontend.get("navigation") if isinstance(frontend.get("navigation"), list) else []
    origin = ""
    if binding and binding.canonical_hostname:
        origin = f"https://{binding.canonical_hostname}"
    return {
        "slug": institute.slug,
        "name": institute.name,
        "frontend_mode": institute.frontend_mode,
        "canonical_origin": origin,
        "enabled_modules": list(institute.enabled_modules or []),
        "branding": branding,
        "navigation": navigation,
    }
