from __future__ import annotations

from copy import deepcopy

from django.db import transaction

from .models import Form, FormVersion, Response


class FormsError(Exception):
    pass


def score_answers(schema: dict, answers: dict) -> dict:
    """Score against the frozen schema. Unknown modes return an empty score."""
    scoring = schema.get("scoring") if isinstance(schema, dict) else None
    if not isinstance(scoring, dict) or scoring.get("mode") != "sum":
        return {}
    fields = scoring.get("fields") or []
    total = 0
    for key in fields:
        raw = answers.get(key)
        try:
            total += float(raw)
        except (TypeError, ValueError):
            continue
    return {"mode": "sum", "total": total}


@transaction.atomic
def publish_schema(*, form: Form, schema: dict, title: str | None = None) -> Form:
    """Write a new version when the current one already has responses."""
    schema = deepcopy(schema or {})
    current = form.versions.filter(version=form.version).first()
    if current and current.responses.exists() and current.schema != schema:
        form.version += 1
        current = FormVersion.objects.create(
            form=form, version=form.version, schema=schema, schema_available=True
        )
    elif current is None:
        current = FormVersion.objects.create(
            form=form, version=form.version, schema=schema, schema_available=True
        )
    elif not current.responses.exists():
        current.schema = schema
        current.save(update_fields=["schema"])
    form.schema = schema
    if title is not None:
        form.title = title
    form.save(update_fields=["schema", "version", "title", "updated_at"])
    return form


@transaction.atomic
def submit_response(*, form: Form, respondent, answers: dict, assigned_to=None) -> Response:
    if not form.is_published:
        raise FormsError("فرم منتشر نشده است.")
    version = form.versions.filter(version=form.version).first()
    if version is None:
        version = FormVersion.objects.create(
            form=form, version=form.version, schema=form.schema, schema_available=True
        )
    if form.institute_id != version.form.institute_id:
        raise FormsError("نسخه متعلق به این مرکز نیست.")
    return Response.objects.create(
        institute=form.institute,
        form=form,
        version=version,
        respondent=respondent,
        answers=answers or {},
        assigned_to=assigned_to,
        score=score_answers(version.schema, answers or {}),
    )
