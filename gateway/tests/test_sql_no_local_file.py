"""A database never gets a file from this machine by asking for one.

A MySQL server can answer any statement with "send me this file", and aiomysql 0.2.0 sends it: local_infile=False only stops
the client offering the feature, and the reply is never checked. Whoever connects a database names its server, so a server
of their own would get anything this process can read, its environment included. Run against the real driver, with a stub
server on loopback asking for a canary file. On the unfixed code the stub receives the canary.
"""
import asyncio
import os
import pathlib
import socket
import struct
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
pytest.importorskip("aiomysql")
import sql_plane  # noqa: E402

CANARY = b"canary-file-contents-0123456789"


def _packet(seq: int, payload: bytes) -> bytes:
    return struct.pack("<I", len(payload))[:3] + bytes([seq]) + payload


OK = b"\x00\x00\x00\x02\x00\x00\x00"


class _AsksForAFile:
    """Enough of a MySQL server: greets, accepts any login, says OK to SET, and answers anything else by asking for a file."""

    def __init__(self, path: str):
        self.path, self.received, self.asked = path.encode(), b"", 0
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _read(self, c):
        head = b""
        while len(head) < 4:
            d = c.recv(4 - len(head))
            if not d:
                return None, None
            head += d
        n = int.from_bytes(head[:3], "little"); body = b""
        while len(body) < n:
            d = c.recv(n - len(body))
            if not d:
                return None, None
            body += d
        return head[3], body

    def _serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        try:
            caps = 0xF7FF | (0x8008 << 16)          # protocol 4.1, secure connection, plugin auth
            hello = (b"\x0a8.0.0\x00" + struct.pack("<I", 7) + b"abcdefgh\x00" + struct.pack("<H", caps & 0xFFFF)
                     + b"\x21\x02\x00" + struct.pack("<H", caps >> 16) + b"\x15" + b"\x00" * 10
                     + b"ijklmnopqrst\x00" + b"mysql_native_password\x00")
            c.sendall(_packet(0, hello))
            self._read(c)
            c.sendall(_packet(2, OK))
            while True:
                seq, body = self._read(c)
                if body is None:
                    return
                sql = body[1:].lstrip().upper()
                if body[:1] != b"\x03" or sql.startswith(b"SET") or sql.startswith(b"START") or sql.startswith(b"ROLLBACK"):
                    c.sendall(_packet(1, OK))
                    continue
                self.asked += 1
                c.sendall(_packet(1, b"\xfb" + self.path))
                while True:                              # what the client sends for that file, up to an empty packet
                    s, part = self._read(c)
                    if not part:
                        break
                    self.received += part
                c.sendall(_packet(s + 1 if s is not None else 3, OK))
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self.sock.close()


@pytest.fixture
def stub():
    fd, path = tempfile.mkstemp(prefix="hr-canary-")
    os.write(fd, CANARY); os.close(fd)
    s = _AsksForAFile(path)
    yield s
    s.close(); os.unlink(path)


def _dsn(s):
    return f"mysql://u:p@127.0.0.1:{s.port}/db"


def _settle():
    """Long enough for bytes already on the socket to reach the stub's thread."""
    import time
    time.sleep(0.3)


@pytest.mark.parametrize("call", ["query", "introspect"])
def test_a_server_asking_for_a_file_gets_nothing(stub, call):
    async def go():
        if call == "query":
            return await sql_plane.run_query("mysql", _dsn(stub), "SELECT 1", timeout=5.0)
        return await sql_plane.introspect("mysql", _dsn(stub), sample_rows=0, timeout=5.0)
    try:
        asyncio.run(go())
    except Exception:  # noqa: BLE001  (the turn's error is the next test's business; here only the bytes matter)
        pass
    _settle()
    assert stub.asked >= 1, "the stub never got to ask: this test proved nothing"
    assert CANARY not in stub.received, "the file went to the server"
    assert stub.received == b""


def test_the_caller_is_told_why(stub):
    with pytest.raises(sql_plane.SqlError) as e:
        asyncio.run(sql_plane.run_query("mysql", _dsn(stub), "SELECT 1", timeout=5.0))
    assert "local file" in str(e.value)
    assert stub.path.decode() not in str(e.value)


def test_the_refusal_is_on_the_driver_method_it_replaces():
    """A driver upgrade that renames the method would leave this silently off; the stub tests above would then fail too."""
    from aiomysql.connection import MySQLResult
    assert MySQLResult._read_load_local_packet.__module__ == sql_plane.__name__
