from django.dispatch import Signal

enrollment_confirmed = Signal()
enrollment_cancelled = Signal()
certificate_issued = Signal()
