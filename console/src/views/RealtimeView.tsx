import type { RealtimeReport } from '../types';

interface Props {
  realtime: RealtimeReport;
}

const TASK_LABELS: Record<string, string> = {
  acq_isr: 'Sample ISR (ADC, ring push, PPS discipline)',
  protection: 'Protection pass (DFT, 21/50/51/50BF, trip matrix)',
  pmu: 'Synchrophasor frame (C37.118, 81U/O/R)',
  comms: 'Comms (DNP3 points, SOE drain)',
};

function kib(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

export default function RealtimeView({ realtime }: Props) {
  const { target, rates } = realtime;
  const notAutomated = realtime.compliance.filter((c) => !c.automated).length;

  return (
    <section className="panel">
      <h2>Feeder IED firmware on {target.mcu}</h2>
      <p className="subtle">
        Protection relay and synchrophasor unit on one {target.core} at{' '}
        {target.cpu_hz / 1_000_000} MHz, booted under {target.emulator}. Every task is timed
        with the DWT cycle counter while the on-chip test set injects each scenario; a task
        over its budget fails CI.
      </p>

      <dl className="rt-facts" data-testid="rt-facts">
        <div>
          <dt>Sampling</dt>
          <dd data-testid="rt-sample-rate">
            {rates.sample_hz} Hz ({rates.sample_hz / 60} / cycle)
          </dd>
        </div>
        <div>
          <dt>Protection</dt>
          <dd>{rates.protection_hz} Hz</dd>
        </div>
        <div>
          <dt>PMU reporting</dt>
          <dd>{rates.pmu_hz} fps</dd>
        </div>
        <div>
          <dt>Worst-case CPU load</dt>
          <dd data-testid="rt-util">{realtime.worst_util_pct.toFixed(2)}%</dd>
        </div>
        <div>
          <dt>Flash / RAM</dt>
          <dd data-testid="rt-footprint">
            {kib(target.flash_bytes)} / {kib(target.ram_bytes)}
          </dd>
        </div>
      </dl>

      <h3>Execution time vs budget</h3>
      <table className="grid" data-testid="rt-tasks">
        <thead>
          <tr>
            <th>Task</th>
            <th className="numeric">Rate</th>
            <th className="numeric">Worst case</th>
            <th className="numeric">Mean</th>
            <th className="numeric">Budget</th>
            <th>Headroom</th>
            <th>Worst scenario</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {realtime.tasks.map((task) => (
            <tr key={task.task} data-testid={`rt-task-${task.task}`}>
              <td>
                <span className="mono">{task.task}</span>
                <span className="subtle">{TASK_LABELS[task.task] ?? ''}</span>
              </td>
              <td className="numeric">{task.rate_hz} Hz</td>
              <td className="numeric" data-testid={`rt-max-${task.task}`}>
                {task.max_cycles.toLocaleString('en-US')} cyc
                <span className="subtle">{task.max_us.toFixed(1)} µs</span>
              </td>
              <td className="numeric">{task.mean_cycles.toLocaleString('en-US')}</td>
              <td className="numeric" data-testid={`rt-budget-${task.task}`}>
                {task.budget_cycles.toLocaleString('en-US')}
              </td>
              <td>
                <div className="bar" aria-hidden="true">
                  <span
                    className={task.status === 'over budget' ? 'bar-bad' : ''}
                    style={{
                      width: `${Math.min(100, (task.max_cycles / task.budget_cycles) * 100)}%`,
                    }}
                  />
                </div>
                <span className="subtle">{task.headroom_pct.toFixed(1)}% free</span>
              </td>
              <td className="mono">{task.worst_scenario}</td>
              <td>
                <span
                  className={task.status === 'over budget' ? 'pill pill-bad' : 'pill pill-good'}
                  data-testid={`rt-status-${task.task}`}
                >
                  {task.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="subtle" data-testid="rt-method">
        Resolution {target.resolution_cycles} cycles. {target.method}.
      </p>

      <h3>Secondary-injection scenarios (closed loop on the emulated target)</h3>
      <table className="grid" data-testid="rt-scenarios">
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Expected</th>
            <th>Operated</th>
            <th className="numeric">Trip time</th>
            <th>Bus lockout</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {realtime.scenarios.map((s) => (
            <tr key={s.name} data-testid={`rt-scenario-${s.name}`}>
              <td>
                <span className="mono">{s.name}</span>
                <span className="subtle">{s.description}</span>
              </td>
              <td>{s.expected.join(', ')}</td>
              <td data-testid={`rt-observed-${s.name}`}>{s.observed.join(', ')}</td>
              <td className="numeric" data-testid={`rt-trip-${s.name}`}>
                {s.trip_ms === null ? '—' : `${s.trip_ms.toFixed(1)} ms`}
              </td>
              <td>{s.bus_trip ? '86B operated' : '—'}</td>
              <td>
                <span className={s.pass ? 'pill pill-good' : 'pill pill-bad'}>
                  {s.pass ? 'pass' : 'fail'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="subtle">
        Every scenario runs on a freshly booted relay. No scenario covers long uptime or an
        off-nominal system frequency.
      </p>

      <h3>Synchrophasor compliance — IEEE C37.118.1 P class</h3>
      <table className="grid" data-testid="rt-compliance">
        <thead>
          <tr>
            <th>Test</th>
            <th>Clause</th>
            <th>Limit</th>
            <th className="numeric">Points</th>
            <th className="numeric">Worst TVE</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {realtime.compliance.map((c) => (
            <tr key={c.id} data-testid={`rt-compliance-${c.id}`}>
              <td>{c.test}</td>
              <td className="mono">{c.clause}</td>
              <td>{c.limit}</td>
              <td className="numeric">{c.automated ? c.points : '—'}</td>
              <td className="numeric">
                {c.worst_tve_pct === null ? '—' : `${c.worst_tve_pct.toFixed(4)}%`}
              </td>
              <td>
                <span
                  className={
                    c.status === 'pass'
                      ? 'pill pill-good'
                      : c.status === 'fail'
                        ? 'pill pill-bad'
                        : 'pill pill-warn'
                  }
                  data-testid={`rt-compliance-status-${c.id}`}
                >
                  {c.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="subtle" data-testid="rt-compliance-summary">
        {notAutomated} of {realtime.compliance.length} P-class tests have no automated check, so
        compliance outside nominal frequency is unproven.
      </p>
    </section>
  );
}
