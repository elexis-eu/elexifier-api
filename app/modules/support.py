import flask
import re
import sqlalchemy
from sqlalchemy.sql import func

from app import app, db, celery
from app.user.models import User
from app.user.controllers import verify_user
from app.dataset.models import Datasets
from app.modules.error_handling import InvalidUsage

# TODO: should this be here?
from sqlalchemy import create_engine
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(db_uri, encoding='utf-8')


# --- model ---
class Error_log(db.Model):
    __tablename__ = 'error_log'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_ts = db.Column(db.DateTime(timezone=True), server_default=func.now())
    dsid = db.Column(db.Integer, db.ForeignKey('datasets.id'))
    tag = db.Column(db.String, server_default=None)
    message = db.Column(db.String, server_default=None)

    def __init__(self, dsid, tag=None, message=None):
        self.dsid = dsid
        if message is not None:
            self.message = message
        if tag is not None:
            self.tag = tag


# --- controllers ---
def add_error_log(db, dsid, tag=None, message=None):
    err_log = Error_log(dsid, tag=tag, message=message)
    db.session.add(err_log)
    db.session.commit()
    return


def get_error_log(db, e_id=None, tag=None, dsid=None):
    logs = db.session.query(Error_log)#.order_by(sqlalchemy.desc(Error_log.created_ts)).all()
    if dsid is not None:
        logs = logs.filter(Error_log.dsid == dsid)
    if tag is not None:
        logs = logs.filter(Error_log.tag == tag)
    if e_id is not None:
        logs = logs.filter(Error_log.id == e_id)
    logs = logs.order_by(sqlalchemy.desc(Error_log.created_ts)).all()
    db.session.commit()
    return logs


def delete_error_log(db, e_id, dsid=None):
    if dsid is None:
        db.session.query(Error_log).filter(Error_log.id == e_id).delete()
    else:
        db.session.query(Error_log).filter(Error_log.dsid == dsid).delete()
    db.session.commit()
    return


# --- views ---
@app.route('/api/support/list', methods=['GET'])
def list_error_logs():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    user = User.query.filter_by(id=id).first()
    db.session.close()
    if user is not None and not user.admin:
        raise InvalidUsage('User is not admin.', status_code=401, enum="UNAUTHORIZED")
    tag = flask.request.args.get('tag', default=None)
    dsid = flask.request.args.get('dsid', default=None)
    if dsid is not None:
        dsid = int(dsid)
    logs = get_error_log(db, tag=tag, dsid=dsid)
    logs = [{'id': log.id, 'dsid': log.dsid, 'tag': log.tag, 'message': log.message, 'time': log.created_ts} for log in logs]
    return flask.make_response({'logs': logs}, 200)


@celery.task
@app.route('/api/support/<int:e_id>', methods=['GET'])
def view_error_log(e_id):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    user = User.query.filter_by(id=id).first()
    db.session.close()
    if user is not None and not user.admin:
        raise InvalidUsage('User is not admin.', status_code=401, enum="UNAUTHORIZED")

    log = get_error_log(db, e_id=e_id)[0]

    dataset = Datasets.query.filter_by(id=log.dsid).first()
    pdf = flask.request.args.get('pdf', default=0, type=int) == 1
    xml_lex = flask.request.args.get('xml_lex', default=0, type=int) == 1
    xml_raw = flask.request.args.get('xml_raw', default=0, type=int) == 1

    if xml_raw:
        return flask.send_file(dataset.xml_file_path, attachment_filename='{0}_xml_raw.xml'.format(dataset.id), as_attachment=True)

    elif xml_lex:
        file_path = dataset.xml_file_path.split('.xml')[0] + '-LEX.xml'
        return flask.send_file(file_path, attachment_filename='{0}_xml_lex.xml'.format(dataset.id), as_attachment=True)

    elif pdf:
        file_path = dataset.file_path
        return flask.send_file(file_path, attachment_filename='{0}_dictionary.pdf'.format(dataset.id), as_attachment=True)

    # If no params, return log
    log.message = re.sub('\n', '<br/>', log.message)
    return flask.make_response({'id': log.id, 'dsid': log.dsid, 'tag': log.tag, 'message': log.message, 'time': log.created_ts}, 200)


@app.route('/api/support/<int:e_id>', methods=['DELETE'])
def delete_error_log(e_id):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    user = User.query.filter_by(id=id).first()
    db.session.close()
    #user = controllers.user_data(db, id)
    if user is not None and not user.admin:
        raise InvalidUsage('User is not admin.', status_code=401, enum="UNAUTHORIZED")

    delete_error_log(db, e_id)
    return flask.make_response({'message': 'ok'}, 200)