import path from "node:path"

import { expect, test } from "@playwright/test"

const OUT = path.resolve(__dirname, "../test-results/e2e-artifacts")

test("mobile layout: register, dashboard, new project, settings", async ({ page }) => {
  const errors: string[] = []
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()))
  page.on("pageerror", (e) => errors.push(String(e)))
  await page.goto("/register")
  await page.getByLabel("E-mail").fill(`mobile-${Date.now()}@example.cz`)
  await page.getByLabel("Heslo").fill("tajneheslo123")
  await page.getByRole("button", { name: "Zaregistrovat se" }).click()
  await expect(page.getByRole("heading", { name: "Vaše projekty" })).toBeVisible()
  await page.screenshot({ path: `${OUT}/mobile-dashboard.png`, fullPage: true })
  for (const route of ["/new", "/settings"]) {
    await page.goto(route)
    await page.waitForLoadState("networkidle")
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `horizontal overflow on ${route}`).toBeLessThanOrEqual(1)
    await page.screenshot({ path: `${OUT}/mobile-${route.slice(1)}.png`, fullPage: true })
  }
  expect(errors).toEqual([])
})
