// Gate B runner (FIX_AND_RESTYLE): drives the built SPA in the installed Edge via Playwright,
// records the stream timings (header / first photos / done), checks the nav row, the frame
// captions, keyboard access to the popover and the lightbox, the reduced-motion mode and the
// absence of internal enum names in the UI chrome, and saves screenshots to docs/screenshots/.
//
// Usage: node scripts/ui_gate.mjs [--base http://127.0.0.1:8000] [--qid Q49108] [--qid-mobile Q2783344]
// Requires a running backend that serves the built frontend (backend/app/static).

import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const args = process.argv.slice(2)
const opt = (name, fallback) => {
  const i = args.indexOf(name)
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback
}
const BASE = opt('--base', 'http://127.0.0.1:8000')
const QID_DESKTOP = opt('--qid', 'Q49108')
const QID_MOBILE = opt('--qid-mobile', 'Q2783344')
const WARM = args.includes('--warm') // reuse cached profiles: no timing checks, no quota spent
const SHOTS = !WARM || args.includes('--shots') // warm runs keep the cold-run screenshots
const OUT = resolve('docs/screenshots')
mkdirSync(OUT, { recursive: true })

const ENUM_RE = /\b(campus|dormitory|classroom|library|student_life|commons_category|official_site)\b/i
const report = { checks: [], timings: {}, screenshots: [] }
const check = (name, ok, detail = '') => {
  report.checks.push({ name, ok, detail })
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
}

async function shoot(page, name) {
  if (!SHOTS) return
  const file = resolve(OUT, `${name}.png`)
  await page.screenshot({ path: file, fullPage: false })
  report.screenshots.push(file)
  console.log('shot', file)
}

async function waitTiming(page, key, timeoutMs) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const value = await page.evaluate((k) => (window.__vcTimings || {})[k], key)
    if (typeof value === 'number') return value
    await page.waitForTimeout(100)
  }
  return null
}

async function uiChromeText(page) {
  return page.evaluate(() => {
    const parts = []
    // UI chrome only: photo captions and the lightbox carry titles from Wikimedia (data, not UI)
    for (const el of document.querySelectorAll('[role="tab"], [role="status"], header, main > p, main > section > p, footer, button, [role="progressbar"]')) {
      if (el.closest('figure') || el.closest('[role="dialog"]')) continue
      parts.push(el.textContent || '')
      parts.push(el.getAttribute('aria-label') || '')
    }
    return parts.join('\n')
  })
}

async function runProfile(page, label, qid, { cold }) {
  const url = `${BASE}/u/${qid}${cold ? '?refresh=1' : ''}`
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  const header = await waitTiming(page, 'header', 15000)
  const first = await waitTiming(page, 'firstPhotos', 40000)
  if (first !== null) {
    await page.waitForTimeout(120) // frames mid-develop
    await shoot(page, `${label}-streaming`)
  }
  const done = await waitTiming(page, 'done', 45000)
  report.timings[label] = { header, firstPhotos: first, done }
  if (cold) {
    check(`${label}: header <= 3000 ms`, header !== null && header <= 3000, `${header} ms`)
    check(`${label}: first photos <= 10000 ms`, first !== null && first <= 10000, `${first} ms`)
    check(`${label}: done <= 30000 ms`, done !== null && done <= 30000, `${done} ms`)
  }
  await page.waitForTimeout(1200) // let the last frames develop and the progress line fade
  await shoot(page, `${label}-finished`)
  return { header, first, done }
}

async function checkFinishedPage(page, label) {
  const tabs = await page.locator('[role="tablist"]').count()
  check(`${label}: exactly one sticky nav row`, tabs === 1, `${tabs} tablists`)
  const tabTexts = (await page.locator('[role="tab"]').allTextContents()).map((s) => s.trim())
  const required = ['Общежития', 'Спорт', 'Лаборатории', 'Студенческая жизнь']
  const missing = required.filter((r) => !tabTexts.some((t) => t.startsWith(r)))
  check(`${label}: the four required filters are nav items`, missing.length === 0, missing.join(', ') || tabTexts.join(' | '))
  const sticky = await page.locator('[role="tablist"]').evaluate((el) => getComputedStyle(el.parentElement).position)
  check(`${label}: nav row is sticky`, sticky === 'sticky', sticky)

  const frames = page.locator('figure.frame')
  const frameCount = await frames.count()
  check(`${label}: frames rendered`, frameCount > 0, `${frameCount} frames`)
  let bad = 0
  for (let i = 0; i < Math.min(frameCount, 12); i++) {
    const f = frames.nth(i)
    const hasMark = (await f.locator('.mark').count()) === 1
    const link = f.locator('figcaption a')
    const hasLink = (await link.count()) === 1
    const linkText = hasLink ? await link.textContent() : ''
    const underlined = hasLink ? await link.evaluate((a) => getComputedStyle(a).textDecorationLine.includes('underline')) : false
    const hasDate = /снято|опубликовано|загружено|дата неизвестна/.test(linkText || '')
    if (!(hasMark && hasLink && underlined && hasDate)) bad++
  }
  check(`${label}: every frame shows mark + underlined source + date sentence`, bad === 0, `${bad} of ${Math.min(frameCount, 12)} frames failing`)

  const chrome = await uiChromeText(page)
  const enumHit = chrome.match(ENUM_RE)
  check(`${label}: no internal enum names in the UI chrome`, !enumHit, enumHit ? `found "${enumHit[0]}"` : '')

  const radius = await page.evaluate(() => {
    let max = 0
    for (const el of document.querySelectorAll('button, a, figure, div, p, input, section')) {
      const r = parseFloat(getComputedStyle(el).borderTopLeftRadius || '0')
      if (!el.classList.contains('mark') && r > max) max = r
    }
    return max
  })
  check(`${label}: no rounded corners (except the 10px marks)`, radius === 0, `max radius ${radius}px`)
  const shadows = await page.evaluate(() => {
    let n = 0
    for (const el of document.querySelectorAll('*')) {
      const s = getComputedStyle(el).boxShadow
      if (s && s !== 'none') n++
    }
    return n
  })
  check(`${label}: no box shadows`, shadows === 0, `${shadows} elements with shadows`)
  const blue = await page.evaluate(() => {
    let n = 0
    for (const el of document.querySelectorAll('*')) {
      if (el.closest('.leaflet-container')) continue
      const s = getComputedStyle(el)
      for (const c of [s.color, s.backgroundColor, s.borderTopColor]) {
        const m = /rgba?\((\d+), (\d+), (\d+)/.exec(c || '')
        if (m && Number(m[3]) > Number(m[1]) + 40 && Number(m[3]) > Number(m[2]) + 40 && (s.backgroundColor === c ? s.backgroundColor !== 'rgba(0, 0, 0, 0)' : true)) n++
      }
    }
    return n
  })
  check(`${label}: no blue accents outside the map`, blue === 0, `${blue} blue-ish computed colours`)
}

async function keyboardChecks(page, label) {
  // Popover by keyboard: focus the first mark, Enter opens, Escape closes and restores focus.
  const mark = page.locator('figure.frame figcaption button').first()
  await mark.focus()
  await page.keyboard.press('Enter')
  await page.waitForTimeout(350)
  const popover = page.locator('[role="dialog"][aria-label]').first()
  const popoverOpen = await popover.isVisible().catch(() => false)
  await shoot(page, `${label}-popover`)
  const popoverFocusInside = await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))
  await page.keyboard.press('Escape')
  const focusBack = await page.evaluate(() => document.activeElement?.closest('figcaption') !== null)
  const popoverClosed = (await page.locator('[role="dialog"]').count()) === 0
  check(`${label}: popover opens by keyboard, traps and restores focus`, popoverOpen && popoverFocusInside && popoverClosed && focusBack)

  // Lightbox by keyboard: Enter on a frame image opens; ArrowRight navigates; Escape closes.
  const frameButton = page.locator('figure.frame > button').first()
  await frameButton.focus()
  await page.keyboard.press('Enter')
  const dialog = page.locator('[role="dialog"][aria-modal="true"]')
  await dialog.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(600) // shared-layout spring
  await shoot(page, `${label}-lightbox`)
  const counterBefore = await dialog.locator('span').first().textContent().catch(() => '')
  await page.keyboard.press('ArrowRight')
  await page.waitForTimeout(300)
  const counterAfter = await dialog.locator('span').first().textContent().catch(() => '')
  const focusInside = await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"][aria-modal="true"]'))
  await page.keyboard.press('Escape')
  // the shared-layout spring (300/34) keeps the exiting dialog in the DOM for ~1 s
  let closed = false
  for (let i = 0; i < 25 && !closed; i++) {
    await page.waitForTimeout(100)
    closed = (await page.locator('[role="dialog"][aria-modal="true"]').count()) === 0
  }
  check(`${label}: lightbox opens by keyboard, arrows navigate, Escape closes`, counterBefore !== counterAfter && focusInside && closed, `${counterBefore} -> ${counterAfter}; focus inside=${focusInside}; closed=${closed}`)
}

async function reducedMotionCheck(context, qid) {
  const page = await context.newPage()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`${BASE}/u/${qid}`, { waitUntil: 'domcontentloaded' })
  await waitTiming(page, 'done', 45000)
  const state = await page.evaluate(() => {
    const f = document.querySelector('figure.frame')
    if (!f) return null
    const s = getComputedStyle(f)
    return { opacity: s.opacity, filter: s.filter }
  })
  check('reduced motion: frames are static (opacity 1, no filter)', !!state && state.opacity === '1' && (state.filter === 'none' || /grayscale\(0\)/.test(state.filter)), JSON.stringify(state))
  await shoot(page, 'desktop-reduced-motion')
  await page.close()
}

const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  // Desktop 1440x900, cold university
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' })
  const page = await desktop.newPage()
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await shoot(page, 'desktop-home')
  await runProfile(page, 'desktop', QID_DESKTOP, { cold: !WARM })
  await checkFinishedPage(page, 'desktop')
  await keyboardChecks(page, 'desktop')
  await reducedMotionCheck(desktop, QID_DESKTOP)
  await desktop.close()

  // Mobile 390x844, another cold university
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: 'ru-RU' })
  const mpage = await mobile.newPage()
  await mpage.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await mpage.waitForTimeout(1500)
  await shoot(mpage, 'mobile-home')
  await runProfile(mpage, 'mobile', QID_MOBILE, { cold: !WARM })
  await checkFinishedPage(mpage, 'mobile')
  await mpage.locator('figure.frame > button').first().click()
  await mpage.waitForTimeout(700)
  await shoot(mpage, 'mobile-lightbox')
  await mpage.keyboard.press('Escape')
  await mpage.waitForTimeout(300)
  await mpage.locator('figure.frame figcaption button').first().click()
  await mpage.waitForTimeout(300)
  await shoot(mpage, 'mobile-popover')
  await mobile.close()
} finally {
  await browser.close()
}

writeFileSync(resolve(OUT, 'gate-b-report.json'), JSON.stringify(report, null, 2))
const failed = report.checks.filter((c) => !c.ok)
console.log(`\n${report.checks.length - failed.length} of ${report.checks.length} checks passed; timings: ${JSON.stringify(report.timings)}`)
process.exit(failed.length ? 1 : 0)
