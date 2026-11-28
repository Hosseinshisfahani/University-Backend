"""Thin /api/v1/psy/ wrappers over the shared shop, course, and content modules.

Payload aliases for the psychology screens are added by PsyAdapter, which the
app registers on the tenancy hook. These classes only pin the institute and
keep the psychology permission classes.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.modules.content.views import NewsSlideViewSet, PostViewSet, SitePageViewSet
from apps.modules.lms.views import (
    CourseResourceDetailView,
    CourseResourceListCreateView,
    CourseSessionDetailView,
    CourseSessionListCreateView,
    CourseViewSet,
    MyEnrollmentListView,
    TeachingCourseListView,
)
from apps.modules.shop.views import (
    AdminShopOrderDetailView,
    AdminShopOrderListView,
    AdminShopOrderRefundView,
    AdminShopStatsView,
    CartCouponView,
    CartItemDetailView,
    CartItemListView,
    CartView,
    CouponViewSet,
    ProductCategoryViewSet,
    ProductViewSet,
    ShopOrderViewSet,
)

from .permissions import IsPatient, IsPsyAdmin, IsPsyAdminOrReadOnly, IsTherapist


class _PsyModuleView:
    """Pin the psychology contract onto a module view. URLs stay /api/v1/psy/."""

    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def initial(self, request, *args, **kwargs):
        kwargs["institute_slug"] = "psy"
        super().initial(request, *args, **kwargs)


class PsyAdapter:
    """Adds psychology profile fields. Modules never import this class."""

    def person_name(self, user):
        from .models import TherapistProfile

        profile = getattr(user, "therapist_profile", None)
        if profile is None:
            profile = TherapistProfile.objects.filter(user_id=user.pk).first()
        if profile and profile.display_name:
            return profile.display_name
        return None

    def normalize_input(self, kind, data):
        if kind != "lms.course":
            return data
        raw = data.get("instructor_id")
        if raw in (None, ""):
            return data
        from .models import TherapistProfile

        profile = TherapistProfile.objects.filter(pk=raw).first()
        if profile is None:
            return {**dict(data), "_instructor_missing": True}
        return {**dict(data), "instructor_user_id": profile.user_id}

    def extend_payload(self, kind, obj, data):
        from .models import PatientProfile, TherapistProfile

        if kind == "content.post":
            author = getattr(obj, "author", None)
            profile = getattr(author, "therapist_profile", None) if author is not None else None
            data["author_therapist_id"] = profile.id if profile else None
        elif kind == "shop.order":
            data["patient_name"] = data.get("customer_name") or ""
        elif kind == "lms.course":
            profile = None
            if getattr(obj, "instructor_id", None):
                profile = TherapistProfile.objects.filter(user_id=obj.instructor_id).first()
            data["instructor_id"] = profile.id if profile else None
        elif kind == "lms.enrollment":
            data["workshop"] = data.get("course")
            data["workshop_title"] = data.get("course_title")
            data["workshop_slug"] = data.get("course_slug")
            data["workshop_starts_at"] = data.get("course_starts_at")
            data["workshop_ends_at"] = data.get("course_ends_at")
            data["workshop_banner_image"] = data.get("course_banner_image")
            profile = PatientProfile.objects.filter(user_id=obj.user_id).first()
            data["patient"] = profile.id if profile else None
            data["patient_name"] = data.get("user_name") or ""
            data["patient_phone"] = profile.phone if profile else ""
        return data


class _LegacyContentView:
    """Legacy writes stay 403. The module view answers 404 to a foreign admin."""

    def check_permissions(self, request):
        APIView.check_permissions(self, request)


class PsyBlogPostViewSet(_LegacyContentView, _PsyModuleView, PostViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]


class PsyNewsSlideViewSet(_LegacyContentView, _PsyModuleView, NewsSlideViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]


class PsySitePageViewSet(_LegacyContentView, _PsyModuleView, SitePageViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]


class PsyProductCategoryViewSet(_PsyModuleView, ProductCategoryViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]


class PsyProductViewSet(_PsyModuleView, ProductViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]


class PsyCouponViewSet(_PsyModuleView, CouponViewSet):
    permission_classes = [IsAuthenticated, IsPsyAdmin]


class PsyCartView(_PsyModuleView, CartView):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyCartItemListView(_PsyModuleView, CartItemListView):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyCartItemDetailView(_PsyModuleView, CartItemDetailView):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyCartCouponView(_PsyModuleView, CartCouponView):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyShopOrderViewSet(_PsyModuleView, ShopOrderViewSet):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyAdminShopOrderListView(_PsyModuleView, AdminShopOrderListView):
    pass


class PsyAdminShopOrderDetailView(_PsyModuleView, AdminShopOrderDetailView):
    pass


class PsyAdminShopOrderRefundView(_PsyModuleView, AdminShopOrderRefundView):
    pass


class PsyAdminShopStatsView(_PsyModuleView, AdminShopStatsView):
    pass


class PsyWorkshopViewSet(_PsyModuleView, CourseViewSet):
    permission_classes = [IsPsyAdminOrReadOnly]

    def check_permissions(self, request):
        action = getattr(self, "action", None)
        patient_actions = {
            "enroll",
            "confirm_enrollment",
            "pay_gateway",
            "complete_session",
            "issue_certificate",
            "get_certificate",
        }
        if action in patient_actions:
            if not IsPatient().has_permission(request, self):
                self.permission_denied(request)
            return
        if action == "cancel_enrollment":
            allowed = IsPatient().has_permission(request, self) or IsPsyAdmin().has_permission(
                request, self
            )
            if not allowed:
                self.permission_denied(request)
            return
        if action == "roster":
            if not IsAuthenticated().has_permission(request, self):
                self.permission_denied(request)
            return
        super().check_permissions(request)


class PsyWorkshopSessionListCreateView(_PsyModuleView, CourseSessionListCreateView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, workshop_slug, **kwargs):
        return super().get(request, course_slug=workshop_slug)

    def post(self, request, workshop_slug, **kwargs):
        return super().post(request, course_slug=workshop_slug)


class PsyWorkshopSessionDetailView(_PsyModuleView, CourseSessionDetailView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def patch(self, request, workshop_slug, pk, **kwargs):
        return super().patch(request, course_slug=workshop_slug, pk=pk)

    def delete(self, request, workshop_slug, pk, **kwargs):
        return super().delete(request, course_slug=workshop_slug, pk=pk)


class PsyWorkshopResourceListCreateView(_PsyModuleView, CourseResourceListCreateView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def get(self, request, workshop_slug, **kwargs):
        return super().get(request, course_slug=workshop_slug)

    def post(self, request, workshop_slug, **kwargs):
        return super().post(request, course_slug=workshop_slug)


class PsyWorkshopResourceDetailView(_PsyModuleView, CourseResourceDetailView):
    permission_classes = [IsAuthenticated, IsPsyAdmin]

    def patch(self, request, workshop_slug, pk, **kwargs):
        return super().patch(request, course_slug=workshop_slug, pk=pk)

    def delete(self, request, workshop_slug, pk, **kwargs):
        return super().delete(request, course_slug=workshop_slug, pk=pk)


class PsyPatientEnrollmentView(_PsyModuleView, MyEnrollmentListView):
    permission_classes = [IsAuthenticated, IsPatient]


class PsyTeachingCourseListView(_PsyModuleView, TeachingCourseListView):
    permission_classes = [IsAuthenticated, IsTherapist]
