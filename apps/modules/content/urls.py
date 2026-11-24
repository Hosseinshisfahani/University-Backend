from rest_framework.routers import DefaultRouter

from .views import NewsSlideViewSet, PostViewSet, SitePageViewSet

app_name = "content"

router = DefaultRouter()
router.register("posts", PostViewSet, basename="post")
router.register("slides", NewsSlideViewSet, basename="slide")
router.register("pages", SitePageViewSet, basename="page")

urlpatterns = router.urls
