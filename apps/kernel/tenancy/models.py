from django.conf import settings
from django.db import models

from apps.kernel.core.models import TimeStampedModel


class InstituteQuerySet(models.QuerySet):
    def for_institute(self, institute):
        return self.filter(institute=institute)


class Institute(TimeStampedModel):
    class FrontendMode(models.TextChoices):
        STANDARD = "standard", "استاندارد"
        CUSTOM = "custom", "سفارشی"

    slug = models.SlugField(max_length=64, unique=True, verbose_name="شناسه")
    name = models.CharField(max_length=200, verbose_name="نام")
    is_active = models.BooleanField(default=False, verbose_name="فعال")
    enabled_modules = models.JSONField(default=list, verbose_name="ماژول‌های فعال")
    frontend_mode = models.CharField(
        max_length=16,
        choices=FrontendMode.choices,
        default=FrontendMode.STANDARD,
        verbose_name="حالت فرانت",
    )
    settings = models.JSONField(default=dict, blank=True, verbose_name="تنظیمات")

    class Meta:
        verbose_name = "مرکز"
        verbose_name_plural = "مراکز"
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug

    def module_enabled(self, module_id: str) -> bool:
        return module_id in (self.enabled_modules or [])


class InstituteMembership(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="institute_memberships",
        verbose_name="کاربر",
    )
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="مرکز",
    )
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = "عضویت مرکز"
        verbose_name_plural = "عضویت‌های مرکز"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "institute"],
                name="uniq_membership_user_institute",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.institute_id}"


class InstituteMembershipRole(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = "admin", "مدیر"
        STAFF = "staff", "کارشناس"
        MEMBER = "member", "عضو"

    membership = models.ForeignKey(
        InstituteMembership,
        on_delete=models.CASCADE,
        related_name="role_rows",
        verbose_name="عضویت",
    )
    role = models.CharField(max_length=16, choices=Role.choices, verbose_name="نقش")

    class Meta:
        verbose_name = "نقش عضویت"
        verbose_name_plural = "نقش‌های عضویت"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "role"],
                name="uniq_membership_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.membership_id}:{self.role}"


class InstituteScopedModel(TimeStampedModel):
    """Abstract row owned by exactly one institute.

    Shared modules use this. Caller-supplied institute values are ignored
    by the scoping mixin; the URL slug decides ownership.
    """

    institute = models.ForeignKey(
        Institute,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="مرکز",
    )

    objects = InstituteQuerySet.as_manager()

    class Meta:
        abstract = True


class InstituteDomain(TimeStampedModel):
    """One hostname owned by one institute. Canonical implies active."""

    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="domains",
        verbose_name="مرکز",
    )
    hostname = models.CharField(max_length=253, unique=True, verbose_name="میزبان")
    is_active = models.BooleanField(default=False, verbose_name="فعال")
    is_canonical = models.BooleanField(default=False, verbose_name="اصلی")
    verification_token_hash = models.CharField(max_length=64, blank=True)
    verification_expires_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    tls_ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "دامنه مرکز"
        verbose_name_plural = "دامنه‌های مرکز"
        constraints = [
            models.UniqueConstraint(
                fields=["institute"],
                condition=models.Q(is_canonical=True),
                name="uniq_canonical_domain_per_institute",
            ),
            models.CheckConstraint(
                condition=models.Q(is_canonical=False) | models.Q(is_active=True),
                name="canonical_domain_is_active",
            ),
        ]

    def __str__(self) -> str:
        return self.hostname


class TenancyAuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=64)
    hostname = models.CharField(max_length=253, blank=True)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
