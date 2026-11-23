"""Offline, development-used fictional cases. Not real-world precision/recall.

Run from pilot: python3 scripts/engine6_before_after.py
Requires the baseline commit in local git history; no network calls.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    ('plain', '<p>Jane Doe, CEO</p>', True),
    ('inline', '<span>Jane Doe</span><span>CEO</span>', True),
    ('person_article', '<article itemtype="https://schema.org/Person"><h3>Jane Doe</h3><p>CEO</p></article>', True),
    ('escaped_schema', '<script type="application/ld+json">'+json.dumps({'@type':'Organization','name':'Acme Studio', 'founder':{'@type':'Person','name':'José García','jobTitle':'Founder'}})+'</script>', True),
    ('testimonial', '<div class="testimonial"><p>Jane Doe, CEO</p></div>', False),
    ('wrong_org', '<p>Jane Doe, CEO at Acme Capital</p>', False),
    ('cross_card', '<div><span>Jane Doe</span></div><div><span>CEO</span></div>', False),
    ('editorial', '<article class="blog"><h3>Jane Doe</h3><p>CEO</p></article>', False),
]

def measure():
    from vm1.people import find_decision_makers
    from vm1.htmlparse import parse_html
    from vm1.evidence import PageSnapshot, verify_excerpt_parts
    rows = []
    for name, html, expected in CASES:
        page = parse_html(html, 'https://acme.example/team')
        found = find_decision_makers([PageSnapshot(url=page.url, fetched_at='2026-11-23T00:00:00Z',page=page)],
                                    company_key='acme.example', company_name='Acme Studio')
        found = [p for p in found if verify_excerpt_parts(p.excerpt_parts, page)]
        rows.append({'case':name,'expected_named':expected,'named':bool(found)})
    return rows

if __name__ == '__main__':
    if '--worker' in sys.argv:
        print(json.dumps(measure()))
    else:
        import tarfile
        import io
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.check_output(['git','archive','f8035e1','pilot/vm1'],cwd=ROOT.parent)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(tmp, filter='data')
            worker = Path(tmp)/'pilot/scripts/engine6_before_after.py'
            worker.parent.mkdir()
            worker.write_text(Path(__file__).read_text())
            before = json.loads(subprocess.check_output([sys.executable,str(worker),'--worker'],cwd=tmp))
        after = measure()
        print(json.dumps({'baseline':'f8035e1','fixture_cases':len(CASES),'before':before,'after':after},indent=2))
