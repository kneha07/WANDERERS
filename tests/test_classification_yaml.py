"""The classification issue form and the workflow that counts the votes: they parse, ask for the right fields, label
the issue and run with the least permission. Run: python -m pytest -q tests/test_classification_yaml.py"""
import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FORM = yaml.safe_load((ROOT / '.github' / 'ISSUE_TEMPLATE' / 'classification.yml').read_text())
WF_TEXT = (ROOT / '.github' / 'workflows' / 'classifications.yml').read_text()
WF = yaml.safe_load(WF_TEXT)
ON = WF.get('on', WF.get(True))           # YAML 1.1 reads a bare `on` key as True
JS = (ROOT / 'app' / 'classify.js').read_text()
spec = importlib.util.spec_from_file_location('wanderers_aggregate_votes', ROOT / 'pipeline' / 'aggregate_votes.py')
av = importlib.util.module_from_spec(spec)
spec.loader.exec_module(av)

FIELDS = {f.get('id'): f for f in FORM['body'] if f.get('id')}


# ---------- the issue form ----------
def test_issue_form_parses_with_name_title_and_label():
    assert FORM['name'] and FORM['description']
    assert FORM['title'].startswith('[classify]')
    assert FORM['labels'] == ['classification'] == [av.LABEL]


def test_issue_form_asks_for_object_kind_and_class():
    assert FORM['body'][0]['type'] == 'markdown' and 'public' in FORM['body'][0]['attributes']['value']
    assert FIELDS['object_id']['type'] == 'input'
    assert FIELDS['kind']['type'] == 'dropdown' and FIELDS['kind']['attributes']['options'] == ['target', 'candidate']
    assert FIELDS['class']['type'] == 'dropdown'
    for f in ('object_id', 'kind', 'class'):
        assert FIELDS[f]['validations']['required'] is True, f
    assert FIELDS['notes']['validations']['required'] is False
    ids = [f.get('id') for f in FORM['body'] if f.get('id')]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r'[A-Za-z0-9_-]+', i) for i in ids)


def test_the_five_classes_agree_in_the_form_the_aggregator_and_the_page():
    opts = FIELDS['class']['attributes']['options']
    assert opts == ['Moving', 'Variable', 'Stationary', 'Artifact', 'Unsure']
    assert [av.CLASS_LABELS[c] for c in av.CLASSES] == opts
    assert re.findall(r'\{ key: "(\w+)", label: "(\w+)"', JS) == [(c, av.CLASS_LABELS[c]) for c in av.CLASSES]
    assert list(av.KINDS) == FIELDS['kind']['attributes']['options']


def test_the_aggregator_reads_the_answers_under_the_form_labels():
    # issue forms write "### <label>" above each answer: the parser must know every label the form uses
    for fid in ('object_id', 'kind', 'class'):
        label = ' '.join(FIELDS[fid]['attributes']['label'].lower().split())
        assert av.FIELDS[label] == fid, label
        assert f'["{label}", "{fid}"]' in JS, f'classify.js knows "{label}"'
    body = '\n\n'.join(f"### {FIELDS[f]['attributes']['label']}\n\n{v}" for f, v in (('object_id', 'barnard'), ('kind', 'target'), ('class', 'Moving')))
    assert av.form_fields(body) == {'object_id': 'barnard', 'kind': 'target', 'class': 'Moving'}


def test_the_page_prefills_the_form_by_its_field_ids_and_template_name():
    assert 'const REPO = "kneha07/WANDERERS", TEMPLATE = "classification.yml", LABEL = "classification"' in JS
    for fid in ('object_id', 'kind', 'class'):
        assert f'["{fid}", ' in JS, fid
    assert '["title", `[classify] ${id}: ${label}`]' in JS


# ---------- the workflow ----------
def test_workflow_triggers_on_labelled_issues_a_schedule_and_by_hand():
    assert set(ON) == {'issues', 'schedule', 'workflow_dispatch'}
    assert {'opened', 'edited', 'closed', 'reopened', 'deleted', 'labeled', 'unlabeled'} <= set(ON['issues']['types'])
    assert len(ON['schedule']) == 1 and len(ON['schedule'][0]['cron'].split()) == 5
    cond = WF['jobs']['aggregate']['if']
    assert "contains(github.event.issue.labels.*.name, 'classification')" in cond
    assert "github.event.label.name == 'classification'" in cond, 'a vote that loses its label is recounted too'
    assert "github.event_name != 'issues'" in cond


def test_workflow_permissions_are_minimal():
    assert WF['permissions'] == {'contents': 'read'}
    jobs = WF['jobs']
    assert list(jobs) == ['aggregate']
    assert jobs['aggregate']['permissions'] == {'contents': 'write', 'issues': 'read'}
    assert WF['concurrency']['group'] == 'classifications' and WF['concurrency']['cancel-in-progress'] is False


def test_workflow_reads_votes_with_gh_and_runs_the_aggregator():
    steps = WF['jobs']['aggregate']['steps']
    runs = '\n'.join(s.get('run', '') for s in steps)
    assert re.search(r'gh issue list --repo "\$GITHUB_REPOSITORY" --label classification --state all --limit \d+\s+--json number,title,body,author,createdAt,labels', runs)
    assert 'python pipeline/aggregate_votes.py "$RUNNER_TEMP/issues.json" --out app/data/classifications.json' in runs
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout@'))
    assert checkout['with']['ref'] == 'main'
    gh_step = next(s for s in steps if 'gh issue list' in s.get('run', ''))
    assert gh_step['env']['GH_TOKEN'] == '${{ github.token }}'


def test_workflow_commits_only_when_the_snapshot_changed():
    run = WF['jobs']['aggregate']['steps'][-1]['run']
    lines = [ln.strip() for ln in run.splitlines() if ln.strip()]
    assert lines[0].startswith('if git diff --quiet -- app/data/classifications.json; then') and 'exit 0' in lines[0]
    assert 'git add app/data/classifications.json' in lines
    assert lines[-1] == 'git push origin HEAD:main'
    assert not re.search(r'git add (-A|\.|--all)', run)


def test_workflow_never_puts_issue_text_into_a_shell_command():
    for s in WF['jobs']['aggregate']['steps']:
        assert 'github.event' not in s.get('run', ''), s.get('name')
    assert 'secrets.' not in WF_TEXT
    for m in re.findall(r'uses: ([\w./-]+@[\w.]+)', WF_TEXT):
        assert m.split('@')[0] in ('actions/checkout', 'actions/setup-python'), m
