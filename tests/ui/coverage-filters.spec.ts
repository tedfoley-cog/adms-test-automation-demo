import { expect, test } from '@playwright/test';

test.describe('Coverage view: search, filter and sort over the real report', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('coverage-table')).toBeVisible();
  });

  test('combining layer, tier and below-target filters: firmware Tier 1 is lifted to target', async ({
    page,
  }) => {
    await page.getByTestId('filter-layer').selectOption('firmware');
    await page.getByTestId('filter-tier').selectOption('Tier 1');

    await expect(page.getByTestId('result-count')).toHaveText('2 of 17 modules');
    const names = await page.locator('tbody tr.row td:first-child .mono').allTextContents();
    expect(names.sort()).toEqual(['fault_detect.c', 'recloser.c']);
    await expect(page.getByTestId('coverage-recloser.c')).toContainText('100.0%');
    await expect(page.getByTestId('coverage-fault_detect.c')).toContainText('100.0%');

    await page.getByTestId('filter-below').check();
    await expect(page.getByTestId('result-count')).toHaveText('0 of 17 modules');
    await expect(page.getByTestId('no-results')).toBeVisible();
  });

  test('the service layer lists the extracted ace-service modules', async ({ page }) => {
    await page.getByTestId('filter-layer').selectOption('service');

    await expect(page.getByTestId('result-count')).toHaveText('5 of 17 modules');
    const names = await page.locator('tbody tr.row td:first-child .mono').allTextContents();
    expect(names.sort()).toEqual(['__init__.py', 'ace.py', 'hdb_export.py', 'schemas.py', 'service.py']);
    await expect(page.getByTestId('row-agc.py')).toHaveCount(0);
  });

  test('searching by governing standard finds the protection module, not the DNP3 one', async ({
    page,
  }) => {
    await page.getByTestId('filter-search').fill('IEC 60255');
    await expect(page.getByTestId('result-count')).toHaveText('1 of 17 modules');
    await expect(page.getByTestId('row-fault_detect.c')).toContainText(
      'Feeder overcurrent protection (50/51)',
    );
    await expect(page.getByTestId('row-dnp3_outstation.c')).toHaveCount(0);

    await page.getByTestId('filter-search').fill('savecase');
    await expect(page.getByTestId('result-count')).toHaveText('2 of 17 modules');
    await expect(page.getByTestId('row-savecase.py')).toContainText(
      'Legacy HDB savecase ingest for migration parity',
    );
    await expect(page.getByTestId('row-hdb_export.py')).toContainText(
      'HDB savecase export reader feeding AGC',
    );
  });

  test('sorting by gap descending puts the remaining Tier 2 gaps on top, largest first', async ({
    page,
  }) => {
    await page.getByTestId('filter-below').check();
    await page.getByTestId('sort-gap').click();
    await page.getByTestId('sort-gap').click();

    const first = page.locator('tbody tr.row').first();
    await expect(first).toContainText('75.0');
    const names = await page.locator('tbody tr.row td:first-child .mono').allTextContents();
    expect(names).toEqual(['dnp3_outstation.c', 'state_estimator.py']);
  });

  test('a search with no domain match shows the empty state and clears back to all modules', async ({
    page,
  }) => {
    await page.getByTestId('filter-search').fill('synchrophasor');
    await expect(page.getByTestId('no-results')).toHaveText('No modules match the current filters.');
    await expect(page.getByTestId('result-count')).toHaveText('0 of 17 modules');

    await page.getByTestId('filter-search').fill('');
    await expect(page.getByTestId('result-count')).toHaveText('17 of 17 modules');
  });
});
