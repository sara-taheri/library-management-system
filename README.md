# Library Management System

A simple command-line Library Management System built with Python.

This project demonstrates Object-Oriented Programming, file-based data storage, user authentication, borrowing and returning books, and automated testing with pytest.

## Features

- User registration and login
- Password hashing using SHA-256
- Member and admin roles
- View available books
- Borrow books
- Return books
- Add books (admin only)
- Remove books (admin only)
- View members (admin only)
- JSON-based data storage
- Automated tests with pytest

## Project Structure

```text
final-sara/
│
├── auth.py          # User authentication and authorization
├── library.py       # Main library operations
├── main.py          # Command-line application
├── model.py         # Book and User models
├── storage.py       # JSON data loading and saving
├── test.py          # Automated tests
│
├── books.json       # Book data
├── users.json       # Sample user data
├── borrows.json     # Borrow records
│
├── .gitignore
└── README.md

## Requirements

- Python 3.11+
- Web app dependencies: `pip install -r requirements.txt`
- Development/test dependencies: `pip install -r requirements-dev.txt`
- Copy `.env.example` to `.env` and set at least `SECRET_KEY` (optional in development)

## How to Run

Clone the repository:

```bash
git clone https://github.com/sara-taheri/library-management-system.git
cd library-management-system
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Web application

The project is being upgraded into a full web application (FastAPI + SQLAlchemy/SQLite,
server-rendered UI). First, migrate the legacy JSON data into the database:

```bash
python scripts/migrate_json_to_db.py     # reads books.json / users.json / borrows.json
                                         # creates data/library.db; JSON files are never modified
```

Then start the server:

```bash
uvicorn app.main:app --reload
```

- Home page: http://127.0.0.1:8000/
- Log in / register: http://127.0.0.1:8000/login · http://127.0.0.1:8000/register
- Interactive API docs (Swagger UI): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health
- Books API: http://127.0.0.1:8000/api/books (supports `q`, `genre`, `available_only`, `page`, `page_size`)

#### Authentication (Phase 3)

| Endpoint | Method | Access | Purpose |
|---|---|---|---|
| `/api/auth/register` | POST | public | Create an account (always role `member`) |
| `/api/auth/login` | POST | public | Start a signed session cookie |
| `/api/auth/logout` | POST | any | End the session |
| `/api/auth/me` | GET | member+ | Current user profile |
| `/api/admin/overview` | GET | **admin** | Library statistics (RBAC-protected) |

Server-rendered pages: `/` (home), `/login`, `/register`, `/account` (dashboard),
`/admin` (admin overview). Forms carry CSRF tokens and use the
Post/Redirect/Get pattern with flash messages.

Security notes:

- Passwords are hashed with **bcrypt**. Accounts migrated from the legacy
  `users.json` (unsalted SHA-256) are **transparently upgraded to bcrypt on
  their first successful login** - no user is locked out.
- Demo accounts from the legacy data: `admin / admin123` (role admin) and
  `member / member123` (role member). Change or remove them for real deployments.
- Sessions are signed cookies (`itsdangerous`): HttpOnly, SameSite=Lax, and
  Secure in production. Set a strong `SECRET_KEY` in `.env` - the app refuses
  to boot in production with the default one.

### Legacy command-line app

The original CLI still works and is unchanged (renamed entrypoint):

```bash
python cli.py
```

### Tests

```bash
python -m pytest
```

## Project Structure

```text
library-management-system/
├── app/                    # FastAPI web application
│   ├── main.py             #   application factory (create_app), middleware, error pages
│   ├── config.py           #   environment-based settings (.env support)
│   ├── database.py         #   SQLAlchemy engine/session helpers
│   ├── deps.py             #   FastAPI dependencies (get_db, auth guards: require_user/require_admin)
│   ├── web.py              #   Jinja2 templates + shared render helper
│   ├── models/             #   ORM models: User, Book, Loan, CalendarEvent
│   ├── schemas/            #   Pydantic request/response schemas (book, auth, admin)
│   ├── services/           #   framework-free business logic (auth_service, stats_service)
│   ├── routers/            #   HTTP routers: books, auth, admin (JSON) + pages (HTML)
│   ├── templates/          #   Jinja2 pages: base layout, home, login, register, account, admin, error
│   ├── static/             #   app.css (design-system seed)
│   └── utils/              #   security (bcrypt + legacy upgrade), sessions, csrf, flash, urls
├── scripts/
│   └── migrate_json_to_db.py   # one-time legacy JSON -> SQLite migration
├── tests/                  # pytest suite (API, pages, services, security, migration, legacy domain)
├── cli.py                  # legacy command-line application (was main.py)
├── auth.py                 # legacy CLI authentication (kept working)
├── library.py              # legacy CLI library operations (kept working)
├── model.py / storage.py   # legacy CLI models / JSON storage
├── books.json / users.json / borrows.json   # legacy data (kept as seed + backup)
├── requirements.txt / requirements-dev.txt / .env.example
└── README.md
```