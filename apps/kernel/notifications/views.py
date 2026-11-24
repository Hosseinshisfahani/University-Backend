import hashlib

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.kernel.tenancy.models import Institute, InstituteMembershipRole
from apps.kernel.tenancy.registry import BOOTSTRAP_INSTITUTE_SLUG
from apps.kernel.tenancy.services import is_institute_admin, user_has_role

from .models import SmsMessage
from .services import send_sms

User = get_user_model()

PLATFORM_PURPOSES = {
    SmsMessage.Purpose.OTP_REGISTER,
    SmsMessage.Purpose.OTP_PASSWORD_RESET,
}
ROLE_QUERY = {
    "patient": InstituteMembershipRole.Role.MEMBER,
    "therapist": InstituteMembershipRole.Role.STAFF,
}


def _display_name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


def _institute_slug(request) -> str:
    raw = ""
    if hasattr(request, "query_params"):
        raw = (request.query_params.get("institute") or "").strip()
    if not raw and hasattr(request, "data"):
        raw = str(request.data.get("institute") or "").strip()
    return raw or BOOTSTRAP_INSTITUTE_SLUG


def _role_label(user, slug: str) -> str:
    if user_has_role(user, slug, InstituteMembershipRole.Role.STAFF):
        return "therapist"
    if user_has_role(user, slug, InstituteMembershipRole.Role.MEMBER):
        return "patient"
    return ""


def _paginate(qs, request, *, default_size=25):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(
            100, max(1, int(request.query_params.get("page_size", default_size)))
        )
    except (TypeError, ValueError):
        page_size = default_size
    total = qs.count()
    start = (page - 1) * page_size
    return page, page_size, total, qs[start : start + page_size]


class IsInstituteSmsAdmin(BasePermission):
    """Institute admin for the requested center. Staff without that role is refused."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        slug = _institute_slug(request)
        request.sms_institute_slug = slug
        return is_institute_admin(user, slug)


class AdminRecipientListView(APIView):
    permission_classes = [IsAuthenticated, IsInstituteSmsAdmin]

    def get(self, request):
        slug = request.sms_institute_slug
        role = ROLE_QUERY.get((request.query_params.get("role") or "").strip())
        roles = [role] if role else [
            InstituteMembershipRole.Role.MEMBER,
            InstituteMembershipRole.Role.STAFF,
        ]
        q = (request.query_params.get("q") or "").strip()
        qs = User.objects.exclude(phone="").filter(
            phone__isnull=False,
            institute_memberships__institute__slug=slug,
            institute_memberships__is_active=True,
            institute_memberships__role_rows__role__in=roles,
        )
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(phone__icontains=q)
            )
        qs = qs.order_by("first_name", "last_name", "username").distinct()[:100]
        results = [
            {
                "id": user.pk,
                "username": user.username,
                "display_name": _display_name(user),
                "phone": user.phone,
                "role": _role_label(user, slug),
            }
            for user in qs
        ]
        return Response({"results": results})


class AdminSmsSendView(APIView):
    permission_classes = [IsAuthenticated, IsInstituteSmsAdmin]

    def post(self, request):
        slug = request.sms_institute_slug
        try:
            institute = Institute.objects.get(slug=slug, is_active=True)
        except Institute.DoesNotExist:
            return Response({"detail": "مرکز پیدا نشد."}, status=status.HTTP_404_NOT_FOUND)
        user_ids = request.data.get("user_ids") or []
        message = (request.data.get("message") or "").strip()
        if not message or not user_ids:
            return Response(
                {"detail": "گیرنده و متن پیام الزامی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ids = [int(pk) for pk in user_ids]
        except (TypeError, ValueError):
            return Response(
                {"detail": "شناسه کاربران نامعتبر است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        users = list(
            User.objects.filter(
                pk__in=ids,
                institute_memberships__institute=institute,
                institute_memberships__is_active=True,
            ).distinct()
        )
        digest = hashlib.sha256(message.encode()).hexdigest()[:8]
        sent = 0
        skipped = 0
        for user in users:
            row = send_sms(
                phone=user.phone,
                body=message,
                purpose=SmsMessage.Purpose.ADMIN_MANUAL,
                user=user,
                institute=institute,
                unique_id=f"admin:{request.user.pk}:{user.pk}:{digest}",
            )
            if row.status == SmsMessage.Status.SENT:
                sent += 1
            else:
                skipped += 1
        skipped += max(0, len(ids) - len(users))
        return Response({"sent": sent, "skipped": skipped})


class AdminSmsMessageListView(APIView):
    permission_classes = [IsAuthenticated, IsInstituteSmsAdmin]

    def get(self, request):
        slug = request.sms_institute_slug
        qs = (
            SmsMessage.objects.select_related("user")
            .filter(institute__slug=slug)
            .exclude(purpose__in=PLATFORM_PURPOSES)
            .order_by("-created_at")
        )
        page, page_size, total, items = _paginate(qs, request)
        results = [
            {
                "id": row.pk,
                "phone": row.phone,
                "purpose": row.purpose,
                "status": row.status,
                "body": row.body,
                "user": row.user_id,
                "created_at": row.created_at,
            }
            for row in items
        ]
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )
