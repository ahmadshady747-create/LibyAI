# LibyAI — which layer owns what

LibyAI has two data layers that share one SQLite file. This note states
which one is authoritative for each job, so a future change does not
silently build a second, diverging implementation. It is a statement of
the current, tested reality — not a wish list.

## Channels (Messenger-first pivot)

- **Channel layer (`app/channels/`)** — one adapter per channel behind
  the `ChannelAdapter` interface (`base.py`): `verify_webhook`,
  `verify_signature`, `parse_incoming`, `send_text`. Messenger
  (`messenger.py`) is PRIMARY, WhatsApp (`whatsapp.py`) is secondary
  and optional. Both adapters share the fail-closed HMAC-SHA256
  verification in `base.py` (`verify_hmac_sha256`), checked BEFORE the
  body is parsed. Deduplication is `(channel, external_message_id)`,
  not a bare WhatsApp wamid: the same external id on two channels is
  two different messages. The legacy `provider` column is kept and
  always holds the same value as `channel`.
- Messenger parsing strictly ignores `is_echo` messages, delivery
  receipts and read receipts, to prevent reply loops. Staff messages
  are tagged `@Bot` at the webhook and routed to the admin path with
  `group_id` `<channel>_staff`.
- Staff authorization is channel-aware (`db.is_sender_authorized`):
  phone numbers on WhatsApp/simulator (exact normalized match), exact
  Messenger PSIDs on Messenger — PSIDs are never phone-normalized.

## The two layers

- **Legacy layer (`db.py`, `admin_service.py`, `customer_service.py`,
  `router.py`, `job_queue.py`)** — raw SQLite, dict rows, the tables
  `business_info`, `catalog_items`, `resources`, `business_faqs`,
  `doctors`, `services`, `clinic_info`, `audit_logs`, `daily_overrides`,
  `message_jobs`, and the conversation tables. This layer owns:
  - all admin mutations and their atomicity (`apply_admin_mutation_atomic`
    writes the target update, the daily override (doctors only), the
    audit log, and the job completion in one transaction);
  - the message job queue and its leases (lease/retry semantics
    unchanged by the pivot; only the dedup key was generalized);
  - customer answers, including the guardrail fast path, the clinical-
    advice refusal (medical sectors only), the commercial handoff, and
    the offline fallback;
  - staff authorization (`db.is_sender_authorized`, channel-aware;
    `db.is_staff_authorized` remains the phone-number path).
- **Business data model:** `business_info` (single row id=1) is the
  source of truth for business identity, sector and policies; the
  legacy `clinic_info` key-value table stays as the store for webhook
  tokens and staff lists. The catalog view unions `catalog_items` with
  the legacy `services` table (no data duplication, no divergence):
  admin service-price updates stay on `services`, catalog updates on
  `catalog_items`. The medical schedule path (doctors, emergency and
  follow-up tables) is preserved for medical sectors only.
- **Guardrails (`guardrails.py`)** — the policy engine. Safety order:
  (1) medical Level 1 emergency (medical sectors only, bypasses the
  debouncer and the LLM exactly as before), (2) commercial handoff
  (all sectors), (3) medical Level 2 clinical-advice restriction
  (medical sectors only), (4) routine. `triage.py`,
  `patient_service.py` and `patient_processor.py` are thin
  backward-compatible shims over `guardrails.py`, `customer_service.py`
  and `customer_processor.py`; new code must import the new names.

- **SQLModel layer (`app/database/models.py`, `app/services/db_service.py`)**
  — SQLModel objects over the same `doctors` and `services` tables, plus
  a mirrored `clinic_config` table that the simulator settings endpoint
  keeps in sync. This layer is used for:
  - lookups that feed the AI parsers (`find_doctor_fuzzy` in the admin
    fallback parser, doctor/service lookups in the patient fallback);
  - AI data ingestion (`ingest_clinic_data_with_ai` upserts);
  - clinic configuration reads/writes, which already delegate to the
    legacy `clinic_info` table (`get_clinic_configs`,
    `update_clinic_config` call into `db.py`).

## Authoritative delegations (do not re-implement)

- Staff updates: `app/services/admin_processor.py` does nothing itself
  except delegate to `admin_service.handle_admin_group_message`. The
  SQLModel mutation block that used to sit after that delegation was
  unreachable dead code and was removed in round 4.
- Customer answers: `app/services/llm_service.py::generate_customer_response`
  delegates to `customer_service.handle_customer_query`
  (`generate_patient_response` is a thin alias). The Gemini prompt
  block that used to sit after that delegation was unreachable dead code
  and was removed in round 4. There is currently no live Gemini customer
  path; the live Gemini paths are admin-update parsing and data
  ingestion, both behind a configured key with a rule-based fallback.
- Webhooks: the signed Meta webhooks are the production entry points —
  `/webhook/messenger` (primary, `app/channels/messenger.py`) and
  `/webhook/whatsapp` (secondary, `app/api/webhook.py` via the
  `WhatsAppAdapter`). The legacy webhook (`/whatsapp/webhook`,
  `router.py`) is legacy-only: it is retained for the local simulator /
  direct-payload gateway path and for backward compatibility with
  existing deployments. All routes enforce IDENTICAL fail-closed
  `X-Hub-Signature-256` verification (see `SECURITY.md`): missing
  signature → 401, unconfigured app secret → 403, invalid signature →
  403, constant-time comparison, and the signature is checked BEFORE
  the body is parsed or any dispatch/mutation happens. The only
  intentional difference is that the legacy route also accepts a
  simplified direct `{sender, message}` JSON payload, and accepts
  unsigned payloads only when `ENVIRONMENT` is not production (local
  development). A webhook for a channel not in `ENABLED_CHANNELS`
  returns 404. New integrations must use `/webhook/messenger` or
  `/webhook/whatsapp`.

## Fixes from round 4 that belong here

- SQLModel datetimes must be timezone-aware. The models and
  `db_service` used naive `datetime.utcnow()`, which SQLModel rejects
  at insert/update time, so SQLModel upserts (used by AI data ingestion)
  failed outright on a SQLModel-created table. All of them now use
  `datetime.now(timezone.utc)`. Do not reintroduce naive datetimes in
  the SQLModel layer; the legacy layer's raw SQL timestamps are a
  separate, text-based convention and are not affected.

## Known duplication that remains (deliberately, for now)

- Two fuzzy finders used to exist with separate scoring. Round 5 merged
  them into one: `db_service.find_doctor_fuzzy` and
  `db_service.find_service_fuzzy` are now thin adapters over the legacy
  finders — they keep their SQLModel return types (and the doctor
  adapter keeps the active-only filter), but the scoring lives only in
  `db.py`. `test_layer_authority.py` guards that both layers return the
  same row id for the same query, for doctors and for services.
- Update paths are also adapters now (round 6): 
  `db_service.update_doctor_today_status`, `update_doctor_fee`, and
  `update_service_price` write through the legacy atomic functions and
  only convert the result to a SQLModel object. That also fixed the
  status/today_status sync bug in the old SQLModel status update.
  What remains unmerged is upsert/delete/wipe (ingest uses the SQLModel
  upserts; the simulator delete/reset endpoints use raw legacy SQL),
  plus the `clinic_config` mirror noted above.
- `clinic_config` (SQLModel) mirrors `clinic_info` (legacy). The
  simulator settings endpoint writes both; `db_service` config reads
  come from `clinic_info`. Do not read config from `clinic_config`
  directly without checking the mirror is still written.
- The seed data is fictional demo data only (see `SECURITY.md`); the
  repository is public. Never commit real business data to it.
