# STIF Campus AI Cloud Readiness

Status checked 2026-11-20. This document is preparation only: no Neon project, bucket, hosted service, domain, upload, deployment, or real-record migration has been created or used.

## Checkpoint 1 — PostgreSQL verification

- Verified with the project `.venv` Python 3.12 and Psycopg 3.3.9.
- A temporary local PostgreSQL 18 cluster was initialized, used for the integration tests, stopped, and removed. Its database contained only synthetic fixtures.
- The installed PostgreSQL Windows service and the project's SQLite database were not used as test targets.
- PostgreSQL integration tests cover the adapter, schema migration and advisory lock, API workflows, concurrent enquiry limits, and synthetic snapshot import. Neon, its pooler, and hosted TLS behavior remain unverified.

## Checkpoint 2 — Neon setup (manual action remains)

When the owner approves database creation:

1. Create a Neon account and project in the dashboard. Choose **AWS Asia Pacific (Singapore), `aws-ap-southeast-1`** if it is still offered at creation time. It is the closest currently listed Neon region to Tirupati among the regions Neon documents. Neon fixes the project region at creation, so confirm the choice before creating the project. See [Neon's region list and region-change rule](https://neon.com/docs/introduction/regions).
2. Create the PostgreSQL database/role for this application. Keep credentials private. Prefer an application role with only the privileges required by the schema and application. The current `api.manage init-db` and adapter initialization apply schema migrations, so separate runtime and migration roles are a future hardening decision.
3. In Neon, copy the generated TLS-enabled connection string. Keep its TLS setting; do not remove `sslmode`. Use the **pooled** URL for the request-serving FastAPI process after a hosted pooler verification. The backend opens short-lived request connections and uses explicit transactions; its transaction-scoped advisory locks do not rely on session state. Use a **direct** URL for maintenance tools unless the pooler has been verified for that operation. Do not paste either URL into source files, issues, screenshots, or frontend settings.
4. Set `STIF_DATABASE_URL` privately in the backend process environment. A non-empty value selects PostgreSQL; an unavailable or invalid PostgreSQL selection does not fall back to SQLite. Leave `STIF_DB_PATH` available as the local SQLite path. Run `python -m api.manage init-db` to create the PostgreSQL schema; this does not copy SQLite records.
5. Confirm Neon’s current quotas and billing in its dashboard before the founder demo. Its current Free plan has finite per-project compute, storage, and transfer limits and can scale to zero; a free quota is not an uptime commitment. Review [current Neon plan limits](https://neon.com/docs/introduction/plans).

The account owner must create the account/project and privately configure the connection string. This repository contains only a commented placeholder in `.env.example`.

`/health` remains the liveness surface. `/ready` checks that the selected application database can execute a simple query and returns only `ready`/`not_ready`; it does not include connection details. Setting `STIF_ENV=production` makes FastAPI startup refuse SQLite selection. Configure `STIF_ENV` and `STIF_DATABASE_URL` together in the backend environment.

## Checkpoint 2 — SQLite snapshot and migration procedure

The migration tool requires a separately named and validated snapshot. It never accepts the configured live SQLite path as its migration input. The migration target must be PostgreSQL, have the versioned application schema, and contain no users, programmes, or enquiries. It refuses to merge into a populated target. The data import itself is one transaction and is retriable only after confirming that the destination is empty.

Run these from the project root in PowerShell. First provide a PostgreSQL URL privately; this example reads it interactively instead of placing a credential in command history:

```powershell
$env:STIF_DATABASE_URL = Read-Host 'Paste the private PostgreSQL connection URL'
```

Create a new snapshot at a unique path. The source is read through SQLite's backup API; the source file is never replaced or modified by this command.

```powershell
$snapshot = 'data/migration_snapshots/stif_snapshot_YYYYMMDD_HHMMSS.db'
& .\.venv\Scripts\python.exe -m api.migrate_sqlite snapshot --output $snapshot
```

Initialize the destination schema explicitly, then run a read-only dry-run. The dry-run validates the snapshot, schema, destination emptiness, source counts, and foreign-key integrity; it does not import rows.

```powershell
& .\.venv\Scripts\python.exe -m api.manage init-db
& .\.venv\Scripts\python.exe -m api.migrate_sqlite run --snapshot $snapshot --dry-run --report 'data/migration_snapshots/dry-run-report.json'
```

Only after a separate approval to migrate the real records, take and verify a new snapshot, confirm the destination is the intended empty database, stop application writes, and run:

```powershell
& .\.venv\Scripts\python.exe -m api.migrate_sqlite run --snapshot $snapshot --apply --report 'data/migration_snapshots/import-report.json'
```

The report contains counts, status, and a snapshot digest; it does not contain account or enquiry fields. The importer carries over roles, users (including existing password hashes), programmes, and enquiries with IDs, references, UTC timestamps, and foreign-key relationships. It resets identity sequences and verifies destination counts and foreign keys. Sessions are deliberately skipped; everyone must authenticate again after cutover.

The test suite exercises this flow with synthetic records only. No real SQLite data has been snapshotted or imported. The source database must remain backed up and unchanged through validation. For rollback after cutover, stop writes first: simply switching `STIF_DATABASE_URL` off would discard any PostgreSQL writes made after cutover. Reconcile or export those changes before returning to SQLite.

Snapshots can contain names, emails, phone numbers, password hashes, and enquiry text. Keep them local, restrict filesystem access, and follow the college's retention/approval policy. `data/migration_snapshots/` is Git-ignored; do not remove the source SQLite database or its backup until the college has approved retention and verified the new system.

## Checkpoint 3 — Local and shared artifact storage

`api.artifact_storage` keeps `local` as the default and provides opt-in S3-compatible R2 storage. It transfers only the public SVCE knowledge directories (`raw*`, `processed*`, `index*`, `sources`) plus approved URL inventory files. Database files, reports, staging, and chat attachments are excluded. No student attachment is persistently stored by the current API; extracted user text stays in the request flow.

For R2 mode, configure `STIF_STORAGE_BACKEND=r2`, bucket, HTTPS S3 endpoint, access key ID and secret through the backend secret manager. Install the pinned `boto3` dependency. The backend requires PostgreSQL for shared generation publication locks; it downloads and checks the active manifest and file hashes during startup, then publishes new immutable generations with the active manifest switched last. It refuses stale generation publication. Old generations are deliberately retained; no automated deletion is implemented. The active generation must be explicitly seeded once from approved local knowledge using `python -m api.storage_cli seed-local --confirm-initial-seed`; that command uploads data and must not be run until the owner has approved the bucket and the data handling. No external storage was contacted and no artifact was uploaded in this phase.

The current local `data/index_fast/chunks.jsonl` is about 51 MB. R2 standard storage currently includes 10 GB-month and monthly request quotas with no egress fee, but usage above those quotas is billed; account onboarding requires an R2 subscription. Check current [R2 pricing](https://developers.cloudflare.com/r2/pricing/) and [R2 setup requirements](https://developers.cloudflare.com/r2/get-started/) before account creation. A future cleanup mechanism for old generations needs a separate, reviewed retention policy.

## Checkpoint 4 — Deployment preparation only

- `render.yaml` prepares a Singapore Render web service with the pinned backend dependencies, schema initialization, `/ready`, secure-cookie mode, production PostgreSQL requirement, R2 artifact mode, and dashboard-only secrets (`sync: false`). It is configuration only; no service was created. Review all values, particularly `STIF_CORS_ORIGINS`, before importing it.
- Cloudflare Pages can build from `frontend` using `npm ci` and `npm run build`, publishing `dist`; set `VITE_API_BASE_URL` to the backend HTTPS URL in the Pages build environment. Hash routing needs no custom SPA rewrite. `frontend/public/_headers` adds basic headers. Current Pages Free limits include 500 monthly builds and 30-day retention for non-current deployments; verify [current Pages limits](https://developers.cloudflare.com/pages/platform/limits/).
- Backend CORS now takes exact HTTPS origins from `STIF_CORS_ORIGINS`; wildcard origins are rejected. `STIF_ALLOWED_HOSTS` restricts Host headers to explicit API hostnames (no wildcard). The browser API wrapper includes HttpOnly cookies. Prefer app and API subdomains under the same owned site (for example, `app.example` and `api.example`) so `SameSite=Lax` works. Using unrelated `pages.dev` and `onrender.com` hostnames is cross-site; browser third-party-cookie restrictions may prevent login and would need an explicitly designed cookie/domain solution. Do not weaken cookie or CSRF controls to work around that.
- Render has a Singapore region, terminates TLS, and defaults service disks to ephemeral; R2 is therefore necessary for indexes. Its current paid starter web service is listed at $7/month (verify [pricing](https://render.com/pricing)); its free plan is unsuitable for an always-on demo. Render documents Singapore in its [regions](https://render.com/docs/regions) and HTTP service setup in [web-service docs](https://render.com/docs/web-services). Region latency to the Neon Singapore database is likely preferable to a US/EU region, but actual end-to-end latency has not been benchmarked.
- `preDeployCommand` runs idempotent schema migrations, not SQLite record transfer. Initially populate Neon and R2 only after explicit approval; startup/readiness will fail if required services or the active artifact generation are missing.

No frontend/API deployment, domain setup, DNS change, provider account, or paid resource was created.

## Checkpoint 5 — Security review (in progress)

- Production mode rejects SQLite. Readiness returns generic state only and checks DB plus selected R2 manifest availability. Explicit R2 configuration never falls back to local storage. Storage logs include only operation and exception type; never credentials, prompt content, retrieved chunks, or file names.
- CORS allows only explicit HTTPS origins (or loopback HTTP for local development), with credentials enabled for the existing HttpOnly session cookie. State-changing routes keep the custom CSRF header and server-side authorization. Do not use wildcard origins.
- Rate limiting remains in-process. Multiple backend instances therefore do not share login/register counters; this must be addressed before public multi-instance use (for example, an approved shared limiter) or keep a single instance and monitor abuse.
- OpenRouter receives user questions, retrieved context, and possibly attachment text. OpenRouter documents provider-specific handling; the currently configured free NVIDIA Nemotron 3.5 Lightning page says not to upload confidential or personal information and that NVIDIA logs free-endpoint sessions to improve its products. Therefore do not use this free endpoint with student PII, private submissions, or sensitive attachments; obtain college data-handling approval or select a provider/model with suitable contractual terms. See [OpenRouter privacy policy](https://openrouter.ai/privacy) and [the model's data notice](https://openrouter.ai/nvidia/nemotron-3.5-lightning%3Afree). This is a material launch blocker for personal data.
- No production security certification is claimed. College privacy/consent approval, provider review, cookie/CORS browser verification on the final domains, backup/restore rehearsal, abuse monitoring, and dependency maintenance remain open.

## Checkpoint 6 — Remaining local verification and approval boundary

Still to perform before marking the roadmap complete: full local backend suite after the storage/CORS changes, frontend production build, existing local E2E workflow on a throwaway DB, final docs/demo walkthrough, and inspect final diff. No cloud service should be touched until the owner separately approves account creation, paid R2/Render resources, domain/DNS, any upload, or migration of real records. A real data transfer additionally needs a verified fresh SQLite snapshot, approved retention, destination checks, maintenance window, and the separately guarded migration command above.
