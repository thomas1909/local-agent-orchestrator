// Portfolio screenshot capture — zero-dependency Chrome DevTools Protocol driver.
//
// The corporate environment blocks npm/PyPI egress, so we cannot install the
// Playwright package. Chromium is already cached under ms-playwright, so we drive
// it directly over CDP using Node's built-in WebSocket (Node 22+).
//
//   CAPTURE_MODE=online  node scripts/capture.mjs   (API up — 5 views × 2 themes)
//   CAPTURE_MODE=offline node scripts/capture.mjs   (API down — offline banner × 2 themes)
import { spawn } from "node:child_process"
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { fileURLToPath } from "node:url"
import { dirname, resolve, join } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, "..")
const OUT = resolve(ROOT, "..", "docs", "screenshots")
const BASE = process.env.BASE_URL ?? "http://localhost:3000"
const MODE = process.env.CAPTURE_MODE ?? "online"
const PORT = 9222
const CHROME =
  process.env.CHROME_PATH ??
  join(
    process.env.USERPROFILE,
    "AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe",
  )

const ids = JSON.parse(readFileSync(resolve(ROOT, ".capture-runs.json"), "utf8"))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ── Minimal CDP client over the browser-level WebSocket ───────────────────────
class CDP {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    this.sessionId = null
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      }
    })
  }
  send(method, params = {}, useSession = true) {
    const id = ++this.id
    const payload = { id, method, params }
    if (useSession && this.sessionId) payload.sessionId = this.sessionId
    this.ws.send(JSON.stringify(payload))
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
  }
}

async function connect(url) {
  const ws = new WebSocket(url)
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true })
    ws.addEventListener("error", rej, { once: true })
  })
  return new CDP(ws)
}

async function getJSON(path) {
  const res = await fetch(`http://127.0.0.1:${PORT}${path}`)
  return res.json()
}

// ── App-level helpers (run JS in the page) ────────────────────────────────────
async function evalJS(cdp, expression) {
  const r = await cdp.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  })
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text)
  return r.result.value
}

async function waitForText(cdp, text, timeout = 15000) {
  const t0 = Date.now()
  const lit = JSON.stringify(text)
  while (Date.now() - t0 < timeout) {
    const ok = await evalJS(cdp, `document.body && document.body.innerText.includes(${lit})`)
    if (ok) return
    await sleep(200)
  }
  throw new Error(`Timeout waiting for text: ${text}`)
}

async function clickByText(cdp, text, tag = "*") {
  const lit = JSON.stringify(text)
  return evalJS(
    cdp,
    `(() => {
       const els = [...document.querySelectorAll(${JSON.stringify(tag)})];
       const el = els.find(e => e.textContent && e.textContent.includes(${lit}));
       if (!el) return false;
       el.scrollIntoView({block:'center'});
       try { el.focus() } catch (e) {}
       const opts = { bubbles: true, cancelable: true, view: window };
       el.dispatchEvent(new PointerEvent('pointerdown', opts));
       el.dispatchEvent(new MouseEvent('mousedown', opts));
       el.dispatchEvent(new PointerEvent('pointerup', opts));
       el.dispatchEvent(new MouseEvent('mouseup', opts));
       el.dispatchEvent(new MouseEvent('click', opts));
       el.click();
       return true
     })()`,
  )
}

async function navigate(cdp, url) {
  await cdp.send("Page.navigate", { url })
  await sleep(1200) // initial paint; specific waits follow per view
}

async function shoot(cdp, name) {
  await sleep(500)
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png" })
  writeFileSync(resolve(OUT, `${name}.png`), Buffer.from(data, "base64"))
  console.log(`  ✓ ${name}.png`)
}

async function captureTheme(browser, theme) {
  // Fresh page target per theme.
  const { targetId } = await browser.send("Target.createTarget", { url: "about:blank" }, false)
  const { sessionId } = await browser.send(
    "Target.attachToTarget",
    { targetId, flatten: true },
    false,
  )
  const cdp = browser
  cdp.sessionId = sessionId

  await cdp.send("Page.enable")
  await cdp.send("Runtime.enable")
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 2,
    mobile: false,
  })
  // Force theme on every new document (next-themes storageKey = "theme").
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try{localStorage.setItem('theme', ${JSON.stringify(theme)})}catch(e){}`,
  })

  if (MODE === "offline") {
    await navigate(cdp, `${BASE}/runs`)
    await waitForText(cdp, "Backend non joignable")
    await shoot(cdp, `offline-${theme}`)
  } else {
    // runs list
    await navigate(cdp, `${BASE}/runs`)
    await waitForText(cdp, "Combien font")
    await shoot(cdp, `runs-${theme}`)

    // new run dialog
    await clickByText(cdp, "Nouveau run", "button")
    await waitForText(cdp, "Nouvelle tâche", 5000)
    await shoot(cdp, `new-run-${theme}`)

    // detail — result tab
    await navigate(cdp, `${BASE}/runs/${ids.calc}`)
    await waitForText(cdp, "22200")
    await shoot(cdp, `detail-result-${theme}`)

    // detail — trace tab (expand the tool span for richness)
    await clickByText(cdp, "Trace", '[role="tab"]')
    await waitForText(cdp, "Arbre de spans", 8000)
    await sleep(300)
    await clickByText(cdp, "tool:calculator").catch(() => {})
    await sleep(300)
    await shoot(cdp, `detail-trace-${theme}`)

    // approval panel
    await navigate(cdp, `${BASE}/runs/${ids.delete}`)
    await waitForText(cdp, "Approbation requise")
    await shoot(cdp, `approval-${theme}`)
  }

  cdp.sessionId = null
  await browser.send("Target.closeTarget", { targetId }, false)
}

async function main() {
  const userDataDir = mkdtempSync(join(tmpdir(), "agentlocal-cap-"))
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--hide-scrollbars",
      "--disable-extensions",
      "--no-proxy-server",
      "about:blank",
    ],
    { stdio: "ignore" },
  )

  try {
    // Wait for the debugger endpoint.
    let wsUrl
    for (let i = 0; i < 40; i++) {
      try {
        const v = await getJSON("/json/version")
        wsUrl = v.webSocketDebuggerUrl
        if (wsUrl) break
      } catch {}
      await sleep(250)
    }
    if (!wsUrl) throw new Error("Chrome debugger did not start")

    const browser = await connect(wsUrl)
    for (const theme of ["light", "dark"]) {
      console.log(`Theme: ${theme}`)
      await captureTheme(browser, theme)
    }
    browser.ws.close()
  } finally {
    chrome.kill()
    try { rmSync(userDataDir, { recursive: true, force: true }) } catch {}
  }
}

main().then(
  () => { console.log("done"); process.exit(0) },
  (err) => { console.error(err); process.exit(1) },
)
