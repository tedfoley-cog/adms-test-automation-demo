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
    await expect(page.getByTestId('legacy-status-RTGENACE')).toHaveText(
      'extracted to service, verified',
    );
    await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('100.0%');
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText(
      'services/ace-service/ace_service/ace.py',
    );
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText('NERC BAL-001');

    await expect(page.getByTestId('legacy-status-LOADSHED')).toHaveText('not started');
    await expect(page.getByTestId('legacy-cov-LOADSHED')).toHaveText('—');
    await expect(page.getByTestId('legacy-LOADSHED')).toContainText('none');

    await expect(page.getByTestId('legacy-status-HAB_SAVECASE')).toHaveText('ported, unverified');
  });

  test('savecase replay parity compares Fortran with the external ace-service within tolerance', async ({
    page,
  }) => {
    await expect(page.getByTestId('parity-service')).toContainText('services/ace-service');
    await expect(page.getByTestId('parity-ace')).toContainText('-116.3462');
    await expect(page.getByTestId('parity-ace')).toContainText('-116.3400');
    await expect(page.getByTestId('parity-GEN.HARBOR1')).toContainText('0.4000');
    await expect(page.getByTestId('parity-GEN.MESQUITE_CT')).toContainText('1.2000');
    await expect(page.getByTestId('parity-summary')).toContainText('Max absolute delta 0.0062 MW');
    await expect(page.getByTestId('parity-summary')).toContainText(
      'within the 0.0174 MW single-precision bound',
    );
    await expect(page.getByTestId('parity-summary')).toContainText(
      'pinned by 29 characterization tests',
    );
  });

  test('the seeded parity sweep reports 500 savecases with no failures', async ({ page }) => {
    await expect(page.getByTestId('sweep-cases')).toContainText('seed 742');
    await expect(page.getByTestId('sweep-cases')).toContainText('500');
    await expect(page.getByTestId('sweep-failures')).toContainText('0');
    await expect(page.getByTestId('sweep-ambiguous')).toContainText('0');
    await expect(page.getByTestId('sweep-categories')).toContainText('ramp clipped');
    await expect(page.getByTestId('sweep-categories')).toContainText('deadband');
  });

  test('drilling into a task explains its readiness: blocked, pinned or verified', async ({ page }) => {
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
    await expect(page.getByTestId('legacy-drawer-spec')).toHaveText('docs/specs/RTGENACE.md');
    await expect(page.getByTestId('legacy-drawer-deployment')).toContainText('ACE_SERVICE_URL');
    await expect(page.getByTestId('legacy-drawer-tests')).toHaveText('29');
    await expect(page.getByTestId('legacy-drawer-readiness')).toHaveText(
      'Verified: 29 pinned behaviours, parity on rtnet_ems_0742.export and 500 seeded savecases (0 failures)',
    );

    await page.getByTestId('legacy-HAB_SAVECASE').click();
    await expect(page.getByTestId('legacy-drawer-tests')).toHaveText('13');
    await expect(page.getByTestId('legacy-drawer-readiness')).toHaveText(
      'Ready for rewrite: legacy behaviour is pinned',
    );
  });
});
