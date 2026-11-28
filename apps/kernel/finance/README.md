# Finance (`apps.kernel.finance`)

Platform-wide wallet, append-only ledger, payments (Vandar IPG), and withdrawals.

- Currency stored on the wallet and ledger: **IRR (Rials)**, `decimal_places=0`.
- Wallet top-up requests are **toman**. `start_topup` is the only `* 10` conversion. It stores and charges rials.
- Balance display in toman stays on the frontend.
- Domain apps must call `finance.services` — never mutate `Wallet.balance` directly.
- No imports from `psy_institute` (or other domains); use opaque `reference` / `ticket_reference` strings.
- `confirm_payment` emits `payment_succeeded` (kwargs: `payment`) after a wallet top-up is credited and after a Vandar checkout handler returns. Listeners must not raise.
- Shop orders are settled by `apps.modules.shop`, not by finance and not by `psy_institute`. `AppConfig.ready` registers one Vandar checkout handler for both `shop.order:` and the legacy `psy.order:` prefix. `apps/modules/shop/signals.py` emits `order_paid`, `order_shipped`, `order_cancelled`, and `order_refunded`. Copied rows were also rewritten from `psy.order:{id}` to `shop.order:{id}` (`shop/migrations/0002_copy_psy_shop.py`). Both prefixes stay reserved so a public top-up cannot claim them.

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
| `PLATFORM_FRONTEND_ORIGIN` | Absolute frontend origin (scheme + host, no path). Standard institutes with no canonical domain return to `{origin}/i/<slug>/...`. Leave it empty and that return becomes a hostless `/i/<slug>/...` redirect, which the callback refuses to emit |
| `VANDAR_SEND_URL` / `VANDAR_REDIRECT_BASE_URL` / `VANDAR_VERIFY_URL` / `VANDAR_TRANSACTION_URL` | Vandar IPG endpoints |

`Payment.provider` value `sep` remains valid for historical payments.
