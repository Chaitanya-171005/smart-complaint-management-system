"""Read the source only at the trusted ingress boundary, before privacy scrubbing."""

import ipaddress

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .tracking_limits import TrackingUnavailable


def trusted_proxy_networks():
    entries = getattr(settings, "ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS", [])
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ValueError("Missing trusted proxy configuration")
    networks = tuple(ipaddress.ip_network(value, strict=True) for value in entries)
    if any(network.prefixlen == 0 for network in networks):
        raise ValueError("Unrestricted proxy trust is not permitted")
    return networks


def tracking_source_configured():
    if getattr(settings, "SCMS_HTTPS_MODE", "") == "direct":
        return True
    if getattr(settings, "SCMS_HTTPS_MODE", "") != "proxy":
        return False
    try:
        return bool(trusted_proxy_networks())
    except (TypeError, ValueError):
        return False


@sensitive_variables()
def tracking_source(request):
    """Proxy mode requires one overwritten X-Real-IP from an allowlisted peer.

    Never trust X-Forwarded-For chains. Direct mode ignores all client forwarding
    headers. Return the source only to the limiter; do not attach it to request
    or complaint data. NAT users still share their observed address allowance.
    """
    try:
        peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        if getattr(peer, "ipv4_mapped", None):
            peer = peer.ipv4_mapped
        if settings.SCMS_HTTPS_MODE == "direct":
            return str(peer)
        if settings.SCMS_HTTPS_MODE != "proxy" or not any(
            peer in network for network in trusted_proxy_networks()
        ):
            raise ValueError
        source = request.META.get("HTTP_X_REAL_IP", "")
        # A single literal address only: no chains, zone IDs, ports or names.
        if not isinstance(source, str) or "%" in source:
            raise ValueError
        return str(ipaddress.ip_address(source))
    except (TypeError, ValueError):
        raise TrackingUnavailable("Reference tracking is temporarily unavailable.") from None
