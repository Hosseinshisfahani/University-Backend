from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    من توسعه دهنده اول این سیستم ام
    هر چیزی که میخوای برای کاربر باشه رو اینجا بنویس
    """

    email = models.EmailField(verbose_name="ایمیل", blank=True)
    phone = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        verbose_name="تلفن",
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=~models.Q(phone=""),
                name="accounts_user_phone_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.get_full_name() or self.username