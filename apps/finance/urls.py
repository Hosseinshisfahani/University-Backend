from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "finance"

router = DefaultRouter()
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("withdrawals", views.WithdrawalViewSet, basename="withdrawal")

urlpatterns = [
    path("wallet/", views.WalletView.as_view(), name="wallet"),
    path("wallet/ledger/", views.LedgerListView.as_view(), name="ledger"),
    path("vandar/initiate/", views.VandarInitiateView.as_view(), name="vandar-initiate"),
    path("vandar/callback/", views.VandarCallbackView.as_view(), name="vandar-callback"),
    *router.urls,
]
