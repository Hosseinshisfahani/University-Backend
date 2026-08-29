from rest_framework.permissions import BasePermission, SAFE_METHODS, IsAuthenticated


def _in_group(user, name: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=name).exists()


class IsPsyAdmin(BasePermission):
    message = "این بخش فقط برای مدیر کلینیک در دسترس است."

    def has_permission(self, request, view):
        return _in_group(request.user, "psy_admin") or (
            request.user and request.user.is_staff
        )


class IsTherapist(BasePermission):
    def has_permission(self, request, view):
        return _in_group(request.user, "psy_therapist") and hasattr(
            request.user, "therapist_profile"
        )


class IsPatient(BasePermission):
    def has_permission(self, request, view):
        return _in_group(request.user, "psy_patient") and hasattr(
            request.user, "patient_profile"
        )


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
