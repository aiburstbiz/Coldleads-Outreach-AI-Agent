"""
dev1_research/email_finder.py

Reliable, deterministic company email extraction — runs a regex directly
over scraped website text (especially the contact/about pages), instead
of depending on external search (news_search.py) or Groq's judgment,
both of which can fail due to rate limits or simply miss it.

This exists because contact.email was coming back null far too often
in testing — this tool's whole purpose is cold outreach, so knowing
WHO to actually send the email to is not optional.

Usage:
    from dev1_research.email_finder import find_best_email
    email = find_best_email(scraped_site, company_domain="kfintech.com")
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}"
)

# Emails on generic hosting/tracking domains that are never a real
# company contact — filter these out even if regex matches them
JUNK_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "godaddy.com",
    "cloudflare.com", "google.com", "gstatic.com", "schema.org",
    "w3.org", "youremail.com",
}

# Prefixes that indicate a real, useful business contact (ranked best
# to still-acceptable) vs prefixes that are usually not what a
# salesperson wants to email (noreply, unsubscribe, etc.)
PREFERRED_PREFIXES = ["info", "contact", "sales", "hello", "support", "enquiry", "enquiries"]
JUNK_PREFIXES = ["noreply", "no-reply", "donotreply", "unsubscribe", "bounce", "mailer-daemon", "postmaster"]

# Page types (matching scraper.py's PAGE_TYPE_KEYWORDS) worth prioritizing,
# since an email found on the Contact page is far more trustworthy than
# one found buried in a blog post or terms-of-service page
PRIORITY_PAGE_TYPES = ["contact", "about", "home"]


def _domain_of_email(email: str) -> str:
    return email.split("@", 1)[1].lower()


def _is_junk_email(email: str, own_domain: str = "") -> bool:
    local_part = email.split("@", 1)[0].lower()
    domain = _domain_of_email(email)

    if domain in JUNK_DOMAINS:
        return True
    if any(local_part.startswith(p) for p in JUNK_PREFIXES):
        return True
    # Image/asset filenames that regex sometimes falsely matches
    # (e.g. "logo@2x.png" style patterns are rare but possible if a
    # filename slips into scraped text without proper filtering)
    if re.search(r"\.(png|jpg|jpeg|gif|svg|webp)$", email, re.IGNORECASE):
        return True
    return False


def _score_email(email: str, own_domain: str, page_type: str) -> int:
    """Higher score = more likely to be the right email to use for outreach."""
    local_part = email.split("@", 1)[0].lower()
    domain = _domain_of_email(email)
    score = 0

    # Strongest signal: email is on the company's own domain
    if own_domain and (domain == own_domain or domain.endswith("." + own_domain)):
        score += 20

    # Good signal: a business-appropriate prefix
    if any(local_part == p or local_part.startswith(p) for p in PREFERRED_PREFIXES):
        score += 10

    # Found on a high-trust page type
    if page_type in PRIORITY_PAGE_TYPES:
        score += PRIORITY_PAGE_TYPES.index(page_type) == 0 and 8 or 4

    return score


def find_best_email(scraped_site, own_domain: str = "") -> str | None:
    """
    Scan all successfully scraped pages for email addresses and return
    the single best candidate for cold outreach.

    Args:
        scraped_site: a ScrapedSite object (has .pages, each with
                       .page_type, .text, .success) OR the dict form
                       (ScrapedSite.to_dict()) — both are handled.
        own_domain:    the company's own domain (e.g. "kfintech.com"),
                        used to strongly prefer emails on that domain
                        over unrelated ones picked up incidentally.

    Returns:
        Best email address found, or None if nothing usable was found.
    """
    # Normalize input: accept both dataclass and dict forms
    if hasattr(scraped_site, "pages"):
        pages = scraped_site.pages
        get_type = lambda p: p.page_type
        get_text = lambda p: p.text
        get_success = lambda p: p.success
    else:
        pages = scraped_site.get("pages", []) if scraped_site else []
        get_type = lambda p: p.get("page_type", "")
        get_success = lambda p: p.get("success", False)
        get_text = lambda p: p.get("text", "")

    candidates: list[tuple[str, int]] = []
    seen_emails: set[str] = set()

    for page in pages:
        if not get_success(page):
            continue
        text = get_text(page) or ""
        page_type = get_type(page)

        for match in EMAIL_RE.finditer(text):
            email = match.group(0).lower().rstrip(".,;:")
            if email in seen_emails:
                continue
            if _is_junk_email(email, own_domain):
                continue
            seen_emails.add(email)
            score = _score_email(email, own_domain, page_type)
            candidates.append((email, score))

    if not candidates:
        logger.info("No usable email found across %d scraped pages", len(pages))
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_email, best_score = candidates[0]
    logger.info(
        "Best email found: %s (score=%d, %d total candidates)",
        best_email, best_score, len(candidates),
    )
    return best_email


if __name__ == "__main__":
    # Quick standalone test with fake scraped content
    class FakePage:
        def __init__(self, page_type, text, success=True):
            self.page_type = page_type
            self.text = text
            self.success = success

    class FakeSite:
        def __init__(self, pages):
            self.pages = pages

    test_site = FakeSite([
        FakePage("home", "Welcome to Acme. Follow us on social media."),
        FakePage("contact", "Reach us at info@acme.com or call us. Also noreply@acme.com for automated updates."),
        FakePage("blog", "Written by john.doe@personalblog.net, not related to Acme."),
    ])

    result = find_best_email(test_site, own_domain="acme.com")
    print(f"Best email: {result}")
    assert result == "info@acme.com", f"Expected info@acme.com, got {result}"
    print("Test passed.")