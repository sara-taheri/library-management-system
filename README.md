# Library Management System

A university web application for a small library: members browse the catalog,
borrow and return books, and keep a personal calendar; librarians manage the
catalog and see live library statistics.

The project is a **single FastAPI process** with **SQLite** and
**server-rendered Jinja2 pages**. A JSON API under `/api` shares the same
services as the HTML pages so the two interfaces cannot drift. The original
command-line app is still included and still works.

Version: **1.0.0**

## Main features

- Registration, login, logout (HTML forms and JSON API)
- Roles: **member** and **admin**, enforced in services and route guards
- Public catalog with search, genre filter, and availability filter
- Admin book create / edit / safe deactivate (hard delete only via API)
- Borrowing with a due date, return by owner or admin, borrowing history
- Automatic book-return calendar reminder when a book is borrowed
- Shared monthly calendar with a selected-day briefing (books due, borrowing activity)
- Calendar task runner on the selected date (same engine as the CLI; no background worker)
- Simple A ± B calculator stored as a completed calendar task
- First-boot sample catalog and bcrypt demo accounts when the database is empty
- Admin dashboard with live metrics and recent activity
- CSRF on every HTML form, signed session cookies, bcrypt passwords
- Styled HTML error pages for browsers; JSON errors for `/api`
- Deterministic pytest suite (API, pages, services, migration, legacy CLI)

## Technology stack

| Layer | Choice |
|---|---|
| Language | Python 3.10+ (developed and tested on 3.13) |
| Web | FastAPI, Uvicorn, Jinja2, Starlette sessions |
| Database | SQLite via SQLAlchemy 2.0 (no Alembic) |
| Auth | bcrypt (legacy SHA-256 hashes upgraded on login) |
| Tests | pytest, httpx / TestClient, Ruff, pytest-cov |
| Browser E2E | Playwright smoke suite (optional; see limitation below) |

There is **no** Redis, Celery, Docker, SPA framework, or second calendar
system. Schema changes for existing databases are applied by
`python scripts/upgrade_db.py`.

## Project structure

```text
library-management-system/
├── app/                         FastAPI web application
│   ├── main.py                  application factory, security headers, error handlers
│   ├── config.py                settings from environment / optional .env
│   ├── database.py              SQLAlchemy engine/session helpers (naive UTC)
│   ├── deps.py                  get_db, require_user, require_admin
│   ├── web.py                   Jinja2 render helper (CSRF, flashes, nav_active)
│   ├── models/                  User, Book, Loan, CalendarEvent
│   ├── schemas/                 Pydantic request/response models
│   ├── services/                framework-free business logic
│   ├── routers/                 JSON API + HTML page handlers
│   ├── templates/               Jinja2 pages (all extend base.html)
│   ├── static/app.css           design system
│   └── utils/                   bcrypt, sessions, CSRF, flash, safe redirects
├── scripts/
│   ├── migrate_json_to_db.py    one-time legacy JSON → SQLite
│   ├── upgrade_db.py            idempotent ALTER for existing SQLite files
│   └── run_calendar_tasks.py    process due calendar tasks
├── tests/                       pytest (tmp SQLite; never touches data/library.db)
│   └── e2e/                     Playwright smoke tests (skip if Chromium cannot launch)
├── cli.py                       legacy command-line app (unchanged)
├── auth.py / library.py / model.py / storage.py
├── books.json / users.json / borrows.json   legacy seed + backup (never modified by migrate)
├── requirements.txt / requirements-dev.txt / .env.example / ruff.toml
└── README.md
```

## How authentication works

1. `POST /register` or `POST /api/auth/register` creates a **member**
   (self-service cannot pick the admin role).
2. Login verifies the password. New hashes use **bcrypt**. Accounts migrated
   from `users.json` keep unsalted SHA-256 until their **first successful
   login**, then the stored hash is upgraded to bcrypt automatically.
3. A signed session cookie (`lms_session`) is set: HttpOnly, SameSite=Lax,
   and Secure when `ENVIRONMENT=production`.
4. Every HTML form includes a per-session CSRF token (`_csrf`). Invalid
   tokens redirect with a flash error; the action is not performed.
5. `next` redirect targets after login are validated (`safe_redirect_target`)
   so open redirects are blocked.
6. Stale sessions (deleted user id) are cleared and treated as logged out.

## User roles and permissions

| Action | Guest | Member | Admin |
|---|---|---|---|
| Browse catalog, book detail, calendar (public events) | yes | yes | yes |
| Register / log in | yes | — | — |
| Borrow / return own loans, personal calendar events | no | yes | yes |
| Create announcement / maintenance events | no | no | yes |
| Create / edit / deactivate books | no | no | yes |
| List all loans, admin dashboard | no | no | yes |
| Return another member's loan | no | no | yes |

Hiding a link in the navbar is **not** the access control. Page handlers
redirect unauthenticated users to `/login?next=…` and members away from
admin URLs with a flash (“Access denied. Admins only.”). JSON endpoints
return 401 / 403.

## Book management

- Catalog: `GET /books` (public). Search `q`, genre, `available=1`.
  Admins may pass `all=1` to include deactivated titles.
- Create / edit: `/books/new`, `/books/{id}/edit` (admin). Total copies
  cannot drop below copies currently on loan.
- Deactivate (web): `POST /books/{id}/delete` hides the book from the
  default catalog and keeps loan history. Permanent delete is
  `DELETE /api/books/{id}?hard=true` and is refused while loans exist.

## Borrow and return workflow

- `POST /books/{id}/borrow` (signed-in): one active loan per member per
  title; 409 if no copy is free. `available_copies` is decremented.
  Due date = now + `LOAN_PERIOD_DAYS` (default 14). A pending
  `book_return` calendar event is created for the due date.
- `POST /loans/{id}/return`: owner or admin. Restores a copy, marks the
  loan `returned` (history is kept), and cancels the pending reminder.
- Member dashboard (`/account`) lists active loans (with Return) and
  history. Admin ledger: `/admin/loans` (All / Active / Overdue / Returned).

## Calendar and events

One `events` table is used for the monthly UI **and** for runner tasks.

| Type | Who can create | Visible to | Runner task? |
|---|---|---|---|
| general | signed-in | creator + admins | no |
| reminder, book_return, custom_task | signed-in | creator + admins | yes |
| announcement, maintenance | admin | everyone, including guests | yes |

Clicking a date on `/calendar` opens a **day briefing**: books due that
day, borrow/return activity, and pending tasks. Visibility matches the
rest of the app (members see their own loans; admins see everyone;
guests see no loan lists). Signed-in users can **Run pending tasks**
for that date (reuses `runner_service.run_due_tasks`) and store an
**A ± B** calculation as a completed `custom_task` on that date.

`python scripts/run_calendar_tasks.py` still processes **pending** tasks
with `scheduled_at <= now`. It is a one-shot command (suitable for cron),
not a thread inside Uvicorn. `--now` can simulate a later clock. The web
button does not replace the CLI; both call the same function.

## Admin dashboard and statistics

`GET /admin` (admin only) reads `stats_service.library_overview`:

Members, book titles, available books, available copies, borrowed books,
active loans, overdue loans, due-soon loans (next 7 days), calendar
events, upcoming events, plus a **recent activity** feed built from the
latest loans and events (no fake rows). Several tiles link to the
matching list.

`GET /api/admin/overview` still returns the original count fields
(`users`, `books`, `loans_total`, `loans_active`, `events`).

## Security measures

- bcrypt password hashing; generic “Invalid username or password.”
- CSRF on HTML state-changing forms
- Signed cookies; production refuses the default `SECRET_KEY`
- Open-redirect guard on login `next`
- Parameterised SQLAlchemy queries (raw SQL only in `upgrade_db.py` DDL)
- Response headers: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`
- Unhandled exceptions are logged server-side; clients never receive a
  traceback

## Error handling

| Client | 401 / 403 / 404 / 405 | Unexpected failure |
|---|---|---|
| Browser | styled `error.html` | HTTP 500, same page, generic message |
| `/api/*` or `Accept: application/json` | `{"detail": "…"}` | HTTP 500 JSON, generic message |

Validation errors stay 422 (Pydantic) or 400/409 with a human message
from the service layer. Forms re-render with the typed values preserved.

## Testing strategy

Tests build `create_app(database_url=sqlite:////tmp/…)` so they **never**
write to `data/library.db`. Coverage includes:

- JSON API (books, loans, events, auth, admin)
- HTML pages (CSRF, flashes, PRG, RBAC, catalog, calendar)
- services (auth upgrade, stats, runner)
- `migrate_json_to_db.py` and `upgrade_db.py`
- legacy CLI domain (`tests/test_legacy_domain.py`)
- 500 handler and security headers
- Playwright smoke tests under `tests/e2e/` (skipped if the browser
  cannot launch)

## Playwright status and limitation

The repository includes eight Playwright journeys in `tests/e2e/test_smoke.py`
(homepage, login success/failure, catalog, member denied admin, admin
dashboard, borrow/return, create event). They use a throwaway database
and bcrypt test users (`testmember` / `testadmin`) — **not** production
credentials.

In this development sandbox Chromium **downloads** but **does not launch**:

```text
error while loading shared libraries: libnspr4.so
```

`apt-get` is not available here, so the OS libraries cannot be installed.
`pytest` then **skips** those eight tests instead of reporting a fake pass.
On a machine with Playwright OS dependencies installed they can be run
as shown below.

## Installation requirements

- Python 3.10 or newer
- `pip`
- Git (to clone)
- Optional: Playwright + Chromium + OS libraries for browser tests

## Python virtual environment

```bash
git clone https://github.com/sara-taheri/library-management-system.git
cd library-management-system
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

## Dependency installation

```bash
pip install -r requirements.txt        # run the app
pip install -r requirements-dev.txt    # app + pytest, httpx, ruff, pytest-cov
```

## Database setup and migration

On first start, `create_app()` runs SQLAlchemy `create_all()`. If the
**books** table is empty it inserts the sample titles from `books.json`.
If the **users** table is empty it inserts the classroom demo accounts
with **bcrypt** hashes. Restarting never duplicates rows. `borrows.json`
is **not** imported automatically.

Tests pass `create_app(database_url=...)` and therefore **do not** seed,
so they keep using throwaway empty databases.

To rebuild from the legacy JSON files by hand (including skipping the
orphan borrow row):

```bash
python scripts/migrate_json_to_db.py
```

That command refuses to overwrite a database that already has rows unless
you pass `--reset` (JSON files are never modified). First-boot seed and
this script are independent: use migrate only when you want an explicit
reset/import.

If you already have a `data/library.db` from an older checkpoint:

```bash
python scripts/upgrade_db.py
```

This applies missing columns/renames in place and is safe to run repeatedly.

## Environment variables

Copy the template if you want a local file (optional in development):

```bash
cp .env.example .env
```

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | `dev-insecure-change-me` | Signs the session cookie. **Required** when `ENVIRONMENT=production`. |
| `ENVIRONMENT` | `development` | `development` or `production` (Secure cookie + secret check). |
| `DATABASE_URL` | `sqlite:///<repo>/data/library.db` | SQLAlchemy URL. Only SQLite is tested. |
| `LOAN_PERIOD_DAYS` | `14` | Days until a new loan is due. |
| `APP_NAME` | `Library Management System` | Shown in `/health` and page titles. |
| `SESSION_COOKIE_NAME` | `lms_session` | Cookie name. |
| `SESSION_MAX_AGE_DAYS` | `7` | Session lifetime. |

## How to run the application

```bash
uvicorn app.main:app --reload
```

Then open:

- Home: http://127.0.0.1:8000/
- Login / register: http://127.0.0.1:8000/login · http://127.0.0.1:8000/register
- Catalog: http://127.0.0.1:8000/books
- Calendar: http://127.0.0.1:8000/calendar
- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs

### Demo accounts (local classroom / demo only)

A **fresh empty database** (first `uvicorn` start) creates these accounts
with bcrypt. The same usernames exist after `python scripts/migrate_json_to_db.py`
(legacy SHA-256 hashes, upgraded to bcrypt on first login).

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | admin |
| `member` | `member123` | member |

Plaintext passwords are **never stored in the database** — only bcrypt
(or, for un-upgraded migrate rows, the SHA-256 hash from `users.json`).

These are **sample classroom accounts**. Change or delete them before any
real deployment. Self-service `/register` always creates a **member**.

### Legacy command-line app

```bash
python cli.py
```

Uses `books.json` / `users.json` / `borrows.json` directly. It is separate
from the web database.

### Calendar runner (optional)

```bash
python scripts/run_calendar_tasks.py
python scripts/run_calendar_tasks.py --verbose --now 2026-12-31T00:00:00
```

## How to run pytest

From the repository root, with the venv active:

```bash
python -m pytest
```

## How to run Ruff

```bash
python -m ruff check app tests scripts
```

`ruff.toml` enables rules `F` and `B`, and ignores `B008` (FastAPI
`Depends()` in argument defaults).

## How to run coverage

```bash
python -m pytest --cov=app --cov-report=term-missing
```

## How to run Playwright tests

Optional — not required to use or grade the pytest suite.

```bash
pip install playwright pytest-playwright
python -m playwright install chromium
# On Linux you may also need Playwright's OS packages, e.g.
# python -m playwright install-deps chromium
python -m pytest tests/e2e
```

If Chromium cannot start, those tests skip with an explicit reason.

## Known limitations

- Single-process Uvicorn; no gunicorn/Docker/production process manager is
  bundled.
- `/docs` (Swagger) is public even in production.
- No login rate limiting.
- Catalog HTML lists up to 100 books (the JSON API paginates).
- Calendar on very small screens scrolls horizontally rather than switching
  to a separate list view.
- Playwright needs OS libraries that this sandbox cannot install
  (`libnspr4.so`).
- PostgreSQL is not part of the project; only SQLite is tested.
- The CLI and the web app do **not** share a live database.

## JSON API (summary)

| Method | Path | Access |
|---|---|---|
| GET | `/api/books` | public |
| GET | `/api/books/{id}` | public |
| POST / PUT / DELETE | `/api/books`, `/api/books/{id}` | admin |
| POST | `/api/loans` | signed-in |
| POST | `/api/loans/{id}/return` | owner or admin |
| GET | `/api/loans/me` | signed-in |
| GET | `/api/loans`, `/api/loans/{id}` | admin / owner |
| GET / POST | `/api/events` | public list / signed-in create |
| GET / PUT / DELETE | `/api/events/{id}` | visibility / owner or admin |
| POST | `/api/events/{id}/cancel` | owner or admin |
| POST | `/api/auth/register`, `/api/auth/login` | public |
| POST | `/api/auth/logout` | any |
| GET | `/api/auth/me` | signed-in |
| GET | `/api/admin/overview` | admin |
