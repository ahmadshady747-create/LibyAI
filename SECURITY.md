# LibyAI — Security notes for production

## Secrets have no defaults
- `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, and `ADMIN_SECRET_KEY`
  have no development default values in the code. If they are missing,
  webhook verification rejects requests, simulator admin rejects, and a
  production startup aborts without a configured app secret.
- Never commit a real `.env` file. The `.env.example` file contains
  placeholders only.

## Environment default is production
- Starting the app any way other than `run.py` defaults to production
  (fail-closed). `run.py` is the local development entrypoint and sets
  development explicitly, and binds to localhost by default. A public
  deployment must set `LIBYAI_HOST` explicitly and sit behind a reverse
  proxy; do not expose the app directly.

## Webhook authentication
- The signed Meta webhook (`/webhook/whatsapp`) requires a valid
  `X-Hub-Signature-256` HMAC signature.
- The legacy webhook (`/whatsapp/webhook`) also requires a valid
  signature in production. In development it accepts unsigned local
  payloads for simulator and gateway testing only.
- Webhook verification requires a configured verify token on both sides;
  a missing token on both sides no longer passes.

## Simulator
- Simulator endpoints are disabled in production unless
  `ENABLE_PROD_SIMULATOR=true` AND a valid `X-Admin-Key` is provided.
- The simulator state endpoint requires admin access, because it returns
  clinic configuration. Patient and admin simulator messages are also
  disabled in production unless the simulator is explicitly enabled.
- Staff authorization is exact full-number matching only. There is no
  wildcard value that authorizes every sender.

## CORS
- Only the origins listed in `ALLOWED_ORIGINS` are allowed, credentials
  are never allowed, and only the methods and headers the app uses are
  permitted. The default list is local origins only.

## Seed data and repository visibility
- This repository is PUBLIC. Its seed data is fictional demo data only
  (Al-Noor Demo Clinic, invented doctors/services/phones in
  `seed_demo.py`); the real facility seed was replaced before the
  repository was made public. Never commit real clinic data — real
  facility names, real staff/doctor names, or real phone numbers — to
  this repository: real clinic data stays out of git entirely and is
  loaded only into a private deployment database.
- Audit logs store raw message text. Before a production deployment,
  decide a retention period for audit logs and conversation history and
  enforce it; the current code has no automatic deletion for audit logs.
