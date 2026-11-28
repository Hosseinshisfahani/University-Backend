"""Frozen psychology tables kept after their data moved into shared modules.

The model classes and migrations stay so historical rows and the copy
migrations remain readable. Application code and Django admin write the
module tables. Direct writes here raise unless a maintenance path opts in.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_writes_allowed: ContextVar[bool] = ContextVar("psy_legacy_table_writes", default=False)

# Concrete models whose tables are history. Keep this aligned with the classes
# that inherit LegacyTable.
FROZEN_MODEL_NAMES = (
    "SessionType",
    "TherapistSessionOffer",
    "TherapistAvailability",
    "AvailabilityException",
    "LeaveRequest",
    "AppointmentSlot",
    "Appointment",
    "TherapistReview",
    "PsychometricForm",
    "PsychometricResponse",
    "Workshop",
    "WorkshopEnrollment",
    "WorkshopSession",
    "WorkshopResource",
    "WorkshopSessionProgress",
    "WorkshopCertificate",
    "BlogPost",
    "NewsSlide",
    "SitePage",
    "ProductCategory",
    "Product",
    "Coupon",
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "CouponRedemption",
)


class LegacyTableFrozen(Exception):
    """A write targeted a psychology table that no longer owns the data."""

    def __init__(self, model):
        label = model._meta.label
        super().__init__(
            f"{label} is a frozen history table. Write the shared module that "
            "owns this data, or use allow_legacy_table_writes() for an explicit "
            "maintenance path."
        )


@contextmanager
def allow_legacy_table_writes():
    """Open the history tables for one deliberate maintenance write."""

    token = _writes_allowed.set(True)
    try:
        yield
    finally:
        _writes_allowed.reset(token)


def legacy_writes_allowed() -> bool:
    if _writes_allowed.get():
        return True
    frame = sys._getframe()
    while frame is not None:
        # Referential actions (SET_NULL, CASCADE bookkeeping) originate here.
        # Public queryset writes from admin and application code do not.
        if frame.f_globals.get("__name__") == "django.db.models.deletion":
            return True
        frame = frame.f_back
    return False


def ensure_legacy_writes_allowed(model) -> None:
    if not legacy_writes_allowed():
        raise LegacyTableFrozen(model)


class LegacyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        ensure_legacy_writes_allowed(self.model)
        return super().update(**kwargs)

    def delete(self):
        ensure_legacy_writes_allowed(self.model)
        return super().delete()

    def bulk_create(self, objs, **kwargs):
        ensure_legacy_writes_allowed(self.model)
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        ensure_legacy_writes_allowed(self.model)
        return super().bulk_update(objs, fields, **kwargs)


class LegacyManager(models.Manager.from_queryset(LegacyQuerySet)):
    pass


class LegacyTable(models.Model):
    """Abstract base for psychology models retained after extraction."""

    objects = LegacyManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        ensure_legacy_writes_allowed(type(self))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        ensure_legacy_writes_allowed(type(self))
        return super().delete(*args, **kwargs)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls._meta.abstract:
            return
        current = cls.__dict__.get("objects")
        if not isinstance(current, LegacyManager):
            cls.add_to_class("objects", LegacyManager())
