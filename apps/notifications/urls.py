from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("admin/recipients/", views.AdminRecipientListView.as_view(), name="admin-recipients"),
    path("admin/send/", views.AdminSmsSendView.as_view(), name="admin-send"),
    path("admin/messages/", views.AdminSmsMessageListView.as_view(), name="admin-messages"),
]
