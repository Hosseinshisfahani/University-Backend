"""Admin forms for the psychology institute."""

from __future__ import annotations

import json
import re

from django import forms

from . import models

_SPLIT_RE = re.compile(r"[\n\r,،;؛|]+")
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
_QUOTE_CHARS = "\"'“”«»"


def parse_specialties(value) -> list[str]:
    """Turn admin-friendly text, or loose JSON, into a list of specialty names.

    Accepted input:
    - one specialty per line
    - comma-separated text (English or Persian comma)
    - a JSON array of strings
    - bracket groups such as ``[مشاوره خانواده][مشاوره پژوهش]``
    """
    if value is None:
        return []
    if isinstance(value, list):
        return _normalize(value, split_further=False)

    text = str(value).strip()
    if not text:
        return []

    parsed = _loads_json_list(text)
    if parsed is not None:
        return _normalize(parsed, split_further=False)

    bracketed = _BRACKET_RE.findall(text)
    leftover = _BRACKET_RE.sub("", text).strip(" \t\r\n,،;؛")
    if bracketed and not leftover:
        return _normalize(bracketed, split_further=True)

    return _normalize(_SPLIT_RE.split(text), split_further=False)


def _loads_json_list(text: str) -> list | None:
    if text[0] not in "[{":
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, str):
        return [parsed]
    return None


def _normalize(items, *, split_further: bool) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, (list, dict)) or item is None:
            continue
        parts = _SPLIT_RE.split(str(item)) if split_further else [str(item)]
        for part in parts:
            text = part.strip().strip(_QUOTE_CHARS).strip()
            if split_further:
                text = text.strip("[]").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
    return cleaned


class SpecialtyListWidget(forms.Textarea):
    def __init__(self, attrs=None):
        defaults = {
            "rows": 6,
            "cols": 40,
            "class": "vLargeTextField",
            "placeholder": "مشاوره خانواده\nمشاوره پژوهش",
        }
        if attrs:
            defaults.update(attrs)
        super().__init__(defaults)

    def format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        return value


class SpecialtyListField(forms.Field):
    widget = SpecialtyListWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "help_text",
            "هر تخصص را در یک خط بنویسید، یا آن‌ها را با ویرگول جدا کنید.",
        )
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        if value is None:
            return ""
        return value

    def to_python(self, value):
        return parse_specialties(value)


class TherapistProfileAdminForm(forms.ModelForm):
    specialties = SpecialtyListField(label="تخصص‌ها")

    class Meta:
        model = models.TherapistProfile
        fields = "__all__"
