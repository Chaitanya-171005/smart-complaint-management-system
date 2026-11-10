"""B13 shared, ephemeral rolling-window limits, separate from complaint data."""

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
import weakref
from functools import lru_cache
from urllib.parse import urlsplit

from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

LIMIT = 10
WINDOW = 600
EPOCH_KEY = "scms:b13:epoch"
VERIFICATION_TTL = 30
_verified_until = weakref.WeakKeyDictionary()
_verification_lock = threading.Lock()

# The entire prune/check/insert/expire operation is atomic across app workers.
# Entries contain only server time and an independent random attempt nonce.
SLIDING_WINDOW = """#!lua
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000000 + tonumber(t[2])
local window = tonumber(ARGV[1]) * 1000000
local epoch = redis.call('GET', KEYS[2])
if not epoch then
    redis.call('SET', KEYS[2], string.format('%.0f', now))
    return {-1, tonumber(ARGV[1])}
end
if now - tonumber(epoch) < window then
    return {-1, math.ceil((tonumber(epoch) + window - now) / 1000000)}
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(1, math.ceil((tonumber(first[2]) + window - now) / 1000000))}
end
if redis.call('ZADD', KEYS[1], 'NX', now, ARGV[3]) ~= 1 then
    return {-1, tonumber(ARGV[1])}
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
return {1, 0}
"""


class TrackingUnavailable(Exception):
    """A generic refusal: never include source, URL, credentials or Redis errors."""


def limiter_configured():
    url = getattr(settings, "ANONYMOUS_TRACKING_REDIS_URL", "")
    secret = getattr(settings, "ANONYMOUS_TRACKING_SOURCE_SECRET", "")
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme in {"redis", "rediss"} and parsed.hostname
            and not parsed.query and not parsed.fragment
            and isinstance(secret, str) and len(secret) >= 32
            and settings.ANONYMOUS_TRACKING_LIMITER_READY
        )
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def redis_client(url):
    # URL query overrides are refused above. Never retry a possibly executed
    # EVAL: an ambiguous timeout must fail closed, not consume another slot.
    return Redis.from_url(
        url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1,
        retry=Retry(NoBackoff(), 0), max_connections=20,
    )


def verify_ephemeral_backend(client):
    """Check operational safeguards before storing even a transient source key.

    A dedicated, non-replicated, memory-only Redis is required. Deployment must
    also forbid manual snapshots, FLUSH, MONITOR, tracing and host swap/dumps.
    """
    # Flagged Lua scripts (Redis 7+) refuse execution before any write at OOM.
    version = str(client.info("server").get("redis_version", "")).split(".")[0]
    if not version.isdecimal() or int(version) < 7:
        raise TrackingUnavailable
    expected = {
        "save": "", "appendonly": "no", "maxmemory-policy": "noeviction",
        "slowlog-log-slower-than": "-1", "notify-keyspace-events": "",
    }
    for name, value in expected.items():
        if client.config_get(name).get(name) != value:
            raise TrackingUnavailable
    if int(client.config_get("maxmemory").get("maxmemory", 0)) <= 0:
        raise TrackingUnavailable
    replication = client.info("replication")
    if replication.get("role") != "master" or replication.get("connected_slaves") != 0:
        raise TrackingUnavailable
    persistence = client.info("persistence")
    if (persistence.get("rdb_bgsave_in_progress") != 0 or persistence.get("aof_enabled") != 0
            or persistence.get("aof_rewrite_in_progress") != 0):
        raise TrackingUnavailable


def ensure_ephemeral_backend(client):
    """Cache only a successful attestation, for at most 30 monotonic seconds.

    This caches no source/credential data and grants no allowance. Epoch/Lua
    restart quarantine remains checked atomically on every attempt. Services
    denying CONFIG GET/INFO are unsupported; no unverified fallback is allowed.
    """
    with _verification_lock:
        now = time.monotonic()
        if now < _verified_until.get(client, 0):
            return
        _verified_until.pop(client, None)
        verify_ephemeral_backend(client)
        _verified_until[client] = now + VERIFICATION_TTL


def invalidate_backend(client):
    with _verification_lock:
        _verified_until.pop(client, None)


@sensitive_variables()
def consume_attempt(source):
    """Return (allowed, retry seconds); accept no reference/complaint argument.

    Only an HMAC of an IPv4 address or IPv6 /64 becomes a Redis key, for <=600s
    after its last allowed attempt. No source key is attached to request/model.
    """
    client = None
    try:
        if not limiter_configured():
            raise TrackingUnavailable
        address = ipaddress.ip_address(source)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if isinstance(address, ipaddress.IPv6Address):
            address = ipaddress.ip_network((address, 64), strict=False).network_address
        key = "scms:b13:source:" + hmac.new(
            settings.ANONYMOUS_TRACKING_SOURCE_SECRET.encode("utf-8"),
            address.packed, hashlib.sha256,
        ).hexdigest()
        client = redis_client(settings.ANONYMOUS_TRACKING_REDIS_URL)
        ensure_ephemeral_backend(client)
        # A non-identifying global epoch is initialized inside the same script.
        # After restart/lost state, refuse all lookups for a full window even
        # if Redis restarted between the configuration check and this EVAL.
        allowed, retry = client.eval(SLIDING_WINDOW, 2, key, EPOCH_KEY, WINDOW, LIMIT, secrets.token_hex(16))
        if allowed not in (0, 1) or not isinstance(retry, int) or not 0 <= retry <= WINDOW:
            raise TrackingUnavailable
        return bool(allowed), retry
    except TrackingUnavailable:
        # Expected refusal (including restart quarantine) does not invalidate a
        # successful configuration check. Lua still enforces it on every call.
        raise TrackingUnavailable("Reference tracking is temporarily unavailable.") from None
    except Exception:
        if client is not None:
            invalidate_backend(client)
        # Redis errors can include endpoints/credentials/key material. Neither
        # pass them to a response nor emit exception text to logs/APM.
        raise TrackingUnavailable("Reference tracking is temporarily unavailable.") from None
