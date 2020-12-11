from app import db, app
import datetime
import jwt
from sqlalchemy.sql import func
from flask_bcrypt import Bcrypt
import string
import random


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(120), unique = True, nullable = False)
    email = db.Column(db.String(120), unique = True, nullable = False)
    password_hash = db.Column(db.String(120), nullable = True)
    authenticated = db.Column(db.Boolean, default=False)
    registered_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    sketch_engine_uid = db.Column(db.Integer)
    admin = db.Column(db.Boolean, default=False)

    def __init__(self, email, password, sketch_engine_uid=None):
        self.email = email
        self.username = email

        if sketch_engine_uid is not None:
            letters = string.ascii_letters
            self.sketch_engine_uid = sketch_engine_uid
            # generate random password
            self.set_password(''.join(random.choice(letters) for _ in range(12)))
        else:
            self.set_password(password)

    def __str__(self):
        return '<User id: {0}, email: {1}>'.format(self.id, self.email)

    def set_password(self, password):
        self.password_hash = Bcrypt(app).generate_password_hash(password).decode('utf-8')
        return

    def check_password(self, password):
        return Bcrypt.check_password_hash(Bcrypt, self.password_hash, password)

    def get_auth_token(self):
        payload = {
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30),
                'iat': datetime.datetime.utcnow(),
                'sub': self.id
                }
        return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256').decode('utf-8')

    @staticmethod
    def decode_auth_token(auth_token):
        """
        Decodes the auth token
        :param auth_token:
        :return: integer|string
        """
        if 'Bearer ' in auth_token:
            auth_token = auth_token.replace('Bearer ', '')
        try:
            payload = jwt.decode(auth_token, app.config['SECRET_KEY'])
            return payload['sub']
        except jwt.ExpiredSignatureError:
            return 'Signature expired. Please log in again.'
        except jwt.InvalidTokenError:
            return 'Invalid token. Please log in again.'

    @staticmethod
    def decode_sketch_token(sketch_token):
        try:
            payload = jwt.decode(sketch_token, verify=False)
            return payload['user']
        except jwt.ExpiredSignatureError:
            return 'Signature expired. Please log in again.'
        except jwt.InvalidTokenError:
            return 'Invalid token. Please log in again.'


class BlacklistToken(db.Model):
    """
    Token Model for storing JWT tokens
    """
    __tablename__ = 'blacklist_tokens'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    token = db.Column(db.String(500), unique=True, nullable=False)
    blacklisted_on = db.Column(db.DateTime, nullable=False)

    def __init__(self, token):
        self.token = token
        self.blacklisted_on = datetime.datetime.now()

    def __repr__(self):
        return '<id: token: {}'.format(self.token)
