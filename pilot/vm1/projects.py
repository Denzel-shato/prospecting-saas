"""Locate portfolio pages and short first-party evidence of a delivered client application."""

from __future__ import annotations

import re

from .htmlparse import PageData

_APPLICATION = re.compile(
    r"\b(?:web[- ](?:app(?:lication)?s?)|front[- ]?end (?:codebase|application|interface)|"
    r"(?:client |customer |self[- ]service |admin(?:istration)? )?portals?|dashboards?|"
    r"(?:business|multi[- ]user|custom|workflow|Rails|Django|React|Laravel|SaaS) (?:web )?applications?|"
    r"(?:scheduling|booking|reservation|workflow|work management|membership) (?:systems?|platforms?|software)|"
    r"web and mobile (?:no-code )?platforms?)\b", re.I)
_OTHER_VOICE = {"quote", "client", "nav", "footer", "aside"}
_OTHER_SECTION = re.compile(r"\b(?:testimonials?|what (?:our |the )?client[s]? sa(?:ys?|id)|"
                            r"related (?:work|projects?|stories)|(?:more|other) (?:projects?|case studies))\b", re.I)
_UNSUITABLE = re.compile(r'["“”]|\b(?:if|would|could|never|not|instead of|rather than|'
                         r'our (?:own |internal )?(?:product|platform|dashboard|portal)|'
                         r'in[- ]house (?:product|platform)|for (?:our own|our (?:team|staff|employees)|internal use)|proof of concept|prototype only)\b', re.I)
_CLIENT = re.compile(r"\b(?:(?:our|the) client\b|(?:our|the) customer (?:asked|engaged|hired) us\b)", re.I)
_DELIVERY = (r"(?:built|shipped|delivered|implemented|developed|created|engineered|replaced|"
             r"rebuilt|moderni[sz]ed|migrated|launched|refactored)")
_NAMED_CLIENT = re.compile(r"\bfor (?:the )?([A-Z][\w’'-]*(?: [A-Z][\w’'-]*){0,4})\b")
_REQUEST = re.compile(r"\b([A-Z][\w'-]*(?: [A-Z][\w'-]*){0,2})(?:['’]s [A-Z]+)? (?:turned to|engaged|hired)\b")
_AUDIENCE = re.compile(r"\b(?:teams?|businesses|customers?|clients?|professionals?|organizations?|"
                       r"startups?|companies|enterprises?|agencies|developers?|merchants?|everyone)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_OTHER_ACTOR = re.compile(r"\b(?:who|so (?:they|the client)|they (?:built|launched)|to (?:help|evaluate|use)|"
                          r"(?:use|adopt|access) our|branding|brand identity|logo|packaging)\b", re.I)

_COMMISSION = re.compile(
    r"\b(?:[Oo]ur (?:brief|task|challenge) was to (?:help|support) [A-Z][\w’'-]+|"
    r"[A-Z][\w’'-]*(?: [A-Z][\w’'-]*){0,4} (?:approached|hired|engaged) us|"
    r"[Ww]e (?:worked|partnered|collaborated) with [A-Z][\w’'-]*(?: [A-Z][\w’'-]*){0,3} "
    r"to (?:build|develop|deliver|replace))\b")
_RESULT = re.compile(r"\b(?:the result was|(?:we|our team|the team) (?:launched|shipped|delivered)|"
                     r"went live|first production deployment)\b", re.I)
_PRODUCTION = re.compile(r"\bour team\b.{0,65}\bfrom scratch\b.{0,95}\bdeploy(?:ed|ment) (?:in)?to production\b", re.I)
_WORKED_ON = re.compile(r"\bwe(?:['’]ve| have) (?:ever )?worked on\b", re.I)
_WEB_SERVICE = re.compile(r"\b(?:web (?:development|application development)|front[- ]?end development)\b", re.I)

# Published client case studies frequently describe an explicitly commissioned
# project as "We partnered with Client, a startup, to create a web application".
# The appositive is not itself evidence; require the same sentence to identify
# the client relationship, commissioned creation and an application artifact.
_PARTNERED_APP = re.compile(
    r"\b(?:we|our team) (?:partnered|collaborated|worked) with "
    r"(?P<client>(?-i:[A-Z])[\w’'-]*(?: (?-i:[A-Z])[\w’'-]*){0,3})"
    r"(?:, [^.!?]{0,90})? to (?:create|build|develop|deliver|launch)\b", re.I)

# Some genuine delivered client systems are described without a public client
# name because of NDA. Only accept this when the SAME case detail explicitly
# says the client's identity is confidential, and separately attributes a
# completed application deliverable to the studio.
_NDA_CLIENT = re.compile(
    r"\b(?:client|customer) (?:and (?:product|project) )?names? "
    r"(?:are|is) (?:kept )?confidential\b.{0,55}\bNDA\b"
    r"|\b(?:client|customer)(?:'s)? name (?:is|was) (?:withheld|confidential|"
    r"undisclosed)\b", re.I)


def project_terms(text: str) -> list[str]:
    return sorted({m.group().lower() for m in _APPLICATION.finditer(text)})


def _passages(page: PageData):
    for i, block in enumerate(page.blocks):
        if page.ctx_at(i) & _OTHER_VOICE or _OTHER_SECTION.search(page.section_at(i)):
            continue
        # A case study may use <article>. Quoted customer speech still has to stay out.
        if block.lstrip().startswith(('"', "“", "‘")):
            continue
        for sentence in _SENTENCE.split(block):
            if sentence and not _UNSUITABLE.search(sentence):
                yield i, sentence


def _excerpt(text: str, start: int, end: int) -> str:
    start = max(0, start)
    # Keep the matched relationship and artifact, trim spare words at the right edge.
    stop = min(len(text), start + 195, end + 45)
    if stop < len(text):
        space = text.rfind(" ", end, stop + 1)
        if space >= end:
            stop = space
    return text[start:stop].strip()


def _case_outcome(passages, seller):
    """Some studios document a client brief and a delivered result in adjacent, distinct passages."""
    for n, (i, scope) in enumerate(passages):
        commission = _COMMISSION.search(scope)
        if commission:
            for j, outcome in passages[n + 1:n + 17]:
                if not 0 < j - i <= 12:
                    continue
                app = _APPLICATION.search(outcome)
                result = _RESULT.search(outcome)
                if (app and result and not _OTHER_ACTOR.search(outcome)
                        and max(app.end(), result.end()) - min(app.start(), result.start()) <= 170):
                    return [_excerpt(scope, commission.start(), commission.end()),
                            _excerpt(outcome, min(app.start(), result.start()), max(app.end(), result.end()))]
                # On a named case, an attributed application and a production deployment
                # together support delivery. A brief or a list of features alone does not.
                built = _PRODUCTION.search(outcome)
                if built:
                    for k, product in passages[n:n + 20]:
                        artifact = _APPLICATION.search(product)
                        work = _WORKED_ON.search(product)
                        if i <= k <= j + 3 and artifact and work and work.end() <= 185:
                            return [_excerpt(product, 0, work.end()), _excerpt(outcome, built.start(), built.end())]
        if seller:
            help_client = re.search(r"\bhelped (?:the|our) client (?:moderni[sz]e|replace|build|launch)\b", scope, re.I)
            firm = seller.search(scope)
            if help_client and firm and firm.end() <= help_client.start() and help_client.start() - firm.end() < 3:
                app = re.search(r"\b(?:app|application)\b", scope[help_client.end():], re.I)
                if app and help_client.end() + app.end() - firm.start() <= 170:
                    for j, services in passages[max(0, n - 8):n + 9]:
                        service = _WEB_SERVICE.search(services)
                        if service and abs(j - i) <= 5:
                            return [_excerpt(scope, firm.start(), help_client.end() + app.end()),
                                    _excerpt(services, service.start(), service.end())]
    return []


def project_excerpts(page: PageData, kind: str, names: list[str]) -> list[str]:
    """Keep delivery and client attribution on one case. Index entries must stand on their own."""
    brand = "|".join(r"[-\s]+".join(re.escape(word) for word in re.split(r"[-\s]+", n)) for n in names if n)
    actor = r"we|our team" + ("|" + brand if brand else "")
    delivered = re.compile(rf"\b(?:{actor})(?:['’]ve| have)?\s+(?:designed and )?{_DELIVERY}\b", re.I)
    passages = list(_passages(page))
    nda_note = next((sentence for _, sentence in passages if
                     len(sentence) <= 240 and _NDA_CLIENT.search(sentence)), None)
    clients = {}
    for i, sentence in passages:
        link = _CLIENT.search(sentence)
        if link:
            clients[i] = _excerpt(sentence, link.start(), link.end() + 25)
        elif sentence.lower().rstrip(":") == "client" and i + 1 < len(page.blocks):
            value = page.blocks[i + 1]
            if (re.fullmatch(r"[A-Z][\w &.,'’()-]{1,85}", value)
                    and not page.ctx_at(i + 1) & _OTHER_VOICE):
                clients[i] = value
    if kind == "detail":
        for _, sentence in passages:
            partner = _PARTNERED_APP.search(sentence)
            if partner:
                app = _APPLICATION.search(sentence, partner.end())
                if (app and app.end() - partner.start() <= 185
                        and not _AUDIENCE.search(partner.group("client"))
                        and not _OTHER_ACTOR.search(sentence[partner.end():app.start()])):
                    return [_excerpt(sentence, partner.start(), app.end())]
    for i, sentence in passages:
        for action in delivered.finditer(sentence):
            app = _APPLICATION.search(sentence, action.end())
            if not app or app.end() - action.start() > 195 or _OTHER_ACTOR.search(sentence[action.end():app.start()]):
                continue
            proof = _excerpt(sentence, action.start(), app.end())
            named = _NAMED_CLIENT.search(sentence, app.end())
            if named and named.end() - action.start() <= 185:
                beneficiary = named[1].casefold()
                context = (page.title + " " + page.section_at(i)).casefold()
                if (beneficiary in context and not _AUDIENCE.search(beneficiary)
                        and beneficiary not in {n.casefold() for n in names}):
                    return [_excerpt(sentence, action.start(), named.end())]
            if kind == "detail":
                if _CLIENT.search(proof):
                    return [proof]
                nearby = [(abs(j - i), clients[j]) for j in range(max(0, i - 12), i + 13) if j in clients]
                if nearby:
                    return [proof, min(nearby)[1]]
                if nda_note:
                    return [proof, nda_note]
        # A portfolio tile may describe the built artifact without a verb. Require the named
        # beneficiary from this tile's heading to reappear in the very same application description.
        if kind == "index" and sentence.startswith(("A ", "An ")):
            app = _APPLICATION.search(sentence)
            if app and app.start() <= 55:
                for title in page.blocks[max(0, i - 2):i]:
                    if (2 <= len(title) <= 65 and title[0].isupper() and not _AUDIENCE.search(title)
                            and " for " + title in sentence[app.end():]):
                        end = sentence.index(" for " + title, app.end()) + 5 + len(title)
                        if end <= 175:
                            return [_excerpt(sentence, 0, end)]
    seller = re.compile(rf"\b(?:{brand})\b", re.I) if brand else None
    if kind == "detail":
        outcome_parts = _case_outcome(passages, seller)
        if outcome_parts:
            return outcome_parts
    # A client can hire a studio to rescue an existing frontend. A request alone is insufficient:
    # require a separate completed release that names both the same client and the studio.
    if kind == "detail" and seller:
        for n, (_, scope) in enumerate(passages):
            request = _REQUEST.search(scope)
            app = _APPLICATION.search(scope)
            if not request or not app or not seller.match(scope, request.end()+1):
                continue
            if app.end() <= request.end() or app.end() - request.start() > 185:
                continue
            client = re.escape(request[1])
            launch = re.compile(rf"\b{client} (?:successfully )?(?:released|launched|shipped)\b", re.I)
            for _, outcome in passages[n + 1:n + 32]:
                event = launch.search(outcome)
                partner = seller.search(outcome)
                if event and partner and 0 < partner.end() - event.start() <= 185:
                    return [_excerpt(scope, request.start(), app.end()), _excerpt(outcome, event.start(), partner.end())]
    return []
