"""Одна проверка сайта: DNS, HTTP-ответ и срок действия TLS-сертификата."""

import socket
import ssl
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx


def cert_days_left(host: str, port: int, timeout: float) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), UTC)
    return (expires - datetime.now(UTC)).days


def check_url(url: str, timeout: float) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    result: dict[str, Any] = {
        "url": url,
        "ts": datetime.now(UTC),
        "up": False,
        "dns_ok": False,
        "status_code": None,
        "response_seconds": None,
        "cert_days_left": None,
        "error": None,
    }

    try:
        socket.getaddrinfo(host, None)
        result["dns_ok"] = True
    except socket.gaierror as exc:
        result["error"] = f"dns: {exc}"
        return result

    try:
        start = time.monotonic()
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        result["response_seconds"] = round(time.monotonic() - start, 3)
        result["status_code"] = response.status_code
        result["up"] = response.status_code < 400
    except httpx.HTTPError as exc:
        result["error"] = f"http: {exc.__class__.__name__}"

    if parsed.scheme == "https":
        try:
            result["cert_days_left"] = cert_days_left(host, parsed.port or 443, timeout)
        except (OSError, ssl.SSLError) as exc:
            result["error"] = result["error"] or f"tls: {exc.__class__.__name__}"

    return result
