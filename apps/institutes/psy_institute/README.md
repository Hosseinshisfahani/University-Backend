# Psychology Institute (`apps.institutes.psy_institute`)

Domain app for the university psychology center: therapists, patients, session types, admin-owned availability templates → generated or one-off slots, appointments with 24h refund policy, leave requests, psychometric forms (JSON schema), workshops, blog/about, and tickets (including wallet withdrawals via `apps.finance`).

## Roles (Django groups)

| Group | Capability |
|---|---|
| `psy_admin` | Session types, weekly templates, slot CRUD, regenerate slots, register appointments (pending / wallet / offline), move/cancel, leave review, content |
| `psy_therapist` | Read-only agenda, meeting links, notes, submit/cancel pending leave requests |
| `psy_patient` | Book/pay from open slots, cancel (24h policy), tests, workshops, tickets |

Bootstrap groups: `POST /api/v1/psy/roles/ensure-groups/` (admin).

## Key services

- `services.regenerate_slots_for_therapist` — materialize generic open time blocks from admin-owned weekly templates (session type is chosen at booking)
- `services.create_open_slot` / `delete_open_slot` — one-off admin slot CRUD with overlap guard
- `services.book_slot` / `confirm_appointment_payment` / `admin_book_appointment` / `cancel_appointment` / `move_appointment`
- `services.submit_leave_request` / `approve_leave_request` / `reject_leave_request`

Wallet captures and refunds go through `apps.finance.services` with opaque refs like `psy.appointment:42`. Offline admin confirms (`payment_ref=offline`) skip the wallet ledger.
