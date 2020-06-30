import time


def print_log(name, message):
    ts = time.gmtime()
    ts = time.strftime("%Y-%m-%d %H:%M:%S", ts)
    print('[{0}][{1}]: {2}'.format(ts, name, message))
