from django.http import Http404

from .hosts import require_host_agreement
from .models import Institute
from .registry import REGISTRY


class InstituteScopedMixin:
    """Resolve ``institute_slug`` and force every queryset through it.

    Direct ``Model.objects.get`` calls are not covered. Views must use
    ``get_queryset``.
    """

    required_module: str | None = None

    def initial(self, request, *args, **kwargs):
        slug = kwargs.get("institute_slug") or getattr(self, "kwargs", {}).get("institute_slug")
        try:
            institute = Institute.objects.get(slug=slug)
        except Institute.DoesNotExist as exc:
            raise Http404("مرکز پیدا نشد.") from exc
        if not institute.is_active:
            raise Http404("مرکز پیدا نشد.")
        require_host_agreement(request, institute)
        if self.required_module:
            if self.required_module not in REGISTRY:
                raise Http404("ماژول پیدا نشد.")
            if not institute.module_enabled(self.required_module):
                raise Http404("ماژول پیدا نشد.")
        self.institute = institute
        super().initial(request, *args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().filter(institute=self.institute)

    def perform_create(self, serializer):
        serializer.save(institute=self.institute)
