"""Domain canonicalization and dedup keys. Stdlib only (no public-suffix list).

Known limitation: the registrable-domain logic uses a small built-in set of multi-part
suffixes and shared-hosting suffixes. It is adequate for a US-focused pilot, not general.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au", "co.nz", "co.in",
    "com.br", "com.mx", "co.za", "co.jp", "com.sg", "com.cn",
}
# Many unrelated tenants share these; the tenant label is part of the identity.
SHARED_HOSTING_SUFFIXES = {
    "github.io", "gitlab.io", "vercel.app", "netlify.app", "herokuapp.com", "pages.dev",
    "web.app", "firebaseapp.com", "wixsite.com", "squarespace.com", "webflow.io",
    "carrd.co", "framer.website", "framer.app", "notion.site", "wordpress.com",
    "blogspot.com", "onrender.com", "fly.dev", "azurewebsites.net", "appspot.com",
}
# Not a company's own first-party site: directories, socials, marketplaces, reference sites.
NON_FIRST_PARTY_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "github.com", "clutch.co", "goodfirms.co", "upwork.com", "fiverr.com", "crunchbase.com",
    "glassdoor.com", "indeed.com", "yelp.com", "wikipedia.org", "wikidata.org",
    "openstreetmap.org", "bbb.org", "designrush.com", "themanifest.com", "sortlist.com",
    "g2.com", "capterra.com", "dribbble.com", "behance.net", "medium.com", "reddit.com",
    "google.com", "tiktok.com", "pinterest.com", "angel.co", "wellfound.com",
    "builtin.com", "zoominfo.com", "dnb.com", "apollo.io", "hunter.io",
}
_LEGAL_SUFFIX_TOKENS = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "gmbh", "pllc", "lp",
}


def registrable_domain(host: str) -> str | None:
    host = (host or "").strip().strip(".").lower()
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if "." not in host:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    for suffix in SHARED_HOSTING_SUFFIXES:
        if host == suffix:
            return None
        if host.endswith("." + suffix):
            tenant = host[: -(len(suffix) + 1)].split(".")[-1]
            return f"{tenant}.{suffix}"
    labels = host.split(".")
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def canonical_domain(url_or_host: str) -> str | None:
    s = (url_or_host or "").strip()
    if not s:
        return None
    if "://" not in s:
        s = "//" + s
    try:
        host = urlsplit(s).hostname
    except ValueError:
        return None
    return registrable_domain(host or "")


def is_first_party_candidate(domain: str | None) -> bool:
    return bool(domain) and domain not in NON_FIRST_PARTY_DOMAINS


def normalize_name(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    tokens = [t for t in tokens if t not in _LEGAL_SUFFIX_TOKENS]
    return " ".join(tokens)
