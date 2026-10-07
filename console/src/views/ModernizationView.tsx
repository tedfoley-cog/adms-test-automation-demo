import { useState } from 'react';

import type { LegacyTask, ModernizationReport } from '../types';

const STATUS_CLASS: Record<LegacyTask['port_status'], string> = {
  'extracted to service, verified': 'pill pill-good',
  'ported, unverified': 'pill',
  'not started': 'pill pill-bad',
};

interface Props {
  modernization: ModernizationReport;
}

export default function ModernizationView({ modernization }: Props) {
  const [selected, setSelected] = useState<LegacyTask | null>(null);
  const { parity } = modernization;
  const parityTask = modernization.tasks.find((task) => task.parity_checked);
  const pinned = parityTask ? parityTask.characterization_tests : 0;

  const readiness = (task: LegacyTask) => {
    if (task.characterization_tests === 0) {
      return 'Blocked: no behaviour is pinned before the rewrite';
    }
    if (task.port_status === 'extracted to service, verified') {
      return `Verified: ${task.characterization_tests} pinned behaviours, parity on ${parity.savecase} and ${parity.sweep.cases} seeded savecases (${parity.sweep.failures} failures)`;
    }
    return 'Ready for rewrite: legacy behaviour is pinned';
  };

  return (
    <section className="panel">
      <h2>
        Legacy clone {modernization.clone} — {modernization.platform}
      </h2>
      <p className="subtle">
        Fortran batch tasks still running the area. A task can only be retired once the ported
        service reproduces it on the same savecase and carries characterization tests.
      </p>

      <table className="grid" data-testid="legacy-table">
        <thead>
          <tr>
            <th>Task</th>
            <th>Function</th>
            <th>Source</th>
            <th className="numeric">Fortran lines</th>
            <th>Target module</th>
            <th className="numeric">Target coverage</th>
            <th>Port status</th>
          </tr>
        </thead>
        <tbody>
          {modernization.tasks.map((task) => (
            <tr
              key={task.id}
              className="row"
              data-testid={`legacy-${task.id}`}
              onClick={() => setSelected(task)}
            >
              <td>
                <strong>{task.id}</strong>
                <span className="subtle">{task.cycle} cycle</span>
              </td>
              <td>
                {task.function}
                <span className="subtle">{task.standard}</span>
              </td>
              <td>
                <span className="mono">{task.source}</span>
              </td>
              <td className="numeric" data-testid={`legacy-lines-${task.id}`}>
                {task.executable_lines}
              </td>
              <td>
                <span className="mono">{task.target_module ?? 'none'}</span>
              </td>
              <td className="numeric" data-testid={`legacy-cov-${task.id}`}>
                {task.target_coverage_pct === null
                  ? '—'
                  : `${task.target_coverage_pct.toFixed(1)}%`}
              </td>
              <td>
                <span
                  className={STATUS_CLASS[task.port_status]}
                  data-testid={`legacy-status-${task.id}`}
                >
                  {task.port_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>
        Savecase replay parity — {parity.savecase}{' '}
        <span className="subtle" data-testid="parity-service">
          legacy Fortran vs {parity.service}
        </span>
      </h3>
      <table className="grid" data-testid="parity-table">
        <thead>
          <tr>
            <th>Quantity</th>
            <th className="numeric">Legacy Fortran</th>
            <th className="numeric">Ported service</th>
            <th className="numeric">Delta</th>
          </tr>
        </thead>
        <tbody>
          <tr data-testid="parity-ace">
            <td>Reporting ACE (MW)</td>
            <td className="numeric">{parity.legacy_ace_mw.toFixed(4)}</td>
            <td className="numeric">{parity.modern_ace_mw.toFixed(4)}</td>
            <td className="numeric">
              {(parity.modern_ace_mw - parity.legacy_ace_mw).toFixed(4)}
            </td>
          </tr>
          {parity.setpoints.map((setpoint) => (
            <tr key={setpoint.unit} data-testid={`parity-${setpoint.unit}`}>
              <td>{setpoint.unit} regulation (MW)</td>
              <td className="numeric">{setpoint.legacy_mw.toFixed(4)}</td>
              <td className="numeric">{setpoint.modern_mw.toFixed(4)}</td>
              <td className="numeric">{(setpoint.modern_mw - setpoint.legacy_mw).toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="subtle" data-testid="parity-summary">
        Max absolute delta {parity.max_abs_delta_mw.toFixed(4)} MW across the replay
        {pinned === 0
          ? '. No characterization tests exist yet, so parity is a single spot check rather than evidence.'
          : `, within the ${parity.tolerance_mw.toFixed(4)} MW single-precision bound (${parity.logic_delta_mw.toFixed(4)} MW once inputs are rounded to REAL*4). Behaviour is pinned by ${pinned} characterization tests.`}
      </p>

      <h3>Seeded parity sweep</h3>
      <table className="grid" data-testid="parity-sweep">
        <tbody>
          <tr data-testid="sweep-cases">
            <td>Random savecases (seed {parity.sweep.seed})</td>
            <td className="numeric">{parity.sweep.cases}</td>
          </tr>
          <tr data-testid="sweep-failures">
            <td>Failures</td>
            <td className="numeric">
              <span className={parity.sweep.failures === 0 ? 'pill pill-good' : 'pill pill-bad'}>
                {parity.sweep.failures}
              </span>
            </td>
          </tr>
          <tr data-testid="sweep-ace">
            <td>Max ACE delta (MW)</td>
            <td className="numeric">{parity.sweep.max_ace_delta_mw.toFixed(4)}</td>
          </tr>
          <tr data-testid="sweep-setpoint">
            <td>Max setpoint delta (MW)</td>
            <td className="numeric">{parity.sweep.max_setpoint_delta_mw.toFixed(4)}</td>
          </tr>
          <tr data-testid="sweep-logic">
            <td>Max delta on REAL*4-rounded inputs (MW)</td>
            <td className="numeric">{parity.sweep.max_logic_delta_mw.toFixed(4)}</td>
          </tr>
          <tr data-testid="sweep-ambiguous">
            <td>Deadband-ambiguous cases (setpoints not compared)</td>
            <td className="numeric">{parity.sweep.deadband_ambiguous}</td>
          </tr>
          <tr data-testid="sweep-categories">
            <td>Behaviours exercised</td>
            <td>
              {Object.entries(parity.sweep.categories)
                .map(([name, count]) => `${name} ${count}`)
                .join(' · ')}
            </td>
          </tr>
        </tbody>
      </table>

      {selected && (
        <aside className="drawer" role="dialog" aria-label="Legacy task" data-testid="legacy-drawer">
          <div className="drawer-head">
            <div>
              <h2 data-testid="legacy-drawer-title">{selected.id}</h2>
              <span className="mono">{selected.source}</span>
            </div>
            <button type="button" onClick={() => setSelected(null)} data-testid="legacy-drawer-close">
              ×
            </button>
          </div>
          <dl className="detail">
            <div>
              <dt>Program units</dt>
              <dd data-testid="legacy-drawer-units">{selected.program_units.join(', ')}</dd>
            </div>
            <div>
              <dt>Source lines</dt>
              <dd data-testid="legacy-drawer-lines">
                {selected.source_lines} total / {selected.executable_lines} executable
              </dd>
            </div>
            <div>
              <dt>Specification</dt>
              <dd className="mono" data-testid="legacy-drawer-spec">{selected.spec ?? 'none'}</dd>
            </div>
            <div>
              <dt>Deployment</dt>
              <dd className="mono" data-testid="legacy-drawer-deployment">
                {selected.deployment ?? 'in monolith'}
              </dd>
            </div>
            <div>
              <dt>Characterization tests</dt>
              <dd data-testid="legacy-drawer-tests">{selected.characterization_tests}</dd>
            </div>
            <div>
              <dt>Migration readiness</dt>
              <dd data-testid="legacy-drawer-readiness">
                {readiness(selected)}
              </dd>
            </div>
          </dl>
        </aside>
      )}
    </section>
  );
}
