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
    path("sep/initiate/", views.SepInitiateView.as_view(), name="sep-initiate"),
    path("sep/callback/", views.SepCallbackView.as_view(), name="sep-callback"),
    *router.urls,
]
