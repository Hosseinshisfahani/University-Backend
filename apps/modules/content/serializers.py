from rest_framework import serializers

from apps.kernel.tenancy.services import extend_payload, person_name

from .models import NewsSlide, Post, SitePage


class PostSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "body",
            "cover_image",
            "is_published",
            "published_at",
            "author_name",
        ]
        read_only_fields = ["author_name"]

    def get_author_name(self, obj: Post) -> str | None:
        if not obj.author_id:
            return None
        return person_name(obj.institute, obj.author)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return extend_payload(instance.institute, "content.post", instance, data)


class NewsSlideSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsSlide
        fields = [
            "id",
            "title",
            "body",
            "image",
            "link_url",
            "link_label",
            "sort_order",
            "is_published",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"image": {"required": False, "allow_null": True}}

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        image = data.get("image") if hasattr(data, "get") else None
        if image is None or isinstance(image, str):
            try:
                data.pop("image")
            except (KeyError, AttributeError, TypeError):
                pass
        return super().to_internal_value(data)


class SitePageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SitePage
        fields = ["id", "key", "title", "body", "updated_at"]
