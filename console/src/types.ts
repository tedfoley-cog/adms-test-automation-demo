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
  port_status: 'ported, unverified' | 'not started';
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

export interface ModernizationReport {
  clone: string;
  platform: string;
  tasks: LegacyTask[];
  parity: {
    savecase: string;
    legacy_ace_mw: number;
    modern_ace_mw: number;
    max_abs_delta_mw: number;
    matches: boolean;
    setpoints: ParitySetpoint[];
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

export interface RealtimeTask {
  task: string;
  rate_hz: number;
  budget_cycles: number;
  max_cycles: number;
  mean_cycles: number;
  max_us: number;
  headroom_pct: number;
  worst_scenario: string;
  status: 'within budget' | 'over budget';
}

export interface RealtimeScenario {
  name: string;
  description: string;
  expected: string[];
  observed: string[];
  bus_trip: boolean;
  trip_ms: number | null;
  util_pct: number;
  pass: boolean;
}

export interface ComplianceTest {
  id: string;
  test: string;
  clause: string;
  limit: string;
  automated: boolean;
  status: 'pass' | 'fail' | 'not automated';
  points: number;
  worst_tve_pct: number | null;
}

export interface RealtimeReport {
  generated_at: string;
  label: string;
  target: {
    mcu: string;
    core: string;
    cpu_hz: number;
    emulator: string;
    resolution_cycles: number;
    flash_bytes: number;
    ram_bytes: number;
    method: string;
  };
  rates: { sample_hz: number; protection_hz: number; pmu_hz: number; comms_hz: number };
  worst_util_pct: number;
  tasks: RealtimeTask[];
  scenarios: RealtimeScenario[];
  compliance: ComplianceTest[];
}
