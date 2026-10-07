import { useEffect, useMemo, useState } from 'react';

import BacklogView from './views/BacklogView';
import CoverageView from './views/CoverageView';
import ModernizationView from './views/ModernizationView';
import RealtimeView from './views/RealtimeView';
import RunsView from './views/RunsView';
import type {
  BacklogItem,
  CoverageReport,
  ModernizationReport,
  RealtimeReport,
  TestRun,
} from './types';

type Tab = 'coverage' | 'realtime' | 'modernization' | 'runs' | 'backlog';

const TABS: { id: Tab; label: string }[] = [
  { id: 'coverage', label: 'Coverage' },
  { id: 'realtime', label: 'Real-time' },
  { id: 'modernization', label: 'Legacy modernization' },
  { id: 'runs', label: 'Test runs' },
  { id: 'backlog', label: 'Verification backlog' },
];

export default function App() {
  const [report, setReport] = useState<CoverageReport | null>(null);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [modernization, setModernization] = useState<ModernizationReport | null>(null);
  const [realtime, setRealtime] = useState<RealtimeReport | null>(null);
  const [backlog, setBacklog] = useState<BacklogItem[]>([]);
  const [tab, setTab] = useState<Tab>('coverage');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch('coverage.json').then((r) => r.json() as Promise<CoverageReport>),
      fetch('testruns.json').then((r) => r.json() as Promise<TestRun[]>),
      fetch('modernization.json').then((r) => r.json() as Promise<ModernizationReport>),
      fetch('realtime.json').then((r) => r.json() as Promise<RealtimeReport>),
    ])
      .then(([coverage, history, legacy, rt]) => {
        setReport(coverage);
        setRuns(history);
        setModernization(legacy);
        setRealtime(rt);
      })
      .catch(() =>
        setError(
          'Reports not found. Run tools/build_coverage_report.py, tools/build_legacy_inventory.py and tools/build_realtime_report.py.',
        ),
      );
  }, []);

  const belowTarget = useMemo(
    () => (report ? report.modules.filter((m) => m.status === 'below target') : []),
    [report],
  );
  const tier1Gap = useMemo(
    () => belowTarget.filter((m) => m.tier === 'Tier 1').length,
    [belowTarget],
  );

  if (error) {
    return (
      <main className="shell">
        <p className="error" data-testid="load-error">
          {error}
        </p>
      </main>
    );
  }

  if (!report || !modernization || !realtime) {
    return (
      <main className="shell">
        <p data-testid="loading">Loading coverage report…</p>
      </main>
    );
  }

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">Grid control portfolio</p>
          <h1>Verification Console</h1>
        </div>
        <dl className="kpis">
          <div className="kpi">
            <dt>Line coverage</dt>
            <dd data-testid="kpi-overall">{report.overall_pct.toFixed(1)}%</dd>
          </div>
          <div className="kpi">
            <dt>Modules below target</dt>
            <dd data-testid="kpi-below">{belowTarget.length}</dd>
          </div>
          <div className="kpi">
            <dt>Legacy tasks unverified</dt>
            <dd data-testid="kpi-legacy">
              {modernization.tasks.filter((task) => task.characterization_tests === 0).length}
            </dd>
          </div>
          <div className="kpi">
            <dt>Tier 1 gaps</dt>
            <dd data-testid="kpi-tier1">{tier1Gap}</dd>
          </div>
          <div className="kpi">
            <dt>Queued for generation</dt>
            <dd data-testid="kpi-backlog">{backlog.length}</dd>
          </div>
        </dl>
      </header>

      <nav className="tabs" aria-label="Views">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === tab ? 'tab tab-active' : 'tab'}
            data-testid={`tab-${item.id}`}
            aria-current={item.id === tab}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <main>
        {tab === 'coverage' && (
          <CoverageView
            report={report}
            backlog={backlog}
            onQueue={(item) => setBacklog((current) => [...current, item])}
          />
        )}
        {tab === 'realtime' && <RealtimeView realtime={realtime} />}
        {tab === 'modernization' && <ModernizationView modernization={modernization} />}
        {tab === 'runs' && <RunsView runs={runs} report={report} />}
        {tab === 'backlog' && (
          <BacklogView
            report={report}
            backlog={backlog}
            onQueue={(item) => setBacklog((current) => [...current, item])}
            onRemove={(id) => setBacklog((current) => current.filter((i) => i.id !== id))}
          />
        )}
      </main>

      <footer className="footer">
        Report {report.label} generated {new Date(report.generated_at).toUTCString()} ·{' '}
        {report.lines_covered}/{report.lines_total} executable lines covered
      </footer>
    </div>
  );
}
