import os

from auth import Auth
from library import Library


def create_test_library():
    books_file = "test_books.json"
    users_file = "test_users.json"
    borrows_file = "test_borrows.json"

    for filename in [books_file, users_file, borrows_file]:
        if os.path.exists(filename):
            os.remove(filename)

    return Library(
        books_file=books_file,
        users_file=users_file,
        borrows_file=borrows_file
    )


def test_register():
    library = create_test_library()
    auth = Auth(library)

    result = auth.register("test_user", "1234")

    assert result is True
    assert len(library.users) == 1
    assert library.users[0].username == "test_user"


def test_login():
    library = create_test_library()
    auth = Auth(library)

    auth.register("test_user", "1234")

    assert auth.login("test_user", "1234") is True
    assert auth.is_logged_in() is True


def test_wrong_password():
    library = create_test_library()
    auth = Auth(library)

    auth.register("test_user", "1234")

    assert auth.login("test_user", "wrong") is False
    assert auth.is_logged_in() is False


def test_borrow_book():
    library = create_test_library()

    library.add_book(
        1,
        "Clean Code",
        "Robert C. Martin",
        3
    )

    result = library.borrow_book("test_user", 1)

    assert result is True
    assert library.books[0].stock == 2
    assert len(library.borrows) == 1


def test_return_book():
    library = create_test_library()

    library.add_book(
        1,
        "Clean Code",
        "Robert C. Martin",
        3
    )

    library.borrow_book("test_user", 1)

    result = library.return_book("test_user", 1)

    assert result is True
    assert library.books[0].stock == 3
    assert len(library.borrows) == 0


def test_borrow_unavailable_book():
    library = create_test_library()

    library.add_book(
        1,
        "Clean Code",
        "Robert C. Martin",
        1
    )

    library.borrow_book("test_user", 1)

    result = library.borrow_book("another_user", 1)

    assert result is False
    assert library.books[0].stock == 0