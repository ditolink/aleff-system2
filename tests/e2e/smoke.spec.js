// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('portfólio público', () => {
  test('index carrega hero', async ({ page }) => {
    await page.goto('/index.html');
    await expect(page.locator('#hero, .hero')).toBeVisible();
  });

  test('busca tem pager ou resultados', async ({ page }) => {
    await page.goto('/search.html');
    await expect(page.locator('#searchInput')).toBeVisible();
    await page.waitForTimeout(800);
    const grid = page.locator('#resGrid .rcard, #stLoading, #stEmpty');
    await expect(grid.first()).toBeVisible({ timeout: 15000 });
  });
});
