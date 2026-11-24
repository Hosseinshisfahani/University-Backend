from django.urls import path

from .views import ModerationActionView, ModerationListView, ReviewListView

urlpatterns = [
    path("", ReviewListView.as_view()),
    path("moderation/", ModerationListView.as_view()),
    path("moderation/<int:pk>/<str:action>/", ModerationActionView.as_view()),
]
