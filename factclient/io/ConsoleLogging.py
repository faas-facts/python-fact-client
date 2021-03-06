from datetime import datetime


# simple console logging module
class ConsoleLogging:
    connected = True

    def connect(self, env):
        return

    def send(self, message, trace):
        print("[{}] [{}] {}".format(datetime.now().timestamp() * 1000, message, trace))
