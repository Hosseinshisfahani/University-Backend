# Deploy (University-Backend)

2GB VPS. Host nginx on 80/443. Compose **pulls** images — never `docker compose build` or `next build` on the server.

| Role | URL |
|------|-----|
| Frontend image | `ghcr.io/hosseinshisfahani/university-frontend` |
| Backend image | `ghcr.io/hosseinshisfahani/university-backend` |
| University | https://icqt.ac.ir |
| Psy | https://ayehh.ir |
| Django admin | https://ayehh.ir/django-admin/ (also icqt) |
| Health | `http://127.0.0.1:8000/api/v1/health/` |

## Layout on the VPS (`DEPLOY_PATH=/var/www/university`)

- `docker-compose.prod.yml`
- `compose.env` (from `compose.env.example`, gitignored)
- `.env` (Django; copy `deploy/templates/backend.env.example`)
- `deploy/app.env` (from `deploy/app.env.example`, gitignored)
- `data/media/`

## First boot

1. DNS A/AAAA for `icqt.ac.ir`, `ayehh.ir`, and `www` of both → this VPS **before** certbot.
2. Copy compose + `deploy/` onto the box. Create `compose.env`, `deploy/app.env`, `.env`.
3. GitHub PAT with `read:packages`. On the VPS:

```bash
export GHCR_TOKEN=...
export DEPLOY_PATH=/var/www/university
# docker login happens inside provision.sh
./deploy/scripts/provision.sh
```
