# Backend — Django REST Modular Monolith

Single Django project, multiple isolated domain apps, one shared PostgreSQL database. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full specification.

## Structure

```
backend/
  manage.py
  requirements.txt
  config/                      # Django project
    settings/
      base.py                  # shared settings (env-driven)
      dev.py                   # DEBUG, localhost CORS, insecure-cookie fallbacks
      prod.py                  # hardened: HSTS, secure cookies, proxy SSL header
    urls.py                    # everything versioned under /api/v1/
    wsgi.py / asgi.py
  apps/
    kernel/                    # platform kernel: every institute and module depends on it
      core/                    # TimeStampedModel, API middleware, private media storage, health check
      accounts/                # custom User model + cookie-based JWT auth
      tenancy/                 # institutes, memberships, domains, module registry
      finance/                 # platform wallet, ledger, payments (Vandar), withdrawals (IRR)
      notifications/           # platform SMS / notifications
    modules/                   # shared tenant-scoped capabilities
      content/ reviews/ forms/ shop/ lms/ booking/
    institutes/
      psy_institute/           # psychology profiles, clinical notes, tests, tickets; thin module adapters
```

Three layers: the platform kernel (`kernel/core`, `kernel/accounts`, `kernel/tenancy`, `kernel/finance`, `kernel/notifications`), shared `modules/*`, and `institutes/*`. Modules and the kernel never import an institute. `institutes.psy_institute` is the only institute today.

## Setup

Requires Python 3.12 and PostgreSQL.

```bash
cd backend
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # then edit values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Settings default to `config.settings.dev`; production runs with `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login/` | Validate credentials, set HttpOnly JWT cookies |
| `POST /api/v1/auth/refresh/` | Rotate tokens using the refresh cookie |
| `POST /api/v1/auth/logout/` | Blacklist refresh token, clear cookies |
| `GET /api/v1/auth/me/` | Current user profile |
| `GET /api/v1/auth/csrf/` | Set the CSRF cookie |
| `GET/POST /api/v1/finance/...` | Wallet, ledger, payments (Vandar), withdrawals |
| `GET/POST /api/v1/psy/...` | Psychology institute domain API |
| `GET /api/v1/docs/` | Swagger UI (OpenAPI schema at `/api/v1/schema/`) |

## Auth security model

- Access and refresh JWTs are issued **only** as `HttpOnly`, `Secure`, `SameSite=Lax` cookies — never in JSON bodies, never readable by JavaScript.
- The refresh cookie is path-scoped to `/api/v1/auth/` so it never travels with regular API requests.
- Refresh tokens rotate on every refresh and the old one is blacklisted; logout blacklists and clears everything.
- Unsafe methods on cookie-authenticated requests are CSRF-checked (`apps/kernel/accounts/authentication.py`); the frontend echoes the CSRF cookie in the `X-CSRFToken` header.

## Rules for new apps

1. One domain concern per app; apps own their models, serializers, views, urls.
2. Reads across apps: direct imports/ORM. Writes across apps: **Django Signals only**.
3. Register new apps in `LOCAL_APPS` (`config/settings/base.py`) and mount their urls in `config/urls.py` under `/api/v1/`.
4. `kernel/*` never imports from `modules/*` or `institutes/*`.
