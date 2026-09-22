import LiftRequestForm from '../components/LiftRequestForm';
import type { BacklogItem, CoverageReport } from '../types';

interface Props {
  report: CoverageReport;
  backlog: BacklogItem[];
  onQueue: (item: BacklogItem) => void;
  onRemove: (id: string) => void;
}

export default function BacklogView({ report, backlog, onQueue, onRemove }: Props) {
  return (
    <section className="panel two-column">
      <div>
        <h2>Request a coverage lift</h2>
        <LiftRequestForm report={report} onQueue={onQueue} />
      </div>
      <div>
        <h2>Queued work</h2>
        {backlog.length === 0 ? (
          <p className="subtle" data-testid="backlog-empty">
            Nothing queued yet. Submit a request or queue a module from the coverage drawer.
          </p>
        ) : (
          <ul className="backlog" data-testid="backlog-list">
            {backlog.map((item) => (
              <li key={item.id} data-testid={`backlog-${item.moduleName}`}>
                <div className="backlog-head">
                  <span className="mono">{item.moduleName}</span>
                  <span className={`tier tier-${item.tier.replace(' ', '').toLowerCase()}`}>
                    {item.tier}
                  </span>
                  <span className="pill">{item.targetPct}% target</span>
                </div>
                <p className="subtle">{item.technique}</p>
                <p>{item.justification}</p>
                <button type="button" onClick={() => onRemove(item.id)} data-testid={`remove-${item.moduleName}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
