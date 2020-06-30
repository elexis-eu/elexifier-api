from app import db
from sqlalchemy.sql import func


class Transformer(db.Model):

    __tablename__ = 'transformers'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    name = db.Column(db.String)
    created_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    entity_spec = db.Column(db.String)
    transform = db.Column(db.JSON)
    saved = db.Column(db.Boolean, default=False)
    #task_id = db.Column(db.String, server_default=None)
    file_download_status = db.Column(db.String, server_default=None)
