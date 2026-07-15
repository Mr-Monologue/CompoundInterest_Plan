// v2.1 Product Core Types

export interface WeeklyInvestmentPlan {
  id: number;
  week_start: string;
  week_end: string;
  status: 'DRAFT' | 'FROZEN' | 'SUPERSEDED' | 'CLOSED';
  strategy_version: string;
  total_candidate_amount: number | null;
  total_final_amount: number | null;
  core_budget: number;
  satellite_budget: number;
  core_final: number;
  satellite_final: number;
  unallocated_core: number;
  unallocated_satellite: number;
  blocked_item_count: number;
  review_required_item_count: number;
  weekly_budget: number;
  generated_at?: string;
  frozen_at?: string;
}

export interface WeeklyPlanItem {
  id: number;
  weekly_plan_id: number;
  asset_code: string;
  asset_name?: string;
  asset_role: 'core' | 'satellite' | 'defensive';
  theme?: string;
  proxy_code?: string;
  data_quality_status: 'PASS' | 'WARNING' | 'REVIEW_REQUIRED' | 'BLOCKED' | 'SOURCE_ERROR';
  valuation_state?: string;
  risk_status?: string;
  exposure_status?: string;
  candidate_action?: string;
  final_action?: string;
  fixed_amount: number | null;
  dynamic_amount: number | null;
  candidate_amount: number | null;
  allocated_fixed: number | null;
  allocated_dynamic: number | null;
  final_amount: number | null;
  reason_summary?: string;
  investment_thesis?: string;
  invalidation_conditions?: string;
  calculation_trace?: string;
  nav?: number | null;
  nav_date?: string;
  proxy_close?: number | null;
  proxy_ma200?: number | null;
  dev_pct?: number | null;
  market_data_date?: string;
  data_source?: string;
}

export interface PlanBuildRequest {
  week_start: string;
  config_id: number;
  rebuild?: boolean;
}

export interface PlanFreezeResult {
  ok: boolean;
  status: string;
  journals?: number;
}

export type DecisionAction = 'APPROVED' | 'SKIPPED' | 'DEFERRED' | 'CANCELLED';

export interface DecisionRequest {
  user_action: DecisionAction;
  approved_amount?: number;
  reason?: string;
  user_note?: string;
}

export interface ExecutionRecord {
  id: number;
  weekly_plan_item_id: number;
  execution_status: 'PENDING' | 'EXECUTED' | 'FAILED' | 'CANCELLED';
  actual_amount?: number;
  actual_price?: number;
  actual_units?: number;
  fee?: number;
  platform?: string;
  external_reference?: string;
  executed_at?: string;
  user_note?: string;
}

export interface ExecutionRequest {
  execution_status: 'PENDING' | 'EXECUTED';
  actual_amount?: number;
  actual_price?: number;
  actual_units?: number;
  fee?: number;
  platform?: string;
  external_reference?: string;
  executed_at?: string;
  user_note?: string;
}

export interface ReconciliationRecord {
  id: number;
  execution_record_id: number;
  reconciliation_status: 'PENDING' | 'MATCHED' | 'MISMATCH' | 'REJECTED';
  planned_amount?: number;
  approved_amount?: number;
  actual_amount?: number;
  amount_variance?: number;
  transaction_id?: number;
}

export interface ReconciliationRequest {
  confirm: boolean;
}

export interface WeeklyReview {
  id: number;
  weekly_plan_id: number;
  status: 'DRAFT' | 'INCOMPLETE' | 'READY_FOR_USER' | 'USER_CONFIRMED' | 'CLOSED';
  planned_total: number;
  approved_total: number;
  actual_total: number;
  matched_total: number;
  approval_variance_total: number;
  execution_variance_total: number;
  item_count: number;
  approved_count: number;
  executed_count: number;
  matched_count: number;
  skipped_count: number;
  blocked_count: number;
}

export interface FollowUpAction {
  id: number;
  weekly_review_id: number;
  action_type: string;
  description: string;
  status: 'OPEN' | 'DONE' | 'DISMISSED';
  verification_result?: string;
}

export interface ApiError {
  error_code: string;
  detail?: string;
  status: number;
}
