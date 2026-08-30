from model import Book, User
from storage import load_data, save_data

class Library:
    
    def __init__(self, books_file="books.json", users_file="users.json", borrows_file="borrows.json"):
        self.books_file = books_file
        self.users_file = users_file
        self.borrows_file = borrows_file
        self.books = self.load_books()
        self.users = self.load_users()
        self.borrows = self.load_borrows()

    def load_books(self):
        loaded_data = load_data(self.books_file)
        books_list = []
        for item in loaded_data:
            if all(key in item for key in ['id', 'title', 'author', 'stock']):
                books_list.append(Book(item['id'], item['title'], item['author'], item['stock']))
        return books_list

    def load_users(self):
        loaded_data = load_data(self.users_file)
        users_list = []
        for item in loaded_data:
            if all(key in item for key in ['username', 'password', 'role']):
                users_list.append(User(item['username'], item['password'], item['role']))
        return users_list

    def load_borrows(self):
        return load_data(self.borrows_file)

    def save_books(self):
        save_data(self.books_file, [book.to_dict() for book in self.books])

    def save_users(self):
        save_data(self.users_file, [user.to_dict() for user in self.users])

    def save_borrows(self):
        save_data(self.borrows_file, self.borrows)

    def display_all_books(self):
        if not self.books:
            print("empty library")
            return
        print("\n--- books list ---")
        for book in self.books:
            print(f"ID: {book.id}, Title: {book.title}, Author: {book.author}, Stock: {book.stock}")
        print("------------------")
        

    def add_book(self, book_id, title, author, stock):
        is_duplicate = False
        for book in self.books:
            if book.title.lower() == title.lower() and book.author.lower() == author.lower():
                is_duplicate = True
                book.stock += stock
                print(f"book already exists, updated stock to {book.stock}")
                self.save_books()
                break
        if not is_duplicate:
            new_book = Book(book_id, title, author, stock)
            self.books.append(new_book)
            print(f"book '{title}' added successfully.")
            self.save_books()
            return True
        return False

    def remove_book(self, book_id):
        for book in self.books:
            if book.id == book_id:
                self.books.remove(book)
                print(f"book '{book.title}' removed successfully.")
                self.save_books()
                return True
        print("book not found.")
        return False

    def borrow_book(self, username, book_id):
        for book in self.books:
            if book.id == book_id:
                if book.stock <= 0:
                    print("book is not available.")
                    return False
                book.stock -= 1
                self.borrows.append({"username": username, "book_id": book_id})
                self.save_books()
                self.save_borrows()
                print(f"book '{book.title}' borrowed successfully.")
                return True
        print("book not found.")
        return False

    def return_book(self, username, book_id):
        for borrow in self.borrows:
            if borrow["username"] == username and borrow["book_id"] == book_id:
                self.borrows.remove(borrow)
                for book in self.books:
                    if book.id == book_id:
                        book.stock += 1
                        self.save_books()
                        self.save_borrows()
                        print(f"book '{book.title}' returned successfully.")
                        return True
        print("no borrow record found.")
        return False

    def display_members(self):
        if not self.users:
            print("no members found.")
            return
        print("\n--- members list ---")
        for user in self.users:
            print(f"username: {user.username}, role: {user.role}")
        print("--------------------")