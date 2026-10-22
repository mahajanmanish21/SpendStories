"""Where statement passwords are kept.

On a Mac they go in your login Keychain (encrypted by macOS, unlocked when you log in),
under the service name "SpendStories". SpendStories itself only keeps a list of the
*labels* you chose (e.g. "hdfc card"), never the passwords.

Elsewhere, or when SPENDSTORIES_PASSWORD_STORE=file, they go in passwords.toml in your
library folder, readable only by you. Passwords are never printed or logged, and never
stored in the transactions database.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

SERVICE = "SpendStories"


class KeychainStore:
    name = "macOS Keychain"

    def __init__(self, home: Path):
        self.index = home / "password-labels.txt"

    @staticmethod
    def available() -> bool:
        return sys.platform == "darwin" and shutil.which("security") is not None

    def labels(self) -> list[str]:
        if not self.index.exists():
            return []
        return [l for l in self.index.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _write_index(self, labels: list[str]) -> None:
        self.index.write_text("".join(f"{l}\n" for l in labels), encoding="utf-8")

    def get(self, label: str) -> str | None:
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", label, "-w"],
                           capture_output=True, text=True)
        return r.stdout.rstrip("\n") if r.returncode == 0 else None

    def set(self, label: str, password: str) -> None:
        # Sent through `security -i` on stdin, so the password never shows up in the process list.
        q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        cmd = f"add-generic-password -U -s {q(SERVICE)} -a {q(label)} -l {q('SpendStories: ' + label)} -w {q(password)}\n"
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise RuntimeError("couldn't save to the Keychain: " + (r.stderr or "").strip())
        if label not in self.labels():
            self._write_index(self.labels() + [label])

    def remove(self, label: str) -> bool:
        r = subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", label],
                           capture_output=True, text=True)
        self._write_index([l for l in self.labels() if l != label])
        return r.returncode == 0


class FileStore:
    name = "passwords.toml (only readable by you)"

    def __init__(self, home: Path):
        self.path = home / "passwords.toml"

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        with open(self.path, "rb") as f:
            return {str(k): str(v) for k, v in (tomllib.load(f).get("passwords") or {}).items()}

    def _write(self, data: dict[str, str]) -> None:
        q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        body = "# Statement passwords for SpendStories. Keep this file private.\n[passwords]\n" + \
               "".join(f"{q(k)} = {q(v)}\n" for k, v in data.items())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(self.path, 0o600)

    def labels(self) -> list[str]:
        return list(self._read())

    def get(self, label: str) -> str | None:
        return self._read().get(label)

    def set(self, label: str, password: str) -> None:
        data = self._read()
        data[label] = password
        self._write(data)

    def remove(self, label: str) -> bool:
        data = self._read()
        found = data.pop(label, None) is not None
        self._write(data)
        return found


def store_for(home: Path):
    if os.environ.get("SPENDSTORIES_PASSWORD_STORE") != "file" and KeychainStore.available():
        return KeychainStore(home)
    return FileStore(home)


def saved_passwords(home: Path, extra: list[str] | None = None) -> list[tuple[str, str]]:
    """Every password we know, as (label, password), for trying on a locked file."""
    store = store_for(home)
    out = []
    for label in store.labels():
        pw = store.get(label)
        if pw:
            out.append((label, pw))
    for i, pw in enumerate(extra or [], start=1):
        out.append((f"config #{i}", pw))
    return out


def guess_label(filename: str) -> str:
    """A friendly default label from a statement's file name: 'HDFC_CC_Oct26.pdf' -> 'hdfc'."""
    import re

    words = [w for w in re.split(r"[^a-z]+", Path(filename).stem.lower()) if len(w) > 1]
    skip = {"statement", "stmt", "estatement", "account", "acct", "card", "credit", "debit", "cc", "for",
            "the", "of", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
    words = [w for w in words if w not in skip and set(w) != {"x"}]   # "XX1234" is a masked number
    return words[0] if words else "statements"
