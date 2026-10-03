# Finance (`apps.finance`)

Platform-wide wallet, append-only ledger, payments (Vandar IPG), and withdrawals.

- Currency stored on the wallet and ledger: **IRR (Rials)**, `decimal_places=0`.
- Wallet top-up requests are **toman**. `initiate_vandar_payment` is the only `* 10` conversion. It stores and charges rials.
- Balance display in toman stays on the frontend.
- Domain apps must call `finance.services` — never mutate `Wallet.balance` directly.
- No imports from `psy_institute` (or other domains); use opaque `reference` / `ticket_reference` strings.

## HTTP API (`/api/v1/finance/`)

| Endpoint | Notes |
|---|---|
| `GET /wallet/` | Own balance |
| `GET /wallet/ledger/` | Recent ledger |
| `POST/GET /payments/` | Create / list (manual or generic) |
| `POST /payments/{id}/confirm/` | Admin confirm → credit |
| `POST /vandar/initiate/` | Authenticated top-up. `amount` is toman. Returns `{redirect_url, provider_ref, payment}` |
| `GET\|POST /vandar/callback/` | Public Vandar return. Verifies, credits once, redirects to the frontend |
| `POST/GET /withdrawals/` | Cash-out hold on wallet |
| `POST /withdrawals/{id}/approve\|paid\|reject/` | Admin processing |

## Vandar IPG

Sandbox is the default (`VANDAR_SANDBOX_MODE=true`): no outbound HTTP.

| Env | Purpose |
|---|---|
| `VANDAR_SANDBOX_MODE` | `true` (default) / `false` for production |
| `VANDAR_API_KEY` | IPG key from the Vandar dashboard. Required when sandbox is off |
| `VANDAR_CALLBACK_URL` | Public return URL for this environment. Required when sandbox is off. No default host |
| `VANDAR_FRONTEND_SUCCESS_URL` / `VANDAR_FRONTEND_FAILURE_URL` | Browser redirects after callback. No default host |
| `VANDAR_SEND_URL` / `VANDAR_REDIRECT_BASE_URL` / `VANDAR_VERIFY_URL` / `VANDAR_TRANSACTION_URL` | Vandar IPG endpoints |

`Payment.provider` value `sep` remains valid for historical payments.
