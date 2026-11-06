"""Small helpers shared by the package scanner modules."""

import asyncio
from datetime import datetime
from urllib.parse import quote

from limescape_plugin_sdk import NodeInputError


class BronFout(Exception):
    """A public source (deps.dev, Packagist or OSV.dev) answered with a non-success status."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def seg(value, safe: str = "") -> str:
    """One URL path segment; `safe="/"` keeps slashes for multi-segment names."""
    return quote(str(value), safe=safe)


def json_van(response, bron: str):
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise NodeInputError(f"{bron} gaf geen geldige JSON terug") from exc


async def alle(coroutines):
    """Like asyncio.gather, but waits for every task before re-raising the first failure (no orphaned requests)."""
    resultaten = await asyncio.gather(*coroutines, return_exceptions=True)
    for resultaat in resultaten:
        if isinstance(resultaat, BaseException):
            raise resultaat
    return resultaten


def decodeer(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def datum_nl(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d-%m-%Y")
    except ValueError:
        return ""
