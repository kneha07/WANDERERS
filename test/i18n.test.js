// Language dictionaries (app/i18n-<lang>.js, built by scripts/build_i18n.py): a number template such as
// "{0} light-years away" must keep every placeholder in its translation, or i18n.js drops that number from the page.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const app = path.join(__dirname, "..", "app");
const ph = (s) => (s.match(/\{\d+\}/g) || []).sort().join();

for (const f of fs.readdirSync(app).filter((n) => /^i18n-[a-z]{2}\.js$/.test(n))) {
  test(`${f}: every translation keeps the placeholders of its English template`, () => {
    const box = { window: {} };
    vm.runInNewContext(fs.readFileSync(path.join(app, f), "utf8"), box);
    const d = box.window.I18N_DICT;
    assert.ok(d && Object.keys(d).length > 500, "dictionary loads");
    const bad = Object.entries(d).filter(([k, v]) => ph(k) !== ph(v)).map(([k]) => k);
    assert.deepStrictEqual(bad, []);
  });
}
