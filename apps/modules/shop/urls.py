from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "shop"

router = DefaultRouter()
router.register("categories", views.ProductCategoryViewSet, basename="shop-category")
router.register("products", views.ProductViewSet, basename="shop-product")
router.register("coupons", views.CouponViewSet, basename="shop-coupon")
router.register("orders", views.ShopOrderViewSet, basename="shop-order")

urlpatterns = [
    path("cart/", views.CartView.as_view()),
    path("cart/items/", views.CartItemListView.as_view()),
    path("cart/items/<int:pk>/", views.CartItemDetailView.as_view()),
    path("cart/coupon/", views.CartCouponView.as_view()),
    path("admin/orders/", views.AdminShopOrderListView.as_view()),
    path("admin/orders/<int:pk>/", views.AdminShopOrderDetailView.as_view()),
    path("admin/orders/<int:pk>/refund/", views.AdminShopOrderRefundView.as_view()),
    path("admin/stats/", views.AdminShopStatsView.as_view()),
    *router.urls,
]
