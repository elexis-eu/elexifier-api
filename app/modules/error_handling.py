from flask import jsonify
from app import app


class InvalidUsage(Exception):
    status_code = 400
    enum = "ERROR"

    def __init__(self, message, status_code=None, enum=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if enum is not None:
            self.enum = enum

    def to_dict(self):
        rv = dict()
        rv['message'] = self.message
        rv['status_code'] = self.status_code
        rv['enum'] = self.enum
        return rv


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response