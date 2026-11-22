"""Universal company-fact vocabulary (Issue #5).

ARCHITECTURE (see docs/ICP-FOUNDATION.md)
  facts      what the company's own pages STATE, with provenance and a verbatim excerpt. Extraction
             (vm1.evidence) reads this vocabulary only. It never sees an ICP policy, so the same pages
             always yield the same evidence no matter which customer profile is being evaluated.
  policy     which of those facts matter to ONE customer profile, and how much (vm1.policy).
  engine     deterministic qualification of facts under a policy (vm1.score).

This module is the single registry of claim types. A policy may only reference claim types listed here,
which is how a typo in a policy file is caught at load time instead of silently scoring nothing.

Adding a fact: add the claim type to CLAIM_TYPES, add its detector table below (phrase patterns) or an
extractor in vm1.evidence, and add a test. Policies then reference it by name; no engine change.

Nothing in here is an ICP decision. A phrase table says "this wording is a storefront signal", never
"storefront signals make a lead good".
"""

from __future__ import annotations

import re

# Offered/mentioned capability tags. ``service:<tag>`` is emitted only where the company offers the thing
# (see evidence._offering); the same keyword elsewhere is recorded as ``mention:<tag>`` and earns nothing.
SERVICE_TAGS = (
    "react", "nextjs", "typescript", "frontend", "web_app", "custom_software",      # software development
    "home_services", "healthcare_practice", "professional_services",                  # local/professional services
)

CLAIM_TYPES: dict[str, str] = {
    # identity: what the company says it IS
    "entity_type:studio_or_agency": "self-referential software/web/digital studio or agency wording",
    "entity_type:client_services": "says it builds things for clients (no studio/agency noun)",
    "entity_type:consulting_engagements": "firm refers to its own consulting/client engagements (weak)",
    "entity_type:marketing_agency": "self-referential marketing/advertising/growth agency wording",
    "entity_type:ai_automation_consultancy": "self-referential AI/automation agency or consultancy wording",
    # distinct-signal families: each evidence item's value is one category; policies count distinct categories
    "company_type:saas_vendor_signal": "product-vendor wording (trial, demo, account, pricing, docs, platform, scale)",
    "company_type:enterprise_signal": "listed/large-corporation wording",
    "company_type:local_service_signal": "local service-business wording (estimates, service area, licensed, ...)",
    "company_type:storefront_signal": "online-store wording (add to cart, free shipping, returns, ...)",
    # capabilities / offered services
    **{f"service:{t}": f"company offers {t} (offering context verified)" for t in SERVICE_TAGS},
    **{f"mention:{t}": f"keyword for {t} WITHOUT offering context (weight 0)" for t in SERVICE_TAGS},
    "capability:ecommerce_platform": "first-party 'powered by / built on' a named ecommerce platform",
    "capability:email_capture": "first-party newsletter/email-capture offer",
    "capability:loyalty_or_subscription": "first-party rewards, loyalty or subscription offer",
    "capability:customer_intake": "first-party scheduling/booking/quote-request wording",
    # location and size
    "location:us": "US address/location statement or dataset record",
    "location:india_hq": "explicit first-party India headquarters or base",
    "location:non_us": "non-US place or postcode statement (detection is partial)",
    "size:employees": "explicit self-referential headcount (unknown when conflicting)",
    # negatives and informational signals
    "negative:staffing_recruiting": "homepage describes a staffing/recruiting business",
    "negative:staffing_mention": "staffing/recruiting wording on a secondary page",
    "negative:staff_augmentation": "staff-augmentation / hire-developers wording",
    "negative:global_consultancy": "global consultancy / systems-integrator wording",
    "signal:client_work": "client-work/portfolio wording beyond a bare label (NOT purchase intent)",
    "signal:hiring_info_only": "hiring wording; recorded, weight 0 (NOT purchase intent)",
}

# ---- phrase tables for the newer fact families (compiled once; matched by vm1.evidence) ------------------------
# Format matches evidence.VENDOR_SIGNALS: category -> (pattern, max block length). Short maxima keep matches to
# labels/CTAs/short statements, not paragraphs of prose that merely discuss the topic.
LOCAL_SERVICE_SIGNALS: dict[str, tuple[re.Pattern, int]] = {
    "free_estimate": (re.compile(r"\bfree (?:estimates?|quotes?|in-home (?:estimates?|consultations?))\b", re.I), 200),
    "emergency_service": (re.compile(r"\b(?:24/7|24-hour|same[- ]day)\b[^.]{0,30}\b(?:emergency|service|repairs?)\b|"
                                     r"\bemergency (?:service|repairs?)\b", re.I), 200),
    "service_area": (re.compile(r"\bserving\b[^.]{0,60}\b(?:surrounding|nearby|neighboring) "
                                r"(?:areas?|communities|cities|towns|counties)\b|\bservice areas?\b", re.I), 200),
    "licensed_insured": (re.compile(r"\blicensed(?:,)?(?: and|,| &)?(?: bonded(?:,)?(?: and| &)?)? insured\b", re.I), 200),
    "family_owned": (re.compile(r"\b(?:family|locally|veteran)[- ]owned(?: and operated)?\b", re.I), 200),
}
STOREFRONT_SIGNALS: dict[str, tuple[re.Pattern, int]] = {
    "add_to_cart": (re.compile(r"\badd to (?:cart|bag|basket)\b", re.I), 120),
    "shop_cta": (re.compile(r"\bshop (?:now|all|the collection|best sellers|new arrivals)\b|\bnew arrivals\b|"
                            r"\bbest sellers\b", re.I), 120),
    "free_shipping": (re.compile(r"\bfree (?:shipping|delivery)\b|\bships? free\b", re.I), 200),
    "returns_policy": (re.compile(r"\b(?:\d+-day|free|easy|hassle-free) returns?\b|\breturns? (?:&|and) exchanges?\b", re.I), 200),
    "cart_checkout": (re.compile(r"^(?:cart|view cart|my cart|your cart(?: \(\d+\))?|checkout|bag)$", re.I), 40),
}
ECOMMERCE_PLATFORM = {
    "ecommerce_platform": (re.compile(r"\b(?:powered|built) (?:by|on) (?:shopify|woocommerce|bigcommerce|magento)\b", re.I), 120),
}
EMAIL_CAPTURE = {
    "email_capture": (re.compile(r"\b(?:join|subscribe to|sign up for) our (?:newsletter|email list|emails|mailing list)\b|"
                                 r"\bget \d+% off your first order\b|\bunlock \d+% off\b", re.I), 160),
}
LOYALTY_SUBSCRIPTION = {
    "loyalty_or_subscription": (re.compile(r"\b(?:rewards|loyalty) (?:program|club|points)\b|\bsubscribe (?:&|and) save\b|"
                                           r"\bmembership program\b", re.I), 160),
}
CUSTOMER_INTAKE = {
    "customer_intake": (re.compile(r"\b(?:schedule|book|request)(?: an?| your| online)? "
                                   r"(?:service|appointment|visit|estimate|quote)\b|"
                                   r"\bcall (?:us )?(?:today )?to (?:schedule|book)\b|\bonline booking\b", re.I), 160),
}
# Service lines a LOCAL/PROFESSIONAL service business offers. Whether a company "offers" one is decided by
# evidence._offering exactly as for any other capability (feature lists, docs, testimonials do not count).
SERVICE_LINE_PATTERNS: dict[str, list[re.Pattern]] = {
    "home_services": [re.compile(
        r"\b(?:hvac|heating (?:and|&) (?:cooling|air)|air conditioning|plumbing|plumbers?|electricians?|"
        r"electrical (?:services|repair|contractors?)|roofing|landscaping|lawn care|pest control|"
        r"(?:house |home )?cleaning services|janitorial|garage doors?|remodeling|handyman)\b", re.I)],
    "healthcare_practice": [re.compile(
        r"\b(?:dental (?:care|practice|office|services)|dentists?|orthodont\w+|chiropract\w+|veterinar\w+|"
        r"physical therapy|physiotherapy|optometr\w+|dermatolog\w+|medical practice|urgent care|med ?spa)\b", re.I)],
    "professional_services": [re.compile(
        r"\b(?:law firm|attorneys?|accounting (?:firm|services)|tax (?:preparation|services)|bookkeeping|"
        r"insurance agency|property management|real estate (?:agency|brokerage)|financial planning|"
        r"wealth management)\b", re.I)],
}
MARKETING_AGENCY_RE = re.compile(
    r"\b(?:(?:digital|growth|performance|e-?commerce|social media|content|seo|ppc|paid media|email|lifecycle|"
    r"brand(?:ing)?|creative|advertising|full[- ]service)\s+(?:marketing\s+)?(?:agency|firm|consultancy|studio)|"
    r"marketing\s+(?:agency|firm|consultancy))\b", re.I)
AI_CONSULTANCY_RE = re.compile(
    r"\b(?:ai|artificial intelligence|automation|workflow automation|ai automation|machine learning)\s+"
    r"(?:agency|consultancy|consulting (?:firm|company|practice)|studio)\b", re.I)
