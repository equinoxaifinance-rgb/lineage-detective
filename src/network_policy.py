"""Shared outbound-network policy for judge-hosted Lineage Detective paths."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


def _blocked_address(raw: str) -> bool:
    address = ipaddress.ip_address(raw)
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_network_url(
    url: str,
    *,
    allow_private: bool,
    label: str = "Network URL",
) -> str:
    """Validate scheme, authority, port, and every current DNS answer.

    Hosted mode accepts only public HTTPS destinations. Local mode deliberately permits HTTP
    and private addresses so a developer can use the official DataHub quickstart.
    """
    value = str(url or "").strip()
    parsed = urlsplit(value)
    schemes = {"http", "https"} if allow_private else {"https"}
    if parsed.scheme.lower() not in schemes:
        raise ValueError(f"{label} must use {'HTTP or HTTPS' if allow_private else 'HTTPS'}")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain embedded credentials")
    host = parsed.hostname
    if not host:
        raise ValueError(f"{label} must contain a hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port") from exc
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if not allow_private and effective_port != 443:
        raise ValueError(f"{label} must use the standard HTTPS port in hosted mode")
    try:
        answers = {
            item[4][0]
            for item in socket.getaddrinfo(host, effective_port, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ConnectionError(f"{label} hostname could not be resolved: {host}") from exc
    if not answers:
        raise ConnectionError(f"{label} hostname returned no network addresses: {host}")
    if not allow_private and any(_blocked_address(raw) for raw in answers):
        raise ValueError(f"{label} cannot resolve to a private or local network address")
    # Remove fragments because they never belong in an API request.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "", parsed.query, ""))


def validate_resolution(url: str, *, allow_private: bool, label: str = "Network URL") -> None:
    """Recheck DNS immediately before a request to reduce rebinding/TOCTOU exposure."""
    validate_network_url(url, allow_private=allow_private, label=label)
