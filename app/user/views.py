from app import app, db
from app.user.models import User
from app.user.controllers import verify_user
from app.modules.error_handling import InvalidUsage
import app.modules.log as log
import flask
from flask.json import jsonify

# TODO: should this be here?
from sqlalchemy import create_engine
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(db_uri, encoding='utf-8')


@app.route('/api/user/new', methods=['POST'])
def add_user():
    # Check all required fields
    for field in ['email', 'password']:
        if field not in flask.request.json:
            raise InvalidUsage('Field {0} is mising.', status_code=422, enum='POST_ERROR')

    email = flask.request.json['email']
    password = flask.request.json['password']

    # Check if user already exists
    #user = db.session.query(User).filter_by(email=email).first()
    user = User.query.filter_by(email=email).first()
    if user is not None:
        db.session.close()
        raise InvalidUsage('User already exists', status_code=409, enum='USER_EXISTS')

    user = User(email, password)
    db.session.add(user)
    db.session.commit()

    response = {
        'message': 'Registration was successful',
        'username': '',
        'email': user.email,
        'auth_token': user.get_auth_token()
    }
    log.print_log(app.name, 'Registered new user {}'.format(user))
    return flask.make_response(jsonify(response), 200)


@app.route('/api/user/logged-in', methods=['GET'])
def user_data():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    user = User.query.filter_by(id=id).first()
    db.session.close()

    if user is not None:
        response = {
            'username': user.username,
            'email': user.email,
            'admin': user.admin
        }
        return flask.make_response(jsonify(response),200)
    else:
        raise InvalidUsage('Provide a valid auth token.', status_code=409, enum="INVALID_AUTH_TOKEN")


@app.route('/api/login', methods=['GET', 'POST'])
def login():
    # Sketch-engine login
    if 'sketch_token' in flask.request.json:
        user_data = User.decode_sketch_token(flask.request.json['sketch_token'])
        user = User.query.filter_by(id=user_data['id']).first()
        # check if ske user exists
        if user is None:
            user = User(user_data['email'], None, sketch_engine_uid=user_data['id'])
            db.session.add(user)
            db.session.commit()
            db.session.close()

    # Regular login
    else:
        # Check required fields
        for field in ['login', 'password']:
            if field not in flask.request.json:
                raise InvalidUsage("Field {0:s} is missing".format(field), status_code=422, enum='POST_ERROR')

        email = flask.request.json['login']
        password = flask.request.json['password']
        #user = db.session.query(User).filter_by(email=email).first()
        user = User.query.filter_by(email=email).first()
        db.session.close()

        if user is None or not user.check_password(password):
            # proper login handling if more time ... (?)
            raise InvalidUsage("Wrong password or user does not exist!", status_code=403, enum="LOGIN_ERROR")

    # Return auth token
    auth_token = user.get_auth_token()
    response = {
        'auth_token': auth_token,
        'username': user.username,
        'email': user.email,
    }
    return flask.make_response(jsonify(response), 200)


# ---------------- OLD ----------------
import app.user.controllers as controllers


@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
def user_delete(userid):
    # THIS IS NOT USED AND IT DOESN'T WORK
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    if id != userid:
        raise InvalidUsage("User ids don't match", status_code=401, enum="UNAUTHORIZED")
    controllers.delete_user(engine, userid)
    return flask.make_response(jsonify({ 'message': 'OK'}), 200)


