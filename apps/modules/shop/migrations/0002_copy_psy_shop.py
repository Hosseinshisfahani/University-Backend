from django.db import connection, migrations


def _name(value) -> str:
    if not value:
        return ""
    return getattr(value, "name", "") or ""


def _copy(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    Patient = apps.get_model("psy_institute", "PatientProfile")
    psy = Institute.objects.get(slug="psy")
    pairs = (
        ("ProductCategory", "ProductCategory", ("name", "slug", "description", "sort_order", "is_active", "created_at", "updated_at"), {}),
        ("Coupon", "Coupon", (
            "code", "kind", "value", "max_discount", "min_order_total", "starts_at", "ends_at",
            "max_uses", "max_uses_per_user", "used_count", "is_active", "created_at", "updated_at",
        ), {}),
        ("Product", "Product", (
            "title", "slug", "kind", "description", "body_md", "price", "compare_at_price",
            "is_published", "is_available", "sort_order", "created_at", "updated_at",
        ), {"image": "image", "digital_file": "digital_file"}),
    )
    for old_name, new_name, fields, files in pairs:
        Old = apps.get_model("psy_institute", old_name)
        New = apps.get_model("shop", new_name)
        for row in Old.objects.all().iterator():
            values = {field: getattr(row, field) for field in fields}
            for target, source in files.items():
                values[target] = _name(getattr(row, source))
            if new_name == "Product":
                values["category_id"] = row.category_id
            values["institute_id"] = psy.pk
            New.objects.update_or_create(id=row.pk, defaults=values)
            if hasattr(row, "created_at"):
                New.objects.filter(pk=row.pk).update(created_at=row.created_at, updated_at=row.updated_at)

    OldCart = apps.get_model("psy_institute", "Cart")
    NewCart = apps.get_model("shop", "Cart")
    for row in OldCart.objects.all().iterator():
        user_id = Patient.objects.values_list("user_id", flat=True).get(pk=row.patient_id)
        NewCart.objects.update_or_create(
            id=row.pk,
            defaults={"institute_id": psy.pk, "user_id": user_id, "coupon_id": row.coupon_id},
        )
        NewCart.objects.filter(pk=row.pk).update(created_at=row.created_at, updated_at=row.updated_at)

    OldItem = apps.get_model("psy_institute", "CartItem")
    NewItem = apps.get_model("shop", "CartItem")
    for row in OldItem.objects.all().iterator():
        NewItem.objects.update_or_create(
            id=row.pk,
            defaults={"cart_id": row.cart_id, "product_id": row.product_id, "quantity": row.quantity},
        )

    OldOrder = apps.get_model("psy_institute", "Order")
    NewOrder = apps.get_model("shop", "Order")
    order_fields = (
        "number", "status", "requires_shipping", "shipping_full_name", "shipping_phone",
        "shipping_province", "shipping_city", "shipping_address", "shipping_postal_code",
        "subtotal", "discount_total", "shipping_fee", "total", "coupon_code", "payment_ref",
        "deposit_ledger_ref", "refund_ledger_ref", "hold_expires_at", "gateway_payment_id",
        "paid_at", "shipped_at", "tracking_code", "canceled_at", "cancellation_reason", "admin_note",
    )
    for row in OldOrder.objects.all().iterator():
        user_id = Patient.objects.values_list("user_id", flat=True).get(pk=row.patient_id)
        values = {field: getattr(row, field) for field in order_fields}
        values.update({"institute_id": psy.pk, "user_id": user_id, "coupon_id": row.coupon_id})
        NewOrder.objects.update_or_create(id=row.pk, defaults=values)
        NewOrder.objects.filter(pk=row.pk).update(created_at=row.created_at, updated_at=row.updated_at)

    OldLine = apps.get_model("psy_institute", "OrderItem")
    NewLine = apps.get_model("shop", "OrderItem")
    for row in OldLine.objects.all().iterator():
        NewLine.objects.update_or_create(
            id=row.pk,
            defaults={
                "order_id": row.order_id,
                "product_id": row.product_id,
                "title": row.title,
                "kind": row.kind,
                "unit_price": row.unit_price,
                "quantity": row.quantity,
                "line_total": row.line_total,
            },
        )

    OldRedemption = apps.get_model("psy_institute", "CouponRedemption")
    NewRedemption = apps.get_model("shop", "CouponRedemption")
    for row in OldRedemption.objects.all().iterator():
        user_id = Patient.objects.values_list("user_id", flat=True).get(pk=row.patient_id)
        NewRedemption.objects.update_or_create(
            id=row.pk,
            defaults={"coupon_id": row.coupon_id, "order_id": row.order_id, "user_id": user_id},
        )

    Ledger = apps.get_model("finance", "LedgerEntry")
    Payment = apps.get_model("finance", "Payment")
    for row in Ledger.objects.filter(reference__startswith="psy.order:"):
        row.reference = "shop.order:" + row.reference[len("psy.order:") :]
        row.save(update_fields=["reference"])
    for row in Payment.objects.filter(purpose__startswith="psy.order:"):
        row.purpose = "shop.order:" + row.purpose[len("psy.order:") :]
        row.save(update_fields=["purpose"])

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            for table in (
                "shop_productcategory", "shop_product", "shop_coupon", "shop_cart",
                "shop_cartitem", "shop_order", "shop_orderitem", "shop_couponredemption",
            ):
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0001_initial"),
        ("psy_institute", "0019_review_bridge"),
        ("finance", "0004_shop_purchase_entry_type"),
    ]

    operations = [
        migrations.RunPython(_copy, migrations.RunPython.noop),
    ]
