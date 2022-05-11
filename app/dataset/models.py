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
    config = db.Column(db.JSON, server_default=None)

    def __repr__(self):
        return '<Dataset id: {0}, uid: {1}, file: {2}>'.format(self.id, self.uid, self.file_path)

    @staticmethod
    def to_dict(dataset):
        ds = {'id': dataset.id,
              'name': dataset.name,
              'size': dataset.size,
              'upload_uuid': dataset.uid,
              'file_path': dataset.file_path,
              'xml_file_path': dataset.xml_file_path,
              'xml_lex': dataset.xml_lex,
              'xml_ml_out': dataset.xml_ml_out,
              'uploaded_ts': dataset.uploaded_ts,
              'upload_mimetype': dataset.upload_mimetype,
              'lexonomy_access': dataset.lexonomy_access,
              'lexonomy_delete': dataset.lexonomy_delete,
              'lexonomy_edit': dataset.lexonomy_edit,
              'lexonomy_status': dataset.lexonomy_status,
              'status': dataset.status,
              'lexonomy_ml_access': dataset.lexonomy_ml_access,
              'lexonomy_ml_delete': dataset.lexonomy_ml_delete,
              'lexonomy_ml_edit': dataset.lexonomy_ml_edit,
              'lexonomy_ml_status': dataset.lexonomy_ml_status
        }
        return ds

class Datasets_single_entry(db.Model):
    __tablename__ = 'datasets_single_entry'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    entry_name = db.Column(db.String)
    entry_head = db.Column(db.String)
    entry_text = db.Column(db.String)
    xfid = db.Column(db.String)
    contents = db.Column(db.String)

    @staticmethod
    def to_dict(entry):
        dse = {'id': entry.id,
               'dsid': entry.dsid,
               'entry_name': entry.entry_name,
               'entry_head': entry.entry_head,
               'entry_text': entry.entry_text,
               'xfid': entry.xfid,
               'contents': entry.contents}
        return dse
