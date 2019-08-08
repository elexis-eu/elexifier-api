#!/usr/bin/env python
from getpass import getpass
import sys

from flask import current_app
from server import app, bcrypt
from models import User
from flask_sqlalchemy import SQLAlchemy




def main():
    """Main entry point for script."""
    db = SQLAlchemy()
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine)
        if User.query.all():
            print('A user already exists! Create another? (y/n):')
            create = input()
            if create == 'n':
                return

        print('Enter username: ')
        username = input()
        password_hash = getpass()
        assert password_hash == getpass('Password (again):')

        user = User(
            username=username, 
            password_hash=bcrypt.generate_password_hash(password_hash).decode('utf-8'),
            authenticated=True)
        db.session.add(user)
        db.session.commit()
        print('User added.')


if __name__ == '__main__':
    sys.exit(main())