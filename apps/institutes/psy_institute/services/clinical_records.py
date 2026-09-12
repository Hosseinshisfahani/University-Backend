"""Private clinical reports and master-file access requests."""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from ..models import (
    Appointment,
    ClinicalReport,
    FileAccessRequest,
    PatientProfile,
    TherapistProfile,
)

DEFAULT_ACCESS_DAYS = 7


class ClinicalRecordError(Exception):
    pass


def missing_report_appointments(*, therapist: TherapistProfile | None = None):
    qs = Appointment.objects.filter(
        status=Appointment.Status.COMPLETED,
        clinical_report__isnull=True,
    ).select_related("patient__user", "therapist", "session_type")
    if therapist is not None:
        qs = qs.filter(therapist=therapist)
    return qs.order_by("starts_at")


def sync_expired_access_requests(queryset: QuerySet | None = None) -> int:
    """Flip stale approved grants to expired. Called lazily on read."""
    qs = queryset if queryset is not None else FileAccessRequest.objects.all()
    return qs.filter(
        status=FileAccessRequest.Status.APPROVED,
        expires_at__lt=timezone.now(),
    ).update(status=FileAccessRequest.Status.EXPIRED)


def has_full_file_access(
    *, therapist: TherapistProfile, patient: PatientProfile
) -> bool:
    sync_expired_access_requests(
        FileAccessRequest.objects.filter(therapist=therapist, patient=patient)
    )
    return FileAccessRequest.objects.filter(
        therapist=therapist,
        patient=patient,
        status=FileAccessRequest.Status.APPROVED,
        expires_at__gte=timezone.now(),
    ).exists()


def patients_with_full_file_access(*, therapist: TherapistProfile):
    sync_expired_access_requests(
        FileAccessRequest.objects.filter(therapist=therapist)
    )
    return FileAccessRequest.objects.filter(
        therapist=therapist,
        status=FileAccessRequest.Status.APPROVED,
        expires_at__gte=timezone.now(),
    ).values_list("patient_id", flat=True)


@transaction.atomic
def submit_clinical_report(
    *,
    therapist: TherapistProfile,
    appointment: Appointment,
    summary: str,
    assessment: str,
    treatment_plan: str,
    risk_flags=None,
) -> ClinicalReport:
    appointment = Appointment.objects.select_related("patient", "therapist").get(
        pk=appointment.pk
    )
    if appointment.therapist_id != therapist.id:
        raise ClinicalRecordError("Not your appointment.")
    if appointment.status != Appointment.Status.COMPLETED:
        raise ClinicalRecordError(
            "Clinical reports can only be filed for completed appointments."
        )
    if ClinicalReport.objects.filter(appointment=appointment).exists():
        raise ClinicalRecordError("This appointment already has a clinical report.")
    summary = (summary or "").strip()
    assessment = (assessment or "").strip()
    treatment_plan = (treatment_plan or "").strip()
    if not summary or not assessment or not treatment_plan:
        raise ClinicalRecordError(
            "Summary, assessment, and treatment plan are required."
        )
    flags = list(risk_flags or [])
    try:
        return ClinicalReport.objects.create(
            appointment=appointment,
            therapist=therapist,
            patient=appointment.patient,
            summary=summary,
            assessment=assessment,
            treatment_plan=treatment_plan,
            risk_flags=flags,
        )
    except IntegrityError as exc:
        raise ClinicalRecordError(
            "This appointment already has a clinical report."
        ) from exc


@transaction.atomic
def submit_file_access_request(
    *,
    therapist: TherapistProfile,
    patient: PatientProfile,
    reason: str = "",
) -> FileAccessRequest:
    sync_expired_access_requests(
        FileAccessRequest.objects.filter(therapist=therapist, patient=patient)
    )
    active = FileAccessRequest.objects.filter(
        therapist=therapist,
        patient=patient,
        status__in=[
            FileAccessRequest.Status.PENDING,
            FileAccessRequest.Status.APPROVED,
        ],
    )
    if active.exists():
        raise ClinicalRecordError(
            "An active file-access request already exists for this patient."
        )
    return FileAccessRequest.objects.create(
        therapist=therapist,
        patient=patient,
        reason=(reason or "").strip(),
        status=FileAccessRequest.Status.PENDING,
    )


@transaction.atomic
def approve_file_access_request(
    *,
    request: FileAccessRequest,
    admin_user,
    access_days: int = DEFAULT_ACCESS_DAYS,
) -> FileAccessRequest:
    row = FileAccessRequest.objects.select_for_update().get(pk=request.pk)
    if row.status != FileAccessRequest.Status.PENDING:
        raise ClinicalRecordError("Only pending requests can be approved.")
    days = int(access_days or DEFAULT_ACCESS_DAYS)
    if days < 1:
        raise ClinicalRecordError("Access window must be at least 1 day.")
    now = timezone.now()
    row.status = FileAccessRequest.Status.APPROVED
    row.granted_by = admin_user
    row.decided_at = now
    row.expires_at = now + timedelta(days=days)
    row.save(
        update_fields=[
            "status",
            "granted_by",
            "decided_at",
            "expires_at",
            "updated_at",
        ]
    )
    return row


@transaction.atomic
def reject_file_access_request(
    *,
    request: FileAccessRequest,
    admin_user,
    decision_note: str = "",
) -> FileAccessRequest:
    row = FileAccessRequest.objects.select_for_update().get(pk=request.pk)
    if row.status != FileAccessRequest.Status.PENDING:
        raise ClinicalRecordError("Only pending requests can be rejected.")
    row.status = FileAccessRequest.Status.REJECTED
    row.granted_by = admin_user
    row.decided_at = timezone.now()
    row.decision_note = decision_note or ""
    row.save(
        update_fields=[
            "status",
            "granted_by",
            "decided_at",
            "decision_note",
            "updated_at",
        ]
    )
    return row
