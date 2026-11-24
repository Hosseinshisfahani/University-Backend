from rest_framework import serializers

from .models import Form, Response


class FormSerializer(serializers.ModelSerializer):
    class Meta:
        model = Form
        fields = ["id", "title", "slug", "description", "schema", "version", "is_published"]
        read_only_fields = ["version"]


class ResponseSerializer(serializers.ModelSerializer):
    form_version = serializers.IntegerField(source="version.version", read_only=True)

    class Meta:
        model = Response
        fields = [
            "id",
            "form",
            "form_version",
            "respondent",
            "answers",
            "status",
            "assigned_to",
            "reviewer_notes",
            "score",
            "submitted_at",
        ]
        read_only_fields = [
            "id",
            "form_version",
            "respondent",
            "score",
            "submitted_at",
            "status",
        ]
