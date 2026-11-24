from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.kernel.notifications.models import OtpChallenge
from apps.kernel.notifications.services import OtpError, request_otp, verify_otp
from apps.kernel.notifications.ssmss_client import normalize_phone

from .cookies import delete_jwt_cookies, set_access_cookie, set_refresh_cookie
from .csrf import CsrfOnMutation
from .models import User
from .serializers import (
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)

# The auth endpoints below disable the default cookie authentication class:
# they must work when the access token is missing or expired, and they
# operate on the (path-scoped) refresh cookie instead.


class LoginView(CsrfOnMutation, TokenObtainPairView):
    """
    Validates credentials and sets the access/refresh tokens as HttpOnly
    cookies. Tokens are never included in the response body.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        tokens = serializer.validated_data
        response = Response(
            {"user": UserSerializer(serializer.user).data},
            status=status.HTTP_200_OK,
        )
        set_access_cookie(response, tokens["access"])
        set_refresh_cookie(response, tokens["refresh"])
        return response


class RegisterView(CsrfOnMutation, APIView):
    """
    Self-serve registration. An institute slug joins that center as a member.
    Omitting it uses TENANCY_COMPAT_REGISTER_INSTITUTE (psy) for one release.
    The psy patient profile is created by the membership receiver, not here.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses={201: UserSerializer})
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        response = Response(
            {"user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )
        set_access_cookie(response, str(refresh.access_token))
        set_refresh_cookie(response, str(refresh))
        return response


class RegisterRequestOtpView(CsrfOnMutation, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
    def post(self, request):
        phone = request.data.get("phone", "")
        try:
            request_otp(phone=phone, purpose=OtpChallenge.Purpose.REGISTER)
        except OtpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "کد تایید ارسال شد."})


class PasswordResetRequestView(CsrfOnMutation, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = normalize_phone(serializer.validated_data["phone"])
        user = User.objects.filter(phone=phone).first()
        if user is None:
            return Response(
                {"detail": "حسابی با این شماره یافت نشد."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            request_otp(phone=phone, purpose=OtpChallenge.Purpose.PASSWORD_RESET)
        except OtpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "کد تایید ارسال شد."})


class PasswordResetConfirmView(CsrfOnMutation, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        try:
            verify_otp(
                phone=phone,
                purpose=OtpChallenge.Purpose.PASSWORD_RESET,
                code=serializer.validated_data["otp"],
            )
        except OtpError as exc:
            return Response({"otp": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(phone=phone).first()
        if user is None:
            return Response(
                {"detail": "حسابی با این شماره یافت نشد."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        return Response({"detail": "رمز عبور به‌روز شد."})


class RefreshView(CsrfOnMutation, TokenRefreshView):
    """
    Rotates the token pair using the refresh cookie and re-sets both
    cookies. The previous refresh token is blacklisted (rotation).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        raw_refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
        if raw_refresh is None:
            return Response(
                {"detail": "Refresh cookie missing."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.get_serializer(data={"refresh": raw_refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        tokens = serializer.validated_data
        response = Response({"detail": "Token refreshed."}, status=status.HTTP_200_OK)
        set_access_cookie(response, tokens["access"])
        if "refresh" in tokens:
            set_refresh_cookie(response, tokens["refresh"])
        return response


class LogoutView(CsrfOnMutation, APIView):
    """Blacklists the refresh token and clears both auth cookies."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: None})
    def post(self, request):
        raw_refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
        if raw_refresh is not None:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass  # already invalid/expired — clearing cookies is enough

        response = Response({"detail": "Logged out."}, status=status.HTTP_200_OK)
        delete_jwt_cookies(response)
        return response


class MeView(APIView):
    """Returns the authenticated user's profile (via the access cookie)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)


@method_decorator(ensure_csrf_cookie, name="get")
class CSRFView(APIView):
    """
    Sets the CSRF cookie. The frontend calls this once on startup, then
    echoes the cookie value in the X-CSRFToken header on mutations.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: None})
    def get(self, request):
        return Response({"detail": "CSRF cookie set."})
