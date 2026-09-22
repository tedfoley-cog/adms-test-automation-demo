import { expect, test } from '@playwright/test';

test.describe('Legacy modernization view', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('tab-modernization').click();
    await expect(page.getByTestId('legacy-table')).toBeVisible();
  });

  test('the Fortran task inventory reports port status and the coverage of each target module', async ({
    page,
  }) => {
    await expect(page.getByTestId('legacy-status-RTGENACE')).toHaveText('ported, characterized');
    await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('100.0%');
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText('app/agc.py');
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText('NERC BAL-001');

    await expect(page.getByTestId('legacy-status-LOADSHED')).toHaveText('not started');
    await expect(page.getByTestId('legacy-cov-LOADSHED')).toHaveText('—');
    await expect(page.getByTestId('legacy-LOADSHED')).toContainText('none');
  });

  test('savecase replay parity shows the ACE delta between Fortran and the ported service', async ({
    page,
  }) => {
    await expect(page.getByTestId('parity-ace')).toContainText('-116.34');
    await expect(page.getByTestId('parity-GEN.HARBOR1')).toContainText('0.4000');
    await expect(page.getByTestId('parity-summary')).toContainText('Max absolute delta 0.0062 MW');
    await expect(page.getByTestId('parity-summary')).toContainText(
      '31 characterization tests pin the legacy behaviour',
    );
  });

  test('drilling into a task explains why it is blocked for rewrite', async ({ page }) => {
    await page.getByTestId('legacy-LOADSHED').click();
    const drawer = page.getByTestId('legacy-drawer');
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId('legacy-drawer-title')).toHaveText('LOADSHED');
    await expect(page.getByTestId('legacy-drawer-units')).toHaveText('LOADSHED');
    await expect(page.getByTestId('legacy-drawer-tests')).toHaveText('0');
    await expect(page.getByTestId('legacy-drawer-readiness')).toHaveText(
      'Blocked: no behaviour is pinned before the rewrite',
    );

    await page.getByTestId('legacy-drawer-close').click();
    await expect(drawer).toBeHidden();

    await page.getByTestId('legacy-RTGENACE').click();
    await expect(page.getByTestId('legacy-drawer-units')).toHaveText('RTGENACE, RPTACE, ALLOCR');
    await expect(page.getByTestId('legacy-drawer-tests')).toHaveText('14');
    await expect(page.getByTestId('legacy-drawer-readiness')).toHaveText('Ready for rewrite');
  });
});
