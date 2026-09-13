import hashlib

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SmsMessage
from .permissions import IsSmsAdmin
from .services import send_sms

User = get_user_model()

ROLE_GROUPS = {
    "patient": "psy_patient",
    "therapist": "psy_therapist",
}


def _display_name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username


def _role_for_user(user) -> str:
    names = set(user.groups.values_list("name", flat=True))
    if "psy_therapist" in names:
        return "therapist"
    if "psy_patient" in names:
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


class AdminRecipientListView(APIView):
    permission_classes = [IsAuthenticated, IsSmsAdmin]

    def get(self, request):
        role = (request.query_params.get("role") or "").strip()
        q = (request.query_params.get("q") or "").strip()
        qs = User.objects.exclude(phone="").filter(phone__isnull=False).distinct()
        group = ROLE_GROUPS.get(role)
        if group:
            qs = qs.filter(groups__name=group)
        else:
            qs = qs.filter(groups__name__in=ROLE_GROUPS.values())
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
                "role": _role_for_user(user),
            }
            for user in qs
        ]
        return Response({"results": results})


class AdminSmsSendView(APIView):
    permission_classes = [IsAuthenticated, IsSmsAdmin]

    def post(self, request):
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
        users = User.objects.filter(pk__in=ids)
        digest = hashlib.sha256(message.encode()).hexdigest()[:8]
        sent = 0
        skipped = 0
        for user in users:
            row = send_sms(
                phone=user.phone,
                body=message,
                purpose=SmsMessage.Purpose.ADMIN_MANUAL,
                user=user,
                unique_id=f"admin:{request.user.pk}:{user.pk}:{digest}",
            )
            if row.status == SmsMessage.Status.SENT:
                sent += 1
            else:
                skipped += 1
        skipped += max(0, len(ids) - users.count())
        return Response({"sent": sent, "skipped": skipped})


class AdminSmsMessageListView(APIView):
    permission_classes = [IsAuthenticated, IsSmsAdmin]

    def get(self, request):
        qs = SmsMessage.objects.select_related("user").order_by("-created_at")
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
