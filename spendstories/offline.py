"""Hard guarantee that SpendStories never talks to the network.

Nothing in SpendStories needs the network, but statements are sensitive, so
instead of relying on that we switch off outbound networking for the whole
process before any statement is read. Any attempt by this code or by a
third-party library to open a connection or resolve a hostname raises
``NetworkBlockedError`` instead.
"""

from __future__ import annotations

import socket


class NetworkBlockedError(RuntimeError):
    pass


_installed = False


def _blocked(*_args, **_kwargs):
    raise NetworkBlockedError(
        "SpendStories runs fully offline; a network connection was attempted and blocked."
    )


class _BlockedSocket(socket.socket):
    def connect(self, *args, **kwargs):  # noqa: D401
        if self.family == getattr(socket, "AF_UNIX", None):
            return super().connect(*args, **kwargs)
        _blocked()

    def connect_ex(self, *args, **kwargs):
        if self.family == getattr(socket, "AF_UNIX", None):
            return super().connect_ex(*args, **kwargs)
        _blocked()

    def sendto(self, *args, **kwargs):
        if self.family == getattr(socket, "AF_UNIX", None):
            return super().sendto(*args, **kwargs)
        _blocked()


def block_network() -> None:
    """Disable outbound network access for the current process (idempotent)."""
    global _installed
    if _installed:
        return
    socket.socket = _BlockedSocket  # type: ignore[misc]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]
    socket.gethostbyname = _blocked  # type: ignore[assignment]
    socket.gethostbyname_ex = _blocked  # type: ignore[assignment]
    _installed = True
