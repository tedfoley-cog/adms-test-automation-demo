import { useState } from 'react';

import type { LegacyTask, ModernizationReport } from '../types';

interface Props {
  modernization: ModernizationReport;
}

export default function ModernizationView({ modernization }: Props) {
  const [selected, setSelected] = useState<LegacyTask | null>(null);
  const { parity } = modernization;
  const { corpus } = parity;
  const pinnedTests = modernization.tasks.find((task) => task.id === 'RTGENACE')
    ?.characterization_tests;

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
                  className={
                    task.port_status === 'not started'
                      ? 'pill pill-bad'
                      : task.port_status === 'ported, verified'
                        ? 'pill pill-good'
                        : 'pill'
                  }
                  data-testid={`legacy-status-${task.id}`}
                >
                  {task.port_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Savecase replay parity — {parity.savecase}</h3>
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
        Max absolute delta {parity.max_abs_delta_mw.toFixed(4)} MW across the replay, inside the{' '}
        {parity.ace_bound_mw.toFixed(4)} MW single-precision bound of this savecase: the Fortran
        stores every value as a 32-bit REAL and the 10B bias term amplifies the frequency rounding.
      </p>

      <h3>Characterization corpus — RTGENACE goldens</h3>
      <dl className="detail" data-testid="parity-corpus">
        <div>
          <dt>Savecases replayed</dt>
          <dd data-testid="corpus-cases">
            {corpus.cases} ({corpus.accepted} accepted, {corpus.refused} refused by the reader)
          </dd>
        </div>
        <div>
          <dt>Ported service matches legacy</dt>
          <dd data-testid="corpus-matched">
            {corpus.matched} of {corpus.cases}
            {corpus.diverging.length > 0 && ` — diverging: ${corpus.diverging.join(', ')}`}
          </dd>
        </div>
        <div>
          <dt>Legacy binary reproduces goldens</dt>
          <dd data-testid="corpus-reproduced">
            {corpus.goldens_reproduced} of {corpus.cases}
          </dd>
        </div>
        <div>
          <dt>Worst-case ACE delta</dt>
          <dd data-testid="corpus-ace-delta">
            {corpus.max_ace_delta_mw.toFixed(4)} MW ({corpus.worst_bound_use_pct.toFixed(1)}% of
            its bound)
          </dd>
        </div>
        <div>
          <dt>Deadband knife-edge cases</dt>
          <dd data-testid="corpus-indeterminate">
            {corpus.deadband_indeterminate} judged on the legacy ACE
          </dd>
        </div>
        <div>
          <dt>Characterization tests</dt>
          <dd data-testid="corpus-tests">{pinnedTests ?? 0} pinning RTGENACE</dd>
        </div>
      </dl>

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
              <dt>Characterization tests</dt>
              <dd data-testid="legacy-drawer-tests">{selected.characterization_tests}</dd>
            </div>
            <div>
              <dt>Migration readiness</dt>
              <dd data-testid="legacy-drawer-readiness">
                {selected.characterization_tests === 0
                  ? 'Blocked: no behaviour is pinned before the rewrite'
                  : selected.parity_checked
                    ? `Parity proven on ${corpus.cases} savecases: ready to retire`
                    : 'Ready for rewrite'}
              </dd>
            </div>
          </dl>
        </aside>
      )}
    </section>
  );
}
