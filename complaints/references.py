"""Shared encoding contract for anonymous issuance and future B13 lookup."""

import hashlib
import re


def hash_reference(reference):
    """Return the SHA-256 digest of one canonical 32-character secret reference.

    Issuance supplies secrets.token_hex(16). A lookup caller must turn ValueError
    into its generic no-match response without logging the raw reference.
    """
    if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{32}", reference):
        raise ValueError("A reference must contain exactly 32 lowercase hexadecimal characters.")
    return hashlib.sha256(reference.encode("ascii")).hexdigest()
