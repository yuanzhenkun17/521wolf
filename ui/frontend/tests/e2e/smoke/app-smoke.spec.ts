import { expect, test } from 'playwright/test'

test('renders the app shell on the home page', async ({ page }) => {
  await page.goto('/')

  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('#app > *')).toHaveCount(1)
  await expect(page.locator('main.lycan-app')).toBeVisible()

  const primaryNav = page.getByRole('navigation', { name: '主导航' })
  await expect(primaryNav).toBeVisible()
  await expect(primaryNav.getByRole('button', { name: /大厅/ })).toBeVisible()
  await expect(primaryNav.getByRole('button', { name: /评测/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'The Night Approaches' })).toBeVisible()
})
