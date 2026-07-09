"""
dev1_research/logo.py
Builds and validates a company logo URL via Hunter.io's free logo API
(https://logos.hunter.io/{domain}) — no API key required.
"""

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

HUNTER_LOGO_BASE = "https://logos.hunter.io"
TIMEOUT_SECONDS = 5


def _domain_from_url(website_url: str) -> str | None:
    if not website_url:
        return None
    domain = urlparse(website_url).netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain or None


def get_logo_url(website_url: str) -> str | None:
    """Returns a validated Hunter.io logo URL, or None if the domain
    can't be resolved or Hunter doesn't have a logo for it. Does a HEAD
    request (not a full download) — PPT generation downloads the bytes
    later when it actually builds the slide."""
    domain = _domain_from_url(website_url)
    if not domain:
        return None

    candidate = f"{HUNTER_LOGO_BASE}/{domain}"

    try:
        resp = requests.head(candidate, timeout=TIMEOUT_SECONDS, allow_redirects=True)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return candidate
        logger.info(f"No logo available for {domain} (status={resp.status_code})")
    except requests.RequestException as e:
        logger.warning(f"Logo check failed for {domain}: {e}")

    return None