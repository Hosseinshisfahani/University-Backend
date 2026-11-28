"""Checkout handlers registered by modules.

Finance never imports a module. Each module calls ``register_checkout`` from
its AppConfig.ready().
"""

from __future__ import annotations

from collections.abc import Callable

Handler = Callable  # (payment) -> None


class CheckoutNotFulfillable(Exception):
    """The bank captured the money, but the order, course, or appointment cannot be delivered."""


_handlers: dict[str, tuple[Handler, Handler | None]] = {}


def register_checkout(prefix: str, fulfill: Handler, release: Handler | None = None) -> None:
    _handlers[prefix] = (fulfill, release)


def handler_for(purpose: str) -> tuple[Handler, Handler | None] | None:
    for prefix, pair in _handlers.items():
        if purpose.startswith(prefix):
            return pair
    return None


def clear_handlers() -> None:
    """Test helper. Production code does not call this."""
    _handlers.clear()
