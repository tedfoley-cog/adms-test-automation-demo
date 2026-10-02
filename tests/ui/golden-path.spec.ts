import { expect, test } from '@playwright/test';

test('golden path: triage a Tier 1 gap, tie it to a legacy task, queue it and see the KPIs move', async ({
  page,
}) => {
  await page.goto('/');

  // 1. Baseline KPIs from the committed coverage report.
  await expect(page.getByTestId('kpi-overall')).toHaveText('40.0%');
  await expect(page.getByTestId('kpi-below')).toHaveText('8');
  await expect(page.getByTestId('kpi-tier1')).toHaveText('3');
  await expect(page.getByTestId('kpi-legacy')).toHaveText('3');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('0');

  // 2. Narrow to the worst Tier 1 backend gap and inspect it.
  await page.getByTestId('filter-layer').selectOption('backend');
  await page.getByTestId('filter-tier').selectOption('Tier 1');
  await page.getByTestId('filter-below').check();
  await expect(page.getByTestId('result-count')).toHaveText('1 of 11 modules');

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
  await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('0.0%');
  await expect(page.getByTestId('parity-ace')).toContainText('-116.34');

  // 4. Run history proves the gap is not new.
  await page.getByTestId('tab-runs').click();
  await expect(page.getByTestId('run-baseline')).toContainText('35.6%');
  await expect(page.getByTestId('run-flisr topology fault location')).toContainText('40.0%');
  await expect(page.getByTestId('run-nightly-2026-09-17')).toContainText('34.1%');
  await expect(page.getByTestId('tier-targets')).toContainText(
    '90% line coverage required before release sign-off',
  );

  // 5. Add a second item through the backlog form and verify both are queued.
  await page.getByTestId('tab-backlog').click();
  await expect(page.getByTestId('backlog-agc.py')).toContainText('Unit + API contract');

  await page.getByTestId('form-module').selectOption('firmware/src/recloser.c');
  await page.getByTestId('form-target').fill('90');
  await page.getByTestId('form-technique').selectOption('Unit + fault injection');
  await page
    .getByTestId('form-justification')
    .fill('Autoreclose shot counting and lockout are unexercised before the field release.');
  await page.getByTestId('form-submit').click();

  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
  await expect(page.getByTestId('backlog-list').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('backlog-recloser.c')).toContainText('90% target');

  // 6. Back on coverage, the queued module is still flagged below target.
  await page.getByTestId('tab-coverage').click();
  await page.getByTestId('filter-search').fill('recloser');
  await expect(page.getByTestId('row-recloser.c')).toContainText('below target');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
});
