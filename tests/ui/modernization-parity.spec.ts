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
    await expect(page.getByTestId('legacy-status-RTGENACE')).toHaveText('ported, verified');
    await expect(page.getByTestId('legacy-cov-RTGENACE')).toHaveText('98.4%');
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText('app/rtgenace.py');
    await expect(page.getByTestId('legacy-RTGENACE')).toContainText('NERC BAL-001');

    await expect(page.getByTestId('legacy-status-LOADSHED')).toHaveText('not started');
    await expect(page.getByTestId('legacy-cov-LOADSHED')).toHaveText('—');
    await expect(page.getByTestId('legacy-LOADSHED')).toContainText('none');

    await expect(page.getByTestId('legacy-status-HAB_SAVECASE')).toHaveText('ported, verified');
    await expect(page.getByTestId('legacy-cov-HAB_SAVECASE')).toHaveText('100.0%');
  });

  test('savecase replay parity shows the ACE delta between Fortran and the ported service', async ({
    page,
  }) => {
    await expect(page.getByTestId('parity-ace')).toContainText('-116.34');
    await expect(page.getByTestId('parity-GEN.HARBOR1')).toContainText('0.4000');
    await expect(page.getByTestId('parity-ace')).toContainText('0.0062');
    await expect(page.getByTestId('parity-summary')).toContainText('Max absolute delta 0.0062 MW');
    await expect(page.getByTestId('parity-summary')).toContainText(
      'inside the 0.0069 MW single-precision bound',
    );
  });

  test('the characterization corpus proves parity beyond the single production savecase', async ({
    page,
  }) => {
    await expect(page.getByTestId('corpus-cases')).toHaveText(
      '69 (65 accepted, 4 refused by the reader)',
    );
    await expect(page.getByTestId('corpus-matched')).toHaveText('69 of 69');
    await expect(page.getByTestId('corpus-reproduced')).toHaveText('69 of 69');
    await expect(page.getByTestId('corpus-ace-delta')).toHaveText('0.0260 MW (99.0% of its bound)');
    await expect(page.getByTestId('corpus-indeterminate')).toHaveText('3 judged on the legacy ACE');
    await expect(page.getByTestId('corpus-tests')).toHaveText('142 pinning RTGENACE');
  });

  test('drilling into a task gives its readiness verdict', async ({ page }) => {
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
    await expect(page.getByTestId('legacy-drawer-tests')).toHaveText('142');
    await expect(page.getByTestId('legacy-drawer-readiness')).toHaveText(
      'Parity proven on 69 savecases: ready to retire',
    );
  });
});
