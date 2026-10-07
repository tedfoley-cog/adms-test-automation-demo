export interface ModuleCoverage {
  id: string;
  name: string;
  path: string;
  layer: 'firmware' | 'backend';
  language: string;
  function: string;
  standard: string;
  team: string;
  tier: string;
  target_pct: number;
  lines_total: number;
  lines_covered: number;
  coverage_pct: number;
  gap_pct: number;
  uncovered_lines: number[];
  status: 'meets target' | 'below target';
}

export interface CoverageReport {
  generated_at: string;
  label: string;
  overall_pct: number;
  lines_total: number;
  lines_covered: number;
  tier_targets: Record<string, number>;
  modules: ModuleCoverage[];
}

export interface TestRun {
  label: string;
  generated_at: string;
  overall_pct: number;
  modules_below_target: number;
  lines_total: number;
  lines_covered: number;
}

export interface LegacyTask {
  id: string;
  source: string;
  function: string;
  standard: string;
  cycle: string;
  target_module: string | null;
  port_status: 'ported, verified' | 'ported, unverified' | 'not started';
  source_lines: number;
  executable_lines: number;
  program_units: string[];
  target_coverage_pct: number | null;
  characterization_tests: number;
  parity_checked: boolean;
}

export interface ParitySetpoint {
  unit: string;
  legacy_mw: number;
  modern_mw: number;
}

export interface CorpusParity {
  cases: number;
  accepted: number;
  refused: number;
  goldens_reproduced: number;
  matched: number;
  diverging: string[];
  deadband_indeterminate: number;
  max_ace_delta_mw: number;
  max_setpoint_delta_mw: number;
  worst_bound_use_pct: number;
}

export interface ModernizationReport {
  clone: string;
  platform: string;
  tasks: LegacyTask[];
  parity: {
    savecase: string;
    legacy_ace_mw: number;
    modern_ace_mw: number;
    max_abs_delta_mw: number;
    ace_bound_mw: number;
    matches: boolean;
    setpoints: ParitySetpoint[];
    corpus: CorpusParity;
  };
}

export interface BacklogItem {
  id: string;
  moduleId: string;
  moduleName: string;
  targetPct: number;
  tier: string;
  technique: string;
  justification: string;
  createdAt: string;
}
