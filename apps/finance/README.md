# Finance (`apps.finance`)

Platform-wide wallet, append-only ledger, payments (SEP-ready), and withdrawals.

- Currency: **IRR (Rials)**, `decimal_places=0`. Toman display is frontend-only.
- Domain apps must call `finance.services` — never mutate `Wallet.balance` directly.
- No imports from `psy_institute` (or other domains); use opaque `reference` / `ticket_reference` strings.

## HTTP API (`/api/v1/finance/`)

| Endpoint | Notes |
|---|---|
| `GET /wallet/` | Own balance |
| `GET /wallet/ledger/` | Recent ledger |
| `POST/GET /payments/` | Create / list (manual or generic) |
| `POST /payments/{id}/confirm/` | Admin confirm → credit |
| `POST /sep/initiate/` | Authenticated SEP top-up → `{redirect_url, provider_ref, payment}` |
| `GET\|POST /sep/callback/` | Public bank return → verifies, credits wallet, redirects to frontend |
| `POST/GET /withdrawals/` | Cash-out hold on wallet |
| `POST /withdrawals/{id}/approve\|paid\|reject/` | Admin processing |

## SEP (Saman)

Defaults to **sandbox** (`SEP_SANDBOX_MODE=true`): no outbound bank HTTP; mock token + verify.

| Env | Purpose |
|---|---|
| `SEP_SANDBOX_MODE` | `true` (default) / `false` for production |
| `SEP_TERMINAL_ID` | Required when sandbox is off |
| `SEP_CALLBACK_URL` | Bank return URL (this API's `/sep/callback/`) |
| `SEP_FRONTEND_SUCCESS_URL` / `SEP_FRONTEND_FAILURE_URL` | Browser redirects after callback |
| `SEP_TOKEN_URL` / `SEP_REDIRECT_BASE_URL` / `SEP_VERIFY_URL` | Production SEP endpoints |

Raw SEP request/response payloads are stored on `Payment.metadata` for audit.
