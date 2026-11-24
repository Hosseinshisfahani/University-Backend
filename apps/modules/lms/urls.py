from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "lms"

router = DefaultRouter()
router.register("courses", views.CourseViewSet, basename="course")

urlpatterns = [
    path("enrollments/", views.MyEnrollmentListView.as_view()),
    path("teaching/", views.TeachingCourseListView.as_view()),
    path("courses/<slug:course_slug>/sessions/", views.CourseSessionListCreateView.as_view()),
    path("courses/<slug:course_slug>/sessions/<int:pk>/", views.CourseSessionDetailView.as_view()),
    path("courses/<slug:course_slug>/resources/", views.CourseResourceListCreateView.as_view()),
    path("courses/<slug:course_slug>/resources/<int:pk>/", views.CourseResourceDetailView.as_view()),
    *router.urls,
]
