// Citizen-science classification (app/classify.js): parsing and counting votes like pipeline/aggregate_votes.py, the
// pre-filled GitHub issue link, the card (buttons, keyboard, your vote, the tally and consensus), storage that fails,
// a missing snapshot, and newer votes fetched live without counting any twice. No network: fetch is always a fake.
// node --test test/classify.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../app/classify.js");

const ISSUES = require("../tests/fixtures/classify/issues.json");
const EXPECTED = require("../tests/fixtures/classify/expected.json");
const KNOWN_FILE = require("../tests/fixtures/classify/known.json");
const KNOWN = new Map([...KNOWN_FILE.targets.map((i) => [i, "target"]), ...KNOWN_FILE.candidates.map((i) => [i, "candidate"])]);
const NOW = Date.parse("2026-11-10T12:00:00Z");
const clone = (x) => JSON.parse(JSON.stringify(x));

// ---------- fakes ----------
const form = (oid = "barnard", kind = "target", cls = "Moving") => `### Object ID\n\n${oid}\n\n### Kind\n\n${kind}\n\n### Classification\n\n${cls}\n\n### Notes\n\n_No response_`;
function rest(n, login, oid, cls, at, extra = {}) {
  const kind = /^\d+-\d+$/.test(oid) ? "candidate" : "target";
  return { number: n, title: `[classify] ${oid}: ${cls}`, body: form(oid, kind, cls), user: { login, type: "User" }, created_at: at, labels: [{ name: "classification" }], ...extra };
}
function memStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}
const brokenStorage = { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceededError"); } };
const reply = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => (data instanceof Error ? Promise.reject(data) : clone(data)) });
function fakeFetch(route) {
  const calls = [];
  const f = async (url) => {
    calls.push(String(url));
    const r = route(String(url));
    if (r instanceof Error) throw r;
    return r;
  };
  f.calls = calls;
  return f;
}
const snapshotOnly = (snap) => fakeFetch((u) => (u === C.DATA_URL ? reply(snap) : new TypeError("Failed to fetch")));
const LOCAL = { protocol: "http:", hostname: "localhost", search: "" };
const HOSTED = { protocol: "https:", hostname: "rajryadav4.github.io", search: "" };

// A container element: innerHTML is kept as a string; the buttons and the send link it holds are small fakes that know
// their data-* attribute, so click and keyboard events can be sent "from" them.
function fakeDoc() { return { activeElement: null }; }
function fakeEl(doc) {
  const listeners = {};
  const el = {
    hidden: true, _html: "", _kids: null,
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); this._kids = null; },
    addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
    send(ev) { for (const f of listeners[ev.type] || []) f(ev); return ev; },
    contains: (n) => !!n && n.owner === el,
    kids() {
      if (!this._kids) {
        const btn = [...this._html.matchAll(/data-cls="(\w+)"/g)].map((m) => node({ "data-cls": m[1] }));
        const link = /data-send="1"/.test(this._html) ? [node({ "data-send": "1" })] : [];
        this._kids = { btn, link };
      }
      return this._kids;
    },
    querySelectorAll: (sel) => (sel === "[data-cls]" ? el.kids().btn : []),
    querySelector(sel) {
      const m = /^\[data-cls="(\w+)"\]$/.exec(sel);
      if (m) return el.kids().btn.find((b) => b.getAttribute("data-cls") === m[1]) || null;
      return sel === "[data-send]" ? el.kids().link[0] || null : null;
    },
    listeners,
  };
  function node(attrs) {
    const n = {
      owner: el, getAttribute: (k) => (k in attrs ? attrs[k] : null), dataset: { cls: attrs["data-cls"] },
      closest: (sel) => (sel === "[data-cls]" && attrs["data-cls"]) || (sel === "[data-send]" && attrs["data-send"]) ? n : null,
      focus() { doc.activeElement = n; },
    };
    return n;
  }
  return el;
}
const btn = (el, cls) => el.querySelector(`[data-cls="${cls}"]`);
const click = (el, target) => el.send({ type: "click", target });
function key(el, target, k) {
  const ev = { type: "keydown", key: k, target, prevented: false, stopped: false };
  ev.preventDefault = () => { ev.prevented = true; };
  ev.stopPropagation = () => { ev.stopped = true; };
  return el.send(ev);
}
function setup({ snap = EXPECTED, storage = memStorage(), fetch, location = LOCAL, session = memStorage(), now = () => NOW } = {}) {
  const doc = fakeDoc(), el = fakeEl(doc);
  const inst = C.create({ fetch: fetch !== undefined ? fetch : snapshotOnly(snap), storage, session, location, document: doc, now, defer: (f) => f() });
  return { inst, el, doc, storage, session };
}
async function mounted(opts = {}, mount = { id: "barnard", kind: "target", name: "Barnard's Star" }) {
  const s = setup(opts);
  s.inst.mount(s.el, mount);
  await s.inst.ready();
  return s;
}
const pressed = (el) => [...el.innerHTML.matchAll(/data-cls="(\w+)" aria-pressed="(true|false)"/g)].filter((m) => m[2] === "true").map((m) => m[1]);
const countOf = (el, cls) => +new RegExp(`id="cls\\d+-${cls}-n">.*?<span class="cls-n">(\\d+)<`).exec(el.innerHTML)[1];

// ---------- the five choices and the issue link ----------
test("five classes in order, each with a one-line help", () => {
  assert.deepEqual(C.KEYS, ["moving", "variable", "stationary", "artifact", "unsure"]);
  assert.deepEqual(C.CLASSES.map((c) => c.label), ["Moving", "Variable", "Stationary", "Artifact", "Unsure"]);
  for (const c of C.CLASSES) assert.ok(c.help.length > 10 && c.help.length <= 70 && !/\n/.test(c.help), c.key);
  assert.equal(C.MIN_VOTERS, 3); assert.equal(C.MIN_AGREEMENT, 0.6);
});

test("class names: any case, trailing dots, the British artefact; nothing else", () => {
  for (const [raw, want] of [["MOVING", "moving"], [" stationary. ", "stationary"], ["Artefact", "artifact"], ["artifact!", "artifact"]]) assert.equal(C.classKey(raw), want, raw);
  for (const bad of ["Comet", "", null, 3, "constructor", "__proto__", "toString"]) assert.equal(C.classKey(bad), null, String(bad));
});

test("times: ISO with a zone, normalised to UTC seconds, like the aggregator", () => {
  assert.equal(C.isoTime("2026-11-05T12:00:00+02:00"), "2026-11-05T10:00:00Z");
  assert.equal(C.isoTime("2026-11-05T12:00:00.900Z"), "2026-11-05T12:00:00Z");
  for (const bad of ["2026-11-05T12:00:00", "yesterday", "2026-13-45T00:00:00Z", null, 20261105]) assert.equal(C.isoTime(bad), null, String(bad));
});

test("the issue link opens the classification form with every field filled in", () => {
  assert.equal(C.issueUrl("10226-0001", "candidate", "moving"),
    "https://github.com/kneha07/WANDERERS/issues/new?template=classification.yml&title=%5Bclassify%5D%2010226-0001%3A%20Moving&object_id=10226-0001&kind=candidate&class=Moving");
  const u = new URL(C.issueUrl("pos_162p3288_s53p3194", "target", "artifact"));
  assert.equal(u.origin + u.pathname, "https://github.com/kneha07/WANDERERS/issues/new");
  assert.deepEqual(Object.fromEntries(u.searchParams), { template: "classification.yml", title: "[classify] pos_162p3288_s53p3194: Artifact",
    object_id: "pos_162p3288_s53p3194", kind: "target", class: "Artifact" });
});

test("the issue link survives awkward ids, and falls back to safe values", () => {
  const u = new URL(C.issueUrl("a b&c=d#e+f/é", "planet", "nonsense"));
  assert.equal(u.searchParams.get("object_id"), "a b&c=d#e+f/é");
  assert.equal(u.searchParams.get("kind"), "target");
  assert.equal(u.searchParams.get("class"), "Unsure");
  assert.equal(u.hash, "");
  assert.doesNotMatch(C.issueUrl("x y", "target", "moving"), / |\+/, "spaces are %20, never + or raw");
});

// ---------- reading issues: the same answers as pipeline/aggregate_votes.py ----------
test("a gh issue and the same issue from the REST API read the same", () => {
  const gh = { number: 7, title: "[classify] barnard: Moving", body: form(), author: { login: "Alice", is_bot: false }, createdAt: "2026-11-01T10:00:00Z", labels: [{ name: "classification" }] };
  const r = rest(7, "alice", "barnard", "Moving", "2026-11-01T10:00:00Z");
  assert.deepEqual(C.parseIssue(gh, KNOWN), C.parseIssue(r, KNOWN));
  assert.deepEqual(C.parseIssue(gh, KNOWN).vote, { issue: 7, id: "barnard", kind: "target", user: "alice", class: "moving", at: "2026-11-01T10:00:00Z" });
});

test("issues that are not usable votes, and why", () => {
  const base = rest(3, "alice", "barnard", "Moving", "2026-11-01T10:00:00Z");
  const cases = [
    [{ number: 0 }, "malformed"], [{ number: "3" }, "malformed"], [{ user: null }, "malformed"], [{ created_at: "yesterday" }, "malformed"],
    [{ body: form("barnard", "target", "_No response_"), title: "[classify] " }, "malformed"], [{ body: form("barnard", "planet") }, "malformed"],
    [{ body: form("barnard", "candidate") }, "malformed"], [{ body: form("barnard", "target", "Comet") }, "unknown_class"],
    [{ body: form("nope") }, "unknown_id"], [{ body: form("constructor") }, "unknown_id"], [{ pull_request: { url: "x" } }, "not_a_vote"],
    [{ labels: [{ name: "question" }] }, "not_a_vote"], [{ labels: ["classification", "Spam"] }, "moderated"], [{ user: { login: "bot", type: "Bot" } }, "moderated"],
  ];
  for (const [change, why] of cases) assert.equal(C.parseIssue({ ...base, ...change }, KNOWN).reason, why, JSON.stringify(change));
  for (const bad of [null, [], "x", 3]) assert.equal(C.parseIssue(bad, KNOWN).reason, "malformed");
});

test("form answers: the first heading wins, '_No response_' is empty, the title is the fallback", () => {
  assert.deepEqual(C.formFields(`${form("barnard", "target", "Variable")}\n\n### Classification\n\nMoving`), { object_id: "barnard", kind: "target", class: "Variable" });
  assert.deepEqual(C.formFields("### Object ID\n\n_No response_"), { object_id: "" });
  assert.deepEqual(C.formFields(null), {});
  const v = C.parseIssue({ number: 9, title: "[Classify]10226-0001 : moving", body: "", user: { login: "a" }, created_at: "2026-11-01T00:00:00Z" }).vote;
  assert.deepEqual([v.id, v.kind, v.class], ["10226-0001", "candidate", "moving"]);
});

test("the shared fixture counts exactly as pipeline/aggregate_votes.py counted it", () => {
  const got = C.aggregate(ISSUES, KNOWN);
  assert.deepEqual(got.objects, EXPECTED.objects);
  for (const k of ["ignored", "replaced", "last_issue", "last_vote", "votes_counted"]) assert.deepEqual(got[k], EXPECTED[k], k);
});

test("counting does not depend on the order of the issues", () => {
  const want = JSON.stringify(C.aggregate(ISSUES, KNOWN));
  let seed = 3;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let k = 0; k < 5; k++) {
    const shuffled = ISSUES.slice().sort(() => rnd() - 0.5);
    assert.equal(JSON.stringify(C.aggregate(shuffled, KNOWN)), want);
  }
});

test("consensus needs 3 voters and 60% agreement; agreement rounds half up like the aggregator", () => {
  const c = (o) => ({ moving: 0, variable: 0, stationary: 0, artifact: 0, unsure: 0, ...o });
  assert.deepEqual(C.consensusOf(c({}), 0), { consensus: null, agreement: null, top: null });
  assert.equal(C.consensusOf(c({ moving: 2 }), 2).consensus, null);
  assert.deepEqual(C.consensusOf(c({ moving: 2, artifact: 1 }), 3), { top: "moving", agreement: 0.667, consensus: "moving" });
  assert.deepEqual(C.consensusOf(c({ variable: 3, moving: 1, unsure: 1 }), 5), { top: "variable", agreement: 0.6, consensus: "variable" });
  assert.deepEqual(C.consensusOf(c({ moving: 2, stationary: 2 }), 4), { top: "moving", agreement: 0.5, consensus: null });
  assert.equal(C.consensusOf(c({ moving: 1 }), 16).agreement, 0.063);
});

// ---------- the snapshot and live votes ----------
test("the snapshot is checked: bad votes, bad thresholds and odd ids are dropped or kept safely", () => {
  const d = C.normalize({ min_voters: -1, min_agreement: 7, last_issue: 12, last_vote: "nope", objects: {
    constructor: { kind: "target", votes: [{ issue: 1, user: "A", class: "moving", at: "2026-11-01T00:00:00Z" }, { issue: 2, user: "b", class: "comet", at: "2026-11-01T00:00:00Z" }] },
    old: { kind: "candidate", counts: { moving: 2, unsure: -4, artifact: 1.5 } }, junk: 5 } });
  assert.equal(d.minVoters, 3); assert.equal(d.minAgreement, 0.6); assert.equal(d.lastIssue, 12); assert.equal(d.lastVote, null);
  assert.deepEqual(d.objects.get("constructor").votes, [{ issue: 1, user: "a", class: "moving", at: "2026-11-01T00:00:00Z" }]);
  assert.equal(C.tallyVotes(d.objects.get("old")).voters, 2, "counts-only objects still show their counts");
  assert.ok(!d.objects.has("junk"));
  for (const bad of [null, [], "x"]) assert.equal(C.normalize(bad).objects.size, 0);
});

test("live votes: issue numbers already in the snapshot are never counted again", () => {
  const snap = C.normalize(EXPECTED);
  const live = [rest(4, "dave", "barnard", "Moving", "2026-11-01T13:00:00Z"), rest(25, "zed", "barnard", "Moving", "2026-11-09T00:00:00Z"),
    rest(26, "zed2", "barnard", "Artifact", "2026-11-09T01:00:00Z")];
  const r = C.mergeIssues(snap, live);
  assert.equal(r.added, 1);
  assert.equal(r.ignored.duplicate, 2);
  assert.equal(C.tallyVotes(r.data.objects.get("barnard")).voters, 5);
  assert.equal(C.tallyVotes(snap.objects.get("barnard")).voters, 4, "the snapshot itself is untouched");
});

test("live votes: the same issue twice, or merged twice, counts once", () => {
  const snap = C.normalize(EXPECTED), item = rest(30, "zed", "wise0855", "Moving", "2026-11-09T00:00:00Z");
  const once = C.mergeIssues(snap, [item, clone(item)]);
  assert.equal(once.added, 1); assert.equal(once.ignored.duplicate, 1);
  const twice = C.mergeIssues(once.data, [item]);
  assert.equal(twice.added, 0);
  assert.deepEqual(C.tallyVotes(twice.data.objects.get("wise0855")).counts, { moving: 2, variable: 1, stationary: 0, artifact: 0, unsure: 1 });
});

test("live votes: a newer vote from the same person replaces their snapshot vote", () => {
  const snap = C.normalize(EXPECTED);
  const r = C.mergeIssues(snap, [rest(31, "Carol", "barnard", "Moving", "2026-11-09T00:00:00Z")]);
  const t = C.tallyVotes(r.data.objects.get("barnard"));
  assert.equal(t.voters, 4); assert.equal(t.counts.moving, 4); assert.equal(t.counts.variable, 0); assert.equal(r.replaced, 1);
  const old = C.mergeIssues(snap, [rest(32, "carol", "barnard", "Unsure", "2026-10-01T00:00:00Z")]);   // older than her counted vote
  assert.equal(C.tallyVotes(old.data.objects.get("barnard")).counts.variable, 1);
  assert.equal(old.added, 0);
});

test("live votes: broken, unknown-class and moderated issues are skipped", () => {
  const snap = C.normalize(EXPECTED);
  const r = C.mergeIssues(snap, [{ number: 40 }, rest(41, "x", "barnard", "Comet", "2026-11-09T00:00:00Z"),
    rest(42, "y", "barnard", "Moving", "2026-11-09T00:00:00Z", { labels: ["classification", "invalid"] }), "junk"]);
  assert.equal(r.added, 0);
  assert.deepEqual([r.ignored.malformed, r.ignored.unknown_class, r.ignored.moderated], [2, 1, 1]);
});

test("live fetching is for the hosted site only (or asked for with ?votes=live)", () => {
  assert.equal(C.liveAllowed(HOSTED), true);
  for (const loc of [LOCAL, { protocol: "https:", hostname: "localhost" }, { protocol: "https:", hostname: "app.test" }, { protocol: "file:", hostname: "" }, null, undefined])
    assert.equal(C.liveAllowed(loc), false, JSON.stringify(loc));
  assert.equal(C.liveAllowed({ ...LOCAL, search: "?votes=live" }), true);
  assert.equal(C.liveAllowed({ ...HOSTED, search: "?target=barnard&votes=snapshot" }), false);
});

test("the live query asks GitHub's search for this repo's classification issues since the snapshot", () => {
  const u = new URL(C.liveUrl(C.normalize(EXPECTED)));
  assert.equal(u.origin + u.pathname, "https://api.github.com/search/issues");
  assert.equal(u.searchParams.get("q"), "repo:kneha07/WANDERERS is:issue label:classification created:>=2026-11-05");
  assert.equal(u.searchParams.get("per_page"), "100");
  assert.equal(new URL(C.liveUrl(C.emptyData())).searchParams.get("q"), "repo:kneha07/WANDERERS is:issue label:classification");
});

// ---------- the card ----------
test("the card: heading, five toggle buttons with their help, unique ids, shown", async () => {
  const { el } = await mounted();
  const h = el.innerHTML;
  assert.equal(el.hidden, false);
  assert.match(h, /<h3 class="cls-title" id="cls1-h">Classify this object <span class="tag-chip">Citizen science<\/span><\/h3>/);
  assert.match(h, /Watch the time-lapse/);
  const buttons = [...h.matchAll(/<button type="button" class="cls-btn" data-cls="(\w+)" aria-pressed="false" aria-describedby="([^"]+)">(\w+)<\/button>/g)];
  assert.deepEqual(buttons.map((b) => b[1]), C.KEYS);
  assert.deepEqual(buttons.map((b) => b[3]), C.CLASSES.map((c) => c.label));
  const ids = [...h.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length, "no duplicate ids");
  for (const b of buttons) for (const ref of b[2].split(" ")) assert.ok(ids.includes(ref), ref);
  for (const c of C.CLASSES) assert.ok(h.includes(C.esc(c.help)), c.key);
  assert.match(h, /role="group" aria-label="Your classification of Barnard&#39;s Star"/);
});

test("the candidate card has no heading of its own and asks about the track", async () => {
  const { el } = await mounted({}, { id: "10226-0001", kind: "candidate", name: "candidate 10226-0001", heading: false });
  assert.doesNotMatch(el.innerHTML, /<h3/);
  assert.match(el.innerHTML, /Look at its track and the sky view/);
});

test("names are escaped", async () => {
  const { el } = await mounted({}, { id: "barnard", kind: "target", name: `<img src=x onerror="alert(1)">` });
  assert.doesNotMatch(el.innerHTML, /<img/);
  assert.match(el.innerHTML, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
});

test("tally: counts, bars and a consensus with its agreement and voters", async () => {
  const { el } = await mounted();
  assert.match(el.innerHTML, /<p class="cls-consensus is-yes">Community consensus: <b>Moving<\/b>, 75% of 4 voters agree\.<\/p>/);
  assert.equal(countOf(el, "moving"), 3); assert.equal(countOf(el, "variable"), 1); assert.equal(countOf(el, "unsure"), 0);
  assert.match(el.innerHTML, /<i style="width:75%"><\/i>/);
  assert.match(el.innerHTML, /Community votes from GitHub, counted up to 5 Nov 2026\./);
});

test("tally: no consensus yet, and no votes at all", async () => {
  const w = await mounted({}, { id: "wise0855", kind: "target", name: "WISE 0855" });
  assert.match(w.el.innerHTML, /No consensus yet: 3 voters so far\. A consensus needs at least 3 voters, 60% of them agreeing\./);
  const e = await mounted({}, { id: "rw_aur", kind: "target", name: "RW Aurigae" });
  assert.match(e.el.innerHTML, /No community votes yet\./);
  assert.match(e.el.innerHTML, /Pick one\. Your vote is kept on this device and counted here straight away\./);
});

test("voting: pressed state, saved on the device, counted at once as yours, and a pre-filled link to send it", async () => {
  const { inst, el, storage } = await mounted({}, { id: "wise0855", kind: "target", name: "WISE 0855" });
  click(el, btn(el, "moving"));
  assert.deepEqual(pressed(el), ["moving"]);
  assert.deepEqual(JSON.parse(storage.getItem(C.STORE_KEY)), { "target:wise0855": { cls: "moving", at: "2026-11-10T12:00:00Z" } });
  assert.equal(countOf(el, "moving"), 2);
  assert.match(el.innerHTML, /<span class="cls-yours">incl\. yours<\/span>/);
  assert.match(el.innerHTML, /Community consensus: <b>Moving<\/b>, 50% of 4 voters agree|No consensus yet: 4 voters/);
  assert.match(el.innerHTML, /Your vote: <b>Moving<\/b>\. Saved on this device and counted here\./);
  const href = /data-send="1" href="([^"]+)" target="_blank" rel="noopener noreferrer">Send my vote/.exec(el.innerHTML)[1].replace(/&amp;/g, "&");
  assert.equal(href, C.issueUrl("wise0855", "target", "moving"));
  assert.match(el.innerHTML, /needs a free GitHub account and creates a public issue/);
  assert.equal(inst.summary("wise0855", "target").mineCounted, true);
});

test("your vote can tip a consensus here, and pressing it again takes it back", async () => {
  const { inst, el, storage } = await mounted({}, { id: "10226-0001", kind: "candidate", name: "c" });
  click(el, btn(el, "stationary"));
  assert.equal(inst.summary("10226-0001", "candidate").consensus, null, "2 of 4 is not a consensus");
  click(el, btn(el, "moving"));
  assert.equal(inst.summary("10226-0001", "candidate").agreement, 0.75);
  click(el, btn(el, "moving"));
  assert.deepEqual(pressed(el), []);
  assert.deepEqual(JSON.parse(storage.getItem(C.STORE_KEY)), {});
  assert.equal(countOf(el, "moving"), 2);
});

test("keyboard: arrows, Home and End move between the choices (and do not step the time-lapse)", async () => {
  const { el, doc } = await mounted();
  const at = () => doc.activeElement && doc.activeElement.getAttribute("data-cls");
  let ev = key(el, btn(el, "moving"), "ArrowRight");
  assert.equal(at(), "variable"); assert.ok(ev.prevented && ev.stopped);
  key(el, doc.activeElement, "ArrowDown"); assert.equal(at(), "stationary");
  key(el, doc.activeElement, "End"); assert.equal(at(), "unsure");
  key(el, doc.activeElement, "ArrowRight"); assert.equal(at(), "moving", "wraps around");
  key(el, doc.activeElement, "ArrowLeft"); assert.equal(at(), "unsure");
  key(el, doc.activeElement, "Home"); assert.equal(at(), "moving");
  ev = key(el, doc.activeElement, "Enter");
  assert.ok(!ev.prevented && !ev.stopped, "Enter and Space are the button's own");
  ev = key(el, { closest: () => null }, "ArrowRight");
  assert.ok(!ev.prevented, "keys outside the choices are left alone");
});

test("keyboard focus stays on the choice you pressed when the card redraws", async () => {
  const { el, doc } = await mounted();
  btn(el, "variable").focus();
  click(el, doc.activeElement);
  assert.equal(doc.activeElement.getAttribute("data-cls"), "variable");
  assert.ok(el.contains(doc.activeElement), "the new button, not the replaced one");
});

test("blocked storage: the vote still works for this visit, and the card says so", async () => {
  const { inst, el } = await mounted({ storage: brokenStorage });
  assert.match(el.innerHTML, /not letting the site save/);
  click(el, btn(el, "artifact"));
  assert.deepEqual(pressed(el), ["artifact"]);
  assert.equal(inst.mine("barnard", "target").cls, "artifact");
  const none = await mounted({ storage: null });
  click(none.el, btn(none.el, "unsure"));
  assert.deepEqual(pressed(none.el), ["unsure"]);
});

test("storage that holds junk is ignored, and only good entries are kept", async () => {
  for (const raw of ["{not json", "[1,2]", "null", '"x"']) {
    const { el } = await mounted({ storage: memStorage({ [C.STORE_KEY]: raw }) });
    assert.deepEqual(pressed(el), [], raw);
    assert.doesNotMatch(el.innerHTML, /not letting the site save/, raw);
  }
  const keep = { "target:barnard": { cls: "variable", at: "2026-11-02T00:00:00Z", sent: { cls: "comet", at: "x" } }, "target:r_dra": { cls: "planet" } };
  const { inst, el } = await mounted({ storage: memStorage({ [C.STORE_KEY]: JSON.stringify(keep) }) });
  assert.deepEqual(pressed(el), ["variable"]);
  assert.deepEqual(inst.mine("barnard", "target"), { cls: "variable", at: "2026-11-02T00:00:00Z" });
  assert.equal(inst.mine("r_dra", "target"), null);
});

test("sending: the card remembers you opened the form, and asks again after a change of mind", async () => {
  const { el, inst } = await mounted({}, { id: "wise0855", kind: "target", name: "WISE 0855" });
  click(el, btn(el, "moving"));
  click(el, el.querySelector("[data-send]"));
  assert.deepEqual(inst.mine("wise0855", "target").sent, { cls: "moving", at: "2026-11-10T12:00:00Z" });
  assert.match(el.innerHTML, /You opened the GitHub form for it on 10 Nov 2026\./);
  assert.match(el.innerHTML, /Open the GitHub form again/);
  click(el, btn(el, "variable"));
  assert.match(el.innerHTML, /You changed it after sending Moving\. Send it again: only your newest vote counts\./);
  assert.match(el.innerHTML, /class=Variable/);
});

test("a vote you sent is not counted twice once the community count holds it", async () => {
  const storage = memStorage({ [C.STORE_KEY]: JSON.stringify({ "target:wise0855": { cls: "moving", at: "2026-11-08T00:00:00Z", sent: { cls: "moving", at: "2026-11-08T00:00:00Z" } } }) });
  const before = await mounted({ storage }, { id: "wise0855", kind: "target", name: "w" });
  assert.equal(countOf(before.el, "moving"), 2, "not in the snapshot yet: counted here");
  const snap = clone(EXPECTED);
  snap.objects.wise0855.votes.push({ issue: 40, user: "me", class: "moving", at: "2026-11-08T00:01:00Z" });
  const after = await mounted({ storage, snap }, { id: "wise0855", kind: "target", name: "w" });
  assert.equal(countOf(after.el, "moving"), 2, "now in the snapshot: counted once");
  assert.equal(after.inst.summary("wise0855", "target").mineCounted, false);
});

test("a missing, broken or unreachable snapshot leaves an empty tally and a working vote", async () => {
  const routes = [[() => reply({}, 404), /No community votes have been published yet/], [() => reply(new SyntaxError("bad")), /could not be loaded/],
    [() => reply({}, 500), /could not be loaded/], [() => new TypeError("Failed to fetch"), /could not be loaded/]];
  for (const [route, msg] of routes) {
    const { el, inst } = await mounted({ fetch: fakeFetch(route) });
    assert.match(el.innerHTML, msg);
    assert.match(el.innerHTML, /No community votes yet\./);
    click(el, btn(el, "moving"));
    assert.equal(countOf(el, "moving"), 1);
    assert.equal(inst.state().data.objects.size, 0);
  }
  const s = setup({ fetch: null });
  s.inst.mount(s.el, { id: "barnard", kind: "target" });
  await s.inst.ready();
  assert.match(s.el.innerHTML, /could not be loaded/);
});

test("the card says it is loading until the snapshot arrives", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const s = setup({ fetch: fakeFetch(() => gate.then(() => reply(EXPECTED))) });
  s.inst.mount(s.el, { id: "barnard", kind: "target" });
  assert.match(s.el.innerHTML, /Loading the community votes…/);
  release();
  await s.inst.ready();
  assert.match(s.el.innerHTML, /75% of 4 voters agree/);
});

test("hosted site: newer votes from GitHub's search are added, and older issue numbers are skipped", async () => {
  const fetch = fakeFetch((u) => (u === C.DATA_URL ? reply(EXPECTED)
    : u.startsWith("https://api.github.com/search/issues?") ? reply({ total_count: 3, items: [rest(4, "dave", "barnard", "Moving", "2026-11-01T13:00:00Z"),
      rest(26, "zoe", "barnard", "Moving", "2026-11-09T09:00:00Z"), rest(27, "yan", "barnard", "Stationary", "2026-11-09T10:00:00Z")] })
    : new TypeError("unexpected " + u)));
  const { el, inst } = await mounted({ fetch, location: HOSTED });
  assert.deepEqual(fetch.calls, [C.DATA_URL, C.liveUrl(C.normalize(EXPECTED))]);
  assert.equal(inst.state().live, 2);
  assert.match(el.innerHTML, /Community consensus: <b>Moving<\/b>, 67% of 6 voters agree\./);
  assert.match(el.innerHTML, /plus 2 newer votes fetched live\./);
});

test("hosted site: a rate limit, an error or no network keeps the snapshot, silently", async () => {
  for (const live of [() => reply({ message: "API rate limit exceeded" }, 403), () => reply({}, 422), () => new TypeError("Failed to fetch"), () => reply(new SyntaxError("x")), () => reply({ items: "no" })]) {
    const fetch = fakeFetch((u) => (u === C.DATA_URL ? reply(EXPECTED) : live()));
    const { el, inst } = await mounted({ fetch, location: HOSTED });
    assert.equal(fetch.calls.length, 2);
    assert.equal(inst.state().live, 0);
    assert.equal(inst.state().state, "ok");
    assert.match(el.innerHTML, /75% of 4 voters agree/);
    assert.doesNotMatch(el.innerHTML, /fetched live/);
  }
});

test("local runs and tests never call the GitHub API", async () => {
  const fetch = fakeFetch((u) => (u === C.DATA_URL ? reply(EXPECTED) : new Error("must not be called: " + u)));
  await mounted({ fetch, location: LOCAL });
  await mounted({ fetch, location: { protocol: "https:", hostname: "localhost", search: "" } });
  assert.ok(fetch.calls.every((u) => u === C.DATA_URL), fetch.calls.join(" "));
});

test("hosted site: one live search per few minutes per tab, kept in session storage", async () => {
  const session = memStorage();
  let t = NOW;
  const items = [rest(26, "zoe", "barnard", "Moving", "2026-11-09T09:00:00Z")];
  const make = () => fakeFetch((u) => (u === C.DATA_URL ? reply(EXPECTED) : reply({ items })));
  const a = make(), b = make(), c = make();
  await mounted({ fetch: a, session, location: HOSTED, now: () => t });
  const second = await mounted({ fetch: b, session, location: HOSTED, now: () => t + 60 * 1000 });
  assert.deepEqual(b.calls, [C.DATA_URL], "the cached answer is used");
  assert.equal(second.inst.state().live, 1);
  t += C.LIVE_TTL_MS + 1;
  await mounted({ fetch: c, session, location: HOSTED, now: () => t });
  assert.equal(c.calls.length, 2, "asked again once the cache is old");
  assert.equal(a.calls.length, 2);
  await mounted({ fetch: make(), session: brokenStorage, location: HOSTED });   // a blocked session store is fine too
});

// ---------- the Sky Survey table badges ----------
function fakeRows(ids) {
  return ids.map((id) => {
    const cell = { html: '<span class="badge b-unex">unexplained</span>', insertAdjacentHTML(_, h) { this.html += h; } };
    const old = id === "11391-0001" ? [{ removed: false, remove() { this.removed = true; } }] : [];
    return { id, cell, old, getAttribute: (k) => (k === "data-id" ? id : null), querySelectorAll: (s) => (s === ".cls-badge" ? old : []),
      querySelector: (s) => (s === ".badge" ? { parentElement: cell } : null) };
  });
}

test("survey rows get a consensus badge only when there is a consensus; stale badges go", async () => {
  const s = setup();
  const rows = fakeRows(["10226-0001", "11391-0001", "9999-0001"]);
  s.inst.badges({ querySelectorAll: (sel) => (sel === "tr[data-id]" ? rows : []) });
  await s.inst.ready();
  assert.match(rows[0].cell.html, /<span class="cls-badge" title="Community consensus: Moving, 67% of 3 voters"><span class="visually-hidden">Community: <\/span>Moving 67%<\/span>$/);
  assert.equal(rows[1].cell.html, '<span class="badge b-unex">unexplained</span>', "one voter: no consensus, no badge");
  assert.ok(rows[1].old[0].removed);
  assert.doesNotMatch(rows[2].cell.html, /cls-badge/);
  assert.equal(s.inst.badgeHtml("9999-0001"), "");
  s.inst.badges(null);   // nothing to decorate: no error
});

test("a card re-used for another candidate keeps one set of listeners", async () => {
  const { inst, el } = await mounted({}, { id: "10226-0001", kind: "candidate", name: "a" });
  inst.mount(el, { id: "11391-0001", kind: "candidate", name: "b" });
  assert.equal(el.listeners.click.length, 1);
  click(el, btn(el, "unsure"));
  assert.equal(inst.mine("11391-0001", "candidate").cls, "unsure");
  assert.equal(inst.mine("10226-0001", "candidate"), null);
  inst.unmount(el);
  assert.equal(el.hidden, true); assert.equal(el.innerHTML, "");
  click(el, { closest: (s) => (s === "[data-cls]" ? { getAttribute: () => "moving" } : null) });
  assert.equal(inst.mine("11391-0001", "candidate").cls, "unsure", "an unmounted card ignores clicks");
  assert.equal(inst.mount(el, { id: "" }), null);
  assert.equal(inst.mount(null, { id: "x" }), null);
});
