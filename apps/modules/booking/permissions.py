from rest_framework.permissions import BasePermission

from apps.kernel.tenancy.services import user_has_role

from .models import Provider


def _institute(view):
    return getattr(view, "institute", None)


class IsBookingAdmin(BasePermission):
    def has_permission(self, request, view):
        institute = _institute(view)
        return bool(institute and user_has_role(request.user, institute.slug, "admin"))


class IsProvider(BasePermission):
    """Staff membership plus a provider row in this institute."""

    def has_permission(self, request, view):
        institute = _institute(view)
        user = request.user
        if not institute or not user_has_role(user, institute.slug, "staff"):
            return False
        return Provider.objects.filter(institute=institute, user=user, is_active=True).exists()


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        institute = _institute(view)
        return bool(institute and user_has_role(request.user, institute.slug, "member"))
