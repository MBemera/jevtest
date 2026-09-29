"""JSON-lines client for the control server that runs inside the app process."""

import itertools
import json
import socket
import threading


class HostError(Exception):
    """The host answered but could not do what was asked."""

    def __init__(self, message, kind="harness", detail=None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail or {}


class HostConnectionLost(Exception):
    """The connection dropped: the app process has probably exited or crashed."""


class HostClient:
    def __init__(self, port, token, host="127.0.0.1"):
        self.address = (host, int(port))
        self.token = token
        self.sock = None
        self.stream = None
        self.ids = itertools.count(1)
        self.lock = threading.Lock()

    def connect(self, timeout=10.0):
        self.sock = socket.create_connection(self.address, timeout=timeout)
        self.stream = self.sock.makefile("rwb")

    def close(self):
        for item in (self.stream, self.sock):
            try:
                if item is not None:
                    item.close()
            except OSError:
                pass
        self.sock = self.stream = None

    def call(self, command, args=None, timeout=90.0):
        with self.lock:
            if self.sock is None:
                try:
                    self.connect()
                except OSError as error:
                    raise HostConnectionLost(str(error)) from None
            request_id = next(self.ids)
            payload = {"id": request_id, "token": self.token, "cmd": command, "args": args or {}}
            try:
                self.sock.settimeout(timeout)
                self.stream.write((json.dumps(payload) + "\n").encode("utf-8"))
                self.stream.flush()
                line = self.stream.readline()
            except (OSError, socket.timeout) as error:
                self.close()
                raise HostConnectionLost(f"{type(error).__name__}: {error}") from None
            if not line:
                self.close()
                raise HostConnectionLost("the app process closed the connection")
        response = json.loads(line.decode("utf-8"))
        if not response.get("ok"):
            raise HostError(response.get("error", "unknown error"), response.get("kind", "harness"), response)
        return response.get("result")
