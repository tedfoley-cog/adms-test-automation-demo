import { expect, test } from '@playwright/test';

test.describe('Coverage drawer drill-down', () => {
  test('opening the network module shows its standard, uncovered lines and queues generation once', async ({
    page,
  }) => {
    await page.goto('/');
    await page.getByTestId('filter-search').fill('network.py');
    await page.getByTestId('row-network.py').click();

    const drawer = page.getByTestId('drawer');
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId('drawer-title')).toHaveText('network.py');
    await expect(page.getByTestId('drawer-standard')).toHaveText('IEC 61968');
    await expect(page.getByTestId('drawer-team')).toHaveText('ADMS Applications');
    await expect(page.getByTestId('drawer-coverage')).toContainText('97.0% of');
    await expect(page.getByTestId('drawer-uncovered')).toHaveText('50, 68');

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
