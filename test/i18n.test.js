// Language dictionaries (app/i18n-<lang>.js, built by scripts/build_i18n.py): a number template such as
// "{0} light-years away" must keep every placeholder in its translation, or i18n.js drops that number from the page.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const app = path.join(__dirname, "..", "app");
const ph = (s) => (s.match(/\{\d+\}/g) || []).sort().join();

// The browser language picks the menu entry: Hong Kong / Macau before Taiwan, so "zh-Hant-HK" is not read as Taiwan.
const pageLang = (browser, query = "") => {
  const html = {};
  const box = {
    URLSearchParams, location: { search: query, href: "http://x/" }, localStorage: { getItem: () => null, setItem() {} },
    navigator: { language: browser },
    document: { documentElement: html, querySelectorAll: () => [], createElement: () => ({}), head: { append() {} } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(app, "i18n.js"), "utf8"), box);
  return html.lang || "en";
};
test("i18n.js: browser language and ?lang pick the right version", () => {
  assert.strictEqual(pageLang("zh-CN"), "zh-CN");
  assert.strictEqual(pageLang("zh"), "zh-CN");
  assert.strictEqual(pageLang("zh-TW"), "zh-TW");
  assert.strictEqual(pageLang("zh-Hant"), "zh-TW");
  assert.strictEqual(pageLang("zh-HK"), "zh-HK");
  assert.strictEqual(pageLang("zh-Hant-HK"), "zh-HK");
  assert.strictEqual(pageLang("zh-MO"), "zh-HK");
  assert.strictEqual(pageLang("ko-KR"), "ko");
  assert.strictEqual(pageLang("fr-FR"), "en");
  assert.strictEqual(pageLang("zh-CN", "?lang=hk"), "zh-HK");
});

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
