from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    """
    من توسعه دهنده اول این سیستم ام
    هر چیزی که میخوای برای کاربر باشه رو اینجا بنویس
    """

    email = models.EmailField(verbose_name="ایمیل", blank=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self) -> str:
        return self.get_full_name() or self.username
