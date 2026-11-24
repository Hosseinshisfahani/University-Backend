from rest_framework.routers import DefaultRouter

from .views import FormViewSet, ResponseViewSet

router = DefaultRouter()
router.register("forms", FormViewSet, basename="form")
router.register("responses", ResponseViewSet, basename="response")

urlpatterns = router.urls
