# LibyAI — which layer owns what

LibyAI has two data layers that share one SQLite file. This note states
which one is authoritative for each job, so a future change does not
silently build a second, diverging implementation. It is a statement of
the current, tested reality — not a wish list.

## The two layers

- **Legacy layer (`db.py`, `admin_service.py`, `patient_service.py`,
  `router.py`, `job_queue.py`)** — raw SQLite, dict rows, the tables
  `doctors`, `services`, `clinic_info`, `audit_logs`, `daily_overrides`,
  `message_jobs`, and the conversation tables. This layer owns:
  - all admin mutations and their atomicity (`apply_admin_mutation_atomic`
    writes the doctors update, the daily override, the audit log, and the
    job completion in one transaction);
  - the message job queue and its leases;
  - patient answers, including the triage fast path, the clinical-advice
    refusal, and the offline fallback;
  - staff authorization (`db.is_staff_authorized`, full-number matching).

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
- Patient answers: `app/services/llm_service.py::generate_patient_response`
  delegates to `patient_service.handle_patient_query`. The Gemini prompt
  block that used to sit after that delegation was unreachable dead code
  and was removed in round 4. There is currently no live Gemini patient
  path; the live Gemini paths are admin-update parsing and data
  ingestion, both behind a configured key with a rule-based fallback.
- Webhooks: the signed Meta webhook (`/webhook/whatsapp`) is the
  production entry point; the legacy webhook (`/whatsapp/webhook`)
  requires a valid Meta signature in production and accepts unsigned
  local payloads only in development (see `SECURITY.md`).

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
- Two doctor/service update paths still exist because their callers
  expect different return types. Merging those needs a single return
  type and a migration of every caller, which is a larger round than
  the finder merge. Until then, change an update path only with the
  full suite still passing.
- `clinic_config` (SQLModel) mirrors `clinic_info` (legacy). The
  simulator settings endpoint writes both; `db_service` config reads
  come from `clinic_info`. Do not read config from `clinic_config`
  directly without checking the mirror is still written.
- The seed data describes a real facility. The repository must stay
  private until that seed is audited (see `SECURITY.md`).
