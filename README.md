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

Requirements
Python 3
pytest

How to Run
Clone the repository:
git clone <repository-url>
cd final-sara