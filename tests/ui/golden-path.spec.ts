import { expect, test } from '@playwright/test';

test('golden path: inspect the extracted ACE service, tie it to its legacy task, queue work and see the KPIs move', async ({
  page,
}) => {
  await page.goto('/');

  // 1. KPIs from the committed coverage report: Tier 1 gaps closed, LOADSHED still unpinned.
  await expect(page.getByTestId('kpi-overall')).toHaveText('85.5%');
  await expect(page.getByTestId('kpi-below')).toHaveText('2');
  await expect(page.getByTestId('kpi-tier1')).toHaveText('0');
  await expect(page.getByTestId('kpi-legacy')).toHaveText('1');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('0');

  // 2. AGC now lives in the external ace-service; narrow to it and inspect it.
  await page.getByTestId('filter-layer').selectOption('service');
  await page.getByTestId('filter-tier').selectOption('Tier 1');
  await expect(page.getByTestId('result-count')).toHaveText('3 of 17 modules');
  await page.getByTestId('filter-below').check();
  await expect(page.getByTestId('result-count')).toHaveText('0 of 17 modules');
  await page.getByTestId('filter-below').uncheck();

  await page.getByTestId('row-ace.py').click();
  await expect(page.getByTestId('drawer-function')).toHaveText(
    'Automatic generation control / reporting ACE (RTGENACE port)',
  );
  await page.getByTestId('drawer-queue').click();
  await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
  await page.getByTestId('drawer-close').click();

  // 3. The same module is the verified replacement of a legacy Fortran task.
  await page.getByTestId('tab-modernization').click();
  await expect(page.getByTestId('legacy-RTGENACE')).toContainText(
    'services/ace-service/ace_service/ace.py',
  );
  await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('100.0%');
  await expect(page.getByTestId('parity-ace')).toContainText('-116.34');
  await expect(page.getByTestId('sweep-failures')).toContainText('0');

  // 4. Run history proves the gap is not new.
  await page.getByTestId('tab-runs').click();
  await expect(page.getByTestId('run-baseline')).toContainText('35.6%');
  await expect(
    page.getByTestId('run-RTGENACE extracted to ace-service + Tier 1 coverage lift'),
  ).toContainText('85.5%');
  await expect(page.getByTestId('run-nightly-2026-09-17')).toContainText('34.1%');
  await expect(page.getByTestId('tier-targets')).toContainText(
    '90% line coverage required before release sign-off',
  );

  // 5. Add a second item through the backlog form and verify both are queued.
  await page.getByTestId('tab-backlog').click();
  await expect(page.getByTestId('backlog-ace.py')).toContainText('Unit + API contract');

  await page.getByTestId('form-module').selectOption('firmware/src/dnp3_outstation.c');
  await page.getByTestId('form-target').fill('90');
  await page.getByTestId('form-technique').selectOption('Unit + fault injection');
  await page
    .getByTestId('form-justification')
    .fill('Class 0 responses are unexercised against IEEE 1815 before the field release.');
  await page.getByTestId('form-submit').click();

  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
  await expect(page.getByTestId('backlog-list').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('backlog-dnp3_outstation.c')).toContainText('90% target');

  // 6. Back on coverage, the queued module is still flagged below target.
  await page.getByTestId('tab-coverage').click();
  await page.getByTestId('filter-search').fill('dnp3');
  await expect(page.getByTestId('row-dnp3_outstation.c')).toContainText('below target');
  await expect(page.getByTestId('kpi-backlog')).toHaveText('2');
});
