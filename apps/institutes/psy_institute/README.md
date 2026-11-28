# Psychology Institute (`apps.institutes.psy_institute`)

Domain app for the university psychology center: therapist and patient profiles, clinical notes, psychometric forms, and tickets (including wallet withdrawals via `apps.kernel.finance`).

Scheduling, workshops (courses), the shop, blog/news, and reviews belong to `apps.modules` (`booking`, `lms`, `shop`, `content`, `reviews`). `/api/v1/psy/...` keeps thin adapters for one compatibility release. Shop settlement stays in the shop module.

## Roles (Django groups)

| Group | Capability |
|---|---|
| `psy_admin` | Session types, weekly templates, slot CRUD, regenerate slots, register appointments (pending / wallet / offline), move/cancel, leave review, content |
| `psy_therapist` | Read-only agenda, meeting links, notes, submit/cancel pending leave requests |
| `psy_patient` | Book/pay from open slots, cancel (24h policy), tests, workshops, shop, tickets |

Bootstrap groups: `POST /api/v1/psy/roles/ensure-groups/` (admin).

## Key services

- `services.regenerate_slots_for_therapist` — materialize generic open time blocks from admin-owned weekly templates (session type is chosen at booking)
- `services.create_open_slot` / `delete_open_slot` — one-off admin slot CRUD with overlap guard
- `services.book_slot` / `confirm_appointment_payment` / `admin_book_appointment` / `cancel_appointment` / `move_appointment`
- `services.submit_leave_request` / `approve_leave_request` / `reject_leave_request`

Appointment wallet captures and refunds go through `apps.kernel.finance.services` with opaque refs like `booking.appointment:42`. Offline admin confirms (`payment_ref=offline`) skip the wallet ledger. The old `psy.appointment:` ledger prefix was rewritten onto `booking.appointment:`.

## Shop and courses

Catalog, cart, coupons, orders, and courses live in `apps.modules` under `/api/v1/institutes/<slug>/shop/` and `/lms/`. Gateway checkout is Vandar. The shop app registers one handler for `shop.order:{id}` and legacy `psy.order:{id}`; `apps/modules/shop/signals.py` emits `order_paid`, `order_shipped`, `order_cancelled`, and `order_refunded` after that handler runs. Copied rows were also rewritten from `psy.order:{id}` to `shop.order:{id}`. This app sends SMS when the order belongs to psy. Physical shipping uses the institute shop setting; `PSY_SHOP_SHIPPING_FEE` is the bootstrap fallback for psy.
