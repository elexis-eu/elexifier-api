from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from server import app
import datetime
from sqlalchemy.sql import func
import jwt


db = SQLAlchemy(app)


class User(db.Model):

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique = True, nullable = False)
    password_hash = db.Column(db.String(120), nullable = False)
    authenticated = db.Column(db.Boolean, default=False)

    def is_active(self):
        """True, as all users are active."""
        return True

    def get_id(self):
        """Return the email address to satify Flask-Login's requirements."""
        return self.id

    def is_authenticated(self):
        """Return True if the user is authenticated."""
        return self.authenticated

    def is_anonymous(self):
        """False, as anonymous users aren't supported."""
        return False

    def encode_auth_token(self, user_id):
        """
        Generates the Auth Token
        :return: string
        """
        try:
            payload = {
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=0, seconds=3600),
                'iat': datetime.datetime.utcnow(),
                'sub': user_id
            }
            return jwt.encode(
                payload,
                app.secret_key,
                algorithm='HS256'
            )
        except Exception as e:
            return e

    @staticmethod
    def decode_auth_token(auth_token):
        """
        Decodes the auth token
        :param auth_token:
        :return: integer|string
        """
        try:
            payload = jwt.decode(auth_token, app.config.get('SECRET_KEY'))
            return payload['sub']
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




class App_config(db.Model):
    
    __tablename__ = 'app_config'

    secret_key = db.Column(db.String, primary_key=True)



class Datasets(db.Model):
    
    __tablename__ = 'datasets'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uid = db.Column(db.Integer, db.ForeignKey('users.id'))
    name = db.Column(db.String)
    size = db.Column(db.Integer)
    file_path = db.Column(db.String)
    uploaded_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    upload_mimetype = db.Column(db.String) 
    upload_uuid = db.Column(db.String)
   


class Datasets_single_entry(db.Model):

    __tablename__ = 'datasets_single_entry'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    entry_name = db.Column(db.String)
    entry_head = db.Column(db.String)
    xfid = db.Column(db.String)
    contents = db.Column(db.String)
  


class Transformer(db.Model):

    __tablename__ = 'transformers'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    name = db.Column(db.String)
    created_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    entity_spec = db.Column(db.String)
    transform = db.Column(db.PickleType)
   

