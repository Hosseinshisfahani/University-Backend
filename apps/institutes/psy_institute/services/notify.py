import jdatetime
from django.utils import timezone

from apps.kernel.notifications.models import SmsMessage
from apps.kernel.notifications.services import send_sms
from apps.kernel.tenancy.models import Institute


def _psy_institute():
    return Institute.objects.filter(slug="psy").first()

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _phone(user) -> str:
    return (getattr(user, "phone", None) or "").strip()


def _when(dt) -> str:
    """Tehran-local Jalali label, e.g. دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۱۱:۰۰"""
    local = jdatetime.datetime.fromgregorian(
        datetime=timezone.localtime(dt), locale="fa_IR"
    )
    label = (
        f"{local.strftime('%A')} {local.day} {local.strftime('%B')} {local.year}، "
        f"ساعت {local.strftime('%H:%M')}"
    )
    return label.translate(_PERSIAN_DIGITS)


def _patient_user(appointment):
    patient = getattr(appointment, "patient", None)
    if patient is not None:
        return patient.user, getattr(patient, "phone", "") or ""
    return appointment.customer, ""


def _patient_name(appointment) -> str:
    user, _phone_fallback = _patient_user(appointment)
    return user.get_full_name() or user.username


def notify_appointment(appointment, event: str) -> None:
    """SMS both parties. Failures are swallowed so booking is never blocked."""
    try:
        therapist = getattr(appointment, "therapist", None)
        therapist_name = therapist.display_name if therapist is not None else appointment.provider.display_name
        therapist_user = therapist.user if therapist is not None else appointment.provider.user
        when = _when(appointment.starts_at)
        patient_name = _patient_name(appointment)
        patient_user, patient_phone = _patient_user(appointment)
        messages = {
            "booked": (
                f"درخواست نوبت شما با {therapist_name} در {when} ثبت شد.",
                f"درخواست نوبت جدید با مراجع {patient_name} در {when} ثبت شد.",
            ),
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
            "completed": (
                f"نوبت شما با {therapist_name} در {when} انجام شد.",
                f"نوبت مراجع {patient_name} در {when} انجام شد.",
            ),
        }
        patient_body, therapist_body = messages[event]
        institute = _psy_institute()
        send_sms(
            phone=_phone(patient_user) or patient_phone,
            body=patient_body,
            purpose=SmsMessage.Purpose.APPOINTMENT,
            user=patient_user,
            unique_id=f"appt:{event}:{appointment.pk}:patient",
            institute=institute,
        )
        send_sms(
            phone=_phone(therapist_user),
            body=therapist_body,
            purpose=SmsMessage.Purpose.APPOINTMENT,
            user=therapist_user,
            unique_id=f"appt:{event}:{appointment.pk}:therapist",
            institute=institute,
        )
    except Exception:
        return


def notify_leave(leave, decision: str) -> None:
    """SMS the provider when an admin decides a leave request."""
    try:
        bodies = {
            "approved": "درخواست مرخصی شما تایید شد.",
            "rejected": "درخواست مرخصی شما رد شد.",
            "canceled": "درخواست مرخصی لغو شد.",
        }
        body = bodies.get(decision)
        if not body:
            return
        user = leave.provider.user
        send_sms(
            phone=_phone(user),
            body=body,
            purpose=SmsMessage.Purpose.APPOINTMENT,
            user=user,
            unique_id=f"leave:{decision}:{leave.pk}",
            institute=_psy_institute(),
        )
    except Exception:
        return


def notify_order(order, event: str) -> None:
    """SMS the patient when an order is paid or shipped. Failures never block checkout."""
    try:
        number = order.number
        if event == "paid":
            body = f"سفارش {number} ثبت و پرداخت شد."
        elif event == "shipped":
            body = f"سفارش {number} ارسال شد."
            tracking = (order.tracking_code or "").strip()
            if tracking:
                body += f" کد رهگیری: {tracking}"
        else:
            return
        phone = _phone(order.user) or order.shipping_phone
        send_sms(
            phone=phone,
            body=body,
            purpose=SmsMessage.Purpose.SHOP,
            user=order.user,
            unique_id=f"order:{event}:{order.pk}",
            institute=_psy_institute(),
        )
    except Exception:
        return
