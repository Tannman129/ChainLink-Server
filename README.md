# ChainLink Server 0.1.0

An optional, self-hosted disc golf course catalog for the future ChainLink Android scorekeeper. Android remains offline-first: this service must never be required to play or score a round. This repository contains only the backend.

Course browsing is public. Course creation and layout creation require an administrator session and CSRF token. The WebUI supports sign in and sign out; player accounts currently browse the same public catalog. Compose binds the API to loopback. There is no public registration, synchronization, round storage, or CORS policy enabled. Remote access requires HTTPS and secure cookies.

## Start with Docker Compose

Requirements: Docker Engine with the Compose plugin.

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD to a strong random value.
docker compose up --build -d
curl http://127.0.0.1:8000/health
docker compose logs api migrations
```

PostgreSQL becomes healthy, the one-shot migration service runs `alembic upgrade head`, then the API starts. PostgreSQL has no published host port. Open [Swagger UI](http://127.0.0.1:8000/docs), [ReDoc](http://127.0.0.1:8000/redoc), or [OpenAPI JSON](http://127.0.0.1:8000/openapi.json).

`docker compose stop` stops the stack; `docker compose down` removes this stack's containers and network while retaining the database volume. Do not use `down -v` if you want to retain catalog data. No Docker prune/cleanup commands are required.

## WebUI

Open [ChainLink](http://127.0.0.1:8000/) after starting the existing FastAPI service. The dashboard, courses, layouts, and Coming Soon pages share the official **Midnight Red** identity: background `#101014`, accent `#E53935`, surfaces `#1C1C22`, white text, muted `#B0B0B8`, and border token `#50505A`. Accessible lighter text and darker button variants preserve contrast. Navigation icons are local SVGs; motion respects reduced-motion preferences. The official artwork in `assets/Midnight Red Disc Golf Basket.png` is served as two optimized, uncropped WebP derivatives under `app/static/images/`. It appears beneath the course overview, keeping catalog information and navigation first. Image assets are included in the Python package and existing Docker image. The dashboard reports **API reachability**, not database health. Catalog requests independently show loading, empty, error, and retry states.

The information-focused dashboard previews up to five courses, offers a course selector from the first catalog page, and shows the selected course’s layout count, hole counts, and default par. Default par is calculated only when every hole has a stored default configuration. Course counts show the exact loaded count when the catalog fits on one page, or `12+` when more courses exist. Layout counts are explicitly scoped to the selected course. API reachability and catalog errors remain independent. Round History and Statistics have dedicated navigation entries. Players and Android synchronization remain planned.

Courses are browsed in pages of 12. A lookahead row determines whether another page exists; the interface does not claim a global course count. Open a course to see its description, layouts, holes, recorded playable tee/basket configurations, and per-hole defaults. The Layouts navigation first asks you to choose a course. Players and Rounds remain Coming Soon. There are no editing controls or write requests in this milestone.

The WebUI uses local HTML, CSS, JavaScript, and SVG assets under `app/static/`, with no framework, Node installation, asset compilation, or CDN. FastAPI serves `/` and `/static/`; fragment navigation such as `/#courses` supports direct links and browser history without intercepting API routes. JavaScript is required for catalog browsing; use a current desktop or mobile browser. User-provided course, layout, tee, and basket content is rendered as text, and the WebUI document applies a same-origin Content Security Policy.

Setuptools includes assets as package data, and the existing Dockerfile copies `app/` into the same non-root production image. No additional service or container is needed. Swagger UI at `/docs` remains unchanged (its existing documentation assets may use external resources; the ChainLink WebUI itself does not).

The Android artwork changes prepared in this workspace are documented in [the Android update bundle](artifacts/android-artwork/README.md). They require applying the guarded bundle from a desktop terminal because this session cannot write to the separate Android repository.

## Configuration

Copy `.env.example` to `.env`; `.env` is ignored by Git and Docker builds.

| Variable | Purpose |
| --- | --- |
| `POSTGRES_DB` | Initial database name for Compose |
| `POSTGRES_USER` | Initial database owner for Compose |
| `POSTGRES_PASSWORD` | Required secret; no default |
| `API_PORT` | Host loopback port, default `8000` |
| `DATABASE_URL` | Required for host Python/Alembic; Compose constructs its own internal URL |
| `TEST_DATABASE_URL` | Optional PostgreSQL connection used only by tests |
| `TEST_POSTGRES_PASSWORD` | Required only for `compose.test.yaml` |

Compose interpolates credentials into a URL. Use URL-safe random passwords (for example `openssl rand -hex 32`) and simple database/user names. When constructing your own `DATABASE_URL`, percent-encode special characters in credentials. Compose's PostgreSQL initialization variables apply only to an empty volume; changing `.env` does not rotate an existing database password.

## Local Python development

Use Python 3.12 or newer (the container uses Python 3.13) and a local PostgreSQL database dedicated to ChainLink. Provision it using your normal PostgreSQL administration tools. Compose intentionally does not expose its database, so host development needs a separately accessible instance or an explicit local-only Compose override.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
# Set DATABASE_URL in .env, e.g.:
# postgresql+psycopg://chainlink:URL_ENCODED_PASSWORD@127.0.0.1:5432/chainlink
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

There is no implicit schema creation at application startup. `/health` reports process liveness and version without connecting to PostgreSQL; it is not a database readiness probe.

## Catalog and invariants

All entity IDs use UUIDs, generated by the application and stored as native UUIDs on PostgreSQL.

- `courses` → `layouts` → layout-specific `holes` → `tees` and `baskets`.
- `configurations` store a hole, tee, basket, positive integer par, and optional positive integer distance in feet.
- Only persisted configurations are playable. A hole with two tees and two baskets does not automatically have four playable combinations.
- Composite foreign keys enforce that each configuration's tee and basket belong to its hole. A tee/basket pair may appear only once per hole.
- `hole_defaults` has one row per hole at most. Its composite foreign key requires its selected configuration to belong to that hole. API creation requires exactly one default per hole. Direct database writes can omit defaults; the database enforces at most one, while the API enforces existence.
- Layout names are unique within a course; hole numbers are positive and unique within a layout. Tee and basket names are unique within their hole. Course names need not be globally unique.
- Parent deletion cascades to descendants. No delete/update API is included in 0.1.0.

Complete layouts are created atomically. Request-local tee/basket names resolve to generated UUIDs; graph responses expose those IDs and the default configuration ID. Layouts must contain at least one hole, each with at least one tee, basket, and playable configuration. Defaults are per-hole, scoped through the layout; there is no implicit default layout.

## API examples

The POST examples require an authenticated administrator cookie jar (`$COOKIE_JAR`)
and the current CSRF token (`$CSRF_TOKEN`), obtained through the authentication
flow documented below. Treat both as secrets. Anonymous POST requests return 401.
For local HTTP examples, explicitly configure `SESSION_COOKIE_SECURE=false`.

Create a course:

```bash
curl -X POST http://127.0.0.1:8000/v1/courses \
  -b "$COOKIE_JAR" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"River Park","description":"Local disc golf course"}'
```

Copy the returned `id` into `COURSE_ID`, then create a complete playable layout:

```bash
COURSE_ID='replace-with-returned-uuid'
curl -X POST "http://127.0.0.1:8000/v1/courses/$COURSE_ID/layouts" \
  -b "$COOKIE_JAR" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"Main",
    "holes":[{
      "number":1,
      "tees":["Short","Long"],
      "baskets":["A","B"],
      "configurations":[
        {"tee":"Short","basket":"A","par":3,"distance_ft":250,"is_default":true},
        {"tee":"Long","basket":"B","par":4,"distance_ft":420}
      ]
    }]
  }'
curl 'http://127.0.0.1:8000/v1/courses?limit=100&offset=0'
curl "http://127.0.0.1:8000/v1/courses/$COURSE_ID"
curl "http://127.0.0.1:8000/v1/courses/$COURSE_ID/graph"
```

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Liveness and version |
| `GET /v1/courses` | Course summaries; `limit` 1–500, default 100; `offset` ≥0 |
| `POST /v1/courses` | Create course, HTTP 201 |
| `GET /v1/courses/{course_id}` | Course summary |
| `GET /v1/courses/{course_id}/graph` | Full catalog graph for a course |
| `POST /v1/courses/{course_id}/layouts` | Atomically create complete playable layout, HTTP 201 |

Missing courses return 404; duplicate layout names return 409; malformed UUIDs, unknown input fields, invalid numbers, missing tee/basket references, and invalid defaults return 422 with validation details. Par and distance must be positive integers, not strings/fractions/booleans. Distances may be omitted or null.

## Migrations

```bash
alembic upgrade head
alembic current
alembic revision --autogenerate -m 'Describe schema change'
alembic check
# Only against a disposable database: removes the initial catalog tables/data.
# alembic downgrade base
```

Review generated migrations before use. The initial migration is self-contained and does not import changing application models. In Compose, `docker compose run --rm migrations` applies upgrades against this stack. Back up the database before upgrades; downgrades may destroy data.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

By default each database test migrates a fresh temporary SQLite file with foreign keys enabled. These fast tests cover API validation, course and graph retrieval, explicit playable pairs, defaults, relationship constraints, database cascades, fresh-connection persistence, atomic conflict handling, and migration upgrade/downgrade/schema drift. SQLite is a test fallback, not the deployment database, and cannot prove PostgreSQL-specific behavior.

Run the same suite against PostgreSQL using a dedicated test database:

```bash
TEST_DATABASE_URL='postgresql+psycopg://test_owner:password@127.0.0.1:5432/chainlink_test' pytest -q
```

Tests never use application `DATABASE_URL`. Each PostgreSQL test creates a randomly named `chainlink_test_<uuid>` schema, migrates it, and drops only that schema on completion. The test role needs schema creation privileges. Use a dedicated test database; interrupted tests may leave their uniquely named schemas behind.

Alternatively use the isolated PostgreSQL Compose stack (no published ports or persistent volumes):

```bash
export TEST_POSTGRES_PASSWORD="$(openssl rand -hex 32)"
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

### Browser integration tests

The regular suite includes WebUI route, local asset, packaging-resource, and API compatibility checks. Real Chromium tests are opt-in so the existing Python-only workflow and production image do not need browser dependencies:

```bash
pip install -e '.[test,browser]'
# If a system Chromium is unavailable, install Playwright's browser:
python -m playwright install chromium
RUN_BROWSER_TESTS=1 pytest -q
# Optional: CHAINLINK_BROWSER_EXECUTABLE=/path/to/chromium
```

Browser tests run a temporary local HTTP server against the same isolated database fixtures. They cover actual JavaScript navigation, pagination, course graphs, scoped dashboard counts, course selection, placeholders, independent catalog/API failure and retry states, safe text rendering, GET-only behavior, local asset requests, keyboard navigation, reduced motion, theme tokens, and desktop/tablet/mobile overflow. They do not connect to Unraid. Dashboard screenshots at widths 390, 834, and 1440 are written to the temporary directory as `chainlink-midnight-red-<width>.png`. They use isolated test catalog fixtures, not deployment data.

## Persistent storage and deployment

Compose stores PostgreSQL data in the `postgres_data` named volume (normally `chainlink_postgres_data`). It survives API rebuilds, container replacement, and normal `down`/`up` cycles. It is not a backup. Use PostgreSQL-aware backups such as `pg_dump`, store backups separately, and verify restores. Do not change PostgreSQL major versions against an existing data directory without an upgrade plan.

For future Unraid deployment, map PostgreSQL's data directory to a persistent appdata location or preserve the named volume, keep PostgreSQL private, run migrations before API startup, and configure HTTPS and restrict access appropriately. Loopback binding requires an intentional port-mapping change for LAN clients. Configure backups and secrets before deployment. No Unraid template is shipped yet.

The existing `.github/workflows/docker.yml` runs the Python test suite for pull requests and pushes to `main`. After tests pass, pushes to `main` and manual workflow runs build the production image and publish `ghcr.io/tannman129/chainlink-server:latest` and `:0.1.0`. Pull requests do not publish images. Consumers can replace `build` and the local image tag with the GHCR image for both API and migrations. The workflow currently uses the default SQLite tests; PostgreSQL and browser tests can be run separately as documented above. Build dependencies have bounded compatible ranges; a release should establish reviewed dependency locking and image digest pinning for reproducibility.

## Layout

`app/main.py` defines the application; `app/web.py` serves the WebUI shell and `app/static/` holds local assets; `app/api/` holds routes; `app/models.py` and `app/schemas.py` define storage and API contracts; `app/database.py` and `app/config.py` manage sessions/settings. `migrations/` contains Alembic revisions, and `tests/` contains the isolated test suite.

Implementation references: [SQLAlchemy composite constraints](https://docs.sqlalchemy.org/en/20/core/constraints.html) and [Compose startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/).

Licensed under MIT; see [LICENSE](LICENSE).


## Phase 1 accounts and authentication

No account is required for Android or public course browsing. Only administrators
can use the two existing course-write endpoints. Account provisioning is a local
operator action, not a public web endpoint. All existing catalog UUIDs and rows
are preserved by additive migration `0002`.

### Initial administrator setup

Before a future rollout, back up PostgreSQL and configure strong database credentials.
Run migrations through the existing migration service, then provision an administrator
from an interactive trusted terminal in the application environment:

```sh
# Host Python environment, with DATABASE_URL configured:
alembic upgrade head
python -m app.accounts your-admin-name --role administrator
# Or, after the normal Compose migration/startup process:
docker compose exec api python -m app.accounts your-admin-name --role administrator
```

The command prompts twice with terminal echo disabled. Never pass passwords on the
command line, put them in Compose files, or pipe them into shell history. There are
no default credentials or web bootstrap routes. Usernames are case-insensitive,
3–40 ASCII characters; passwords must be 12–256 characters. Provision additional
players with `python -m app.accounts player-name` (the default role is `player`).
Only trusted operators with database/application access can provision accounts.
Keep at least one administrator credential in a password manager. Self-service
password recovery, password changes and account-management screens are outside this
foundation; an operator can provision a replacement administrator through this command.

### Sessions, CSRF and API clients

- `GET /v1/auth/session` returns current user or null and a CSRF token, creating a
  30-minute anonymous session if needed. Responses must not be cached.
- `POST /v1/auth/login` accepts JSON `username` and `password` plus `X-CSRF-Token`.
  A successful login invalidates the old session and issues a new opaque cookie.
- `POST /v1/auth/logout` requires `X-CSRF-Token`, revokes the session and clears its cookie.
- Both course POST endpoints require an administrator cookie and `X-CSRF-Token`.
  API clients must retain cookies and use the new CSRF token returned after login.
- Cookies are HttpOnly, SameSite=Strict, host-only and Secure by default. Tokens are
  never stored in localStorage; only their SHA-256 hashes are stored server-side.
- Authenticated sessions expire absolutely after `SESSION_HOURS` (default 12,
  range 1–168), without sliding renewal. Login/logout rotate or revoke credentials.
- Argon2id hashes encode their parameters and are upgraded on successful login
  when the library's recommended parameters change.
- Login permits ten attempts per client address per fixed 15-minute window, including
  successful attempts. Database-backed atomic counters work across workers and restarts.
  A window boundary can permit two adjacent bursts. Failures do not reveal whether
  the username exists. Expired sessions and throttle buckets are cleaned during use.

### HTTPS and proxy configuration

Keep `SESSION_COOKIE_SECURE=true` for HTTPS, including remote LAN access. Set it to
`false` only for local HTTP development; secure cookies cannot authenticate over
ordinary HTTP. Compose forwards this setting and `SESSION_HOURS` to the application.
Do not disable browser certificate validation. HTTPS termination can use an existing
reverse proxy; no additional service is required by the application itself.

The current container disables forwarded-header trust. The login limiter uses the
actual connection address, never untrusted X-Forwarded-For. Behind a reverse proxy,
clients therefore share the proxy's login allowance. Do not enable arbitrary proxy
header trust to work around this; configure a narrowly trusted proxy boundary and
revisit limiter address handling deliberately before larger deployments. Preserve
the loopback API binding and private PostgreSQL networking. Configure edge request
size limits and access controls before exposing the service. Do not log request
bodies, Cookie, Set-Cookie or X-CSRF-Token headers. Database backups contain password
hashes and account data and must be protected.

Phase 1 does not add course-editing forms, account registration, Android networking,
rounds, statistics, friends, or external infrastructure.

### Phase 2A: private completed round history

Migration `0003` adds `completed_rounds`, `round_holes`, `round_participants`, and
`round_scores`. Existing catalog and authentication tables are unchanged. Round
ownership references an account with deletion restricted while history exists;
there is no account-deletion API in this phase.

Authenticated players and administrators can use:

- `POST /v1/rounds`: store an immutable completed scorecard (CSRF token required).
- `GET /v1/rounds?limit=100&offset=0`: list only the signed-in account's rounds,
  newest completion first; maximum page size is 100.
- `GET /v1/rounds/{uuid}`: read an owned round; missing and other-account rounds
  both return 404. Administrators have no access override.

The uploader supplies a stable round UUID, a timezone-aware completion timestamp,
course/layout names, played-hole snapshots, and round-local participant UUIDs and
names. Participants do not require accounts. Each participant must have exactly
one positive integer stroke score for every played hole. The scorecard supports
up to 100 holes and 100 participants. Each played hole stores its number, par,
tee name, basket name, and optional distance in feet; all participants in this
foundation use the same played-hole configuration. Totals and scores relative to
par are calculated from the persisted scores and snapshot pars.

Example body (replace the UUIDs when creating a different round):

```json
{
  "id": "3bf4f421-47da-465f-9eab-840d189654ab",
  "completed_at": "2026-10-18T12:30:00Z",
  "course_name": "River Park",
  "layout_name": "Main",
  "holes": [
    {"number": 1, "par": 3, "tee_name": "Short", "basket_name": "A", "distance_ft": 250}
  ],
  "participants": [
    {
      "id": "77f4449c-029f-430c-b5bb-5e590e138df4",
      "name": "Guest player",
      "scores": [{"hole_number": 1, "strokes": 3}]
    }
  ]
}
```

Snapshots are supplied by the scorekeeper and do not require a server catalog
entry. Optional `source_course_id` and `source_layout_id` record provenance only;
they are not foreign keys. Subsequent catalog edits or deletion cannot change
stored scorecards. The server validates scorecard structure, but does not certify
that supplied historical names or scores match a catalog or real-world round.

The first upload returns 201. A semantically identical retry by the owner returns
200 and the original scorecard, including when participant, hole, or score array
ordering differs or the timestamp uses an equivalent timezone offset. A changed
payload or another account reusing that round UUID receives a generic 409;
existing history is never overwritten. A database primary key prevents duplicate
rounds, including competing inserts. There are no edit, sharing, or delete
endpoints. Round responses use `Cache-Control: no-store`.

`tests/test_rounds.py` uses the existing isolated database fixture, so the same
tests run against live PostgreSQL in `compose.test.yaml` and disposable SQLite
locally. Run the isolated PostgreSQL stack with a fresh build after changing tests
or migrations. No Android upload protocol, synchronization,
or public sharing is implemented by this phase.

### Personal statistics

`GET /v1/statistics` requires a session and returns statistics for the authenticated
account only. There is no account selector or public statistics endpoint. Responses
use `Cache-Control: no-store`. The Statistics navigation entry opens the Midnight
Red dashboard, with keyboard-scrollable tables, hole scoring meters, and a monthly
trend chart with equivalent tabular values.

Only participants with an explicit `account_id` matching the session account count.
Names, round ownership, uploading accounts, and participant order never establish
identity. A linked scorecard uploaded by another account counts, without exposing
other participants or granting access to that owner's private round history.

Calculations use immutable hole/course/layout snapshots:

- `total_rounds` and `total_holes` count complete, valid linked scorecards.
- `by_length` gives arithmetic mean strokes and score relative to par per round,
  separately for each hole count. No combined round average mixes 9, 18, or other
  lengths. Course difficulty can still differ within a length group.
- `scoring` percentages use all included holes as the denominator. Birdie is
  exactly one under par; par is even; bogey is one over; worse is two or more
  over. Eagle or better is reported separately. Percentages are null when empty.
- `personal_bests` selects lowest total strokes separately for course/layout
  provenance IDs, snapshot names, and the exact ordered hole setup (number, par,
  tee, basket, and recorded distance). Unknown provenance cannot distinguish two
  otherwise identical offline snapshots. No live catalog lookup is used.
- `recent_rounds` contains the latest 20 valid linked rounds; aggregates include
  the entire valid history. Ordering is completion time descending, then round
  UUID ascending. Equal best scores prefer that same ordering.
- `trends` gives monthly arithmetic mean score relative to par per round, grouped
  by UTC month and hole count. Months without rounds are omitted. The chart
  separates lengths and labels its range; lower values are better.
- `excluded_rounds` counts invalid/incomplete linked scorecards excluded from
  every calculation. The dashboard displays a notice. Empty accounts show an
  empty state rather than performance zeros. Calculated values round to four
  decimal places in the API; the UI rounds averages to two and percentages to one.

No migrations or new dependencies are required for statistics. Run the backend
suite against PostgreSQL 17 using the dedicated `TEST_DATABASE_URL` or isolated
Compose stack described above. Run `RUN_BROWSER_TESTS=1 pytest -q` where Chromium
and local sockets are available to validate mobile/desktop statistics and existing
Round History behavior.
