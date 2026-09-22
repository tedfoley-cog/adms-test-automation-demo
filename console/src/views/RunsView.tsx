import type { CoverageReport, TestRun } from '../types';

interface Props {
  runs: TestRun[];
  report: CoverageReport;
}

export default function RunsView({ runs, report }: Props) {
  const ordered = [...runs].reverse();

  return (
    <section className="panel">
      <h2>Test run history</h2>
      <p className="subtle">
        Each entry is a real execution of the firmware and backend suites merged by
        tools/build_coverage_report.py.
      </p>
      <table className="grid" data-testid="runs-table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Generated</th>
            <th>Line coverage</th>
            <th>Lines covered</th>
            <th>Modules below target</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((run) => (
            <tr key={`${run.label}-${run.generated_at}`} data-testid={`run-${run.label}`}>
              <td className="mono">{run.label}</td>
              <td>{new Date(run.generated_at).toUTCString()}</td>
              <td className="numeric">{run.overall_pct.toFixed(1)}%</td>
              <td className="numeric">
                {run.lines_covered}/{run.lines_total}
              </td>
              <td className="numeric">{run.modules_below_target}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Tier targets</h3>
      <ul className="targets" data-testid="tier-targets">
        {Object.entries(report.tier_targets).map(([tier, target]) => (
          <li key={tier}>
            <span className={`tier tier-${tier.replace(' ', '').toLowerCase()}`}>{tier}</span>
            <span>{target}% line coverage required before release sign-off</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
