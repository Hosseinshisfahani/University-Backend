"""Finance domain signals.

Receivers must not raise. A failed listener must never roll back the
wallet credit that ``confirm_payment`` just recorded.
"""

from django.dispatch import Signal

# Sent once, after a Payment newly reaches SUCCEEDED and the wallet is credited.
# kwargs: payment (Payment).
payment_succeeded = Signal()
