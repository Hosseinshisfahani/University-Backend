"""
Seed psychology institute test data for local frontend development.

Usage:
  python manage.py seed_psy_test_data
  python manage.py seed_psy_test_data --password 'Pass1234!' --with-wallet-credit
"""

from __future__ import annotations

from datetime import date
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import LedgerEntry
from apps.institutes.psy_institute.models import (
    Appointment,
    AppointmentSlot,
    BlogPost,
    ClinicalReport,
    FileAccessRequest,
    LeaveRequest,
    NewsSlide,
    PatientProfile,
    PsychometricForm,
    PsychometricResponse,
    SessionNote,
    SessionType,
    SitePage,
    TherapistAvailability,
    TherapistProfile,
    TherapistReview,
    TherapistSessionOffer,
    Ticket,
    TicketMessage,
    Workshop,
    WorkshopCertificate,
    WorkshopEnrollment,
    WorkshopResource,
    WorkshopSession,
    WorkshopSessionProgress,
)
from apps.institutes.psy_institute.services import regenerate_slots_for_therapist

User = get_user_model()

SAMPLE_FORM_SCHEMA = {
    "fields": [
        {
            "id": "mood",
            "type": "likert",
            "label": "طی دو هفته گذشته، حال روحی کلی شما چگونه بوده است؟",
            "required": True,
            "options": ["1", "2", "3", "4", "5"],
        },
        {
            "id": "sleep",
            "type": "single",
            "label": "کیفیت خواب شما چگونه است؟",
            "required": True,
            "options": ["خوب", "متوسط", "ضعیف"],
        },
        {
            "id": "concerns",
            "type": "multi",
            "label": "کدام موارد برای شما نگران‌کننده است؟",
            "required": False,
            "options": ["اضطراب", "افسردگی", "روابط", "کار/تحصیل"],
        },
        {
            "id": "notes",
            "type": "text",
            "label": "توضیح کوتاه (اختیاری)",
            "required": False,
        },
    ]
}

PATIENT_SEEDS = (
    {
        "username": "patient1",
        "first_name": "سارا",
        "last_name": "احمدی",
        "phone": "09121110001",
        "national_id": "0010000001",
        "birth_date": date(2002, 5, 12),
        "notes_internal": "دانشجوی کارشناسی؛ اضطراب امتحان و مشکل خواب در فصل امتحانات.",
    },
    {
        "username": "patient2",
        "first_name": "رضا",
        "last_name": "محمدی",
        "phone": "09121110002",
        "national_id": "0010000002",
        "birth_date": date(1999, 11, 3),
        "notes_internal": "دانشجوی ارشد؛ مراجعه برای افت انگیزه و برنامه‌ریزی تحصیلی.",
    },
    {
        "username": "patient3",
        "first_name": "مینا",
        "last_name": "کریمی",
        "phone": "09121110003",
        "national_id": "0010000003",
        "birth_date": date(2001, 2, 20),
        "notes_internal": "مراجعه جهت مهارت‌های ارتباطی و مدیریت تعارض.",
    },
    {
        "username": "patient4",
        "first_name": "امیر",
        "last_name": "مرادی",
        "phone": "09121110004",
        "national_id": "0010000004",
        "birth_date": date(2000, 8, 8),
        "notes_internal": "پیگیری برای فرسودگی تحصیلی و تعادل کار و درس.",
    },
    {
        "username": "patient5",
        "first_name": "نگار",
        "last_name": "صالحی",
        "phone": "09121110005",
        "national_id": "0010000005",
        "birth_date": date(2003, 1, 15),
        "notes_internal": "نیاز به مشاوره اولیه درباره سازگاری با محیط دانشگاه.",
    },
)

THERAPIST_SEEDS = (
    {
        "username": "therapist1",
        "first_name": "دکتر",
        "last_name": "نمونه",
        "display_name": "دکتر نمونه",
        "bio": "روان‌شناس بالینی؛ داده آزمایشی برای توسعه پورتال بیمار.",
        "specialties": ["اضطراب", "افسردگی", "مهارت‌های مقابله‌ای"],
        "is_accepting_patients": True,
        "is_active": True,
        "availability": (
            (0, time(9, 0), time(14, 0)),
            (1, time(9, 0), time(14, 0)),
            (2, time(9, 0), time(14, 0)),
        ),
    },
    {
        "username": "therapist2",
        "first_name": "دکتر",
        "last_name": "کاوه",
        "display_name": "دکتر لیلا کاوه",
        "bio": "درمانگر خانواده و روابط بین‌فردی؛ مناسب تست جستجو، فیلتر فعال و ظرفیت پذیرش.",
        "specialties": ["روابط", "خانواده", "ذهن‌آگاهی"],
        "is_accepting_patients": True,
        "is_active": True,
        "availability": (
            (3, time(10, 0), time(15, 0)),
            (5, time(8, 30), time(12, 30)),
        ),
    },
    {
        "username": "therapist3",
        "first_name": "دکتر",
        "last_name": "نادری",
        "display_name": "دکتر پیمان نادری",
        "bio": "پروفایل غیرفعال برای تست فیلترها و نمایش درمانگران سابق مرکز.",
        "specialties": ["روان‌سنجی", "مشاوره تحصیلی"],
        "is_accepting_patients": False,
        "is_active": False,
        "availability": (),
    },
)

MEET_LINKS = (
    "https://meet.google.com/abc-defg-hij",
    "https://meet.google.com/klm-nopq-rst",
)

MEDIA_FIXTURES = {
    "psy/workshops/anxiety-skills-paid.svg": {
        "title": "کارگاه مهارت‌های اضطراب",
        "subtitle": "تمرین تنفس، بازسازی شناختی، مواجهه تدریجی",
        "from": "#0f766e",
        "to": "#14b8a6",
    },
    "psy/workshops/mindfulness-free.svg": {
        "title": "کارگاه ذهن‌آگاهی",
        "subtitle": "شروعی آرام برای حضور در لحظه",
        "from": "#4f46e5",
        "to": "#8b5cf6",
    },
    "psy/workshops/group-therapy-draft.svg": {
        "title": "گروه درمانی",
        "subtitle": "پیش‌نویس محتوای گروهی مرکز",
        "from": "#334155",
        "to": "#64748b",
    },
    "psy/blog/anxiety-breathing-basics.svg": {
        "title": "تنفس آگاهانه",
        "subtitle": "راهنمای کوتاه مدیریت اضطراب",
        "from": "#0891b2",
        "to": "#22d3ee",
    },
    "psy/blog/when-to-see-a-therapist.svg": {
        "title": "زمان مراجعه",
        "subtitle": "چه وقتی کمک حرفه‌ای بگیریم؟",
        "from": "#7c3aed",
        "to": "#c084fc",
    },
    "psy/blog/sleep-hygiene-draft.svg": {
        "title": "بهداشت خواب",
        "subtitle": "پیش‌نویس مقاله آموزشی",
        "from": "#1e293b",
        "to": "#475569",
    },
    "psy/news/hours-update.svg": {
        "title": "ساعات کار مرکز",
        "subtitle": "شنبه تا پنج‌شنبه، ۸ تا ۱۹",
        "from": "#1c39bb",
        "to": "#12a8b5",
    },
    "psy/news/workshops-open.svg": {
        "title": "کارگاه‌های جدید",
        "subtitle": "ثبت‌نام کارگاه‌های بهاره آغاز شد",
        "from": "#007a8c",
        "to": "#d4af37",
    },
    "psy/news/draft-notice.svg": {
        "title": "اطلاعیه داخلی",
        "subtitle": "پیش‌نویس اسلاید اخبار",
        "from": "#334155",
        "to": "#64748b",
    },
}


class Command(BaseCommand):
    help = (
        "Seed psy_institute demo users, appointments, meeting links, "
        "session notes, and psychometric responses."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="Pass1234!",
            help="Password for seeded users (default: Pass1234!).",
        )
        parser.add_argument(
            "--with-wallet-credit",
            action="store_true",
            default=True,
            help="Credit patient wallets so booking works without SEP (default: on).",
        )
        parser.add_argument(
            "--no-wallet-credit",
            action="store_true",
            help="Skip wallet credit for seeded patients.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        credit_wallet = options["with_wallet_credit"] and not options["no_wallet_credit"]

        for name in ("psy_admin", "psy_therapist", "psy_patient"):
            Group.objects.get_or_create(name=name)

        media_paths = self._ensure_media_fixtures()
        admin_user = self._user("admin1", password, "psy_admin", is_staff=True)

        therapists: list[TherapistProfile] = []
        for seed in THERAPIST_SEEDS:
            therapist_user = self._user(
                seed["username"],
                password,
                "psy_therapist",
                first_name=seed["first_name"],
                last_name=seed["last_name"],
            )
            therapist, _ = TherapistProfile.objects.update_or_create(
                user=therapist_user,
                defaults={
                    "display_name": seed["display_name"],
                    "bio": seed["bio"],
                    "specialties": seed["specialties"],
                    "is_accepting_patients": seed["is_accepting_patients"],
                    "is_active": seed["is_active"],
                },
            )
            therapists.append(therapist)

        therapist = therapists[0]

        patients: list[PatientProfile] = []
        for seed in PATIENT_SEEDS:
            user = self._user(
                seed["username"],
                password,
                "psy_patient",
                first_name=seed["first_name"],
                last_name=seed["last_name"],
            )
            patient, _ = PatientProfile.objects.get_or_create(
                user=user,
                defaults={
                    "phone": seed["phone"],
                    "national_id": seed["national_id"],
                    "birth_date": seed["birth_date"],
                    "notes_internal": seed["notes_internal"],
                },
            )
            updated = False
            update_fields = []
            if not patient.phone:
                patient.phone = seed["phone"]
                updated = True
                update_fields.append("phone")
            if not patient.national_id:
                patient.national_id = seed["national_id"]
                updated = True
                update_fields.append("national_id")
            if not patient.birth_date:
                patient.birth_date = seed["birth_date"]
                updated = True
                update_fields.append("birth_date")
            if not patient.notes_internal:
                patient.notes_internal = seed["notes_internal"]
                updated = True
                update_fields.append("notes_internal")
            if updated:
                patient.save(update_fields=[*update_fields, "updated_at"])
            patients.append(patient)

        session_type, _ = SessionType.objects.get_or_create(
            slug="online-45",
            defaults={
                "name": "آنلاین ۴۵ دقیقه",
                "modality": SessionType.Modality.ONLINE,
                "duration_minutes": 45,
                "price": Decimal("500000"),
                "buffer_minutes": 15,
                "is_active": True,
                "sort_order": 1,
            },
        )
        in_person_type, _ = SessionType.objects.get_or_create(
            slug="in-person-60",
            defaults={
                "name": "حضوری ۶۰ دقیقه",
                "modality": SessionType.Modality.IN_PERSON,
                "duration_minutes": 60,
                "price": Decimal("700000"),
                "buffer_minutes": 15,
                "is_active": True,
                "sort_order": 2,
            },
        )
        intake_type, _ = SessionType.objects.get_or_create(
            slug="online-intake-30",
            defaults={
                "name": "ارزیابی اولیه آنلاین ۳۰ دقیقه",
                "modality": SessionType.Modality.ONLINE,
                "duration_minutes": 30,
                "price": Decimal("250000"),
                "buffer_minutes": 10,
                "is_active": True,
                "sort_order": 0,
            },
        )

        for active_therapist in therapists[:2]:
            for offered_type in (session_type, in_person_type, intake_type):
                TherapistSessionOffer.objects.get_or_create(
                    therapist=active_therapist,
                    session_type=offered_type,
                    defaults={"is_active": True},
                )

        today = timezone.localdate()
        for active_therapist, seed in zip(therapists, THERAPIST_SEEDS, strict=False):
            for weekday, start_time, end_time in seed["availability"]:
                TherapistAvailability.objects.get_or_create(
                    therapist=active_therapist,
                    weekday=weekday,
                    defaults={
                        "start_time": start_time,
                        "end_time": end_time,
                        "valid_from": today,
                        "timezone": "Asia/Tehran",
                        "is_active": True,
                    },
                )

        created_slots = 0
        for active_therapist in therapists[:2]:
            created_slots += regenerate_slots_for_therapist(
                therapist=active_therapist,
                range_start=today,
                range_end=today + timedelta(days=14),
            )

        LeaveRequest.objects.get_or_create(
            therapist=therapist,
            starts_on=today + timedelta(days=10),
            ends_on=today + timedelta(days=11),
            defaults={
                "reason": "مرخصی نمونه برای تست پنل ادمین",
                "status": LeaveRequest.Status.PENDING,
            },
        )

        form, form_created = PsychometricForm.objects.get_or_create(
            slug="sample-phq",
            defaults={
                "title": "پرسشنامه نمونه حال روحی",
                "description": "فرم آزمایشی برای تست رندرر پویا در پورتال بیمار.",
                "schema": SAMPLE_FORM_SCHEMA,
                "version": 1,
                "is_published": True,
                "created_by": admin_user,
            },
        )
        if not form_created and not form.is_published:
            form.is_published = True
            form.schema = SAMPLE_FORM_SCHEMA
            form.save(update_fields=["is_published", "schema", "updated_at"])

        if credit_wallet:
            for patient in patients:
                finance_services.credit_wallet(
                    user=patient.user,
                    amount=Decimal("2000000"),
                    entry_type=LedgerEntry.EntryType.DEPOSIT,
                    idempotency_key=f"seed-{patient.user.username}-wallet-v1",
                    reference="seed.psy",
                    description=f"Seed wallet credit for {patient.user.username}",
                )

        appointments = self._seed_appointments(therapist, session_type, patients)
        appointments += self._seed_appointment_history(
            therapist, in_person_type, patients
        )
        notes_created = self._seed_session_notes(therapist, appointments)
        clinical_info = self._seed_clinical_records(
            admin_user, therapists, patients, session_type, appointments
        )
        reviews_info = self._seed_reviews(admin_user, appointments)
        responses_created = self._seed_psychometric_responses(
            form, therapist, patients
        )
        workshops_info = self._seed_workshops(therapist, patients, media_paths)
        blog_info = self._seed_blog(therapist.user, admin_user, media_paths)
        news_info = self._seed_news(media_paths)
        tickets_info = self._seed_tickets(admin_user, patients)
        site_info = self._seed_site_pages(media_paths)

        with_meet = sum(1 for a in appointments if a.meeting_link)
        shared_notes = SessionNote.objects.filter(
            author=therapist, shared_with_patient=True
        ).count()

        self.stdout.write(self.style.SUCCESS("psy seed complete"))
        self.stdout.write(
            f"  admin1 / therapist1–3 / patient1–5  password={password}"
        )
        self.stdout.write(
            f"  session_type=online-45  slots_created≈{created_slots}"
        )
        self.stdout.write(
            f"  appointments={len(appointments)}  with_meeting_link={with_meet}"
        )
        self.stdout.write(
            f"  session_notes_created≈{notes_created}  shared_with_patient={shared_notes}"
        )
        self.stdout.write(
            f"  clinical_reports={clinical_info['reports']}  "
            f"file_access={clinical_info['access']}"
        )
        self.stdout.write(
            f"  reviews approved={reviews_info['approved']} pending={reviews_info['pending']}"
        )
        self.stdout.write(
            f"  psychometric form=sample-phq  responses_created≈{responses_created}"
        )
        self.stdout.write(f"  workshops={workshops_info}")
        self.stdout.write(f"  blog={blog_info}")
        self.stdout.write(f"  news={news_info}")
        self.stdout.write(f"  tickets={tickets_info}")
        self.stdout.write(f"  site_pages={site_info}")
        self.stdout.write(f"  wallet_credit={credit_wallet}")

    def _ensure_media_fixtures(self) -> dict[str, str]:
        """Create small deterministic SVG media files used by seeded content."""
        paths: dict[str, str] = {}
        for relative_path, spec in MEDIA_FIXTURES.items():
            file_path = settings.MEDIA_ROOT / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{spec["title"]}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="{spec["from"]}"/>
      <stop offset="100%" stop-color="{spec["to"]}"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" rx="44" fill="url(#bg)"/>
  <circle cx="1040" cy="120" r="190" fill="rgba(255,255,255,0.16)"/>
  <circle cx="120" cy="560" r="240" fill="rgba(15,23,42,0.16)"/>
  <text x="88" y="275" fill="#fff" font-size="72" font-weight="700" font-family="Tahoma, Arial, sans-serif">{spec["title"]}</text>
  <text x="92" y="365" fill="rgba(255,255,255,0.86)" font-size="36" font-family="Tahoma, Arial, sans-serif">{spec["subtitle"]}</text>
  <text x="92" y="505" fill="rgba(255,255,255,0.72)" font-size="28" font-family="Tahoma, Arial, sans-serif">مرکز مشاوره و روان‌شناسی دانشگاه</text>
</svg>
"""
            if not file_path.exists() or file_path.read_text(encoding="utf-8") != svg:
                file_path.write_text(svg, encoding="utf-8")
            paths[relative_path] = relative_path
        return paths

    def _user(
        self,
        username: str,
        password: str,
        group: str,
        *,
        is_staff: bool = False,
        first_name: str = "",
        last_name: str = "",
    ):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "is_staff": is_staff,
                "first_name": first_name,
                "last_name": last_name,
            },
        )
        fields: list[str] = []
        if created or not user.check_password(password):
            user.set_password(password)
            fields.append("password")
        if is_staff and not user.is_staff:
            user.is_staff = True
            fields.append("is_staff")
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            fields.append("first_name")
        if last_name and user.last_name != last_name:
            user.last_name = last_name
            fields.append("last_name")
        if fields:
            # set_password mutates the hash; save without update_fields when password changes
            if "password" in fields:
                user.save()
            else:
                user.save(update_fields=fields)
        user.groups.add(Group.objects.get(name=group))
        return user

    @transaction.atomic
    def _seed_appointments(
        self,
        therapist: TherapistProfile,
        session_type: SessionType,
        patients: list[PatientProfile],
    ) -> list[Appointment]:
        """Ensure each seeded patient has a confirmed upcoming appointment with therapist1."""
        now = timezone.now()
        open_slots = list(
            AppointmentSlot.objects.select_for_update()
            .filter(
                therapist=therapist,
                status=AppointmentSlot.Status.OPEN,
                starts_at__gte=now + timedelta(hours=1),
            )
            .order_by("starts_at")
        )

        appointments: list[Appointment] = []
        meet_assigned = 0

        for index, patient in enumerate(patients):
            existing = (
                Appointment.objects.filter(
                    therapist=therapist,
                    patient=patient,
                    status=Appointment.Status.CONFIRMED,
                    starts_at__gte=now,
                )
                .select_related("slot", "session_type")
                .order_by("starts_at")
                .first()
            )
            if existing:
                if (
                    existing.session_type.modality == SessionType.Modality.ONLINE
                    and not existing.meeting_link
                    and meet_assigned < len(MEET_LINKS)
                ):
                    existing.meeting_link = MEET_LINKS[meet_assigned]
                    existing.save(update_fields=["meeting_link", "updated_at"])
                    meet_assigned += 1
                appointments.append(existing)
                continue

            if not open_slots:
                self.stdout.write(
                    self.style.WARNING(
                        f"  no open slots left for {patient.user.username}; skip appointment"
                    )
                )
                continue

            slot = open_slots.pop(0)
            meeting_link = ""
            if meet_assigned < len(MEET_LINKS):
                meeting_link = MEET_LINKS[meet_assigned]
                meet_assigned += 1

            slot.status = AppointmentSlot.Status.BOOKED
            slot.session_type = session_type
            slot.hold_expires_at = None
            slot.save(update_fields=["status", "session_type", "hold_expires_at", "updated_at"])

            appt = Appointment.objects.create(
                slot=slot,
                patient=patient,
                therapist=therapist,
                session_type=session_type,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                status=Appointment.Status.CONFIRMED,
                price_snapshot=session_type.price,
                payment_ref=f"seed.payment:{patient.user.username}",
                meeting_link=meeting_link,
            )
            appointments.append(appt)

            # One completed past-like appointment for richer patient detail
            # (reuse a far-future open slot shifted conceptually via a second booking
            # only when enough slots remain — skip if scarce).
            if index == 0 and open_slots:
                # Add a second confirmed upcoming for patient1 without meet link
                # so UI can show both linked and unlinked online sessions.
                extra_slot = open_slots.pop(0)
                extra_slot.status = AppointmentSlot.Status.BOOKED
                extra_slot.hold_expires_at = None
                extra_slot.save(
                    update_fields=["status", "hold_expires_at", "updated_at"]
                )
                appointments.append(
                    Appointment.objects.create(
                        slot=extra_slot,
                        patient=patient,
                        therapist=therapist,
                        session_type=session_type,
                        starts_at=extra_slot.starts_at,
                        ends_at=extra_slot.ends_at,
                        status=Appointment.Status.CONFIRMED,
                        price_snapshot=session_type.price,
                        payment_ref=f"seed.payment:{patient.user.username}:2",
                    )
                )

        return appointments

    def _seed_appointment_history(
        self,
        therapist: TherapistProfile,
        session_type: SessionType,
        patients: list[PatientProfile],
    ) -> list[Appointment]:
        now = timezone.now()
        specs = [
            {
                "patient": patients[0],
                "starts_at": now - timedelta(days=16, hours=2),
                "status": Appointment.Status.COMPLETED,
                "payment_ref": "seed.history:patient1:completed",
                "meeting_link": "",
            },
            {
                "patient": patients[1] if len(patients) > 1 else patients[0],
                "starts_at": now - timedelta(days=10, hours=1),
                "status": Appointment.Status.COMPLETED,
                "payment_ref": "seed.history:patient2:completed",
                "meeting_link": "",
            },
            {
                "patient": patients[1] if len(patients) > 1 else patients[0],
                "starts_at": now - timedelta(days=5, hours=3),
                "status": Appointment.Status.CANCELED_BY_PATIENT,
                "payment_ref": "seed.history:patient2:canceled",
                "canceled_at": now - timedelta(days=5, hours=20),
                "cancellation_reason": "تداخل با امتحان میان‌ترم",
                "refund_policy_applied": Appointment.RefundPolicy.FULL_REFUND,
            },
            {
                "patient": patients[2] if len(patients) > 2 else patients[0],
                "starts_at": now - timedelta(days=2, hours=4),
                "status": Appointment.Status.NO_SHOW,
                "payment_ref": "seed.history:patient3:noshow",
                "cancellation_reason": "عدم حضور در زمان مقرر",
                "refund_policy_applied": Appointment.RefundPolicy.FORFEIT,
            },
            {
                "patient": patients[3] if len(patients) > 3 else patients[0],
                "starts_at": now + timedelta(days=16, hours=5),
                "status": Appointment.Status.PENDING_PAYMENT,
                "payment_ref": "seed.history:patient4:pending",
                "meeting_link": "https://meet.google.com/pending-seed-demo",
            },
        ]

        appointments: list[Appointment] = []
        for spec in specs:
            starts_at = spec["starts_at"]
            ends_at = starts_at + timedelta(minutes=session_type.duration_minutes)
            existing = Appointment.objects.filter(
                payment_ref=spec["payment_ref"]
            ).first()
            if existing:
                changed = []
                for field in (
                    "status",
                    "meeting_link",
                    "cancellation_reason",
                    "refund_policy_applied",
                ):
                    value = spec.get(field, "")
                    if getattr(existing, field) != value:
                        setattr(existing, field, value)
                        changed.append(field)
                canceled_at = spec.get("canceled_at")
                if existing.canceled_at != canceled_at:
                    existing.canceled_at = canceled_at
                    changed.append("canceled_at")
                if changed:
                    existing.save(update_fields=[*changed, "updated_at"])
                appointments.append(existing)
                continue

            slot_status = (
                AppointmentSlot.Status.BLOCKED
                if spec["status"]
                in {
                    Appointment.Status.CANCELED_BY_PATIENT,
                    Appointment.Status.CANCELED_BY_THERAPIST,
                    Appointment.Status.CANCELED_BY_ADMIN,
                }
                else AppointmentSlot.Status.BOOKED
            )
            slot = AppointmentSlot.objects.create(
                therapist=therapist,
                session_type=session_type,
                starts_at=starts_at,
                ends_at=ends_at,
                status=slot_status,
            )
            appointments.append(
                Appointment.objects.create(
                    slot=slot,
                    patient=spec["patient"],
                    therapist=therapist,
                    session_type=session_type,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=spec["status"],
                    price_snapshot=session_type.price,
                    payment_ref=spec["payment_ref"],
                    meeting_link=spec.get("meeting_link", ""),
                    canceled_at=spec.get("canceled_at"),
                    cancellation_reason=spec.get("cancellation_reason", ""),
                    refund_policy_applied=spec.get("refund_policy_applied", ""),
                )
            )
        return appointments

    def _seed_reviews(self, admin_user, appointments: list[Appointment]) -> dict[str, int]:
        by_ref = {a.payment_ref: a for a in appointments}
        approved_appt = by_ref.get("seed.history:patient1:completed")
        pending_appt = by_ref.get("seed.history:patient2:completed")
        created = {"approved": 0, "pending": 0}

        if approved_appt and not TherapistReview.objects.filter(
            appointment=approved_appt
        ).exists():
            TherapistReview.objects.create(
                appointment=approved_appt,
                patient=approved_appt.patient,
                therapist=approved_appt.therapist,
                rating=5,
                body="جلسه خیلی کمک‌کننده بود و حس امنیت داشتم.",
                text_status=TherapistReview.TextStatus.APPROVED,
                reviewed_by=admin_user,
                reviewed_at=timezone.now(),
            )
            created["approved"] = 1
        elif approved_appt:
            created["approved"] = 1

        if pending_appt and not TherapistReview.objects.filter(
            appointment=pending_appt
        ).exists():
            TherapistReview.objects.create(
                appointment=pending_appt,
                patient=pending_appt.patient,
                therapist=pending_appt.therapist,
                rating=4,
                body="درمانگر دقیق گوش داد؛ منتظر تأیید برای نمایش عمومی.",
                text_status=TherapistReview.TextStatus.PENDING,
            )
            created["pending"] = 1
        elif pending_appt:
            created["pending"] = 1

        return created

    def _seed_session_notes(
        self,
        therapist: TherapistProfile,
        appointments: list[Appointment],
    ) -> int:
        if not appointments:
            return 0

        created = 0
        # Shared note on first appointment (case summary visible to patient)
        primary = appointments[0]
        _, was_created = SessionNote.objects.get_or_create(
            appointment=primary,
            author=therapist,
            body="خلاصه جلسه: تمرکز بر مدیریت اضطراب و تمرین تنفس.",
            defaults={"shared_with_patient": True},
        )
        if was_created:
            created += 1
        else:
            note = SessionNote.objects.filter(
                appointment=primary,
                author=therapist,
                body="خلاصه جلسه: تمرکز بر مدیریت اضطراب و تمرین تنفس.",
            ).first()
            if note and not note.shared_with_patient:
                note.shared_with_patient = True
                note.save(update_fields=["shared_with_patient", "updated_at"])

        # Private therapist-only note
        if len(appointments) > 1:
            _, was_created = SessionNote.objects.get_or_create(
                appointment=appointments[1],
                author=therapist,
                body="یادداشت داخلی: پیگیری خواب و دارو با پزشک معالج.",
                defaults={"shared_with_patient": False},
            )
            if was_created:
                created += 1

        # Another shared note if a third appointment exists
        if len(appointments) > 2:
            _, was_created = SessionNote.objects.get_or_create(
                appointment=appointments[2],
                author=therapist,
                body="خلاصه کوتاه: پیشرفت در مهارت‌های مقابله‌ای مشاهده شد.",
                defaults={"shared_with_patient": True},
            )
            if was_created:
                created += 1

        return created

    def _seed_clinical_records(
        self,
        admin_user,
        therapists: list[TherapistProfile],
        patients: list[PatientProfile],
        session_type: SessionType,
        appointments: list[Appointment],
    ) -> dict[str, str]:
        therapist = therapists[0]
        other = therapists[1] if len(therapists) > 1 else therapist
        patient = patients[0]
        now = timezone.now()

        completed = [
            a
            for a in appointments
            if a.therapist_id == therapist.id
            and a.status == Appointment.Status.COMPLETED
        ]
        reports = 0
        if completed:
            primary = completed[0]
            _, was_created = ClinicalReport.objects.get_or_create(
                appointment=primary,
                defaults={
                    "therapist": therapist,
                    "patient": primary.patient,
                    "summary": "جلسه‌ای متمرکز بر مدیریت اضطراب امتحان و تمرین تنفس.",
                    "assessment": "علائم اضطرابی در محدوده خفیف تا متوسط؛ انگیزه درمان خوب است.",
                    "treatment_plan": "ادامه CBT هفتگی و تمرین مواجهه تدریجی با موقعیت‌های ارزیابی.",
                    "risk_flags": [],
                },
            )
            if was_created:
                reports += 1
            else:
                reports += 1

        # Shared-patient appointment so a second therapist can request the master file.
        other_ref = "seed.clinical:therapist2:patient1:completed"
        other_appt = Appointment.objects.filter(payment_ref=other_ref).first()
        if other_appt is None and other.id != therapist.id:
            starts_at = now - timedelta(days=4, hours=2)
            ends_at = starts_at + timedelta(minutes=session_type.duration_minutes)
            slot = AppointmentSlot.objects.create(
                therapist=other,
                session_type=session_type,
                starts_at=starts_at,
                ends_at=ends_at,
                status=AppointmentSlot.Status.BOOKED,
            )
            other_appt = Appointment.objects.create(
                slot=slot,
                patient=patient,
                therapist=other,
                session_type=session_type,
                starts_at=starts_at,
                ends_at=ends_at,
                status=Appointment.Status.COMPLETED,
                price_snapshot=session_type.price,
                payment_ref=other_ref,
            )
        if other_appt:
            _, was_created = ClinicalReport.objects.get_or_create(
                appointment=other_appt,
                defaults={
                    "therapist": other_appt.therapist,
                    "patient": other_appt.patient,
                    "summary": "گزارش درمانگر دوم: پیگیری خلق و الگوی خواب.",
                    "assessment": "افت خفیف خلق؛ افکار خودآسیب‌رسان انکار شد.",
                    "treatment_plan": "هماهنگی با درمانگر اصلی و پایش هفتگی خواب.",
                    "risk_flags": [],
                },
            )
            if was_created:
                reports += 1
            else:
                reports += 1

        access_specs = [
            {
                "therapist": other,
                "patient": patient,
                "status": FileAccessRequest.Status.PENDING,
                "reason": "نیاز به مشاهده سوابق برای تداوم درمان.",
                "expires_at": None,
                "granted_by": None,
            },
            {
                "therapist": other,
                "patient": patients[1] if len(patients) > 1 else patient,
                "status": FileAccessRequest.Status.APPROVED,
                "reason": "بررسی تاریخچه پیش از شروع کارگاه گروهی.",
                "expires_at": now + timedelta(days=7),
                "granted_by": admin_user,
            },
            {
                "therapist": other,
                "patient": patients[2] if len(patients) > 2 else patient,
                "status": FileAccessRequest.Status.EXPIRED,
                "reason": "دسترسی موقت قبلی برای ارزیابی اولیه.",
                "expires_at": now - timedelta(days=1),
                "granted_by": admin_user,
            },
        ]
        access_count = 0
        for spec in access_specs:
            row, _ = FileAccessRequest.objects.get_or_create(
                therapist=spec["therapist"],
                patient=spec["patient"],
                status=spec["status"],
                defaults={
                    "reason": spec["reason"],
                    "expires_at": spec["expires_at"],
                    "granted_by": spec["granted_by"],
                    "decided_at": now if spec["granted_by"] else None,
                },
            )
            if row.reason != spec["reason"] or row.expires_at != spec["expires_at"]:
                row.reason = spec["reason"]
                row.expires_at = spec["expires_at"]
                row.granted_by = spec["granted_by"]
                row.decided_at = now if spec["granted_by"] else None
                row.save(
                    update_fields=[
                        "reason",
                        "expires_at",
                        "granted_by",
                        "decided_at",
                        "updated_at",
                    ]
                )
            access_count += 1

        return {"reports": str(reports), "access": str(access_count)}

    def _seed_psychometric_responses(
        self,
        form: PsychometricForm,
        therapist: TherapistProfile,
        patients: list[PatientProfile],
    ) -> int:
        specs = [
            {
                "patient": patients[0],
                "answers": {
                    "mood": "3",
                    "sleep": "متوسط",
                    "concerns": ["اضطراب"],
                    "notes": "اضطراب قبل از امتحان",
                },
                "status": PsychometricResponse.Status.REVIEWED,
                "reviewer_notes": "پاسخ‌ها با گزارش بالینی هم‌خوان است؛ پیگیری اضطراب امتحان.",
            },
            {
                "patient": patients[1] if len(patients) > 1 else patients[0],
                "answers": {
                    "mood": "2",
                    "sleep": "ضعیف",
                    "concerns": ["افسردگی", "خواب"],
                    "notes": "",
                },
                "status": PsychometricResponse.Status.SUBMITTED,
                "reviewer_notes": "",
            },
            {
                "patient": patients[2] if len(patients) > 2 else patients[0],
                "answers": {
                    "mood": "4",
                    "sleep": "خوب",
                    "concerns": ["روابط"],
                    "notes": "بهبود نسبت به ماه قبل",
                },
                "status": PsychometricResponse.Status.SUBMITTED,
                "reviewer_notes": "",
            },
            {
                "patient": patients[0],
                "answers": {
                    "mood": "4",
                    "sleep": "خوب",
                    "concerns": ["کار/تحصیل"],
                    "notes": "نوبت دوم پرسشنامه",
                },
                "status": PsychometricResponse.Status.REVIEWED,
                "reviewer_notes": "روند مثبت؛ ادامه جلسات آنلاین.",
            },
        ]

        created = 0
        # Drop earlier seed rows that used a private __seed_key marker
        PsychometricResponse.objects.filter(
            form=form,
            answers__has_key="__seed_key",
        ).delete()

        for spec in specs:
            existing = PsychometricResponse.objects.filter(
                form=form,
                patient=spec["patient"],
                answers=spec["answers"],
            ).first()
            if existing:
                changed = False
                if existing.status != spec["status"]:
                    existing.status = spec["status"]
                    changed = True
                if existing.reviewer_notes != spec["reviewer_notes"]:
                    existing.reviewer_notes = spec["reviewer_notes"]
                    changed = True
                if existing.routed_therapist_id != therapist.id:
                    existing.routed_therapist = therapist
                    changed = True
                if changed:
                    existing.save(
                        update_fields=[
                            "status",
                            "reviewer_notes",
                            "routed_therapist",
                            "updated_at",
                        ]
                    )
                continue

            PsychometricResponse.objects.create(
                form=form,
                form_version=form.version,
                patient=spec["patient"],
                answers=spec["answers"],
                routed_therapist=therapist,
                status=spec["status"],
                reviewer_notes=spec["reviewer_notes"],
            )
            created += 1

        return created

    def _seed_workshops(
        self,
        therapist: TherapistProfile,
        patients: list[PatientProfile],
        media_paths: dict[str, str],
    ) -> str:
        now = timezone.now()
        primary_patient = patients[0]
        secondary_patient = patients[1] if len(patients) > 1 else patients[0]
        third_patient = patients[2] if len(patients) > 2 else patients[0]
        paid, _ = Workshop.objects.update_or_create(
            slug="anxiety-skills-paid",
            defaults={
                "title": "کارگاه مهارت‌های اضطراب",
                "description": "کارگاه آزمایشی پولی برای تست ثبت‌نام و کیف پول.",
                "body_md": (
                    "## درباره این کارگاه\n\n"
                    "مهارت‌های عملی برای مدیریت اضطراب روزمره.\n\n"
                    "- تمرین تنفس\n"
                    "- بازسازی شناختی\n"
                    "- برنامه مواجهه تدریجی\n"
                ),
                "instructor": therapist,
                "capacity": 15,
                "price": Decimal("350000"),
                "starts_at": now + timedelta(days=10),
                "ends_at": now + timedelta(days=17, hours=2),
                "banner_image": media_paths["psy/workshops/anxiety-skills-paid.svg"],
                "is_published": True,
                "certificate_enabled": True,
            },
        )
        s1, _ = WorkshopSession.objects.update_or_create(
            workshop=paid,
            sort_order=1,
            defaults={
                "title": "جلسه ۱ — آشنایی و تنفس",
                "summary": "معرفی مدل اضطراب و تمرین تنفس دیافراگمی.",
                "starts_at": now + timedelta(days=10, hours=10),
                "ends_at": now + timedelta(days=10, hours=12),
                "meeting_url": "https://meet.example.com/anxiety-session-1",
                "recording_url": "",
            },
        )
        s2, _ = WorkshopSession.objects.update_or_create(
            workshop=paid,
            sort_order=2,
            defaults={
                "title": "جلسه ۲ — بازسازی شناختی",
                "summary": "شناسایی افکار خودکار و تمرین جایگزینی.",
                "starts_at": now + timedelta(days=3, hours=10),
                "ends_at": now + timedelta(days=3, hours=12),
                "meeting_url": "",
                "recording_url": "https://cdn.example.com/anxiety-session-2.mp4",
            },
        )
        WorkshopResource.objects.update_or_create(
            workshop=paid,
            title="اسلایدهای جلسه ۱",
            defaults={
                "session": s1,
                "sort_order": 1,
                "kind": WorkshopResource.Kind.SLIDES,
                "file_url": "https://cdn.example.com/anxiety-s1-slides.pdf",
            },
        )
        WorkshopResource.objects.update_or_create(
            workshop=paid,
            title="کتابچه تمرینات",
            defaults={
                "session": None,
                "sort_order": 1,
                "kind": WorkshopResource.Kind.PDF,
                "file_url": "https://cdn.example.com/anxiety-workbook.pdf",
            },
        )
        free, _ = Workshop.objects.update_or_create(
            slug="mindfulness-free",
            defaults={
                "title": "کارگاه رایگان ذهن‌آگاهی",
                "description": "کارگاه رایگان آزمایشی — ثبت‌نام بدون پرداخت.",
                "body_md": (
                    "## ذهن‌آگاهی برای شروع\n\n"
                    "یک کارگاه کوتاه و رایگان برای آشنایی با تمرین حضور.\n"
                ),
                "instructor": therapist,
                "capacity": 30,
                "price": Decimal("0"),
                "starts_at": now + timedelta(days=7),
                "ends_at": now + timedelta(days=7, hours=1, minutes=30),
                "banner_image": media_paths["psy/workshops/mindfulness-free.svg"],
                "is_published": True,
                "certificate_enabled": False,
            },
        )
        WorkshopSession.objects.update_or_create(
            workshop=free,
            sort_order=1,
            defaults={
                "title": "جلسه معرفی",
                "summary": "تمرین کوتاه ذهن‌آگاهی.",
                "starts_at": now + timedelta(days=7, hours=9),
                "ends_at": now + timedelta(days=7, hours=10, minutes=30),
                "meeting_url": "https://meet.example.com/mindfulness-intro",
                "recording_url": "",
            },
        )
        Workshop.objects.update_or_create(
            slug="draft-group-therapy",
            defaults={
                "title": "پیش‌نویس گروه درمانی",
                "description": "منتشر نشده — فقط در پنل ادمین.",
                "instructor": therapist,
                "capacity": 8,
                "price": Decimal("500000"),
                "starts_at": now + timedelta(days=21),
                "ends_at": now + timedelta(days=21, hours=2),
                "banner_image": media_paths["psy/workshops/group-therapy-draft.svg"],
                "is_published": False,
            },
        )

        enrollment, created = WorkshopEnrollment.objects.get_or_create(
            workshop=free,
            patient=primary_patient,
            defaults={
                "status": WorkshopEnrollment.Status.ACTIVE,
                "price_snapshot": Decimal("0"),
                "payment_ref": "free",
                "hold_expires_at": None,
            },
        )
        if not created and enrollment.status != WorkshopEnrollment.Status.ACTIVE:
            enrollment.status = WorkshopEnrollment.Status.ACTIVE
            enrollment.price_snapshot = Decimal("0")
            enrollment.payment_ref = "free"
            enrollment.hold_expires_at = None
            enrollment.save()

        paid_enrollment, _ = WorkshopEnrollment.objects.update_or_create(
            workshop=paid,
            patient=secondary_patient,
            defaults={
                "status": WorkshopEnrollment.Status.ACTIVE,
                "price_snapshot": paid.price,
                "payment_ref": "seed.workshop.wallet:patient2",
                "hold_expires_at": None,
                "canceled_at": None,
                "cancellation_reason": "",
            },
        )
        WorkshopSessionProgress.objects.get_or_create(
            enrollment=paid_enrollment,
            session=s1,
        )
        WorkshopSessionProgress.objects.get_or_create(
            enrollment=paid_enrollment,
            session=s2,
        )
        WorkshopCertificate.objects.get_or_create(
            enrollment=paid_enrollment,
            defaults={
                "certificate_code": "PSY-SEED-ANXIETY-P2",
                "file": "",
            },
        )

        WorkshopEnrollment.objects.update_or_create(
            workshop=paid,
            patient=third_patient,
            defaults={
                "status": WorkshopEnrollment.Status.CANCELED,
                "price_snapshot": paid.price,
                "payment_ref": "seed.workshop.canceled:patient3",
                "hold_expires_at": None,
                "canceled_at": now - timedelta(days=1),
                "cancellation_reason": "انصراف آزمایشی برای تست وضعیت لغوشده",
            },
        )

        return (
            f"paid={paid.slug} free={free.slug} "
            f"lms_sessions={paid.sessions.count()} enrollments={paid.enrollments.count() + free.enrollments.count()}"
        )

    def _seed_blog(self, therapist_user, admin_user, media_paths: dict[str, str]) -> str:
        now = timezone.now()
        posts = [
            {
                "slug": "anxiety-breathing-basics",
                "title": "تنفس آگاهانه برای اضطراب",
                "excerpt": "سه تمرین کوتاه تنفس که می‌توانید همین امروز شروع کنید.",
                "body": (
                    "## چرا تنفس مهم است؟\n\n"
                    "وقتی اضطراب بالا می‌رود، دستگاه عصبی سمپاتیک فعال می‌شود.\n\n"
                    "### تمرین ۱ — ۴-۷-۸\n\n"
                    "۱. دم از بینی به مدت ۴ ثانیه\n"
                    "۲. نگه داشتن ۷ ثانیه\n"
                    "۳. بازدم ۸ ثانیه\n"
                ),
                "cover_image": media_paths["psy/blog/anxiety-breathing-basics.svg"],
                "author": therapist_user,
                "is_published": True,
                "published_at": now - timedelta(days=5),
            },
            {
                "slug": "when-to-see-a-therapist",
                "title": "چه زمانی به درمانگر مراجعه کنیم؟",
                "excerpt": "نشانه‌هایی که می‌گویند وقت کمک حرفه‌ای رسیده است.",
                "body": (
                    "## نشانه‌های رایج\n\n"
                    "- اختلال پایدار در خواب یا اشتها\n"
                    "- اجتناب از روابط و فعالیت‌های مهم\n"
                    "- احساس درماندگی بیش از دو هفته\n\n"
                    "رزرو نوبت از صفحه درمانگران مرکز امکان‌پذیر است.\n"
                ),
                "cover_image": media_paths["psy/blog/when-to-see-a-therapist.svg"],
                "author": therapist_user,
                "is_published": True,
                "published_at": now - timedelta(days=2),
            },
            {
                "slug": "draft-sleep-hygiene",
                "title": "پیش‌نویس: بهداشت خواب",
                "excerpt": "هنوز منتشر نشده.",
                "body": "## در حال نگارش\n\nاین مقاله هنوز آماده انتشار نیست.\n",
                "cover_image": media_paths["psy/blog/sleep-hygiene-draft.svg"],
                "author": admin_user,
                "is_published": False,
                "published_at": None,
            },
        ]
        for spec in posts:
            BlogPost.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "title": spec["title"],
                    "excerpt": spec["excerpt"],
                    "body": spec["body"],
                    "cover_image": spec["cover_image"],
                    "author": spec["author"],
                    "is_published": spec["is_published"],
                    "published_at": spec["published_at"],
                },
            )
        published = BlogPost.objects.filter(is_published=True).count()
        return f"published={published} draft=draft-sleep-hygiene"

    def _seed_news(self, media_paths: dict[str, str]) -> str:
        slides = [
            {
                "title": "ساعات کار مرکز مشاوره آیه",
                "body": "مرکز از شنبه تا پنج‌شنبه، ۸ تا ۱۹ پذیرای مراجعان است. برای رزرو جلسه وارد پورتال شوید.",
                "image": media_paths["psy/news/hours-update.svg"],
                "link_url": "/register",
                "link_label": "رزرو نوبت",
                "sort_order": 1,
                "is_published": True,
            },
            {
                "title": "ثبت‌نام کارگاه‌های بهاره آغاز شد",
                "body": "کارگاه مهارت‌های اضطراب و ذهن‌آگاهی با ظرفیت محدود برگزار می‌شود.",
                "image": media_paths["psy/news/workshops-open.svg"],
                "link_url": "/psy/workshops",
                "link_label": "مشاهده کارگاه‌ها",
                "sort_order": 2,
                "is_published": True,
            },
            {
                "title": "اطلاعیه داخلی",
                "body": "این اسلاید پیش‌نویس است و در صفحه عمومی دیده نمی‌شود.",
                "image": media_paths["psy/news/draft-notice.svg"],
                "link_url": "",
                "link_label": "",
                "sort_order": 99,
                "is_published": False,
            },
        ]
        for spec in slides:
            NewsSlide.objects.update_or_create(
                title=spec["title"],
                defaults={
                    "body": spec["body"],
                    "image": spec["image"],
                    "link_url": spec["link_url"],
                    "link_label": spec["link_label"],
                    "sort_order": spec["sort_order"],
                    "is_published": spec["is_published"],
                },
            )
        published = NewsSlide.objects.filter(is_published=True).count()
        return f"published={published} draft=اطلاعیه داخلی"

    def _seed_tickets(self, admin_user, patients: list[PatientProfile]) -> str:
        specs = [
            {
                "patient": patients[0],
                "type": Ticket.Type.GENERAL,
                "subject": "سؤال درباره تغییر زمان جلسه",
                "status": Ticket.Status.IN_PROGRESS,
                "messages": [
                    (patients[0].user, "سلام، امکان جابه‌جایی جلسه این هفته وجود دارد؟", False),
                    (admin_user, "سلام، درخواست شما ثبت شد و درمانگر بررسی می‌کند.", True),
                ],
            },
            {
                "patient": patients[1] if len(patients) > 1 else patients[0],
                "type": Ticket.Type.WITHDRAWAL,
                "subject": "درخواست برداشت موجودی کیف پول",
                "status": Ticket.Status.OPEN,
                "withdrawal_ref": "seed.withdrawal:patient2",
                "bank_details_snapshot": {
                    "iban": "IR820540102680020817909002",
                    "account_owner": "رضا محمدی",
                },
                "messages": [
                    (
                        patients[1].user if len(patients) > 1 else patients[0].user,
                        "لطفاً موجودی کیف پول به حساب معرفی‌شده واریز شود.",
                        False,
                    ),
                ],
            },
            {
                "patient": patients[2] if len(patients) > 2 else patients[0],
                "type": Ticket.Type.COMPLAINT,
                "subject": "گزارش مشکل لینک جلسه",
                "status": Ticket.Status.RESOLVED,
                "messages": [
                    (
                        patients[2].user if len(patients) > 2 else patients[0].user,
                        "لینک جلسه آنلاین باز نمی‌شد.",
                        False,
                    ),
                    (admin_user, "لینک جدید ارسال شد و مشکل رفع شد.", True),
                ],
            },
        ]

        created_or_updated = 0
        for spec in specs:
            ticket, _ = Ticket.objects.update_or_create(
                patient=spec["patient"],
                subject=spec["subject"],
                defaults={
                    "type": spec["type"],
                    "status": spec["status"],
                    "withdrawal_ref": spec.get("withdrawal_ref", ""),
                    "bank_details_snapshot": spec.get("bank_details_snapshot", {}),
                },
            )
            for author, body, is_staff_reply in spec["messages"]:
                TicketMessage.objects.get_or_create(
                    ticket=ticket,
                    author=author,
                    body=body,
                    defaults={"is_staff_reply": is_staff_reply},
                )
            created_or_updated += 1
        return f"rows={created_or_updated}"

    def _seed_site_pages(self, media_paths: dict[str, str]) -> str:
        SitePage.objects.update_or_create(
            key="psy-about",
            defaults={
                "title": "درباره مرکز مشاوره و روان‌شناسی",
                "body": {
                    "hero": {
                        "title": "مرکز مشاوره و روان‌شناسی دانشگاه",
                        "subtitle": "رزرو جلسه، آزمون‌های روان‌سنجی و کارگاه‌های آموزشی در یک پورتال.",
                        "image": media_paths["psy/workshops/mindfulness-free.svg"],
                    },
                    "sections": [
                        {
                            "title": "خدمات",
                            "items": [
                                "جلسات حضوری و آنلاین",
                                "پرسشنامه‌های روان‌سنجی",
                                "کارگاه‌های مهارت‌آموزی",
                            ],
                        },
                        {
                            "title": "اطلاعات تماس",
                            "items": [
                                "تلفن: ۰۲۱-۱۲۳۴۵۶۷۸",
                                "ایمیل: psy-center@example.com",
                            ],
                        },
                    ],
                },
            },
        )
        SitePage.objects.update_or_create(
            key="psy-contact",
            defaults={
                "title": "تماس با مرکز",
                "body": {
                    "address": "ساختمان خدمات دانشجویی، طبقه دوم",
                    "working_hours": "شنبه تا چهارشنبه، ۸ تا ۱۵",
                    "emergency_note": "در شرایط بحران فوری با اورژانس اجتماعی یا مراکز درمانی تماس بگیرید.",
                },
            },
        )
        return "psy-about, psy-contact"
