"""Shop events. The module does not import an institute.

Gateway fulfillment is registered from AppConfig.ready for both
``shop.order:`` and the legacy ``psy.order:`` purpose. The same handler
fulfills either prefix. This module emits the order signals; an institute
does not settle the order.
"""

from django.dispatch import Signal

order_paid = Signal()
order_shipped = Signal()
order_cancelled = Signal()
order_refunded = Signal()
