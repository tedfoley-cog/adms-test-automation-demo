import { expect, test } from '@playwright/test';

test.describe('Coverage drawer drill-down', () => {
  test('opening the extracted AGC module shows its standard and coverage and queues generation once', async ({
    page,
  }) => {
    await page.goto('/');
    await page.getByTestId('filter-search').fill('BAL-001');
    await expect(page.getByTestId('result-count')).toHaveText('3 of 17 modules');
    await page.getByTestId('row-ace.py').click();

    const drawer = page.getByTestId('drawer');
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId('drawer-title')).toHaveText('ace.py');
    await expect(page.getByTestId('drawer-standard')).toHaveText('NERC BAL-001');
    await expect(page.getByTestId('drawer-team')).toHaveText('AEMS Applications');
    await expect(page.getByTestId('drawer-coverage')).toContainText('100.0% of');
    await expect(page.getByTestId('drawer-uncovered')).toHaveText('none');

    await expect(page.getByTestId('kpi-backlog')).toHaveText('0');
    await page.getByTestId('drawer-queue').click();
    await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
    await expect(page.getByTestId('drawer-queue')).toBeDisabled();
    await expect(page.getByTestId('drawer-queue')).toHaveText('Already queued');

    await page.getByTestId('drawer-close').click();
    await expect(drawer).toBeHidden();
    await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
  });

  test('a module that meets its target still opens and reports no uncovered lines', async ({
    page,
  }) => {
    await page.goto('/');
    await page.getByTestId('filter-search').fill('models.py');
    await page.getByTestId('row-models.py').click();

    await expect(page.getByTestId('drawer-coverage')).toContainText('100.0% of');
    await expect(page.getByTestId('drawer-uncovered')).toHaveText('none');
  });
});
