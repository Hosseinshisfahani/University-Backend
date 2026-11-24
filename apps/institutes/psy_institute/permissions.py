from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.kernel.tenancy.registry import BOOTSTRAP_INSTITUTE_SLUG
from apps.kernel.tenancy.services import user_has_role


def _psy_role(user, role: str) -> bool:
    return user_has_role(user, BOOTSTRAP_INSTITUTE_SLUG, role)


class IsPsyAdmin(BasePermission):
    message = "این بخش فقط برای مدیر کلینیک در دسترس است."

    def has_permission(self, request, view):
        return _psy_role(request.user, "admin")


class IsTherapist(BasePermission):
    def has_permission(self, request, view):
        return _psy_role(request.user, "staff") and hasattr(request.user, "therapist_profile")


class IsPatient(BasePermission):
    def has_permission(self, request, view):
        return _psy_role(request.user, "member") and hasattr(request.user, "patient_profile")


class IsPsyAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return IsPsyAdmin().has_permission(request, view)


class IsAuthenticatedOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)
