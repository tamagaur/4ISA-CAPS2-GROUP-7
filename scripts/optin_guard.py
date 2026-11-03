"""
scripts/optin_guard.py - the opt-in tests' fence: nothing but the throwaway server on 127.0.0.1:55432 (2026-11-03).

    python -m scripts.optin_guard MODULE ARGS...     run a module (pytest, scripts.fill_missing, ...) inside the fence

Three layers, so that one mistake is not enough to reach live:
  1. scripts/optin_run.child_env names only the throwaway database and blanks every other value the repo's .env holds.
  2. install() replaces psycopg2.connect (libpq opens its own socket, which layer 3 cannot see) and socket.socket.connect
     (SMTP, HTTP, anything else in Python), and refuses any other destination.
  3. require_throwaway() is called by the opt-in tests themselves, so setting FILLS_SCRATCH_SCHEMA or ROLLOVER_SCRATCH by hand
     with the repo's .env fails instead of cloning live.

A refused attempt is written to the file named by OPTIN_GUARD_LOG, host and port only, never a password: code under test may
catch the exception, and the run must still fail if anything tried. scripts/optin_run.py checks that file.
"""
from __future__ import annotations

import os
import runpy
import socket
import sys
from urllib.parse import urlparse

HOSTS = {"127.0.0.1", "localhost"}
PORT = 55432
LOG_VAR = "OPTIN_GUARD_LOG"


class RefusedConnection(RuntimeError):
    """Something tried to leave the throwaway server."""


def _refuse(host, port, how: str) -> None:
    line = f"{how}: {host}:{port}"
    path = os.environ.get(LOG_VAR)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    raise RefusedConnection(f"REFUSED by scripts/optin_guard.py, only 127.0.0.1:{PORT} is allowed here. {line}")


def require_throwaway(url: str) -> None:
    u = urlparse(url or "")
    if u.hostname not in HOSTS or u.port != PORT:
        _refuse(u.hostname, u.port, "database url")


def _guard_psycopg2() -> None:
    import psycopg2
    from psycopg2.extensions import parse_dsn
    real = psycopg2.connect

    def connect(dsn=None, *args, **kwargs):
        target = {**(parse_dsn(dsn) if dsn else {}), **kwargs}
        host, port = target.get("host"), target.get("port")
        if host not in HOSTS or str(port) != str(PORT):
            _refuse(host, port, "psycopg2.connect")
        return real(dsn, *args, **kwargs)

    psycopg2.connect = connect


def _guard_sockets() -> None:
    real = socket.socket.connect

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host, port = address[0], address[1]
            if host not in HOSTS and host != "::1":
                _refuse(host, port, "socket")
        return real(self, address)

    socket.socket.connect = connect


def install() -> None:
    _guard_psycopg2()
    _guard_sockets()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    install()
    module = sys.argv[1]
    sys.argv = [module, *sys.argv[2:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
