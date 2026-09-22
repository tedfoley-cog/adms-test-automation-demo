import { expect, test } from '@playwright/test';

test.describe('Verification backlog form', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('tab-backlog').click();
    await expect(page.getByTestId('lift-form')).toBeVisible();
  });

  test('an empty submission reports every missing field', async ({ page }) => {
    await page.getByTestId('form-submit').click();

    const errors = page.getByTestId('form-errors').locator('li');
    await expect(errors).toHaveCount(3);
    await expect(errors.nth(0)).toHaveText('Select a module.');
    await expect(errors.nth(1)).toHaveText('Target coverage must be between 1 and 100.');
    await expect(errors.nth(2)).toHaveText('Justification must be at least 20 characters.');
    await expect(page.getByTestId('backlog-empty')).toBeVisible();
    await expect(page.getByTestId('kpi-backlog')).toHaveText('0');
  });

  test('a target below current coverage is rejected against the real module value', async ({
    page,
  }) => {
    await page.getByTestId('form-module').selectOption('app/network.py');
    await page.getByTestId('form-target').fill('60');
    await page
      .getByTestId('form-justification')
      .fill('Topology trace feeds FLISR switching orders and must be pinned.');
    await page.getByTestId('form-submit').click();

    await expect(page.getByTestId('form-errors')).toContainText(
      'Target must exceed the current 68.7% coverage of network.py',
    );
    await expect(page.getByTestId('kpi-backlog')).toHaveText('0');
  });

  test('a valid request is queued, confirmed and removable', async ({ page }) => {
    await page.getByTestId('form-module').selectOption('firmware/src/dnp3_outstation.c');
    await page.getByTestId('form-target').fill('85');
    await page.getByTestId('form-technique').selectOption('Protocol conformance replay');
    await page
      .getByTestId('form-justification')
      .fill('Class 0 responses are unverified against IEEE 1815 object groups 1 and 30.');
    await page.getByTestId('form-submit').click();

    await expect(page.getByTestId('form-confirmation')).toHaveText(
      'dnp3_outstation.c queued at 85% target.',
    );
    await expect(page.getByTestId('kpi-backlog')).toHaveText('1');
    const entry = page.getByTestId('backlog-dnp3_outstation.c');
    await expect(entry).toContainText('Protocol conformance replay');
    await expect(entry).toContainText('85% target');
    await expect(entry).toContainText('Tier 2');

    await page.getByTestId('remove-dnp3_outstation.c').click();
    await expect(page.getByTestId('backlog-empty')).toBeVisible();
    await expect(page.getByTestId('kpi-backlog')).toHaveText('0');
  });
});
