"""Django admin for institute-owned module models.

Superusers see every institute. Other staff see institutes they administer.
A legacy psychology model permission still grants the psychology institute,
so existing staff grants keep working after the table moved.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied

from apps.kernel.tenancy.models import Institute, InstituteMembership, InstituteMembershipRole

_LEGACY_APP = "psy_institute"
_LEGACY_ACTIONS = ("view", "add", "change", "delete")


def _has_model_perm(user, app_label: str, model_name: str, actions) -> bool:
    return any(user.has_perm(f"{app_label}.{action}_{model_name}") for action in actions)


def _admin_institute_ids(user) -> set[int]:
    return set(
        InstituteMembership.objects.filter(
            user=user,
            is_active=True,
            institute__is_active=True,
            role_rows__role=InstituteMembershipRole.Role.ADMIN,
        ).values_list("institute_id", flat=True)
    )


def _related_has_institute(model) -> bool:
    return any(field.name == "institute" for field in model._meta.fields)


class _MatchingInstituteForm(forms.ModelForm):
    institute_parents: tuple[str, ...] = ()

    def clean(self):
        cleaned = super().clean()
        institute = cleaned.get("institute")
        for name in self.institute_parents:
            parent = cleaned.get(name)
            if parent is None or institute is None:
                continue
            parent_institute_id = getattr(parent, "institute_id", None)
            if parent_institute_id and parent_institute_id != institute.pk:
                self.add_error(name, "This record belongs to another institute.")
        return cleaned


def _matching_institute_form(parent_names: tuple[str, ...]):
    class Form(_MatchingInstituteForm):
        institute_parents = parent_names

    return Form


class ModuleAdmin(admin.ModelAdmin):
    """Register a shared-module model in place of a frozen psychology model."""

    legacy_model = ""
    institute_path = "institute"
    institute_parents: tuple[str, ...] = ()

    def get_form(self, request, obj=None, **kwargs):
        if self.institute_parents and kwargs.get("form") is None and self.form is admin.ModelAdmin.form:
            kwargs["form"] = _matching_institute_form(self.institute_parents)
        return super().get_form(request, obj, **kwargs)

    def get_list_display(self, request):
        display = list(super().get_list_display(request))
        if self.institute_path == "institute" and "institute" not in display:
            display.append("institute")
        return display

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if self.institute_path == "institute" and "institute" not in filters:
            filters.append("institute")
        return filters

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        scoped = self._scoped_ids(request)
        if scoped is None:
            return queryset
        return queryset.filter(**{f"{self._lookup()}__in": scoped})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        scoped = self._scoped_ids(request)
        if scoped is not None:
            related = db_field.remote_field.model
            if db_field.name == "institute":
                kwargs["queryset"] = Institute.objects.filter(pk__in=scoped)
            elif _related_has_institute(related):
                kwargs["queryset"] = related._default_manager.filter(institute_id__in=scoped)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        scoped = self._scoped_ids(request)
        if scoped is not None and self._institute_id(obj) not in scoped:
            raise PermissionDenied("This record is outside the institutes you administer.")
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        if super().has_module_permission(request):
            return True
        return self._legacy(request, _LEGACY_ACTIONS)

    def has_view_permission(self, request, obj=None):
        if not self._in_scope(request, obj):
            return False
        if super().has_view_permission(request, obj):
            return True
        return self._legacy(request, ("view", "change"))

    def has_add_permission(self, request):
        if super().has_add_permission(request):
            return True
        return self._legacy(request, ("add",))

    def has_change_permission(self, request, obj=None):
        if not self._in_scope(request, obj):
            return False
        if super().has_change_permission(request, obj):
            return True
        return self._legacy(request, ("change",))

    def has_delete_permission(self, request, obj=None):
        if not self._in_scope(request, obj):
            return False
        if super().has_delete_permission(request, obj):
            return True
        return self._legacy(request, ("delete",))

    def _legacy(self, request, actions) -> bool:
        if not self.legacy_model:
            return False
        return _has_model_perm(request.user, _LEGACY_APP, self.legacy_model, actions)

    def _scoped_ids(self, request):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return set()
        if user.is_superuser:
            return None
        ids = _admin_institute_ids(user)
        if self._legacy(request, _LEGACY_ACTIONS):
            psy_id = Institute.objects.filter(slug="psy").values_list("pk", flat=True).first()
            if psy_id is not None:
                ids.add(psy_id)
        return ids

    def _lookup(self) -> str:
        path = self.institute_path
        if path.endswith("_id"):
            return path
        return f"{path}_id"

    def _institute_id(self, obj):
        current = obj
        for part in self.institute_path.split("__"):
            current = getattr(current, part, None)
            if current is None:
                return None
        return getattr(current, "pk", current)

    def _in_scope(self, request, obj) -> bool:
        if obj is None:
            return True
        scoped = self._scoped_ids(request)
        if scoped is None:
            return True
        return self._institute_id(obj) in scoped
