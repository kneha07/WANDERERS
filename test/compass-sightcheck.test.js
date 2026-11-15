// Sky Compass: a sight check only calibrates when the user taps Calibrate after aiming, and the Day/Night
// switch really changes the page's colours.  node --test test/compass-sightcheck.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
const js = read("app/compass.js"), html = read("app/compass.html"), css = read("app/compass.css");

test("tapping a landmark, sky object, direction or pasted spot starts aiming; it does not calibrate", () => {
  assert.match(js, /#northList[\s\S]{0,200}|northList"\)\.querySelectorAll\("button"\)\.forEach\(\(b\) => \(b\.onclick = \(\) => startAim\(/);
  assert.match(js, /\.dirs button[\s\S]{0,300}startAim\(/, "This is North/East/South/West");
  assert.match(js, /lmUse[\s\S]{0,400}startAim\(/, "pasted map coordinates");
  const calls = [...js.matchAll(/applyFine\(/g)].length;
  assert.equal(calls, 2, "applyFine is defined once and called only from the Calibrate button");
  assert.match(js, /\$\("aimGo"\)\.onclick[\s\S]{0,200}applyFine\(S\.aim/);
});

test("the aim panel has Calibrate and Cancel, and Cancel changes nothing", () => {
  for (const id of ["aimBar", "aimTitle", "aimText", "aimMsg", "aimGo", "aimCancel"]) assert.match(html, new RegExp(`id="${id}"`), id);
  assert.match(html, /id="aimGo"[^>]*>Calibrate</);
  const endAim = js.match(/function endAim\(\) \{([^}]*)\}/)[1];
  assert.doesNotMatch(endAim, /fineTune|fineAz|applyFine/, "Cancel must not touch north");
});

test("Day/Night: the Sky Compass has its own light tokens, so the switch changes the page", () => {
  const block = (sel) => { const i = css.indexOf(sel); assert.ok(i >= 0, sel); return css.slice(i, css.indexOf("}", i)); };
  const night = block(':root, :root[data-theme="dark"]'), day = block(':root[data-theme="light"]');
  for (const v of ["--space", "--panel", "--text", "--dim", "--btn-bg", "--input-bg", "--hud-bg"]) {
    assert.match(night, new RegExp(`${v}:`), `night ${v}`);
    assert.match(day, new RegExp(`${v}:`), `day ${v}`);
  }
  assert.doesNotMatch(css, /:root, :root\[data-theme\] \{/, "a selector that matches both themes would freeze the colours");
  assert.match(html, /class="theme-toggle"/);
  assert.match(html, /<script src="theme\.js"><\/script>/);
});
