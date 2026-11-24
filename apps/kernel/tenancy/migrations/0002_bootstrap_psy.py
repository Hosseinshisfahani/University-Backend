from django.db import migrations


MODULES = ["content", "reviews", "forms", "shop", "lms", "booking"]
GROUP_TO_ROLE = {
    "psy_admin": "admin",
    "psy_therapist": "staff",
    "psy_patient": "member",
}


def bootstrap(apps, schema_editor):
    Institute = apps.get_model("tenancy", "Institute")
    Membership = apps.get_model("tenancy", "InstituteMembership")
    Role = apps.get_model("tenancy", "InstituteMembershipRole")
    User = apps.get_model("accounts", "User")
    Group = apps.get_model("auth", "Group")

    institute, _ = Institute.objects.get_or_create(
        slug="psy",
        defaults={
            "name": "مؤسسه روان‌شناسی",
            "is_active": True,
            "frontend_mode": "custom",
            "enabled_modules": MODULES,
            "settings": {},
        },
    )
    if not institute.is_active or institute.enabled_modules != MODULES:
        institute.is_active = True
        institute.frontend_mode = "custom"
        institute.enabled_modules = MODULES
        institute.save(update_fields=["is_active", "frontend_mode", "enabled_modules"])

    roles_by_user: dict[int, set[str]] = {}
    for group_name, role in GROUP_TO_ROLE.items():
        group = Group.objects.filter(name=group_name).first()
        if group is None:
            continue
        for user_id in group.user_set.values_list("id", flat=True):
            roles_by_user.setdefault(user_id, set()).add(role)

    staff = User.objects.filter(is_active=True, is_staff=True) | User.objects.filter(
        is_active=True, is_superuser=True
    )
    for user in staff.distinct():
        roles_by_user.setdefault(user.pk, set()).add("admin")
        print(f"tenancy bootstrap: granted psy admin to staff user {user.username}")

    for user_id, roles in roles_by_user.items():
        membership, _ = Membership.objects.get_or_create(
            user_id=user_id,
            institute=institute,
            defaults={"is_active": True},
        )
        for role in roles:
            Role.objects.get_or_create(membership=membership, role=role)


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0001_initial"),
        ("accounts", "0003_copy_patient_phone_to_user"),
    ]

    operations = [
        migrations.RunPython(bootstrap, migrations.RunPython.noop),
    ]
