"""Live telemetry network client, URL validation, and snapshot cache manager.

Enforces SSRF prevention (host whitelist, port restriction, userinfo rejection),
cumulative monotonic streaming deadlines, size limits, credential redaction,
and atomic cache writes with TTL support.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ALLOWED_HOSTS = frozenset({"celestrak.org", "www.space-track.org", "api.n2yo.com"})
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT_S = 10.0
CUMULATIVE_TIMEOUT_S = 30.0

_SECRET_REGEX = re.compile(
    r"(?i)(api[_-]?key|password|token|secret|identity)=([^&]+)"
)


def validate_request_url(url: str) -> None:
    """Pre-flight security validation for all outbound HTTP requests."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"SSRF Prevention: Refusing insecure scheme '{parsed.scheme}'")
    if parsed.username or parsed.password:
        raise ValueError("SSRF Prevention: Userinfo in URL is strictly forbidden")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"SSRF Prevention: Host '{host}' not in ALLOWED_HOSTS")
    if parsed.port not in (None, 443):
        raise ValueError(f"SSRF Prevention: Non-standard HTTPS port {parsed.port} forbidden")


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Hardened redirect handler enforcing HTTPS, host allowlist, and userinfo checks."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_request_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sanitize_url(url: str) -> str:
    """Redacts credentials from query strings and strips userinfo for safe logging."""
    redacted = _SECRET_REGEX.sub(r"\1=[REDACTED]", url)
    parsed = urllib.parse.urlparse(redacted)
    if parsed.username or parsed.password:
        host_part = parsed.hostname or ""
        if parsed.port:
            host_part = f"{host_part}:{parsed.port}"
        redacted = urllib.parse.urlunparse(
            (parsed.scheme, host_part, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
    return redacted


def download_stream(
    url: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cumulative_timeout_s: float = CUMULATIVE_TIMEOUT_S,
) -> bytes:
    """Secure streaming download with cumulative deadline and size cap."""
    validate_request_url(url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CubeSatLiveImport/1.0", "Accept-Encoding": "identity"},
    )
    opener = urllib.request.build_opener(StrictRedirectHandler())
    deadline = time.monotonic() + cumulative_timeout_s

    try:
        with opener.open(req, timeout=timeout_s) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_PAYLOAD_BYTES:
                raise ValueError(f"Payload size {cl} exceeds limit of {MAX_PAYLOAD_BYTES} bytes")
            chunks = []
            total = 0
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Cumulative response read timeout of {cumulative_timeout_s}s exceeded"
                    )
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PAYLOAD_BYTES:
                    raise ValueError(f"Response stream exceeded {MAX_PAYLOAD_BYTES} bytes cap")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"HTTP request failed: {sanitize_url(str(err))}") from None
    except urllib.error.URLError as err:
        raise RuntimeError(f"Network transport error: {sanitize_url(str(err))}") from None


class CacheManager:
    """Manages snapshot disk cache in data/celestrak/ with atomic updates."""

    def __init__(self, cache_dir: Path | str, ttl_s: int = 86400):
        self.cache_dir = Path(cache_dir)
        self.ttl_s = ttl_s

    def get_cache_path(self, provider: str, sanitized_query: str) -> Path:
        key = hashlib.sha256(sanitized_query.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{provider}_{key}.json"

    def is_valid(self, path: Path) -> bool:
        if not path.is_file() or path.is_symlink():
            return False
        return (time.time() - os.path.getmtime(path)) < self.ttl_s

    def read(self, path: Path) -> tuple[list[dict], str]:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Cache file is missing or invalid symlink: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "records" in raw:
            ft = raw.get("fetch_time_utc") or datetime.fromtimestamp(
                os.path.getmtime(path), tz=UTC
            ).isoformat()
            return raw["records"], ft
        recs = [raw] if isinstance(raw, dict) else raw
        meta_p = path.with_suffix(".meta.json")
        ft = None
        if meta_p.is_file() and not meta_p.is_symlink():
            try:
                ft = json.loads(meta_p.read_text(encoding="utf-8")).get("fetch_time_utc")
            except Exception:
                pass
        if not ft:
            ft = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat()
        return recs, ft

    def write_atomic(
        self, path: Path, records: list[dict], fetch_time_utc: str | None = None
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".tmp_{os.getpid()}_{path.stem}"
        ft = fetch_time_utc or datetime.now(UTC).isoformat()
        payload = {"fetch_time_utc": ft, "records": records}
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()


def build_celestrak_url(params: dict[str, str]) -> str:
    """Builds a sanitized CelesTrak GP query URL."""
    return f"https://celestrak.org/NORAD/elements/gp.php?{urllib.parse.urlencode(params)}"


def build_spacetrack_login_data(user: str, password: str, query_url: str) -> bytes:
    """Builds form-encoded login payload for Space-Track."""
    return urllib.parse.urlencode(
        {"identity": user, "password": password, "query": query_url}
    ).encode("utf-8")


def build_n2yo_url(norad_id: int, api_key: str) -> str:
    """Builds N2YO REST query URL."""
    return f"https://api.n2yo.com/rest/v1/satellite/tle/{norad_id}&apiKey={api_key}"
