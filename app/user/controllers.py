from app.user.models import User, BlacklistToken
from app.modules.error_handling import InvalidUsage
import flask


def check_auth(func):
    def check_function(*args, **kwargs):
        auth_token = flask.request.headers.get('Authorization')
        uid = User.decode_auth_token(auth_token)
        if type(uid) == str:
            raise InvalidUsage(uid, status_code=409, enum="INVALID_AUTH_TOKEN")
        else:
            result = func(*args, **kwargs)
            return result
    return check_function


def blacklist_token(db, auth_token):
    print('blacklist token')

    db.session.add(BlacklistToken(token=auth_token))
    db.session.commit()
    return None


def is_blacklisted(db, auth_token):
    print('is blacklisted')
    connection = db.connect()
    result = connection.execute("SELECT * FROM blacklist_tokens WHERE token = '{0:s}'".format(auth_token))
    is_blacklisted = len([x for x in result]) != 0
    connection.close()
    return is_blacklisted
