import { expect, test } from '@playwright/test';

test('golden path: confirm the Tier 1 lift, tie AGC to its verified legacy port, queue the next gap', async ({
  page,
}) => {
  await page.goto('/');

  // 1. KPIs from the committed coverage report after the Tier 1 lift and RTGENACE port.
  await expect(page.getByTestId('kpi-overall')).toHaveText('74.6%');
  await expect(page.getByTestId('kpi-below')).toHaveText('3');
  await expect(page.getByTestId('kpi-tier1')).toHaveText('0');
  await expect(page.getByTestId('kpi-legacy')).toHaveText('1');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('0');

  // 2. No Tier 1 backend module is below target any more; inspect AGC among the three.
  await page.getByTestId('filter-layer').selectOption('backend');
  await page.getByTestId('filter-tier').selectOption('Tier 1');
  await page.getByTestId('filter-below').check();
  await expect(page.getByTestId('result-count')).toHaveText('0 of 12 modules');
  await page.getByTestId('filter-below').uncheck();
  await expect(page.getByTestId('result-count')).toHaveText('3 of 12 modules');

  await page.getByTestId('row-agc.py').click();
  await expect(page.getByTestId('drawer-function')).toHaveText(
    'Automatic generation control / reporting ACE',
  );
  await expect(page.getByTestId('drawer-coverage')).toContainText('100.0% of');
  await page.getByTestId('drawer-queue').click();
  await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
  await page.getByTestId('drawer-close').click();

  // 3. AGC sits under the RTGENACE port, now verified against the legacy Fortran.
  await page.getByTestId('tab-modernization').click();
  await expect(page.getByTestId('legacy-RTGENACE')).toContainText('app/rtgenace.py');
  await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('98.4%');
  await expect(page.getByTestId('legacy-status-RTGENACE')).toHaveText('ported, verified');
  await expect(page.getByTestId('parity-ace')).toContainText('-116.34');
  await expect(page.getByTestId('corpus-matched')).toHaveText('69 of 69');

  // 4. Run history shows the lift against the baseline.
  await page.getByTestId('tab-runs').click();
  await expect(page.getByTestId('run-baseline')).toContainText('35.6%');
  await expect(page.getByTestId('run-rtgenace-port-tier1-lift')).toContainText('74.6%');
  await expect(page.getByTestId('run-nightly-2026-09-17')).toContainText('34.1%');
  await expect(page.getByTestId('tier-targets')).toContainText(
    '90% line coverage required before release sign-off',
  );

  // 5. Add a second item through the backlog form and verify both are queued.
  await page.getByTestId('tab-backlog').click();
  await expect(page.getByTestId('backlog-agc.py')).toContainText('Unit + API contract');

  await page.getByTestId('form-module').selectOption('app/state_estimator.py');
  await page.getByTestId('form-target').fill('75');
  await page.getByTestId('form-technique').selectOption('Unit + API contract');
  await page
    .getByTestId('form-justification')
    .fill('Bad-data detection feeds the AGC inputs and has no automated coverage.');
  await page.getByTestId('form-submit').click();

  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
  await expect(page.getByTestId('backlog-list').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('backlog-state_estimator.py')).toContainText('75% target');

  // 6. Back on coverage, the queued module is still flagged below target.
  await page.getByTestId('tab-coverage').click();
  await page.getByTestId('filter-search').fill('state_estimator');
  await expect(page.getByTestId('row-state_estimator.py')).toContainText('below target');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
});
