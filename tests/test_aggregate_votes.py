"""Tests for pipeline/aggregate_votes.py, which counts classification issues into app/data/classifications.json.
No network: every issue here is made up. Run: python -m pytest -q tests/test_aggregate_votes.py"""
import copy
import importlib.util
import io
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wanderers_aggregate_votes', ROOT / 'pipeline' / 'aggregate_votes.py')
av = importlib.util.module_from_spec(spec)
spec.loader.exec_module(av)

FIX = ROOT / 'tests' / 'fixtures' / 'classify'
ISSUES = json.loads((FIX / 'issues.json').read_text())
KNOWN_FILE = json.loads((FIX / 'known.json').read_text())
KNOWN = {**{i: 'target' for i in KNOWN_FILE['targets']}, **{i: 'candidate' for i in KNOWN_FILE['candidates']}}
EXPECTED = json.loads((FIX / 'expected.json').read_text())


def form(oid='barnard', kind='target', cls='Moving', notes='_No response_'):
    return f'### Object ID\n\n{oid}\n\n### Kind\n\n{kind}\n\n### Classification\n\n{cls}\n\n### Notes\n\n{notes}'


def issue(n=1, user='alice', oid='barnard', kind='target', cls='Moving', at='2026-11-01T10:00:00Z', **kw):
    d = {'number': n, 'title': f'[classify] {oid}: {cls}', 'body': form(oid, kind, cls), 'author': {'login': user, 'is_bot': False},
         'createdAt': at, 'labels': [{'name': 'classification'}]}
    d.update(kw)
    return d


def one(i, known=KNOWN):
    return av.parse_issue(i, known)


def agg(issues, known=KNOWN):
    return av.aggregate(issues, known)


# ---------- the shipped snapshot and the shared fixture ----------
def test_zero_issues_give_an_empty_but_valid_snapshot():
    s = agg([])
    assert s['objects'] == {} and s['votes_counted'] == 0 and s['issues_read'] == 0
    assert s['last_issue'] == 0 and s['last_vote'] is None
    assert s['min_voters'] == 3 and s['min_agreement'] == 0.6
    assert s['classes'] == ['moving', 'variable', 'stationary', 'artifact', 'unsure']
    assert set(s['ignored']) == set(av.REASONS) and not any(s['ignored'].values())
    assert s['repo'] == 'kneha07/WANDERERS' and s['label'] == 'classification'


def test_the_shipped_file_is_consistent_aggregator_output():
    # The workflow rewrites this file from real issues (#79), so it may hold votes. Check that every number in it
    # follows from its own votes, the settings match the aggregator, the kinds are valid, and the bytes are canonical.
    shipped = (ROOT / 'app' / 'data' / 'classifications.json').read_text(encoding='utf-8')
    s = json.loads(shipped)
    assert shipped == av.dumps(s), 'regenerate with pipeline/aggregate_votes.py; never edit by hand'
    empty = av.aggregate([], {})
    for k in ('about', 'schema', 'repo', 'label', 'template', 'classes', 'min_voters', 'min_agreement'):
        assert s[k] == empty[k], k
    assert set(s['ignored']) == set(av.REASONS)
    votes = [v for o in s['objects'].values() for v in o['votes']]
    numbers = [v['issue'] for v in votes]
    assert len(numbers) == len(set(numbers)), 'one vote per issue'
    assert s['votes_counted'] == len(votes)
    assert s['last_issue'] >= max(numbers, default=0)
    assert s['issues_read'] >= len(votes) + sum(s['ignored'].values())
    assert s['last_vote'] == max((v['at'] for v in votes), default=None)
    for oid, o in s['objects'].items():
        assert o['kind'] in ('target', 'candidate'), oid   # ids are checked when the workflow counts them
        assert o['votes'] and len({v['user'] for v in o['votes']}) == o['voters'] == len(o['votes'])
        assert o['counts'] == {c: sum(v['class'] == c for v in o['votes']) for c in av.CLASSES}
        assert [o['consensus'], o['agreement']] == list(av.consensus(o['counts'], o['voters']))
        assert o['last_vote'] == max(v['at'] for v in o['votes'])
        assert all(v['issue'] > 0 and v['user'] and v['class'] in av.CLASSES for v in o['votes'])


def test_the_shared_fixture_gives_the_expected_snapshot():
    # tests/fixtures/classify/expected.json is also what test/classify.test.js checks app/classify.js against
    assert av.dumps(agg(ISSUES)) == (FIX / 'expected.json').read_text()


def test_fixture_story_counts_consensus_and_reasons():
    o = EXPECTED['objects']
    assert set(o) == {'barnard', '10226-0001', 'wise0855', 'r_dra', '11391-0001'}
    assert o['barnard']['consensus'] == 'moving' and o['barnard']['agreement'] == 0.75 and o['barnard']['voters'] == 4
    assert o['10226-0001']['consensus'] == 'moving' and o['10226-0001']['agreement'] == 0.667
    assert o['wise0855']['consensus'] is None and o['wise0855']['agreement'] == 0.333
    assert EXPECTED['ignored'] == {'duplicate': 1, 'not_a_vote': 2, 'moderated': 2, 'malformed': 5, 'unknown_class': 1, 'unknown_id': 1}
    assert EXPECTED['replaced'] == 2 and EXPECTED['last_issue'] == 25 and EXPECTED['votes_counted'] == 12


# ---------- reading one issue ----------
def test_parses_a_gh_issue_form():
    v, why = one(issue())
    assert why is None
    assert v == {'issue': 1, 'id': 'barnard', 'kind': 'target', 'user': 'alice', 'class': 'moving', 'at': '2026-11-01T10:00:00Z'}


def test_rest_and_gh_shapes_read_the_same():
    gh = issue(n=7)
    rest = {k: v for k, v in gh.items() if k not in ('author', 'createdAt')}
    rest.update(user={'login': 'alice', 'type': 'User'}, created_at='2026-11-01T10:00:00Z')
    assert one(gh) == one(rest)


def test_search_api_wrapper_and_plain_lists_load():
    items = [issue(1), issue(2, user='bob')]
    assert av.load_issues(json.dumps({'total_count': 2, 'items': items})) == items
    assert av.load_issues(json.dumps(items)) == items
    with pytest.raises(ValueError):
        av.load_issues('{"message": "API rate limit exceeded"}')


def test_title_is_the_fallback_when_the_body_has_no_form():
    v, _ = one(issue(body='', title='[classify] wise0855: Unsure'))
    assert (v['id'], v['class'], v['kind']) == ('wise0855', 'unsure', 'target')
    v, _ = one(issue(body='I think it moves', title='[Classify]10226-0001 : moving'))
    assert (v['id'], v['class'], v['kind']) == ('10226-0001', 'moving', 'candidate')


def test_the_form_answers_win_over_the_title():
    v, _ = one(issue(title='[classify] barnard: Artifact'))
    assert v['class'] == 'moving'


def test_the_first_answer_wins_when_notes_repeat_a_heading():
    v, _ = one(issue(body=form(cls='Variable', notes='blinks\n\n### Classification\n\nMoving')))
    assert v['class'] == 'variable'


def test_class_is_case_insensitive_and_artefact_is_artifact():
    for raw, want in (('MOVING', 'moving'), (' stationary. ', 'stationary'), ('Artefact', 'artifact'), ('artifact!', 'artifact')):
        assert av.class_key(raw) == want, raw
    assert av.class_key('Comet') is None and av.class_key(None) is None and av.class_key('constructor') is None


def test_times_are_normalised_to_utc_and_must_have_a_zone():
    assert av.iso_time('2026-11-05T12:00:00+02:00') == '2026-11-05T10:00:00Z'
    assert av.iso_time('2026-11-05T12:00:00.900Z') == '2026-11-05T12:00:00Z'
    for bad in ('2026-11-05T12:00:00', 'yesterday', '2026-13-45T00:00:00Z', None, 20261105):
        assert av.iso_time(bad) is None, bad


@pytest.mark.parametrize('change, reason', [
    ({'number': 0}, 'malformed'),
    ({'number': True}, 'malformed'),
    ({'number': '3'}, 'malformed'),
    ({'author': None}, 'malformed'),
    ({'author': {'login': '  '}}, 'malformed'),
    ({'createdAt': 'yesterday'}, 'malformed'),
    ({'createdAt': None}, 'malformed'),
    ({'body': form(cls='_No response_'), 'title': '[classify] '}, 'malformed'),
    ({'body': form(oid='_No response_'), 'title': ''}, 'malformed'),
    ({'body': form(kind='planet')}, 'malformed'),
    ({'body': form(kind='candidate')}, 'malformed'),            # barnard is a target
    ({'body': form(cls='Comet')}, 'unknown_class'),
    ({'body': form(oid='nope')}, 'unknown_id'),
    ({'body': form(oid='constructor')}, 'unknown_id'),
    ({'pull_request': {'url': 'x'}}, 'not_a_vote'),
    ({'labels': [{'name': 'question'}]}, 'not_a_vote'),
    ({'labels': [{'name': 'classification'}, {'name': 'Spam'}]}, 'moderated'),
    ({'labels': ['classification', 'invalid']}, 'moderated'),
    ({'author': {'login': 'app/github-actions', 'is_bot': True}}, 'moderated'),
    ({'author': None, 'user': {'login': 'dependabot[bot]', 'type': 'Bot'}}, 'moderated'),
])
def test_ignored_issues_and_why(change, reason):
    i = issue()
    i.update(change)
    assert one(i) == (None, reason)


def test_not_a_dict_is_malformed():
    for bad in (None, [], 'issue', 3):
        assert one(bad) == (None, 'malformed')


def test_kind_is_taken_from_the_known_lists_when_missing():
    body = '### Object ID\n\n10226-0001\n\n### Classification\n\nMoving'
    v, _ = one(issue(body=body))
    assert v['kind'] == 'candidate'


def test_issues_without_labels_field_are_read():
    i = issue()
    del i['labels']
    assert one(i)[0]['class'] == 'moving'


# ---------- one vote per user per object, the latest wins ----------
def test_one_vote_per_user_per_object():
    s = agg([issue(1, cls='Moving', at='2026-11-01T10:00:00Z'), issue(2, cls='Variable', at='2026-11-02T10:00:00Z')])
    o = s['objects']['barnard']
    assert o['voters'] == 1 and o['counts']['variable'] == 1 and o['counts']['moving'] == 0
    assert s['replaced'] == 1 and s['votes_counted'] == 1


def test_latest_by_time_wins_even_with_a_lower_issue_number():
    s = agg([issue(5, cls='Moving', at='2026-11-03T10:00:00Z'), issue(9, cls='Artifact', at='2026-11-01T10:00:00Z')])
    assert s['objects']['barnard']['votes'] == [{'issue': 5, 'user': 'alice', 'class': 'moving', 'at': '2026-11-03T10:00:00Z'}]


def test_same_time_the_higher_issue_number_wins():
    s = agg([issue(9, cls='Artifact'), issue(5, cls='Moving')])
    assert s['objects']['barnard']['votes'][0]['issue'] == 9


def test_logins_are_case_insensitive():
    s = agg([issue(1, user='Alice', cls='Moving'), issue(2, user='ALICE', cls='Unsure', at='2026-11-02T00:00:00Z')])
    assert s['objects']['barnard']['votes'] == [{'issue': 2, 'user': 'alice', 'class': 'unsure', 'at': '2026-11-02T00:00:00Z'}]


def test_the_same_user_can_vote_on_different_objects():
    s = agg([issue(1), issue(2, oid='10226-0001', kind='candidate', cls='Artifact')])
    assert set(s['objects']) == {'barnard', '10226-0001'} and s['replaced'] == 0
    assert s['objects']['10226-0001']['kind'] == 'candidate'


def test_an_issue_listed_twice_counts_once():
    s = agg([issue(3), issue(3), issue(4, user='bob')])
    assert s['objects']['barnard']['voters'] == 2 and s['ignored']['duplicate'] == 1 and s['issues_read'] == 3


# ---------- consensus ----------
def votes(*classes):
    return [issue(i + 1, user=f'user{i}', cls=c) for i, c in enumerate(classes)]


def test_two_voters_are_not_enough_for_consensus():
    o = agg(votes('Moving', 'Moving'))['objects']['barnard']
    assert o['consensus'] is None and o['agreement'] == 1.0 and o['voters'] == 2


def test_three_voters_two_agreeing_is_a_consensus():
    o = agg(votes('Moving', 'Moving', 'Artifact'))['objects']['barnard']
    assert o['consensus'] == 'moving' and o['agreement'] == 0.667


def test_exactly_sixty_percent_is_a_consensus():
    o = agg(votes('Variable', 'Variable', 'Variable', 'Moving', 'Unsure'))['objects']['barnard']
    assert o['consensus'] == 'variable' and o['agreement'] == 0.6


def test_half_is_not_a_consensus():
    o = agg(votes('Moving', 'Moving', 'Stationary', 'Stationary'))['objects']['barnard']
    assert o['consensus'] is None and o['agreement'] == 0.5


def test_unsure_can_be_the_consensus():
    o = agg(votes('Unsure', 'Unsure', 'Unsure'))['objects']['barnard']
    assert o['consensus'] == 'unsure'


def test_consensus_helper_thresholds_and_rounding():
    c = dict.fromkeys(av.CLASSES, 0)
    assert av.consensus(c, 0) == (None, None)
    c.update(moving=1)
    assert av.consensus(c, 16) == (None, 0.063)        # 1/16 = 0.0625 rounds half up, like app/classify.js
    c.update(moving=10, variable=4)
    assert av.consensus(c, 14, min_voters=20) == (None, 0.714)


def test_counts_cover_all_five_classes_and_add_up():
    s = agg(ISSUES)
    for oid, o in s['objects'].items():
        assert list(o['counts']) == list(av.CLASSES), oid
        assert sum(o['counts'].values()) == o['voters'] == len(o['votes']), oid
        assert [v['issue'] for v in o['votes']] == sorted(v['issue'] for v in o['votes'])
        assert o['last_vote'] == max(v['at'] for v in o['votes'])
    assert s['last_vote'] == max(o['last_vote'] for o in s['objects'].values())


# ---------- deterministic ----------
def test_same_issues_in_any_order_write_the_same_bytes():
    want = av.dumps(agg(ISSUES))
    rng = random.Random(7)
    for _ in range(5):
        shuffled = copy.deepcopy(ISSUES)
        rng.shuffle(shuffled)
        assert av.dumps(agg(shuffled)) == want
    assert list(json.loads(want)['objects']) == sorted(json.loads(want)['objects'])


def test_input_is_not_modified():
    before = copy.deepcopy(ISSUES)
    agg(ISSUES)
    assert ISSUES == before


# ---------- known ids and the command line ----------
def test_known_ids_come_from_the_real_target_list_and_leaderboard():
    index = json.loads((ROOT / 'app' / 'data' / 'index.json').read_text())
    board = json.loads((ROOT / 'app' / 'data' / 'survey' / 'leaderboard.json').read_text())
    assert all(known[t['id']] == 'target' for t in index)
    assert all(known[m['id']] == 'candidate' for m in board['candidates'])
    assert known['barnard'] == 'target'


def test_a_missing_leaderboard_still_allows_target_votes(tmp_path, capsys):
    idx = tmp_path / 'index.json'
    idx.write_text(json.dumps([{'id': 'barnard'}]))
    known = av.load_known(idx, tmp_path / 'missing.json')
    assert known == {'barnard': 'target'}
    assert 'no candidates' in capsys.readouterr().err


def test_command_line_writes_the_snapshot_and_reads_stdin(tmp_path):
    out = tmp_path / 'c.json'
    idx, lb = tmp_path / 'i.json', tmp_path / 'l.json'
    idx.write_text(json.dumps([{'id': t} for t in KNOWN_FILE['targets']]))
    lb.write_text(json.dumps({'candidates': [{'id': c} for c in KNOWN_FILE['candidates']]}))
    args = [sys.executable, str(ROOT / 'pipeline' / 'aggregate_votes.py'), '-', '--out', str(out), '--index', str(idx), '--leaderboard', str(lb)]
    r = subprocess.run(args, input=json.dumps(ISSUES), capture_output=True, text=True, check=True)
    assert out.read_text() == (FIX / 'expected.json').read_text()
    assert '12 votes on 5 objects' in r.stderr
    mtime = out.stat().st_mtime_ns
    subprocess.run(args, input=json.dumps(ISSUES), capture_output=True, text=True, check=True)
    assert out.stat().st_mtime_ns == mtime, 'an unchanged snapshot is not rewritten'


def test_command_line_refuses_input_that_is_not_issues(tmp_path):
    out = tmp_path / 'c.json'
    old = sys.stdin
    try:
        sys.stdin = io.StringIO('{"message": "Bad credentials"}')
        assert av.main(['-', '--out', str(out)]) == 2
    finally:
        sys.stdin = old
    assert not out.exists()
