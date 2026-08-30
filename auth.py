import hashlib

from model import User


class Auth:
    def __init__(self, library):
        self.library = library
        self.current_user = None

    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()

    def register(self, username, password, role="member"):
        for user in self.library.users:
            if user.username == username:
                print("This username already exists.")
                return False

        hashed_password = self.hash_password(password)

        new_user = User(username, hashed_password, role)
        self.library.users.append(new_user)
        self.library.save_users()

        print(f"User '{username}' registered successfully.")
        return True

    def login(self, username, password):
        hashed_password = self.hash_password(password)

        for user in self.library.users:
            if user.username == username and user.password == hashed_password:
                self.current_user = user
                print(f"Welcome {username}!")
                return True

        print("Username or password is incorrect.")
        return False

    def logout(self):
        if self.current_user:
            print(f"User '{self.current_user.username}' logged out.")
            self.current_user = None
        else:
            print("No user is currently logged in.")

    def is_logged_in(self):
        return self.current_user is not None

    def is_admin(self):
        return self.is_logged_in() and self.current_user.role == "admin"