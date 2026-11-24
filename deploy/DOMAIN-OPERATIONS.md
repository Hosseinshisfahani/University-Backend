# Domain inventory and cutover

Each hostname is its own `InstituteDomain` row. `www` is not added automatically. The university host stays in frontend configuration and does not use the resolver.

## Inventory

Record, before activation:

- apex and subdomain names, A/AAAA or CNAME, and IPv6
- which name is canonical
- certificate names already issued
- `DJANGO_ALLOWED_HOSTS` and `TENANCY_NEUTRAL_HOSTS` (health and the internal API host)
- `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` for real cross-origin clients only
- `INTERNAL_API_ORIGIN` on the Next server

Do not set `ALLOWED_HOSTS=["*"]` and do not add a wildcard CORS or CSRF trust when a domain is registered.

## Verification

1. `onboard_institute` creates the institute inactive.
2. Start a challenge in Django admin or `begin_verification`. Publish the token at `_university-verify.<hostname>`.
3. `python manage.py verify_institute_domain --hostname <host> --token <txt>` or `--lookup` when `dig` is available.
4. Issue the exact-host certificate with the existing Certbot HTTP-01 webroot. Record `tls_ready_at` only after the certificate answers that hostname.
5. Add the hostname to `DJANGO_ALLOWED_HOSTS` and reload Nginx so the default server still rejects unknown hosts. Overwrite `Host` and forwarded headers from the client.
6. Activate the canonical domain. The API checks the database on every request. Page routing follows within about 60 seconds.
7. Revocation marks the row inactive first, then removes the edge name. A revoked host fails closed at the API immediately.

## Write pause

Set `TENANCY_WRITE_PAUSE=shop` (or another module id) before a module cutover. Mutations on that module return 503. Reads continue. The Vandar callback stays available. Clear the setting after reconciliation and one writer is active.

## Private files

`PRIVATE_MEDIA_ROOT` (default `private_media/`) is outside `MEDIA_ROOT`. Product files and certificates use that storage. `python manage.py relocate_private_media` moves an existing public copy, checks sha256, and deletes the public file only after the hash matches. Nginx and Django both 404 the old `/media/` prefixes.

## Acceptance before contracting legacy storage

Run the Django suite on PostgreSQL (`config.settings.dev` with `DATABASE_URL`). Confirm the canonical-domain check constraint, cross-institute content slugs, and the module registry check. A production snapshot rehearsal still needs the live backup, which this repository does not contain. Do not drop legacy tables or the `psy_*` group dual-write until that rehearsal and the compatibility release are done. The previously deployed frontend still reads `groups`.

## Rollback

Before new writes, switch the pause off and deploy the previous image. After new payments exist, roll forward with a compatible release. Do not restore a ledger snapshot over provider events that arrived after the snapshot.
