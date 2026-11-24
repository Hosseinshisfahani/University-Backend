from django.urls import path
from rest_framework.routers import DefaultRouter

from . import admin_api, module_adapters, schedule_admin, views

app_name = "psy_institute"

router = DefaultRouter()
router.register("session-types", views.SessionTypeViewSet, basename="session-type")
router.register("therapists", views.TherapistProfileViewSet, basename="therapist")
router.register(
    "therapist/availability",
    views.TherapistAvailabilityViewSet,
    basename="therapist-availability",
)
router.register(
    "therapist/exceptions",
    views.AvailabilityExceptionViewSet,
    basename="therapist-exception",
)
router.register(
    "therapist/session-offers",
    views.TherapistSessionOfferViewSet,
    basename="therapist-offer",
)
router.register(
    "therapist/leave-requests",
    views.TherapistLeaveRequestViewSet,
    basename="therapist-leave-request",
)
router.register(
    "therapist/patients",
    views.TherapistPatientViewSet,
    basename="therapist-patient",
)
router.register("appointments", views.AppointmentViewSet, basename="appointment")
router.register("session-notes", views.SessionNoteViewSet, basename="session-note")
router.register(
    "clinical-reports", views.ClinicalReportViewSet, basename="clinical-report"
)
router.register(
    "file-access-requests",
    views.FileAccessRequestViewSet,
    basename="file-access-request",
)
router.register(
    "psychometric-forms",
    views.PsychometricFormViewSet,
    basename="psychometric-form",
)
router.register(
    "psychometric-responses",
    views.PsychometricResponseViewSet,
    basename="psychometric-response",
)
router.register("workshops", module_adapters.PsyWorkshopViewSet, basename="workshop")
router.register(
    "shop/categories", module_adapters.PsyProductCategoryViewSet, basename="shop-category"
)
router.register("shop/products", module_adapters.PsyProductViewSet, basename="shop-product")
router.register("shop/coupons", module_adapters.PsyCouponViewSet, basename="shop-coupon")
router.register("shop/orders", module_adapters.PsyShopOrderViewSet, basename="shop-order")
router.register("blog", module_adapters.PsyBlogPostViewSet, basename="blog")
router.register("news", module_adapters.PsyNewsSlideViewSet, basename="news")
router.register("pages", module_adapters.PsySitePageViewSet, basename="page")
router.register("tickets", views.TicketViewSet, basename="ticket")

urlpatterns = [
    path("slots/regenerate/", views.RegenerateSlotsView.as_view(), name="slots-regenerate"),
    path(
        "admin/slots/",
        schedule_admin.AdminSlotListCreateView.as_view(),
        name="admin-slot-list",
    ),
    path(
        "admin/slots/<int:pk>/",
        schedule_admin.AdminSlotDetailView.as_view(),
        name="admin-slot-detail",
    ),
    path(
        "admin/appointments/",
        schedule_admin.AdminAppointmentCreateView.as_view(),
        name="admin-appointment-create",
    ),
    path(
        "admin/leave-requests/",
        schedule_admin.AdminLeaveRequestListView.as_view(),
        name="admin-leave-request-list",
    ),
    path(
        "admin/leave-requests/<int:pk>/approve/",
        schedule_admin.AdminLeaveRequestApproveView.as_view(),
        name="admin-leave-request-approve",
    ),
    path(
        "admin/leave-requests/<int:pk>/reject/",
        schedule_admin.AdminLeaveRequestRejectView.as_view(),
        name="admin-leave-request-reject",
    ),
    path(
        "admin/therapists/<int:therapist_id>/availability/",
        schedule_admin.AdminTherapistAvailabilityListCreate.as_view(),
        name="admin-therapist-availability-list",
    ),
    path(
        "admin/therapists/<int:therapist_id>/availability/<int:pk>/",
        schedule_admin.AdminTherapistAvailabilityDetail.as_view(),
        name="admin-therapist-availability-detail",
    ),
    path(
        "admin/therapists/<int:therapist_id>/session-offers/",
        schedule_admin.AdminTherapistOfferListCreate.as_view(),
        name="admin-therapist-offer-list",
    ),
    path(
        "admin/therapists/<int:therapist_id>/session-offers/<int:pk>/",
        schedule_admin.AdminTherapistOfferDetail.as_view(),
        name="admin-therapist-offer-detail",
    ),
    path(
        "admin/therapists/<int:therapist_id>/exceptions/",
        schedule_admin.AdminTherapistExceptionListCreate.as_view(),
        name="admin-therapist-exception-list",
    ),
    path(
        "admin/therapists/<int:therapist_id>/exceptions/<int:pk>/",
        schedule_admin.AdminTherapistExceptionDetail.as_view(),
        name="admin-therapist-exception-detail",
    ),
    path("roles/ensure-groups/", views.EnsurePsyGroupsView.as_view(), name="ensure-groups"),
    path("admin/overview/", admin_api.AdminOverviewView.as_view(), name="admin-overview"),
    path(
        "admin/patients/",
        admin_api.AdminPatientListView.as_view(),
        name="admin-patient-list",
    ),
    path(
        "admin/patients/<int:pk>/",
        admin_api.AdminPatientDetailView.as_view(),
        name="admin-patient-detail",
    ),
    path(
        "admin/therapists/",
        admin_api.AdminTherapistListView.as_view(),
        name="admin-therapist-list",
    ),
    path(
        "admin/therapists/<int:pk>/",
        admin_api.AdminTherapistDetailView.as_view(),
        name="admin-therapist-detail",
    ),
    path(
        "admin/finance/summary/",
        admin_api.AdminFinanceSummaryView.as_view(),
        name="admin-finance-summary",
    ),
    path(
        "admin/finance/ledger/",
        admin_api.AdminFinanceLedgerView.as_view(),
        name="admin-finance-ledger",
    ),
    path(
        "admin/finance/payments/",
        admin_api.AdminFinancePaymentsView.as_view(),
        name="admin-finance-payments",
    ),
    path(
        "admin/finance/appointment-revenue/",
        admin_api.AdminFinanceAppointmentRevenueView.as_view(),
        name="admin-finance-appointment-revenue",
    ),
    path("shop/cart/", module_adapters.PsyCartView.as_view(), name="shop-cart"),
    path(
        "shop/cart/items/",
        module_adapters.PsyCartItemListView.as_view(),
        name="shop-cart-items",
    ),
    path(
        "shop/cart/items/<int:pk>/",
        module_adapters.PsyCartItemDetailView.as_view(),
        name="shop-cart-item",
    ),
    path(
        "shop/cart/coupon/",
        module_adapters.PsyCartCouponView.as_view(),
        name="shop-cart-coupon",
    ),
    path(
        "admin/shop/orders/",
        module_adapters.PsyAdminShopOrderListView.as_view(),
        name="admin-shop-orders",
    ),
    path(
        "admin/shop/orders/<int:pk>/",
        module_adapters.PsyAdminShopOrderDetailView.as_view(),
        name="admin-shop-order",
    ),
    path(
        "admin/shop/orders/<int:pk>/refund/",
        module_adapters.PsyAdminShopOrderRefundView.as_view(),
        name="admin-shop-order-refund",
    ),
    path(
        "admin/shop/stats/",
        module_adapters.PsyAdminShopStatsView.as_view(),
        name="admin-shop-stats",
    ),
    path(
        "patient/workshop-enrollments/",
        module_adapters.PsyPatientEnrollmentView.as_view(),
        name="patient-workshop-enrollments",
    ),
    path(
        "therapist/workshops/",
        module_adapters.PsyTeachingCourseListView.as_view(),
        name="therapist-workshop-list",
    ),
    path(
        "therapist/reviews/",
        views.TherapistReviewListView.as_view(),
        name="therapist-review-list",
    ),
    path(
        "therapist/finance/",
        views.TherapistFinanceView.as_view(),
        name="therapist-finance",
    ),
    path(
        "admin/reviews/",
        admin_api.AdminReviewListView.as_view(),
        name="admin-review-list",
    ),
    path(
        "admin/reviews/<int:pk>/approve/",
        admin_api.AdminReviewApproveView.as_view(),
        name="admin-review-approve",
    ),
    path(
        "admin/reviews/<int:pk>/reject/",
        admin_api.AdminReviewRejectView.as_view(),
        name="admin-review-reject",
    ),
    path(
        "workshops/<slug:workshop_slug>/sessions/",
        module_adapters.PsyWorkshopSessionListCreateView.as_view(),
        name="workshop-session-list",
    ),
    path(
        "workshops/<slug:workshop_slug>/sessions/<int:pk>/",
        module_adapters.PsyWorkshopSessionDetailView.as_view(),
        name="workshop-session-detail",
    ),
    path(
        "workshops/<slug:workshop_slug>/resources/",
        module_adapters.PsyWorkshopResourceListCreateView.as_view(),
        name="workshop-resource-list",
    ),
    path(
        "workshops/<slug:workshop_slug>/resources/<int:pk>/",
        module_adapters.PsyWorkshopResourceDetailView.as_view(),
        name="workshop-resource-detail",
    ),
    *router.urls,
]
