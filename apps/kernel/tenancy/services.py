"""Membership writes. Psy roles also update the legacy groups for one release."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.db import transaction

from .models import Institute, InstituteMembership, InstituteMembershipRole
from .registry import BOOTSTRAP_INSTITUTE_SLUG, validate_enabled_modules
from .signals import membership_created, membership_roles_changed

PSY_GROUP_FOR_ROLE = {
    InstituteMembershipRole.Role.ADMIN: "psy_admin",
    InstituteMembershipRole.Role.STAFF: "psy_therapist",
    InstituteMembershipRole.Role.MEMBER: "psy_patient",
}
PSY_ROLE_FOR_GROUP = {group: role for role, group in PSY_GROUP_FOR_ROLE.items()}
ROLE_VALUES = set(PSY_GROUP_FOR_ROLE)


class TenancyError(Exception):
    pass


def get_institute(slug: str) -> Institute:
    try:
        return Institute.objects.get(slug=slug)
    except Institute.DoesNotExist as exc:
        raise TenancyError("مرکز پیدا نشد.") from exc


def set_enabled_modules(institute: Institute, modules: list[str]) -> Institute:
    cleaned = validate_enabled_modules(institute.slug, list(modules))
    institute.enabled_modules = cleaned
    institute.save(update_fields=["enabled_modules", "updated_at"])
    return institute


def memberships_payload(user) -> list[dict]:
    if not user or not getattr(user, "is_authenticated", False):
        return []
    rows = (
        InstituteMembership.objects.filter(
            user=user,
            is_active=True,
            institute__is_active=True,
        )
        .select_related("institute")
        .prefetch_related("role_rows")
    )
    payload = []
    for membership in rows:
        roles = sorted({row.role for row in membership.role_rows.all()})
        if not roles:
            continue
        payload.append({"institute": membership.institute.slug, "roles": roles})
    return payload


def user_has_role(user, slug: str, role: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return InstituteMembershipRole.objects.filter(
        role=role,
        membership__user=user,
        membership__is_active=True,
        membership__institute__slug=slug,
        membership__institute__is_active=True,
    ).exists()


def is_institute_admin(user, slug: str) -> bool:
    return user_has_role(user, slug, InstituteMembershipRole.Role.ADMIN)


_ADAPTERS: dict[str, object] = {}


def register_institute_adapter(slug: str, adapter) -> None:
    """An institute adds its own fields without the shared modules importing it."""
    _ADAPTERS[slug] = adapter


def _adapter(institute):
    if institute is None:
        return None
    return _ADAPTERS.get(getattr(institute, "slug", None))


def extend_payload(institute, kind: str, obj, data: dict) -> dict:
    """Let the institute adapter add keys. The default payload is unchanged."""
    adapter = _adapter(institute)
    method = getattr(adapter, "extend_payload", None)
    if method is None:
        return data
    return method(kind, obj, data)


def normalize_input(institute, kind: str, data: dict) -> dict:
    """Let the institute adapter translate legacy write keys before validation."""
    adapter = _adapter(institute)
    method = getattr(adapter, "normalize_input", None)
    if method is None:
        return data
    return method(kind, data)


def person_name(institute, user) -> str | None:
    """Display name for a user. The adapter may prefer an institute profile name."""
    if user is None:
        return None
    adapter = _adapter(institute)
    method = getattr(adapter, "person_name", None)
    if method is not None:
        name = method(user)
        if name:
            return name
    full = (user.get_full_name() or "").strip()
    return full or user.username


def _sync_psy_groups(user, roles: set[str]) -> None:
    """Keep legacy psy groups aligned with psy membership roles."""
    desired = {PSY_GROUP_FOR_ROLE[role] for role in roles if role in PSY_GROUP_FOR_ROLE}
    legacy_names = set(PSY_GROUP_FOR_ROLE.values())
    current = set(user.groups.filter(name__in=legacy_names).values_list("name", flat=True))
    for name in desired - current:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    remove = current - desired
    if remove:
        user.groups.remove(*Group.objects.filter(name__in=remove))


def _role_set(membership: InstituteMembership) -> set[str]:
    return set(membership.role_rows.values_list("role", flat=True))


@transaction.atomic
def grant_roles(
    *,
    user,
    institute: Institute,
    roles: list[str] | set[str],
    replace: bool = False,
    provision: bool = True,
    allow_inactive: bool = False,
) -> InstituteMembership:
    """Add roles, or replace the set when ``replace`` is true.

    An active membership must end with at least one role. Psy memberships
    also write the legacy groups so the previously deployed frontend works.
    """
    requested = set(roles)
    unknown = requested - ROLE_VALUES
    if unknown:
        raise TenancyError(f"نقش نامعتبر: {', '.join(sorted(unknown))}")
    if not institute.is_active and not allow_inactive:
        raise TenancyError("مرکز غیرفعال است.")

    membership, created = InstituteMembership.objects.get_or_create(
        user=user,
        institute=institute,
        defaults={"is_active": True},
    )
    if not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])

    current = _role_set(membership)
    target = requested if replace else current | requested
    if not target:
        raise TenancyError("عضویت فعال حداقل یک نقش لازم دارد.")

    for role in target - current:
        InstituteMembershipRole.objects.create(membership=membership, role=role)
    if replace:
        membership.role_rows.exclude(role__in=target).delete()

    if institute.slug == BOOTSTRAP_INSTITUTE_SLUG:
        _sync_psy_groups(user, target)

    payload = {
        "institute": institute,
        "user": user,
        "roles": sorted(target),
        "provision": provision,
    }
    if created:
        membership_created.send(sender=InstituteMembership, **payload)
    elif target != current:
        membership_roles_changed.send(sender=InstituteMembership, **payload)
    return membership


def grant_psy_role(user, role: str, *, provision_profile: bool = True) -> InstituteMembership:
    """Test and seed helper. ``role`` is admin, staff, or member."""
    institute = Institute.objects.get(slug=BOOTSTRAP_INSTITUTE_SLUG)
    return grant_roles(
        user=user,
        institute=institute,
        roles=[role],
        provision=provision_profile,
    )


def revoke_role(*, user, institute: Institute, role: str) -> None:
    membership = InstituteMembership.objects.filter(user=user, institute=institute).first()
    if membership is None:
        return
    membership.role_rows.filter(role=role).delete()
    remaining = _role_set(membership)
    if not remaining:
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
    if institute.slug == BOOTSTRAP_INSTITUTE_SLUG:
        _sync_psy_groups(user, remaining)
    membership_roles_changed.send(
        sender=InstituteMembership,
        institute=institute,
        user=user,
        roles=sorted(remaining),
        provision=True,
    )
