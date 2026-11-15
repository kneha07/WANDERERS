// Star search facts and coordinates shared by the console and the Sky Compass (app/search.js).
// node --test test/search.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP = path.join(__dirname, "..", "app");
const win = {};
new Function("window", fs.readFileSync(path.join(APP, "search.js"), "utf8"))(win);
const SS = win.StarSearch;
const kindOf = (spect) => (SS.describe({ spect })[0] || "");

test("luminosity class: giants are giants, only class I stars are supergiants", () => {
  const cases = {
    K0III: /: a giant /, K2IIIp: /: a giant /, "K1.5IIIFe-0.5": /: a giant /, "G8III-IV": /: a giant /, "M0III+": /: a giant /,
    "K3II-III": /: a giant /, "O9.5II": /: a bright giant /, G2Ib: /: a supergiant /, "M1-M2Ia-Iab": /: a supergiant /,
    "M1.5Iab-Ib": /: a supergiant /, "F7:Ib-IIv SB": /: a supergiant /, B8Ia: /: a supergiant /, "F5IV-V": /: a subgiant /,
    G2V: /: a main-sequence star/, sdM1: /: a subdwarf/,
  };
  for (const [sp, re] of Object.entries(cases)) assert.match(kindOf(sp), re, sp);
});

test("white dwarfs keep their description even without a colour class", () => {
  assert.match(kindOf("DA2"), /Spectral type DA2: a white dwarf/);
  assert.equal(kindOf("C6,3"), "Spectral type C6,3.");
});

test("every catalogue star with luminosity class III is described as a giant, never a supergiant", () => {
  const rows = JSON.parse(fs.readFileSync(path.join(APP, "data", "stars.json"), "utf8"));
  const wrong = rows.filter((r) => /III/.test(r[5] || "") && /supergiant/.test(kindOf(r[5])));
  assert.equal(wrong.length, 0, wrong.slice(0, 5).map((r) => `${r[0]} ${r[5]}`).join(", "));
});

test("RA/Dec text never shows 60 seconds: rounding carries into the minute", () => {
  assert.equal(SS.hms(15 * (1 + 59 / 60 + 59.97 / 3600)), "02h00m00.0s");
  assert.equal(SS.hms(359.99999), "00h00m00.0s");
  assert.equal(SS.hms(101.28722), "06h45m08.9s");      // Sirius
  assert.equal(SS.dms(-(10 + 59 / 60 + 59.6 / 3600)), "-11d00m00s");
  assert.equal(SS.dms(-16.71612), "-16d42m58s");
  assert.equal(SS.dms(0.5), "+00d30m00s");
  const rows = JSON.parse(fs.readFileSync(path.join(APP, "data", "stars.json"), "utf8"));
  for (const r of rows) {
    assert.doesNotMatch(SS.hms(r[2]), /m60\.0s$/, r[0]);
    assert.doesNotMatch(SS.dms(r[3]), /m60s$/, r[0]);
  }
});
