from auth import Auth
from library import Library


def handle_register(auth: Auth) -> None:
    username = input("Username: ").strip()
    password = input("Password: ").strip()

    auth.register(username, password)


def handle_login(auth: Auth) -> None:
    username = input("Username: ").strip()
    password = input("Password: ").strip()

    auth.login(username, password)


def handle_borrow(auth: Auth, library: Library) -> None:
    library.display_all_books()

    try:
        book_id = int(input("Enter book ID to borrow: ").strip())
        library.borrow_book(auth.current_user.username, book_id)
    except ValueError:
        print("Invalid ID. Please enter a number.")


def handle_return(auth: Auth, library: Library) -> None:
    try:
        book_id = int(input("Enter book ID to return: ").strip())
        library.return_book(auth.current_user.username, book_id)
    except ValueError:
        print("Invalid ID. Please enter a number.")


def handle_add_book(library: Library) -> None:
    try:
        book_id = int(input("Book ID: ").strip())
        title = input("Title: ").strip()
        author = input("Author: ").strip()
        stock = int(input("Stock: ").strip())

        library.add_book(book_id, title, author, stock)

    except ValueError:
        print("Invalid input. Please check your values.")


def handle_remove_book(library: Library) -> None:
    try:
        book_id = int(input("Enter book ID to remove: ").strip())
        library.remove_book(book_id)
    except ValueError:
        print("Invalid ID. Please enter a number.")


def display_menu() -> None:
    print("\n=== Welcome to Library Management System ===")
    print("1. Register")
    print("2. Login")
    print("3. Logout")
    print("4. View Books")
    print("5. Borrow Book")
    print("6. Return Book")
    print("7. Add Book (Admin)")
    print("8. Remove Book (Admin)")
    print("9. View Members (Admin)")
    print("0. Exit")


def main() -> None:
    library = Library()
    auth = Auth(library)

    while True:
        display_menu()

        choice = input("\nPlease enter your choice: ").strip()

        if choice == "1":
            handle_register(auth)

        elif choice == "2":
            handle_login(auth)

        elif choice == "3":
            auth.logout()

        elif choice == "4":
            library.display_all_books()

        elif choice == "5":
            if not auth.is_logged_in():
                print("Please login first.")
            else:
                handle_borrow(auth, library)

        elif choice == "6":
            if not auth.is_logged_in():
                print("Please login first.")
            else:
                handle_return(auth, library)

        elif choice == "7":
            if not auth.is_admin():
                print("Access denied. Admins only.")
            else:
                handle_add_book(library)

        elif choice == "8":
            if not auth.is_admin():
                print("Access denied. Admins only.")
            else:
                handle_remove_book(library)

        elif choice == "9":
            if not auth.is_admin():
                print("Access denied. Admins only.")
            else:
                library.display_members()

        elif choice == "0":
            print("Goodbye!")
            break

        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()