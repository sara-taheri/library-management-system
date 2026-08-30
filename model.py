class Book:
    def __init__(self, id, title, author, stock):
        self.id = id
        self.title = title
        self.author = author
        self.stock = stock

   
    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "stock": self.stock
        }

class User:
    def __init__(self, username, password, role="member"):
        self.role = role
        self.password = password
        self.username = username

    def to_dict(self):
        return {
        "role":self.role,
        "password":self.password,
        "username":self.username
        }

#class library:
   # def __init__(self, )