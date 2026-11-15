#!/usr/bin/env python3
"""Count the community's classifications of WANDERERS objects into app/data/classifications.json.

People classify what they see as Moving, Variable, Stationary, Artifact or Unsure (app/classify.js, on every target in
the explorer and every Sky Survey candidate). The site is static, so a vote travels as a GitHub issue opened from the
form .github/ISSUE_TEMPLATE/classification.yml in kneha07/WANDERERS, which labels it `classification`. This script
reads those issues as JSON and writes the snapshot the site shows. .github/workflows/classifications.yml runs it.

Input (a file, or - for stdin), any of:
  gh issue list --label classification --state all --limit 5000 --json number,title,body,author,createdAt,labels
  the REST list    GET /repos/kneha07/WANDERERS/issues?labels=classification&state=all      (a JSON list)
  the search API   GET /search/issues?q=repo:kneha07/WANDERERS+label:classification          ({"items": [...]})

Rules (app/classify.js applies the same ones to the newer votes it fetches live):
  - one vote per GitHub user per object: the latest wins (created time, then issue number);
  - ignored, and counted by reason: an issue number seen twice (duplicate); pull requests and issues that lack the
    `classification` label when labels are given (not_a_vote); issues labelled invalid or spam and bot authors
    (moderated); no number, author, ISO time, object id or class, or a kind other than target/candidate, or a kind
    that does not match the object (malformed); a class that is not one of the five (unknown_class); an id that is
    neither a target in app/data/index.json nor a candidate in app/data/survey/leaderboard.json (unknown_id);
  - consensus: at least 3 voters, and at least 60% of them choosing the same class.
The output depends only on the input (no clock, sorted keys and votes), so the same issues always write the same
bytes and the workflow commits only when a vote changed.

Run:  python pipeline/aggregate_votes.py issues.json                 (writes app/data/classifications.json)
      echo '[]' | python pipeline/aggregate_votes.py -              (the empty snapshot)
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'app' / 'data' / 'classifications.json'
INDEX = ROOT / 'app' / 'data' / 'index.json'
LEADERBOARD = ROOT / 'app' / 'data' / 'survey' / 'leaderboard.json'

REPO = 'kneha07/WANDERERS'
LABEL = 'classification'
TEMPLATE = '.github/ISSUE_TEMPLATE/classification.yml'
CLASSES = ('moving', 'variable', 'stationary', 'artifact', 'unsure')
CLASS_LABELS = {'moving': 'Moving', 'variable': 'Variable', 'stationary': 'Stationary', 'artifact': 'Artifact', 'unsure': 'Unsure'}
ALIASES = {'artefact': 'artifact'}           # the site writes British "artefact" elsewhere
KINDS = ('target', 'candidate')
MODERATION_LABELS = ('invalid', 'spam')
MIN_VOTERS = 3
MIN_AGREEMENT = 0.6
REASONS = ('duplicate', 'not_a_vote', 'moderated', 'malformed', 'unknown_class', 'unknown_id')
# Issue forms write each answer under "### <field label>"; the ids are accepted too.
FIELDS = {'object id': 'object_id', 'object_id': 'object_id', 'kind': 'kind', 'classification': 'class', 'class': 'class'}
NO_RESPONSE = '_no response_'

HEADING = re.compile(r'^###\s+(.+?)\s*#*\s*$')
TITLE = re.compile(r'^\s*\[classify\]\s*([^\s:]+)\s*:\s*(.+?)\s*$', re.IGNORECASE)
TIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$')


def class_key(s):
    """'Moving', ' moving. ', 'Artefact' -> the class key, or None."""
    if not isinstance(s, str):
        return None
    k = s.strip().lower().rstrip('.!')
    k = ALIASES.get(k, k)
    return k if k in CLASSES else None


def iso_time(s):
    """An ISO 8601 time with a zone ('2026-11-15T10:44:41Z', '...+02:00') -> 'YYYY-MM-DDTHH:MM:SSZ' in UTC, else None."""
    if not isinstance(s, str) or not TIME.match(s.strip()):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def form_fields(body):
    """The answers of an issue form: {'object_id': ..., 'kind': ..., 'class': ...} (first heading of each wins)."""
    out, done, cur = {}, set(), None
    for line in re.split(r'\r?\n', body if isinstance(body, str) else ''):
        h = HEADING.match(line)
        if h:
            f = FIELDS.get(' '.join(h.group(1).lower().split()))
            cur = f if f and f not in done else None
            if cur:
                done.add(cur)
                out[cur] = ''
            continue
        v = line.strip()
        if cur and v:
            out[cur] = '' if v.lower() == NO_RESPONSE else v
            cur = None
    return out


def _number(issue):
    n = issue.get('number') if isinstance(issue, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None


def _labels(issue):
    ls = issue.get('labels')
    if not isinstance(ls, list):
        return None
    out = []
    for item in ls:
        name = item.get('name') if isinstance(item, dict) else item
        if isinstance(name, str):
            out.append(name.strip().lower())
    return out


def parse_issue(issue, known):
    """One issue -> (vote, None) or (None, reason). known: {object id: 'target' | 'candidate'}.
    Duplicates are the caller's business (they need the other issues)."""
    if not isinstance(issue, dict) or _number(issue) is None:
        return None, 'malformed'
    n = _number(issue)
    if issue.get('pull_request') is not None:
        return None, 'not_a_vote'
    labels = _labels(issue)
    if labels is not None and LABEL not in labels:
        return None, 'not_a_vote'
    if labels is not None and any(m in labels for m in MODERATION_LABELS):
        return None, 'moderated'
    author = issue.get('author')
    if not isinstance(author, dict):
        author = issue.get('user')
    if not isinstance(author, dict):
        return None, 'malformed'
    if author.get('is_bot') is True or author.get('type') == 'Bot':
        return None, 'moderated'
    login = author.get('login')
    if not isinstance(login, str) or not login.strip():
        return None, 'malformed'
    created = issue.get('createdAt') if issue.get('createdAt') is not None else issue.get('created_at')
    at = iso_time(created)
    if at is None:
        return None, 'malformed'
    fields = form_fields(issue.get('body'))
    t = TITLE.match(issue.get('title') if isinstance(issue.get('title'), str) else '')
    raw_id = (fields.get('object_id') or (t.group(1) if t else '')).strip()
    raw_cls = (fields.get('class') or (t.group(2) if t else '')).strip()
    raw_kind = (fields.get('kind') or '').strip().lower()
    if not raw_id or not raw_cls:
        return None, 'malformed'
    cls = class_key(raw_cls)
    if cls is None:
        return None, 'unknown_class'
    if raw_kind and raw_kind not in KINDS:
        return None, 'malformed'
    kind = known.get(raw_id)
    if kind is None:
        return None, 'unknown_id'
    if raw_kind and raw_kind != kind:
        return None, 'malformed'
    return {'issue': n, 'id': raw_id, 'kind': kind, 'user': login.strip().lower(), 'class': cls, 'at': at}, None


def consensus(counts, voters, min_voters=MIN_VOTERS, min_agreement=MIN_AGREEMENT):
    """(consensus class or None, agreement = share of the top class rounded half-up to 3 places, or None)."""
    if voters <= 0:
        return None, None
    top = CLASSES[0]
    for c in CLASSES:
        if counts[c] > counts[top]:
            top = c
    share = counts[top] / voters
    agreement = math.floor(share * 1000 + 0.5) / 1000
    return (top if voters >= min_voters and share >= min_agreement - 1e-9 else None), agreement


def _newer(a, b):
    return (a['at'], a['issue']) > (b['at'], b['issue'])


def _order(issue):
    n = _number(issue)
    return (n or 0, json.dumps(issue, sort_keys=True, default=str))


def aggregate(issues, known, min_voters=MIN_VOTERS, min_agreement=MIN_AGREEMENT):
    """Issues (any order) -> the snapshot dict written to app/data/classifications.json."""
    ignored = {r: 0 for r in REASONS}
    latest, seen = {}, set()
    replaced, last_issue, n_read = 0, 0, 0
    for issue in sorted(issues if isinstance(issues, list) else [], key=_order):
        n_read += 1
        n = _number(issue)
        if n is not None:
            if n in seen:
                ignored['duplicate'] += 1
                continue
            seen.add(n)
            last_issue = max(last_issue, n)
        vote, why = parse_issue(issue, known)
        if vote is None:
            ignored[why] += 1
            continue
        key = (vote['id'], vote['user'])
        prev = latest.get(key)
        if prev is not None:
            replaced += 1
            if not _newer(vote, prev):
                continue
        latest[key] = vote

    objects = {}
    for vote in latest.values():
        o = objects.setdefault(vote['id'], {'kind': vote['kind'], 'votes': []})
        o['votes'].append({k: vote[k] for k in ('issue', 'user', 'class', 'at')})
    for o in objects.values():
        o['votes'].sort(key=lambda v: v['issue'])
        o['counts'] = {c: sum(1 for v in o['votes'] if v['class'] == c) for c in CLASSES}
        o['voters'] = len(o['votes'])
        o['consensus'], o['agreement'] = consensus(o['counts'], o['voters'], min_voters, min_agreement)
        o['last_vote'] = max(v['at'] for v in o['votes'])
    votes = [v for o in objects.values() for v in o['votes']]
    return {
        'about': ('Community classifications of WANDERERS targets and Sky Survey candidates, counted from GitHub issues '
                  f'labelled "{LABEL}" in {REPO} by pipeline/aggregate_votes.py. Do not edit by hand.'),
        'schema': 1,
        'repo': REPO,
        'label': LABEL,
        'template': TEMPLATE,
        'classes': list(CLASSES),
        'min_voters': min_voters,
        'min_agreement': min_agreement,
        'issues_read': n_read,
        'votes_counted': len(votes),
        'replaced': replaced,
        'ignored': ignored,
        'last_issue': last_issue,
        'last_vote': max((v['at'] for v in votes), default=None),
        'objects': {k: objects[k] for k in sorted(objects)},
    }


def dumps(snapshot):
    return json.dumps(snapshot, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def load_known(index_path=INDEX, leaderboard_path=LEADERBOARD):
    """{object id: kind} from the explorer's target list and the Sky Survey's ranked list (a missing file adds none)."""
    known = {}
    try:
        for t in json.loads(Path(index_path).read_text(encoding='utf-8')):
            if isinstance(t, dict) and isinstance(t.get('id'), str):
                known.setdefault(t['id'], 'target')
    except (OSError, ValueError, TypeError) as e:
        print(f'aggregate_votes: no targets from {index_path} ({e})', file=sys.stderr)
    try:
        board = json.loads(Path(leaderboard_path).read_text(encoding='utf-8'))
        for m in board.get('candidates', []) if isinstance(board, dict) else []:
            if isinstance(m, dict) and isinstance(m.get('id'), str):
                known.setdefault(m['id'], 'candidate')
    except (OSError, ValueError, TypeError) as e:
        print(f'aggregate_votes: no candidates from {leaderboard_path} ({e})', file=sys.stderr)
    return known


def load_issues(text):
    """gh / REST: a list; search API: {"items": [...]}."""
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get('items'), list):
        return data['items']
    if isinstance(data, list):
        return data
    raise ValueError('expected a JSON list of issues, or {"items": [...]} from the search API')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Count classification issues into app/data/classifications.json.')
    ap.add_argument('issues', help='issues JSON from gh issue list, the REST API or the search API; - reads stdin')
    ap.add_argument('--out', default=str(OUT), help='where to write the snapshot (default: %(default)s)')
    ap.add_argument('--index', default=str(INDEX), help='explorer targets (default: %(default)s)')
    ap.add_argument('--leaderboard', default=str(LEADERBOARD), help='Sky Survey candidates (default: %(default)s)')
    a = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if a.issues == '-' else Path(a.issues).read_text(encoding='utf-8')
        issues = load_issues(text)
    except (OSError, ValueError) as e:
        print(f'aggregate_votes: cannot read the issues: {e}', file=sys.stderr)
        return 2
    snap = aggregate(issues, load_known(a.index, a.leaderboard))
    out, text = Path(a.out), dumps(snap)
    if not out.exists() or out.read_text(encoding='utf-8') != text:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        tmp.replace(out)
    skipped = ', '.join(f'{k} {v}' for k, v in snap['ignored'].items() if v) or 'none'
    print(f"aggregate_votes: {snap['issues_read']} issues, {snap['votes_counted']} votes on {len(snap['objects'])} objects, "
          f"{snap['replaced']} replaced by a newer vote, ignored: {skipped} -> {out}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
