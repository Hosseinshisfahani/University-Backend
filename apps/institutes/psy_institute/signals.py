"""Psychology reactions to shared-module events. Other institutes are ignored."""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.kernel.tenancy.signals import membership_created, membership_roles_changed

from apps.modules.booking.models import Provider
from apps.modules.booking.signals import (
    appointment_booked,
    appointment_cancelled,
    appointment_completed,
    appointment_confirmed,
    appointment_moved,
    leave_decided,
)
from apps.modules.shop.signals import order_paid, order_shipped

from .models import PatientProfile, TherapistProfile
from .services.notify import notify_appointment, notify_leave, notify_order


def _psy_owned(obj) -> bool:
    institute = getattr(obj, "institute", None)
    slug = getattr(institute, "slug", None)
    if slug:
        return slug == "psy"
    institute_id = getattr(obj, "institute_id", None)
    if not institute_id:
        return False
    from apps.kernel.tenancy.models import Institute

    return Institute.objects.filter(pk=institute_id, slug="psy").exists()


def _provision_psy_patient(institute, user, roles, provision=True, **kwargs):
    """Create the clinical profile only for a psy member role."""
    if not provision or getattr(institute, "slug", None) != "psy":
        return
    if "member" not in (roles or []):
        return
    PatientProfile.objects.get_or_create(
        user=user,
        defaults={"phone": getattr(user, "phone", "") or ""},
    )


@receiver(post_save, sender=TherapistProfile)
def ensure_booking_provider(sender, instance, **kwargs):
    provider, _ = Provider.objects.update_or_create(
        institute_id=instance.institute_id,
        user_id=instance.user_id,
        defaults={
            "display_name": instance.display_name,
            "is_active": instance.is_active,
            "is_accepting": instance.is_accepting_patients,
        },
    )
    if instance.provider_id != provider.id:
        TherapistProfile.objects.filter(pk=instance.pk).update(provider_id=provider.id)
        instance.provider_id = provider.id


@receiver(membership_created)
def provision_patient_on_membership(sender, institute, user, roles, **kwargs):
    _provision_psy_patient(institute, user, roles, **kwargs)


@receiver(membership_roles_changed)
def provision_patient_on_role_change(sender, institute, user, roles, **kwargs):
    _provision_psy_patient(institute, user, roles, **kwargs)


@receiver(appointment_booked)
def sms_appointment_booked(sender, appointment, **kwargs):
    if _psy_owned(appointment):
        notify_appointment(appointment, "booked")


@receiver(appointment_confirmed)
def sms_appointment_confirmed(sender, appointment, **kwargs):
    if _psy_owned(appointment):
        notify_appointment(appointment, "confirmed")


@receiver(appointment_cancelled)
def sms_appointment_cancelled(sender, appointment, **kwargs):
    if _psy_owned(appointment):
        notify_appointment(appointment, "canceled")


@receiver(appointment_completed)
def sms_appointment_completed(sender, appointment, **kwargs):
    if _psy_owned(appointment):
        notify_appointment(appointment, "completed")


@receiver(appointment_moved)
def sms_appointment_moved(sender, appointment, **kwargs):
    if _psy_owned(appointment):
        notify_appointment(appointment, "moved")


@receiver(leave_decided)
def sms_leave_decided(sender, leave, decision, **kwargs):
    if _psy_owned(leave):
        notify_leave(leave, decision)


@receiver(order_paid)
def sms_order_paid(sender, order, **kwargs):
    if _psy_owned(order):
        notify_order(order, "paid")


@receiver(order_shipped)
def sms_order_shipped(sender, order, **kwargs):
    if _psy_owned(order):
        notify_order(order, "shipped")
