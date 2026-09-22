import type { BacklogItem, ModuleCoverage } from '../types';

interface Props {
  module: ModuleCoverage;
  queued: boolean;
  onClose: () => void;
  onQueue: (item: BacklogItem) => void;
}

export default function ModuleDrawer({ module, queued, onClose, onQueue }: Props) {
  const queue = () => {
    onQueue({
      id: `${module.id}-${Date.now()}`,
      moduleId: module.id,
      moduleName: module.name,
      targetPct: module.target_pct,
      tier: module.tier,
      technique: module.layer === 'firmware' ? 'Unit + fault injection' : 'Unit + API contract',
      justification: `Queued from module drawer: ${module.function} is ${module.gap_pct.toFixed(
        1,
      )} points below its ${module.tier} target.`,
      createdAt: new Date().toISOString(),
    });
  };

  return (
    <aside className="drawer" role="dialog" aria-label={`${module.name} detail`} data-testid="drawer">
      <div className="drawer-head">
        <div>
          <h2 data-testid="drawer-title">{module.name}</h2>
          <p className="subtle mono">{module.path}</p>
        </div>
        <button type="button" data-testid="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      <dl className="detail">
        <div>
          <dt>Control function</dt>
          <dd data-testid="drawer-function">{module.function}</dd>
        </div>
        <div>
          <dt>Governing standard</dt>
          <dd data-testid="drawer-standard">{module.standard}</dd>
        </div>
        <div>
          <dt>Owning team</dt>
          <dd data-testid="drawer-team">{module.team}</dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd data-testid="drawer-coverage">
            {module.coverage_pct.toFixed(1)}% of {module.lines_total} lines (target{' '}
            {module.target_pct}%)
          </dd>
        </div>
        <div>
          <dt>Uncovered lines</dt>
          <dd className="mono" data-testid="drawer-uncovered">
            {module.uncovered_lines.length ? module.uncovered_lines.join(', ') : 'none'}
          </dd>
        </div>
      </dl>

      <button
        type="button"
        className="primary"
        data-testid="drawer-queue"
        disabled={queued}
        onClick={queue}
      >
        {queued ? 'Already queued' : 'Queue test generation'}
      </button>
    </aside>
  );
}
