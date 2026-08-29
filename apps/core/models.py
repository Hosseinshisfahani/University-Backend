"""
Shared abstract base models.

The core app holds only domain-agnostic building blocks. It must never
import from domain apps.
"""

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base with automatic created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
