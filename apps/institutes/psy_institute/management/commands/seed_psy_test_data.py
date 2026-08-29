"""
Seed psychology institute test data for local frontend development.

Usage:
  python manage.py seed_psy_test_data
  python manage.py seed_psy_test_data --password 'Pass1234!' --with-wallet-credit
"""

from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

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
    LeaveRequest,
    PatientProfile,
    PsychometricForm,
    PsychometricResponse,
    SessionNote,
    SessionType,
    TherapistAvailability,
    TherapistProfile,
    TherapistSessionOffer,
    Workshop,
    WorkshopEnrollment,
    WorkshopResource,
    WorkshopSession,
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
    },
    {
        "username": "patient2",
        "first_name": "رضا",
        "last_name": "محمدی",
        "phone": "09121110002",
        "national_id": "0010000002",
    },
    {
        "username": "patient3",
        "first_name": "مینا",
        "last_name": "کریمی",
        "phone": "09121110003",
        "national_id": "0010000003",
    },
)

MEET_LINKS = (
    "https://meet.google.com/abc-defg-hij",
    "https://meet.google.com/klm-nopq-rst",
)


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

        admin_user = self._user("admin1", password, "psy_admin", is_staff=True)
        therapist_user = self._user(
            "therapist1",
            password,
            "psy_therapist",
            first_name="دکتر",
            last_name="نمونه",
        )

        therapist, _ = TherapistProfile.objects.get_or_create(
            user=therapist_user,
            defaults={
                "display_name": "دکتر نمونه",
                "bio": "روان‌شناس بالینی — داده آزمایشی برای توسعه پورتال بیمار.",
                "specialties": ["اضطراب", "افسردگی"],
                "is_accepting_patients": True,
                "is_active": True,
            },
        )

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
                },
            )
            updated = False
            if not patient.phone:
                patient.phone = seed["phone"]
                updated = True
            if not patient.national_id:
                patient.national_id = seed["national_id"]
                updated = True
            if updated:
                patient.save(update_fields=["phone", "national_id", "updated_at"])
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

        TherapistSessionOffer.objects.get_or_create(
            therapist=therapist,
            session_type=session_type,
            defaults={"is_active": True},
        )

        today = timezone.localdate()
        for weekday in (0, 1, 2):  # Mon–Wed
            TherapistAvailability.objects.get_or_create(
                therapist=therapist,
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(14, 0),
                valid_from=today,
                defaults={
                    "timezone": "Asia/Tehran",
                    "is_active": True,
                },
            )

        created_slots = regenerate_slots_for_therapist(
            therapist=therapist,
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
        notes_created = self._seed_session_notes(therapist, appointments)
        responses_created = self._seed_psychometric_responses(
            form, therapist, patients
        )
        workshops_info = self._seed_workshops(therapist, patients[0])
        blog_info = self._seed_blog(therapist.user, admin_user)

        with_meet = sum(1 for a in appointments if a.meeting_link)
        shared_notes = SessionNote.objects.filter(
            author=therapist, shared_with_patient=True
        ).count()

        self.stdout.write(self.style.SUCCESS("psy seed complete"))
        self.stdout.write(
            f"  admin1 / therapist1 / patient1–3  password={password}"
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
            f"  psychometric form=sample-phq  responses_created≈{responses_created}"
        )
        self.stdout.write(f"  workshops={workshops_info}")
        self.stdout.write(f"  blog={blog_info}")
        self.stdout.write(f"  wallet_credit={credit_wallet}")

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
        self, therapist: TherapistProfile, patient: PatientProfile
    ) -> str:
        now = timezone.now()
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
                "banner_image": "",
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
        WorkshopSession.objects.update_or_create(
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
                "is_published": False,
            },
        )

        enrollment, created = WorkshopEnrollment.objects.get_or_create(
            workshop=free,
            patient=patient,
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

        return (
            f"paid={paid.slug} free={free.slug} "
            f"lms_sessions={paid.sessions.count()} enrolled_patient1_free=1"
        )

    def _seed_blog(self, therapist_user, admin_user) -> str:
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
                "cover_image": "",
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
                "cover_image": "",
                "author": therapist_user,
                "is_published": True,
                "published_at": now - timedelta(days=2),
            },
            {
                "slug": "draft-sleep-hygiene",
                "title": "پیش‌نویس: بهداشت خواب",
                "excerpt": "هنوز منتشر نشده.",
                "body": "## در حال نگارش\n\nاین مقاله هنوز آماده انتشار نیست.\n",
                "cover_image": "",
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
