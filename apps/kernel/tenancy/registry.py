"""Capability registry.

``enabled_modules`` on an institute is the only per-institute selection.
This table describes which implementations exist. ``ready`` is false until
the module has been extracted from psy_institute. New institutes may enable
only ready capabilities. The bootstrap psy institute may keep unready ids
because its legacy routes still serve them.
"""

from __future__ import annotations

MODULES: tuple[dict, ...] = (
    {
        "id": "content",
        "prefix": "content",
        "ready": True,
        "legacy_prefixes": ["blog", "news", "pages"],
    },
    {
        "id": "reviews",
        "prefix": "reviews",
        "ready": True,
        "legacy_prefixes": ["admin/reviews", "therapist/reviews"],
    },
    {
        "id": "forms",
        "prefix": "forms",
        "ready": True,
        "legacy_prefixes": ["psychometric-forms", "psychometric-responses"],
    },
    {
        "id": "shop",
        "prefix": "shop",
        "ready": True,
        "legacy_prefixes": ["admin/shop", "shop"],
    },
    {
        "id": "lms",
        "prefix": "lms",
        "ready": True,
        "legacy_prefixes": [
            "patient/workshop-enrollments",
            "therapist/workshops",
            "workshops",
        ],
    },
    {
        "id": "booking",
        "prefix": "booking",
        "ready": True,
        "legacy_prefixes": [
            "admin/appointments",
            "admin/leave-requests",
            "admin/slots",
            "appointments",
            "session-types",
            "slots",
            "therapist/availability",
            "therapist/exceptions",
            "therapist/leave-requests",
            "therapist/session-offers",
        ],
    },
)

REGISTRY = {item["id"]: item for item in MODULES}
BOOTSTRAP_INSTITUTE_SLUG = "psy"
ALL_MODULE_IDS = [item["id"] for item in MODULES]


def capability_for_legacy_path(path: str) -> str | None:
    """Map a legacy ``/api/v1/psy/...`` path to a capability id, if any."""
    marker = "/api/v1/psy/"
    if marker not in path:
        return None
    rest = path.split(marker, 1)[1].strip("/")
    if not rest:
        return None
    best_id = None
    best_len = -1
    for item in MODULES:
        for prefix in item["legacy_prefixes"]:
            if rest == prefix or rest.startswith(prefix + "/"):
                if len(prefix) > best_len:
                    best_id = item["id"]
                    best_len = len(prefix)
    return best_id


def validate_enabled_modules(slug: str, modules: list[str]) -> list[str]:
    """Return a cleaned module list or raise ValueError."""
    if len(modules) != len(set(modules)):
        raise ValueError("شناسه ماژول تکراری است.")
    unknown = [item for item in modules if item not in REGISTRY]
    if unknown:
        raise ValueError(f"ماژول ناشناخته: {', '.join(unknown)}")
    if slug != BOOTSTRAP_INSTITUTE_SLUG:
        unready = [item for item in modules if not REGISTRY[item]["ready"]]
        if unready:
            raise ValueError(
                "این ماژول‌ها هنوز استخراج نشده‌اند و برای مرکز جدید قابل فعال‌سازی نیستند: "
                + ", ".join(unready)
            )
    return list(modules)
