import { expect, test } from '@playwright/test';

test('golden path: review Tier 1 coverage, link a legacy task and queue follow-up work', async ({
  page,
}) => {
  await page.goto('/');

  // 1. Current KPIs from the committed coverage report.
  await expect(page.getByTestId('kpi-overall')).toHaveText('99.3%');
  await expect(page.getByTestId('kpi-below')).toHaveText('0');
  await expect(page.getByTestId('kpi-tier1')).toHaveText('0');
  await expect(page.getByTestId('kpi-legacy')).toHaveText('3');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('0');

  // 2. Check that no Tier 1 backend modules miss their target, then inspect AGC.
  await page.getByTestId('filter-layer').selectOption('backend');
  await page.getByTestId('filter-tier').selectOption('Tier 1');
  await page.getByTestId('filter-below').check();
  await expect(page.getByTestId('result-count')).toHaveText('0 of 11 modules');
  await page.getByTestId('filter-below').uncheck();
  await expect(page.getByTestId('result-count')).toHaveText('2 of 11 modules');

  await page.getByTestId('row-agc.py').click();
  await expect(page.getByTestId('drawer-function')).toHaveText(
    'Automatic generation control / reporting ACE',
  );
  await page.getByTestId('drawer-queue').click();
  await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
  await page.getByTestId('drawer-close').click();

  // 3. The same module is the migration target of a legacy Fortran task.
  await page.getByTestId('tab-modernization').click();
  await expect(page.getByTestId('legacy-RTGENACE')).toContainText('app/agc.py');
  await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('100.0%');
  await expect(page.getByTestId('parity-ace')).toContainText('-116.34');

  // 4. Compare the current run with the retained baseline and nightly runs.
  await page.getByTestId('tab-runs').click();
  const liftedRun = page.getByTestId('run-Feeder fault characterization + coverage lift >80%');
  await expect(liftedRun.getByRole('cell').nth(2)).toHaveText('99.3%');
  await expect(liftedRun.getByRole('cell').nth(3)).toHaveText('611/615');
  await expect(liftedRun.getByRole('cell').nth(4)).toHaveText('0');
  await expect(page.getByTestId('run-baseline')).toContainText('35.6%');
  await expect(page.getByTestId('run-nightly-2026-09-17')).toContainText('34.1%');
  await expect(page.getByTestId('tier-targets')).toContainText(
    '90% line coverage required before release sign-off',
  );

  // 5. Add a second item through the backlog form and verify both are queued.
  await page.getByTestId('tab-backlog').click();
  await expect(page.getByTestId('backlog-agc.py')).toContainText('Unit + API contract');

  await page.getByTestId('form-module').selectOption('app/api.py');
  await page.getByTestId('form-target').fill('99');
  await page.getByTestId('form-technique').selectOption('Unit + API contract');
  await page
    .getByTestId('form-justification')
    .fill('Pin the remaining HTTP responses for the health and feeder inventory endpoints.');
  await page.getByTestId('form-submit').click();

  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
  await expect(page.getByTestId('backlog-list').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('backlog-api.py')).toContainText('99% target');

  // 6. Follow-up work does not change the measured coverage or its release status.
  await page.getByTestId('tab-coverage').click();
  await page.getByTestId('filter-search').fill('api.py');
  await expect(page.getByTestId('coverage-api.py')).toHaveText('95.6%');
  await expect(page.getByTestId('row-api.py')).toContainText('meets target');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
});
