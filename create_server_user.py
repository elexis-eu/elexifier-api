#!/usr/bin/env python
from getpass import getpass
import sys

from flask import current_app
from app.models import User
from app import db, app
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import flask

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


def main():
    """Main entry point for script."""
    bcrypt = Bcrypt()
    db = SQLAlchemy()
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine)
        
        user = User(
            username='user', 
            email='user@user.net',
            password_hash=bcrypt.generate_password_hash('user').decode('utf-8'),
            authenticated=True)
        db.session.add(user)
        db.session.commit()
        print('User added.')


if __name__ == '__main__':
    sys.exit(main())