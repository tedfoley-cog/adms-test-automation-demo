import { useMemo, useState } from 'react';

import ModuleDrawer from '../components/ModuleDrawer';
import type { BacklogItem, CoverageReport, ModuleCoverage } from '../types';

type SortKey = 'coverage_pct' | 'gap_pct' | 'name' | 'lines_total';

interface Props {
  report: CoverageReport;
  backlog: BacklogItem[];
  onQueue: (item: BacklogItem) => void;
}

export default function CoverageView({ report, backlog, onQueue }: Props) {
  const [search, setSearch] = useState('');
  const [layer, setLayer] = useState('all');
  const [tier, setTier] = useState('all');
  const [onlyBelow, setOnlyBelow] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('coverage_pct');
  const [ascending, setAscending] = useState(true);
  const [selected, setSelected] = useState<ModuleCoverage | null>(null);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = report.modules.filter((module) => {
      if (layer !== 'all' && module.layer !== layer) return false;
      if (tier !== 'all' && module.tier !== tier) return false;
      if (onlyBelow && module.status !== 'below target') return false;
      if (!needle) return true;
      return (
        module.name.toLowerCase().includes(needle) ||
        module.path.toLowerCase().includes(needle) ||
        module.function.toLowerCase().includes(needle) ||
        module.standard.toLowerCase().includes(needle)
      );
    });

    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === 'name') return a.name.localeCompare(b.name);
      return (a[sortKey] as number) - (b[sortKey] as number);
    });
    return ascending ? sorted : sorted.reverse();
  }, [report.modules, search, layer, tier, onlyBelow, sortKey, ascending]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setAscending((value) => !value);
    } else {
      setSortKey(key);
      setAscending(true);
    }
  };

  return (
    <section className="panel">
      <div className="toolbar">
        <input
          type="search"
          placeholder="Search module, path, function or standard"
          aria-label="Search modules"
          data-testid="filter-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label>
          Layer
          <select
            data-testid="filter-layer"
            value={layer}
            onChange={(event) => setLayer(event.target.value)}
          >
            <option value="all">All</option>
            <option value="firmware">Firmware</option>
            <option value="backend">Backend</option>
            <option value="service">Service</option>
          </select>
        </label>
        <label>
          Tier
          <select
            data-testid="filter-tier"
            value={tier}
            onChange={(event) => setTier(event.target.value)}
          >
            <option value="all">All</option>
            <option value="Tier 1">Tier 1</option>
            <option value="Tier 2">Tier 2</option>
            <option value="Tier 3">Tier 3</option>
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            data-testid="filter-below"
            checked={onlyBelow}
            onChange={(event) => setOnlyBelow(event.target.checked)}
          />
          Below target only
        </label>
        <span className="result-count" data-testid="result-count">
          {rows.length} of {report.modules.length} modules
        </span>
      </div>

      <table className="grid" data-testid="coverage-table">
        <thead>
          <tr>
            <th>
              <button type="button" data-testid="sort-name" onClick={() => toggleSort('name')}>
                Module
              </button>
            </th>
            <th>Function</th>
            <th>Tier</th>
            <th>
              <button
                type="button"
                data-testid="sort-coverage"
                onClick={() => toggleSort('coverage_pct')}
              >
                Coverage
              </button>
            </th>
            <th>Target</th>
            <th>
              <button type="button" data-testid="sort-gap" onClick={() => toggleSort('gap_pct')}>
                Gap
              </button>
            </th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((module) => (
            <tr
              key={module.id}
              data-testid={`row-${module.name}`}
              className="row"
              onClick={() => setSelected(module)}
            >
              <td>
                <span className="mono">{module.name}</span>
                <span className="subtle">{module.path}</span>
              </td>
              <td>{module.function}</td>
              <td>
                <span className={`tier tier-${module.tier.replace(' ', '').toLowerCase()}`}>
                  {module.tier}
                </span>
              </td>
              <td className="numeric" data-testid={`coverage-${module.name}`}>
                <div className="bar">
                  <span style={{ width: `${Math.max(module.coverage_pct, 1)}%` }} />
                </div>
                {module.coverage_pct.toFixed(1)}%
              </td>
              <td className="numeric">{module.target_pct}%</td>
              <td className="numeric">{module.gap_pct.toFixed(1)}</td>
              <td>
                <span
                  className={module.status === 'below target' ? 'pill pill-bad' : 'pill pill-good'}
                >
                  {module.status}
                </span>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="empty" data-testid="no-results">
                No modules match the current filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {selected && (
        <ModuleDrawer
          module={selected}
          queued={backlog.some((item) => item.moduleId === selected.id)}
          onClose={() => setSelected(null)}
          onQueue={onQueue}
        />
      )}
    </section>
  );
}
