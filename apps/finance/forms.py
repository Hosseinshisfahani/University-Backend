"""Django-admin forms for finance. Not exposed via the public REST API."""

from django import forms
from django.db import models


class WalletAdjustBalanceForm(forms.Form):
    """Manual credit/debit. Amount is entered in Toman, stored as IRR (Rials)."""

    class Action(models.TextChoices):
        CREDIT = "credit", "Credit (Increase)"
        DEBIT = "debit", "Debit (Decrease)"

    action = forms.ChoiceField(
        choices=Action.choices,
        label="Action",
        widget=forms.RadioSelect,
    )
    amount = forms.IntegerField(
        min_value=1,
        label="Amount (Toman)",
        help_text=(
            "Positive whole number in Toman. Converted to Rials (×10) before "
            "writing the ledger entry."
        ),
    )
    description = forms.CharField(
        label="Reason / Description",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Required audit note explaining why this adjustment was made.",
    )
