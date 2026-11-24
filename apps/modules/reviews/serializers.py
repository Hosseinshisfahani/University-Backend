from rest_framework import serializers

from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "rating", "body", "text_status", "author_name", "admin_note", "created_at"]

    def get_author_name(self, obj):
        user = obj.author
        return user.get_full_name() or user.username
