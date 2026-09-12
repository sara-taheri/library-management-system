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

### Web API (Phase 2 - in development)

The project is being upgraded into a full web application (FastAPI + SQLAlchemy/SQLite,
server-rendered UI in later phases). First, migrate the legacy JSON data into the database:

```bash
python scripts/migrate_json_to_db.py     # reads books.json / users.json / borrows.json
                                         # creates data/library.db; JSON files are never modified
```

Then start the server:

```bash
uvicorn app.main:app --reload
```

- Interactive API docs (Swagger UI): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health
- Books API: http://127.0.0.1:8000/api/books (supports `q`, `genre`, `available_only`, `page`, `page_size`)

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
│   ├── main.py             #   application factory (create_app)
│   ├── config.py           #   environment-based settings (.env support)
│   ├── database.py         #   SQLAlchemy engine/session helpers
│   ├── deps.py             #   shared FastAPI dependencies (get_db)
│   ├── models/             #   ORM models: User, Book, Loan, CalendarEvent
│   ├── schemas/            #   Pydantic request/response schemas
│   └── routers/            #   HTTP routers (books API for now)
├── scripts/
│   └── migrate_json_to_db.py   # one-time legacy JSON -> SQLite migration
├── tests/                  # pytest suite (API, migration, legacy domain)
├── cli.py                  # legacy command-line application (was main.py)
├── auth.py                 # legacy CLI authentication (kept working)
├── library.py              # legacy CLI library operations (kept working)
├── model.py / storage.py   # legacy CLI models / JSON storage
├── books.json / users.json / borrows.json   # legacy data (kept as seed + backup)
├── requirements.txt / requirements-dev.txt / .env.example
└── README.md
```