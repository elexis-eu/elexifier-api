from app.user.models import User, BlacklistToken
from app.modules.error_handling import InvalidUsage


def verify_user(token):
    if not token:
        raise InvalidUsage("No auth token provided.", status_code=401, enum="UNAUTHORIZED")

    uid = User.decode_auth_token(token)
    if isinstance(uid, str):
        raise InvalidUsage(uid, status_code=401, enum="UNAUTHORIZED")
    #elif is_blacklisted(engine, token):
    #    raise InvalidUsage('User logged out. Please log in again.', status_code=401, enum="UNAUTHORIZED")
    else:
        return uid


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
