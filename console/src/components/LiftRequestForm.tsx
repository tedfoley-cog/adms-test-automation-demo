import { useState } from 'react';

import type { BacklogItem, CoverageReport } from '../types';

const TECHNIQUES = [
  'Unit + fault injection',
  'Unit + API contract',
  'Property-based',
  'Protocol conformance replay',
];

interface Props {
  report: CoverageReport;
  onQueue: (item: BacklogItem) => void;
}

export default function LiftRequestForm({ report, onQueue }: Props) {
  const [moduleId, setModuleId] = useState('');
  const [targetPct, setTargetPct] = useState('');
  const [technique, setTechnique] = useState(TECHNIQUES[0]);
  const [justification, setJustification] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [confirmation, setConfirmation] = useState('');

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const module = report.modules.find((item) => item.id === moduleId);
    const target = Number(targetPct);
    const found: string[] = [];

    if (!module) {
      found.push('Select a module.');
    }
    if (!targetPct || Number.isNaN(target) || target <= 0 || target > 100) {
      found.push('Target coverage must be between 1 and 100.');
    } else if (module && target <= module.coverage_pct) {
      found.push(
        `Target must exceed the current ${module.coverage_pct.toFixed(1)}% coverage of ${module.name}.`,
      );
    }
    if (justification.trim().length < 20) {
      found.push('Justification must be at least 20 characters.');
    }

    setErrors(found);
    if (found.length > 0 || !module) {
      setConfirmation('');
      return;
    }

    onQueue({
      id: `${module.id}-${Date.now()}`,
      moduleId: module.id,
      moduleName: module.name,
      targetPct: target,
      tier: module.tier,
      technique,
      justification: justification.trim(),
      createdAt: new Date().toISOString(),
    });
    setConfirmation(`${module.name} queued at ${target}% target.`);
    setModuleId('');
    setTargetPct('');
    setJustification('');
  };

  return (
    <form className="form" onSubmit={submit} data-testid="lift-form" noValidate>
      <label>
        Module
        <select
          data-testid="form-module"
          value={moduleId}
          onChange={(event) => setModuleId(event.target.value)}
        >
          <option value="">Select a module…</option>
          {report.modules.map((module) => (
            <option key={module.id} value={module.id}>
              {module.name} — {module.coverage_pct.toFixed(1)}%
            </option>
          ))}
        </select>
      </label>

      <label>
        Target coverage (%)
        <input
          type="number"
          data-testid="form-target"
          value={targetPct}
          onChange={(event) => setTargetPct(event.target.value)}
        />
      </label>

      <label>
        Technique
        <select
          data-testid="form-technique"
          value={technique}
          onChange={(event) => setTechnique(event.target.value)}
        >
          {TECHNIQUES.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>

      <label>
        Justification
        <textarea
          data-testid="form-justification"
          rows={3}
          value={justification}
          onChange={(event) => setJustification(event.target.value)}
        />
      </label>

      {errors.length > 0 && (
        <ul className="errors" data-testid="form-errors">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {confirmation && (
        <p className="confirmation" data-testid="form-confirmation">
          {confirmation}
        </p>
      )}

      <button type="submit" className="primary" data-testid="form-submit">
        Queue coverage lift
      </button>
    </form>
  );
}
