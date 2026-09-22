import { expect, test } from '@playwright/test';

test.describe('Coverage view: search, filter and sort over the real report', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('coverage-table')).toBeVisible();
  });

  test('combining layer, tier and below-target filters yields the exact firmware Tier 1 set', async ({
    page,
  }) => {
    await page.getByTestId('filter-layer').selectOption('firmware');
    await page.getByTestId('filter-tier').selectOption('Tier 1');
    await page.getByTestId('filter-below').check();

    await expect(page.getByTestId('result-count')).toHaveText('2 of 11 modules');
    const names = await page.locator('tbody tr.row td:first-child .mono').allTextContents();
    expect(names.sort()).toEqual(['fault_detect.c', 'recloser.c']);
    await expect(page.getByTestId('coverage-recloser.c')).toContainText('0.0%');
    await expect(page.getByTestId('coverage-fault_detect.c')).toContainText('41.9%');
  });

  test('searching by governing standard finds the protection module, not the DNP3 one', async ({
    page,
  }) => {
    await page.getByTestId('filter-search').fill('IEC 60255');
    await expect(page.getByTestId('result-count')).toHaveText('1 of 11 modules');
    await expect(page.getByTestId('row-fault_detect.c')).toContainText(
      'Feeder overcurrent protection (50/51)',
    );
    await expect(page.getByTestId('row-dnp3_outstation.c')).toHaveCount(0);

    await page.getByTestId('filter-search').fill('savecase');
    await expect(page.getByTestId('result-count')).toHaveText('1 of 11 modules');
    await expect(page.getByTestId('row-savecase.py')).toContainText(
      'Legacy HDB savecase ingest for migration parity',
    );
  });

  test('sorting by gap descending puts the two zero-coverage Tier 1 modules on top', async ({
    page,
  }) => {
    await page.getByTestId('filter-below').check();
    await page.getByTestId('sort-gap').click();
    await page.getByTestId('sort-gap').click();

    const first = page.locator('tbody tr.row').first();
    await expect(first).toContainText('90.0');
    const topTwo = await page
      .locator('tbody tr.row td:first-child .mono')
      .allTextContents()
      .then((rows) => rows.slice(0, 2).sort());
    expect(topTwo).toEqual(['agc.py', 'recloser.c']);
  });

  test('a search with no domain match shows the empty state and clears back to all modules', async ({
    page,
  }) => {
    await page.getByTestId('filter-search').fill('synchrophasor');
    await expect(page.getByTestId('no-results')).toHaveText('No modules match the current filters.');
    await expect(page.getByTestId('result-count')).toHaveText('0 of 11 modules');

    await page.getByTestId('filter-search').fill('');
    await expect(page.getByTestId('result-count')).toHaveText('11 of 11 modules');
  });
});
