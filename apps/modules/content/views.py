from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import SAFE_METHODS
from rest_framework.viewsets import ModelViewSet

from apps.kernel.tenancy.permissions import IsInstituteAdminOrReadOnly
from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.kernel.tenancy.services import is_institute_admin

from .models import NewsSlide, Post, SitePage
from .serializers import NewsSlideSerializer, PostSerializer, SitePageSerializer


class PostPagination(PageNumberPagination):
    page_size = 9
    page_size_query_param = "page_size"
    max_page_size = 50


class _HideForeignWrites:
    """A caller who is not this institute's admin gets 404 on writes."""

    def check_permissions(self, request):
        if request.method not in SAFE_METHODS and not is_institute_admin(
            request.user, self.institute.slug
        ):
            raise NotFound()
        super().check_permissions(request)


class _PublishedMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve") and not is_institute_admin(
            self.request.user, self.institute.slug
        ):
            return qs.filter(is_published=True)
        return qs


class PostViewSet(_HideForeignWrites, InstituteScopedMixin, _PublishedMixin, ModelViewSet):
    required_module = "content"
    queryset = Post.objects.select_related("author")
    serializer_class = PostSerializer
    lookup_field = "slug"
    permission_classes = [IsInstituteAdminOrReadOnly]
    pagination_class = PostPagination

    def _stamp_published_at(self, serializer):
        is_published = serializer.validated_data.get(
            "is_published",
            getattr(serializer.instance, "is_published", False) if serializer.instance else False,
        )
        published_at = serializer.validated_data.get(
            "published_at",
            getattr(serializer.instance, "published_at", None) if serializer.instance else None,
        )
        if is_published and published_at is None:
            serializer.validated_data["published_at"] = timezone.now()

    def perform_create(self, serializer):
        self._stamp_published_at(serializer)
        serializer.save(institute=self.institute, author=self.request.user)

    def perform_update(self, serializer):
        self._stamp_published_at(serializer)
        serializer.save()


class NewsSlideViewSet(_HideForeignWrites, InstituteScopedMixin, _PublishedMixin, ModelViewSet):
    required_module = "content"
    queryset = NewsSlide.objects.all()
    serializer_class = NewsSlideSerializer
    permission_classes = [IsInstituteAdminOrReadOnly]


class SitePageViewSet(_HideForeignWrites, InstituteScopedMixin, ModelViewSet):
    required_module = "content"
    queryset = SitePage.objects.all()
    serializer_class = SitePageSerializer
    lookup_field = "key"
    permission_classes = [IsInstituteAdminOrReadOnly]
