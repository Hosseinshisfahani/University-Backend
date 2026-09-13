from django.utils import timezone

from apps.notifications.models import SmsMessage
from apps.notifications.services import send_sms


def _phone(user) -> str:
    return (getattr(user, "phone", None) or "").strip()


def _when(dt) -> str:
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


def _patient_name(appointment) -> str:
    user = appointment.patient.user
    return user.get_full_name() or user.username


def notify_appointment(appointment, event: str) -> None:
    """SMS both parties. Failures are swallowed so booking is never blocked."""
    try:
        therapist_name = appointment.therapist.display_name
        when = _when(appointment.starts_at)
        patient_name = _patient_name(appointment)
        messages = {
            "confirmed": (
                f"نوبت شما با {therapist_name} در {when} تایید شد.",
                f"نوبت جدید با مراجع {patient_name} در {when} ثبت شد.",
            ),
            "canceled": (
                f"نوبت شما با {therapist_name} در {when} لغو شد.",
                f"نوبت مراجع {patient_name} در {when} لغو شد.",
            ),
            "moved": (
                f"نوبت شما با {therapist_name} به {when} تغییر کرد.",
                f"نوبت مراجع {patient_name} به {when} تغییر کرد.",
            ),
        }
        patient_body, therapist_body = messages[event]
        send_sms(
            phone=_phone(appointment.patient.user) or appointment.patient.phone,
            body=patient_body,
            purpose=SmsMessage.Purpose.APPOINTMENT,
            user=appointment.patient.user,
            unique_id=f"appt:{event}:{appointment.pk}:patient",
        )
        send_sms(
            phone=_phone(appointment.therapist.user),
            body=therapist_body,
            purpose=SmsMessage.Purpose.APPOINTMENT,
            user=appointment.therapist.user,
            unique_id=f"appt:{event}:{appointment.pk}:therapist",
        )
    except Exception:
        return
