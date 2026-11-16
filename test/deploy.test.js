// Tests for scripts/deploy.js (the entry-page check before a deploy).
// Run from the repository root:  node --test test/deploy.test.js
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const D = require("../scripts/deploy.js");

test("the real app/ has every entry page", () => assert.deepEqual(D.missing(), []));

test("an empty or absent entry page is reported", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "deploy-"));
  for (const f of D.ENTRY) { fs.mkdirSync(path.dirname(path.join(dir, f)), { recursive: true }); fs.writeFileSync(path.join(dir, f), "x"); }
  fs.writeFileSync(path.join(dir, "sw.js"), "");
  fs.rmSync(path.join(dir, "survey.html"));
  assert.deepEqual(D.missing(dir), ["survey.html", "sw.js"]);
});

test("the list matches the Pages workflow", () => {
  const yml = fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", "pages.yml"), "utf8");
  const list = yml.match(/for f in ([^;]+); do test -s/)[1].trim().split(/\s+/);
  assert.deepEqual(D.ENTRY, list);
});
