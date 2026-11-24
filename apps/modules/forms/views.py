from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response as DrfResponse
from rest_framework.viewsets import ModelViewSet

from apps.kernel.tenancy.permissions import IsInstituteAdminOrReadOnly, IsInstituteMember
from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.kernel.tenancy.services import is_institute_admin

from .models import Form, Response
from .serializers import FormSerializer, ResponseSerializer
from .services import FormsError, publish_schema, submit_response


class _HideForeignWrites:
    def check_permissions(self, request):
        if getattr(self, "action", None) == "submit":
            super().check_permissions(request)
            return
        if request.method not in SAFE_METHODS and not is_institute_admin(
            request.user, self.institute.slug
        ):
            raise NotFound()
        super().check_permissions(request)


class FormViewSet(_HideForeignWrites, InstituteScopedMixin, ModelViewSet):
    required_module = "forms"
    queryset = Form.objects.all()
    serializer_class = FormSerializer
    lookup_field = "slug"
    permission_classes = [IsInstituteAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve", "submit") and not is_institute_admin(
            self.request.user, self.institute.slug
        ):
            return qs.filter(is_published=True)
        return qs

    def perform_create(self, serializer):
        form = serializer.save(institute=self.institute, created_by=self.request.user)
        publish_schema(form=form, schema=form.schema)

    def perform_update(self, serializer):
        schema = serializer.validated_data.get("schema", serializer.instance.schema)
        form = serializer.save()
        publish_schema(form=form, schema=schema)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsInstituteMember],
        url_path="submit",
    )
    def submit(self, request, institute_slug=None, slug=None):
        form = self.get_object()
        answers = request.data.get("answers") or {}
        try:
            row = submit_response(form=form, respondent=request.user, answers=answers)
        except FormsError as exc:
            return DrfResponse({"detail": str(exc)}, status=400)
        return DrfResponse(ResponseSerializer(row).data, status=201)


class ResponseViewSet(InstituteScopedMixin, ModelViewSet):
    required_module = "forms"
    queryset = Response.objects.select_related("version", "respondent")
    serializer_class = ResponseSerializer
    permission_classes = [IsAuthenticated, IsInstituteMember]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if is_institute_admin(self.request.user, self.institute.slug):
            return qs
        return qs.filter(respondent=self.request.user)
