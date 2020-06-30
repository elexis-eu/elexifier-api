from app import db
from sqlalchemy.sql import func


class Datasets(db.Model):
    __tablename__ = 'datasets'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uid = db.Column(db.Integer, db.ForeignKey('users.id'))
    name = db.Column(db.String)
    size = db.Column(db.Integer)
    file_path = db.Column(db.String)
    xml_file_path = db.Column(db.String, server_default=None)
    uploaded_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    upload_mimetype = db.Column(db.String)
    upload_uuid = db.Column(db.String)
    status = db.Column(db.String, server_default=None)
    lexonomy_access = db.Column(db.String, server_default=None)
    lexonomy_delete = db.Column(db.String, server_default=None)
    lexonomy_edit = db.Column(db.String, server_default=None)
    lexonomy_status = db.Column(db.String, server_default=None)
    header_title = db.Column(db.String, server_default=None)
    header_publisher = db.Column(db.String, server_default=None)
    header_bibl = db.Column(db.String, server_default=None)
    ml_task_id = db.Column(db.String, server_default="")
    xml_lex = db.Column(db.String, server_default="")
    xml_ml_out = db.Column(db.String, server_default="")
    lexonomy_ml_access = db.Column(db.String, server_default=None)
    lexonomy_ml_delete = db.Column(db.String, server_default=None)
    lexonomy_ml_edit = db.Column(db.String, server_default=None)
    lexonomy_ml_status = db.Column(db.String, server_default=None)
    pos_elements = db.Column(db.String, server_default=None)
    head_elements = db.Column(db.String, server_default=None)
    xpaths_for_validation = db.Column(db.String, server_default=None)
    root_element = db.Column(db.String, server_default=None)
    dictionary_metadata = db.Column(db.String, server_default=None)
    xml_tags = db.Column(db.JSON, server_default=None)
    character_map = db.Column(db.JSON, server_default=None)


class Datasets_single_entry(db.Model):
    __tablename__ = 'datasets_single_entry'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    entry_name = db.Column(db.String)
    entry_head = db.Column(db.String)
    entry_text = db.Column(db.String)
    xfid = db.Column(db.String)
    contents = db.Column(db.String)
