import { expect, test } from '@playwright/test';

test.describe('Real-time view: feeder IED on the emulated STM32F407', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('tab-realtime').click();
    await expect(page.getByTestId('rt-tasks')).toBeVisible();
  });

  test('every real-time task reports a measured worst case inside its cycle budget', async ({
    page,
  }) => {
    await expect(page.getByTestId('rt-sample-rate')).toHaveText('1920 Hz (32 / cycle)');
    for (const task of ['acq_isr', 'protection', 'pmu', 'comms']) {
      await expect(page.getByTestId(`rt-status-${task}`)).toHaveText('within budget');
    }
    await expect(page.getByTestId('rt-budget-protection')).toHaveText('12,000');
    await expect(page.getByTestId('rt-max-protection')).toContainText('6,279 cyc');
    await expect(page.getByTestId('rt-budget-pmu')).toHaveText('30,000');
    await expect(page.getByTestId('rt-method')).toContainText('Resolution 168 cycles');
    await expect(page.getByTestId('rt-method')).toContainText('no pipeline or flash wait-state');
  });

  test('closed-loop fault scenarios operate the expected protection elements', async ({ page }) => {
    await expect(page.getByTestId('rt-observed-fault_ag_zone1')).toHaveText('21Z1');
    await expect(page.getByTestId('rt-trip-fault_ag_zone1')).toHaveText('14.1 ms');
    await expect(page.getByTestId('rt-observed-fault_bc_zone2')).toHaveText('21Z2');
    await expect(page.getByTestId('rt-observed-fault_ag_high_resistance')).toHaveText('51G');
    await expect(page.getByTestId('rt-observed-breaker_failure')).toHaveText('21Z1, 50BF-86B');
    await expect(page.getByTestId('rt-observed-steady_load')).toHaveText('no trip');
    await expect(page.getByTestId('rt-scenarios').locator('.pill-bad')).toHaveCount(0);
  });

  test('the PMU compliance matrix separates automated checks from untested P-class clauses', async ({
    page,
  }) => {
    await expect(page.getByTestId('rt-compliance-status-ss-magnitude')).toHaveText('pass');
    await expect(page.getByTestId('rt-compliance-status-ss-phase')).toHaveText('pass');
    await expect(page.getByTestId('rt-compliance-status-ss-frequency')).toHaveText(
      'not automated',
    );
    await expect(page.getByTestId('rt-compliance-status-freq-ramp')).toHaveText('not automated');
    await expect(page.getByTestId('rt-compliance-summary')).toContainText(
      '6 of 8 P-class tests have no automated check',
    );
  });
});
