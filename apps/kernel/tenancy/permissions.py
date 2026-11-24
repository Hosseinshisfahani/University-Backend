from rest_framework.permissions import SAFE_METHODS, BasePermission

from .services import user_has_role


def _role_ok(user, institute, roles: set[str]) -> bool:
    if institute is None:
        return False
    return any(user_has_role(user, institute.slug, role) for role in roles)


class IsInstituteMember(BasePermission):
    """Any active role on the institute resolved by the view."""

    def has_permission(self, request, view):
        institute = getattr(view, "institute", None)
        return _role_ok(request.user, institute, {"admin", "staff", "member"})


class IsInstituteStaff(BasePermission):
    def has_permission(self, request, view):
        institute = getattr(view, "institute", None)
        return _role_ok(request.user, institute, {"admin", "staff"})


class IsInstituteAdmin(BasePermission):
    def has_permission(self, request, view):
        institute = getattr(view, "institute", None)
        return _role_ok(request.user, institute, {"admin"})


class IsInstituteAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return IsInstituteAdmin().has_permission(request, view)


class HasMemberRole(BasePermission):
    """The member role on the institute resolved by the view."""

    def has_permission(self, request, view):
        institute = getattr(view, "institute", None)
        return _role_ok(request.user, institute, {"member"})
