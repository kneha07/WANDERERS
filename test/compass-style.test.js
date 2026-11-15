// Sky Compass styles (app/compass.css with app/brand.css): things that must stay visible in Day and Night.
// node --test test/compass-style.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (p) => fs.readFileSync(path.join(__dirname, "..", "app", p), "utf8");
const css = read("compass.css"), brand = read("brand.css"), html = read("compass.html");
const rule = (src, sel) => {   // declarations of the first rule whose selector list is exactly `sel`
  const re = new RegExp(`(^|\\})\\s*${sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`, "m");
  const m = src.match(re); return m ? m[2] : null;
};
const lum = (hex) => { const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };

test("the intro's Skip button is not the brand's off-screen .skip link", () => {
  assert.match(rule(brand, ".skip") || "", /left:\s*-9999px/, "brand.css hides .skip (a keyboard skip link)");
  const cls = html.match(/<button id="skipIntro" class="([^"]+)"/)[1].split(/\s+/);
  assert.ok(!cls.includes("skip"), `#skipIntro classes ${cls}: .skip would put it at left -9999px`);
  const own = cls.find((c) => rule(css, "." + c) && /position:\s*absolute/.test(rule(css, "." + c)));
  assert.ok(own, "compass.css positions the Skip button");
});

test("the intro stays dark in Day mode, so its text keeps the light Night colours", () => {
  const cosmos = rule(css, ".cosmos");
  assert.match(cosmos, /background:\s*#000/);
  const text = cosmos.match(/--text:\s*(#[0-9a-fA-F]{6})/);
  assert.ok(text && lum(text[1]) > 0.7, "the intro defines a light --text for its title and Skip button");
  assert.match(cosmos, /color:\s*var\(--text\)/);
  assert.doesNotMatch(rule(css, ".cosmos-title") || "", /color:/, "the title inherits the intro colour");
});

test("the radar panel stays dark: its canvas labels are drawn in light colours", () => {
  const radar = rule(css, ".radar");
  assert.doesNotMatch(radar, /background:\s*var\(/, "a themed (white in Day) background hides the light E/S/W labels");
  const bg = radar.match(/background:\s*rgba\((\d+),\s*(\d+),\s*(\d+)/);
  assert.ok(bg && Math.max(+bg[1], +bg[2], +bg[3]) < 60, "dark radar background");
});

test("on the photographs the note's dark pill keeps 4.5:1 contrast, even over a white star", () => {
  const pill = rule(css, ".sky-note.on-photo") || "";
  const bg = pill.match(/background:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/), fg = pill.match(/color:\s*(#[0-9a-fA-F]{6})/);
  assert.ok(bg && fg, "the pill has an rgba background and a hex text colour");
  const a = +bg[4], onWhite = "#" + [1, 2, 3].map((i) => Math.round(+bg[i] * a + 255 * (1 - a)).toString(16).padStart(2, "0")).join("");
  const ratio = (lum(fg[1]) + 0.05) / (lum(onWhite) + 0.05);
  assert.ok(ratio >= 4.5, `contrast ${ratio.toFixed(1)}:1 over a white star`);
});

test("the details sheet's path card styles apply (#dPath is itself the .path-card)", () => {
  assert.match(html, /id="dPath" class="path-card"/);
  assert.doesNotMatch(css, /#dPath \.path-card/, "a descendant selector never matches the element itself");
  assert.match(rule(css, "#dPath.path-card") || "", /padding:/);
});
