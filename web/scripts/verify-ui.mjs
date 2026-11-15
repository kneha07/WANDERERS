// Behaviour checks for /explore/ in a real browser. Run from web/: node scripts/verify-ui.mjs [baseUrl]
// Needs the dev server (npm run dev) with a backend that has Barnard's Star, RW Aur and WISE 0855 (det=D6).
import { createRequire } from 'node:module'
const req = createRequire(new URL('../package.json', import.meta.url))
const { chromium } = req('playwright')
const base = process.argv[2] || 'http://localhost:5183/explore/'
const out = []
const check = (name, ok, detail = '') => out.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`)
const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

// First visit: the tutorial opens once; Esc closes it and focus goes back.
await page.goto(base)
await page.locator('dialog[open]').waitFor({ timeout: 5000 })
check('tutorial opens on the first visit', true)
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
check('Esc closes the tutorial', !(await page.locator('dialog[open]').count()))
await page.reload()
await page.waitForTimeout(800)
check('tutorial shows only once', !(await page.locator('dialog[open]').count()))
await page.locator('#help-btn').click()
await page.locator('dialog[open]').waitFor()
await page.locator('#layer-close').click()
await page.waitForTimeout(400)
check('focus returns to the ? button', await page.evaluate(() => document.activeElement?.id === 'help-btn'))

// A chip loads a target; a second chip; Back returns to the first from the cache.
await page.locator("[data-target=\"Barnard's Star\"]").click()
await page.locator('.viewer[data-status=result]').waitFor({ timeout: 120000 })
check('Barnard result shows', (await page.locator('#target-name').innerText()).includes('Barnard'))
await page.locator("[data-target='RW Aur']").click()
await page.locator("#target-name:has-text('RW Aur')").waitFor({ timeout: 120000 })
await page.goBack()
await page.waitForTimeout(300)
check('Back returns to the previous target at once', (await page.locator('#target-name').innerText()).includes('Barnard'))

// Keyboard: Space pauses or plays, arrows step; inside the search field they type.

await page.evaluate(() => document.activeElement && document.activeElement.blur())
const label = () => page.locator('.frame-label').innerText()
await page.keyboard.press('Space') // pause (autoplay is on)
const a = await label()
await page.waitForTimeout(1200)
const b = await label()
check('Space pauses the flipbook', a === b, a)
await page.keyboard.press('ArrowRight')
const c = await label()
check('ArrowRight steps one frame', c !== b, `${b} -> ${c}`)
await page.locator('#q').focus()
await page.keyboard.press('ArrowLeft')
check('arrows inside the search field do not step', (await label()) === c)

// Mark the target: it is a known Gaia star (green), and the URL holds the mark.
await page.evaluate(() => document.activeElement && document.activeElement.blur())
const box = await page.locator('#stage').boundingBox()
const ring = await page.evaluate(() => { const c = document.querySelector('#stage .ring'); return c ? { x: +c.getAttribute('cx'), y: +c.getAttribute('cy') } : null })
const n = 49
await page.mouse.click(box.x + (ring.x / n) * box.width, box.y + (ring.y / n) * box.height)
await page.locator('.cand').first().waitFor()
const badge = await page.locator('.cand .badge').first().innerText()
check('a mark on Barnard is known in Gaia', /Known in Gaia DR3/.test(badge), badge)
check('the URL holds the mark (replaceState)', /[?&]c=/.test(page.url()), page.url())
const toast = await page.locator('.toast').innerText()
check('one toast says the mark', /Candidate 1 marked/.test(toast), toast)
await page.reload()
await page.locator('.viewer[data-status=result]').waitFor({ timeout: 60000 })
check('the mark survives a reload', (await page.locator('.cand').count()) === 1)
await page.getByRole('button', { name: 'Copy share link' }).click()
await page.waitForTimeout(300)
const clip = await page.evaluate(() => navigator.clipboard.readText())
check('Copy share link copies the URL with the mark', clip === page.url(), clip)

// Look presets go to the URL and persist across targets; D6 disables colour.
await page.locator('#look').selectOption('colour')
await page.waitForTimeout(300)
check('look=colour in the URL', page.url().includes('look=colour'))
check('the honesty label shows', (await page.locator('.look-label').innerText()).includes('False-colour infrared'))
await page.locator("[data-target='WISE J085510.83-071442.5']").click()
await page.locator("#target-name:has-text('WISE')").waitFor({ timeout: 180000 })
await page.locator('.viewer[data-status=result]').waitFor({ timeout: 180000 })
check('the look persists across targets', page.url().includes('look=colour'))
const disabled = await page.locator('#look option[value=colour]').evaluate((o) => o.disabled)
check('D6 view disables the colour presets', disabled)
const summary = await page.locator('#brightness .summary').innerText()
check('WISE 0855 D6 brightness shows a change', /Change: \d+%/.test(summary), summary)

// Difference view and the timeline.
await page.getByRole('button', { name: 'Difference' }).click()
check('view=diff in the URL', page.url().includes('view=diff'))
await page.getByRole('button', { name: 'Blink' }).click()
const tl = await page.locator('.timeline').boundingBox()
await page.mouse.click(tl.x + tl.width - 20, tl.y + 30)
const now = await page.locator('.timeline').getAttribute('aria-valuenow')
check('a click near the end of the timeline jumps to the last frame', now === (await page.locator('.timeline').getAttribute('aria-valuemax')), now)

// Sorting the frames table.
await page.locator('#frames th button', { hasText: 'Images' }).click()
check('the frames table sorts by a column', (await page.locator('#frames th[aria-sort=ascending]').count()) === 1)

check('no page errors', errors.length === 0, errors.join(' | '))
console.log(out.join('\n'))
await browser.close()
process.exitCode = out.some((l) => l.startsWith('FAIL')) ? 1 : 0
