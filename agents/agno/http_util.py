"""Small HTTP fetch used by the research agents.

Python's CA bundle on this machine often fails TLS verification. Public
requests fall back to the operating-system trust store through curl.
"""
from __future__ import annotations

import subprocess
import urllib.request


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    headers = dict(headers or {})
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        reason = str(getattr(exc, "reason", exc))
        if "SSL" not in reason.upper() and "CERTIFICATE" not in reason.upper():
            raise
        command = ["curl.exe", "-fsSL", "--max-time", str(timeout)]
        for key, value in headers.items():
            command.extend(["-H", f"{key}: {value}"])
        command.append(url)
        completed = subprocess.run(command, check=True, capture_output=True)
        return completed.stdout
