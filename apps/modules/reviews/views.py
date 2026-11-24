"""Generic review reads and moderation. Clients name a target kind, never a content type."""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.tenancy.permissions import IsInstituteAdmin
from apps.kernel.tenancy.scoping import InstituteScopedMixin
from apps.modules.booking.models import Provider

from .models import Review
from .serializers import ReviewSerializer
from .services import ReviewsError, moderate_review, reviews_for_target

_TARGETS = {"provider": Provider}


class ReviewListView(InstituteScopedMixin, APIView):
    required_module = "reviews"
    permission_classes = [AllowAny]

    def get(self, request, institute_slug=None):
        kind = request.query_params.get("target")
        raw_id = request.query_params.get("target_id")
        model = _TARGETS.get(kind or "")
        if model is None or not (raw_id or "").isdigit():
            return Response({"detail": "target must be provider and target_id is required."}, status=400)
        target = get_object_or_404(model, pk=int(raw_id), institute=self.institute)
        qs = (
            reviews_for_target(self.institute, target)
            .filter(text_status=Review.TextStatus.APPROVED)
            .exclude(body="")
            .select_related("author")
            .order_by("-created_at")[:100]
        )
        return Response(ReviewSerializer(qs, many=True).data)


class ModerationListView(InstituteScopedMixin, APIView):
    required_module = "reviews"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def get(self, request, institute_slug=None):
        qs = Review.objects.filter(institute=self.institute).select_related("author").order_by("-created_at")
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(text_status=status_param)
        return Response(ReviewSerializer(qs[:200], many=True).data)


class ModerationActionView(InstituteScopedMixin, APIView):
    required_module = "reviews"
    permission_classes = [IsAuthenticated, IsInstituteAdmin]

    def post(self, request, pk, action, institute_slug=None):
        review = get_object_or_404(Review, pk=pk, institute=self.institute)
        status = Review.TextStatus.APPROVED if action == "approve" else Review.TextStatus.REJECTED
        if action not in {"approve", "reject"}:
            return Response({"detail": "Unknown action."}, status=404)
        try:
            review = moderate_review(
                review=review,
                status=status,
                reviewer=request.user,
                admin_note=request.data.get("admin_note", ""),
            )
        except ReviewsError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(ReviewSerializer(review).data)
