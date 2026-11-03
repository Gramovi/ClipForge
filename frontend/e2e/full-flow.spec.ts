import fs from "node:fs"
import path from "node:path"

import { expect, test, type ConsoleMessage, type Page } from "@playwright/test"

const VIDEO = process.env.E2E_VIDEO || path.resolve(__dirname, "../../test-media/e2e-cs.mp4")
const OUT = path.resolve(__dirname, "../test-results/e2e-artifacts")

function trackConsole(page: Page) {
  const errors: string[] = []
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error") errors.push(m.text())
  })
  page.on("pageerror", (e) => errors.push(String(e)))
  return errors
}

test.describe.configure({ mode: "serial" })

test("register → upload → process → edit clip → change preset → render → download → ZIP", async ({ page }) => {
  test.skip(!fs.existsSync(VIDEO), `missing test video ${VIDEO}`)
  test.skip(test.info().project.name !== "desktop")
  fs.mkdirSync(OUT, { recursive: true })
  const errors = trackConsole(page)
  const email = `e2e-${Date.now()}@example.cz`

  // 1. register
  await page.goto("/register")
  await page.getByLabel("E-mail").fill(email)
  await page.getByLabel("Heslo").fill("tajneheslo123")
  await page.getByRole("button", { name: "Zaregistrovat se" }).click()
  await expect(page.getByRole("heading", { name: "Vaše projekty" })).toBeVisible()

  // 2. upload (resumable chunked upload through the UI)
  await page.getByTestId("nav-new").click()
  await page.getByTestId("file-input").setInputFiles(VIDEO)
  await expect(page.getByText("Nahráno")).toBeVisible({ timeout: 120_000 })
  await page.getByLabel("Název projektu").fill("E2E – Řeč o penězích")
  await page.getByTestId("preset-karaoke").click()
  await page.getByTestId("start-processing").click()

  // 3. live progress then results (processing runs in the worker)
  await expect(page.getByTestId("project-title")).toHaveText("E2E – Řeč o penězích")
  await expect(page.getByTestId("progress-card").or(page.getByTestId("clip-grid"))).toBeVisible()
  await page.screenshot({ path: `${OUT}/progress.png` })
  await expect(page.getByTestId("clip-grid")).toBeVisible({ timeout: 40 * 60 * 1000 })
  const cards = page.getByTestId("clip-card")
  expect(await cards.count()).toBeGreaterThan(0)
  await page.screenshot({ path: `${OUT}/clips.png`, fullPage: true })

  // 4. open the best clip in the editor
  await cards.first().getByTestId("edit-clip").click()
  await expect(page.getByTestId("preview-player")).toBeVisible()
  await expect(page.getByTestId("transcript")).toBeVisible()
  // play a moment so the live caption preview renders
  await page.getByTestId("play-toggle").click()
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}/editor.png` })

  // 5. change preset + fix a word, then render
  await page.getByTestId("preset-comic").click()
  const firstWord = page.getByTestId("transcript").locator("button").first()
  await firstWord.dblclick()
  await page.getByTestId("word-input").fill("Opraveno")
  await page.getByTestId("word-save").click()
  await page.getByTestId("render-clip").click()
  await expect(page.getByText("Klip je vyrenderovaný.")).toBeVisible({ timeout: 10 * 60 * 1000 })
  await expect(page.getByTestId("rendered-video")).toBeVisible()

  // 6. download the MP4
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-mp4").click()])
  const mp4 = `${OUT}/clip.mp4`
  await dl.saveAs(mp4)
  expect(fs.statSync(mp4).size).toBeGreaterThan(50_000)

  // 7. ZIP of all clips
  await page.getByRole("link", { name: "Zpět na klipy" }).click()
  const [zipDl] = await Promise.all([
    page.waitForEvent("download", { timeout: 20 * 60 * 1000 }),
    page.getByTestId("export-zip").click(),
  ])
  const zip = `${OUT}/clips.zip`
  await zipDl.saveAs(zip)
  expect(fs.statSync(zip).size).toBeGreaterThan(50_000)

  const relevant = errors.filter((e) => !e.includes("Failed to load resource: the server responded with a status of 404"))
  expect(relevant, `console errors:\n${relevant.join("\n")}`).toEqual([])
})
