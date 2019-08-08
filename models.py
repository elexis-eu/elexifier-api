from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from server import app
import datetime
from sqlalchemy.sql import func


db = SQLAlchemy(app)


class User(db.Model):

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String)
    password_hash = db.Column(db.String)
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
   

