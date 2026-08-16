export type ThemePreference = "light" | "dark" | "system";
export type PayFrequency = "weekly" | "biweekly" | "semimonthly" | "monthly" | "annual";
export type TransactionKind = "income" | "expense" | "transfer" | "refund";
export type AccountType = "depository" | "credit" | "loan" | "investment" | "other";
export type SourceType = "manual" | "plaid";

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
}

export interface CurrencyOption {
  code: string;
  name: string;
}

export interface SetupCategoryOption {
  key: string;
  name: string;
  group: string;
  selected_by_default: boolean;
}

export interface SetupStatus {
  initialized: boolean;
  demo_mode: boolean;
  bootstrap_required: boolean;
  google_auth_enabled: boolean;
  invite_only: boolean;
  email_delivery_configured: boolean;
}

export interface SetupOptions {
  currencies: CurrencyOption[];
  pay_frequencies: SelectOption<PayFrequency>[];
  default_categories: SetupCategoryOption[];
}

export interface UserSettings {
  currency: string;
  timezone: string;
  theme: ThemePreference;
  annual_gross_income: string | null;
  pay_frequency: PayFrequency | null;
  advisor_enabled: boolean;
  advisor_share_merchants: boolean;
  advisor_share_planning_names: boolean;
  advisor_include_descriptions: boolean;
  advisor_store_history: boolean;
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  email_verified: boolean;
  settings: UserSettings;
}

export interface AuthSession {
  user: AuthUser;
  csrf_token: string;
}

export interface LoginResult {
  authenticated: boolean;
  two_factor_required: boolean;
  challenge_token: string | null;
  user: AuthUser | null;
  csrf_token: string | null;
}

export interface SecurityStatus {
  is_admin: boolean;
  email_verified: boolean;
  has_password: boolean;
  google_enabled: boolean;
  google_connected: boolean;
  two_factor_enabled: boolean;
  email_delivery_configured: boolean;
  invite_only: boolean;
}

export interface AuthSessionItem {
  id: number;
  current: boolean;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
}

export interface AuthSessionsResponse { sessions: AuthSessionItem[]; }

export interface UserInvitation {
  id: number;
  email: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  delivery?: "email" | "manual" | null;
  invite_url?: string | null;
}

export interface UserInvitationsResponse { invitations: UserInvitation[]; }

export interface InvitationDetails {
  email: string;
  expires_at: string;
  google_enabled: boolean;
}

export interface PasswordResetStatus { valid: boolean; email: string | null; }

export interface TotpSetup { secret: string; otpauth_uri: string; }
export interface TotpConfirmation { recovery_codes: string[]; }

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  email_verified: boolean;
  is_admin: boolean;
  has_password: boolean;
  google_connected: boolean;
  last_login_at: string | null;
}
export interface AdminUsersResponse { users: AdminUser[]; }
export interface ResetDelivery { ok: boolean; delivery: "email" | "manual" | "unavailable"; reset_url?: string | null; }

export interface SetupRequest {
  username: string;
  email: string;
  password: string;
  currency: string;
  timezone: string;
  theme: ThemePreference;
  annual_gross_income: string | null;
  pay_frequency: PayFrequency | null;
  category_keys: string[];
}

export interface Category {
  id: number;
  key: string;
  name: string;
  group: string;
  enabled: boolean;
}

export interface CategorySelection {
  categories: Category[];
}

export interface AccountSummary {
  id: number;
  institution: string | null;
  name: string;
  official_name: string | null;
  display_name: string;
  account_type: AccountType;
  account_subtype: string | null;
  source_type: SourceType;
  mask: string | null;
  current_balance: string;
  available_balance: string | null;
  credit_limit: string | null;
  currency: string;
  last_synced_at: string | null;
  connection_id?: number | null;
}

export interface TransactionItem {
  id: number;
  posted_date: string;
  authorized_date: string | null;
  merchant: string | null;
  provider_merchant?: string | null;
  display_merchant?: string | null;
  description: string;
  original_description: string | null;
  payment_channel: string | null;
  pfc_primary: string | null;
  pfc_detailed: string | null;
  pfc_confidence: string | null;
  amount: string;
  kind: TransactionKind;
  provider_kind?: TransactionKind;
  source_type: SourceType;
  pending: boolean;
  notes: string | null;
  excluded_from_spending?: boolean;
  has_user_override?: boolean;
  applied_rule_id?: number | null;
  account: {
    id: number;
    name: string;
    display_name?: string;
    mask: string | null;
    currency: string;
  };
  category: Pick<Category, "id" | "key" | "name"> | null;
  provider_category?: Pick<Category, "id" | "key" | "name"> | null;
}

export interface PaginatedTransactions {
  items: TransactionItem[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface CategoryTotal {
  key: string;
  name: string;
  amount: string;
}

export interface DailyCashFlow {
  date: string;
  amount: string;
}

export interface DashboardData {
  period: {
    month: string;
    start: string;
    end: string;
  };
  currency: string;
  as_of: string;
  summary: {
    net_worth: string;
    cash_available: string;
    income: string;
    spending: string;
    net_cash_flow: string;
    savings_rate: string | null;
  };
  spending_by_category: CategoryTotal[];
  daily_cash_flow: DailyCashFlow[];
  accounts: AccountSummary[];
  recent_transactions: TransactionItem[];
  excluded_currencies: string[];
}

export interface AccountsResponse {
  accounts: AccountSummary[];
}

export interface CsvImportError { row: number; message: string; }
export interface CsvTransactionImportResult {
  total_rows: number;
  imported: number;
  skipped_duplicates: number;
  errors: CsvImportError[];
}

export interface AccountWritePayload {
  name: string;
  official_name: string | null;
  account_type: AccountType;
  account_subtype: string | null;
  current_balance: string;
  available_balance: string | null;
  credit_limit: string | null;
  currency: string;
  mask_last4: string | null;
}

export interface TransactionWritePayload {
  account_id: number;
  category_id: number | null;
  posted_date: string;
  authorized_date: string | null;
  merchant: string | null;
  provider_merchant?: string | null;
  display_merchant?: string | null;
  description: string;
  amount: string;
  kind: TransactionKind;
  pending: boolean;
  notes: string | null;
}

export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    fields?: Record<string, string[]>;
  };
}

export interface TransactionFilters {
  page?: number;
  page_size?: number;
  start_date?: string;
  end_date?: string;
  account_id?: string;
  category_id?: string;
  search?: string;
  min_amount?: string;
  max_amount?: string;
  kind?: TransactionKind | "";
  pending?: "true" | "false" | "";
  sort?: "date" | "amount" | "merchant" | "description";
  direction?: "asc" | "desc";
}


export interface PlaidInstitution {
  id: number | null;
  name: string;
  logo: string | null;
  primary_color: string | null;
  url: string | null;
}

export interface PlaidConnection {
  id: number;
  status: "active" | "error";
  environment: "sandbox" | "production";
  environment_matches: boolean;
  health: "healthy" | "needs_attention" | "environment_mismatch";
  update_required: boolean;
  update_reason: string | null;
  last_error_code: string | null;
  consent_expiration_at: string | null;
  last_webhook_at: string | null;
  last_synced_at: string | null;
  transactions_update_status: string | null;
  transactions_last_synced_at: string | null;
  transactions_last_error_code: string | null;
  institution: PlaidInstitution;
  accounts: AccountSummary[];
}

export interface PlaidConnectionsResponse {
  configured: boolean;
  environment: "sandbox" | "production";
  connections: PlaidConnection[];
}

export interface PlaidLinkTokenResponse {
  link_token: string;
  environment: "sandbox" | "production";
  mode: "connect" | "update";
  connection_id: number | null;
}

export interface PlaidSyncResult {
  connection_id: number;
  added: number;
  modified: number;
  removed: number;
  update_status: string | null;
  last_synced_at: string;
}

export interface TransactionIntelligencePayload {
  category_id?: number | null;
  display_merchant?: string | null;
  kind_override?: TransactionKind | null;
  excluded_from_spending?: boolean;
}

export interface TransactionRule {
  id: number;
  name: string;
  match_field: "merchant" | "description" | "either";
  pattern: string;
  category: Pick<Category, "id" | "key" | "name"> | null;
  display_merchant: string | null;
  kind_override: TransactionKind | null;
  excluded_from_spending: boolean | null;
  priority: number;
  enabled: boolean;
}

export interface TransactionRulesResponse { rules: TransactionRule[]; }

export interface TransactionRuleCreate {
  name: string;
  match_field: "merchant" | "description" | "either";
  pattern: string;
  category_id: number | null;
  display_merchant: string | null;
  kind_override: TransactionKind | null;
  excluded_from_spending: boolean | null;
  priority: number;
  enabled: boolean;
}

export interface RecurringStream {
  id: number;
  display_name: string;
  kind: "income" | "expense";
  cadence: "weekly" | "biweekly" | "monthly" | "quarterly" | "annual";
  average_amount: string;
  last_amount: string;
  last_date: string;
  next_expected_date: string;
  occurrence_count: number;
  price_change_pct: string | null;
  account: { id: number; name: string; display_name: string; mask: string | null; currency: string };
}

export interface RecurringStreamsResponse {
  currency: string;
  streams: RecurringStream[];
  monthly_outflow_estimate: string;
  monthly_inflow_estimate: string;
}

export type RolloverMode = "off" | "surplus" | "surplus_and_deficit";
export type BudgetDistribution = "even" | "monthly" | "custom";
export type MonthlyBudgetMode = "standalone" | "override";
export type BudgetStatus = "on_track" | "close" | "over" | "no_budget";

export interface BudgetCategoryRef {
  id: number;
  key: string;
  name: string;
  group: string;
  enabled: boolean;
}

export interface AnnualBudgetCategory {
  category: BudgetCategoryRef;
  annual_amount: string;
  distribution: BudgetDistribution;
  monthly_amount: string | null;
  rollover_mode: RolloverMode;
  custom_months: Array<{ month: number; amount: string }>;
}

export interface AnnualBudgetPlan {
  year: number;
  exists: boolean;
  planned_income: string;
  notes: string | null;
  categories: AnnualBudgetCategory[];
}

export interface AnnualBudgetPlanWrite {
  planned_income: string;
  notes: string | null;
  categories: Array<{
    category_id: number;
    annual_amount: string;
    distribution: BudgetDistribution;
    monthly_amount: string | null;
    custom_months: Array<{ month: number; amount: string }>;
    rollover_mode: RolloverMode;
  }>;
}

export interface MonthlyBudgetCategory {
  category: BudgetCategoryRef;
  base_amount: string;
  rollover_amount: string;
  available_amount: string;
  spent_amount: string;
  remaining_amount: string;
  percent_used: string | null;
  status: BudgetStatus;
  rollover_mode: RolloverMode;
}

export interface MonthlyBudgetView {
  period: { month: string; start: string; end: string };
  currency: string;
  source: "annual" | "standalone" | "override" | "unplanned";
  monthly_mode: MonthlyBudgetMode | null;
  has_annual_plan: boolean;
  planned_income: string;
  actual_income: string;
  budgeted: string;
  available_with_rollover: string;
  spent: string;
  remaining: string;
  unallocated: string;
  cash_available: string;
  upcoming_recurring: string;
  planning_commitments: string;
  goal_reserves: string;
  safe_to_spend: string;
  notes: string | null;
  categories: MonthlyBudgetCategory[];
}

export interface MonthlyBudgetWrite {
  mode: MonthlyBudgetMode;
  planned_income: string | null;
  notes: string | null;
  categories: Array<{
    category_id: number;
    planned_amount: string;
    rollover_mode: RolloverMode;
  }>;
}

export interface YearBudgetCategory {
  category: BudgetCategoryRef;
  planned_amount: string;
  ytd_planned_amount: string;
  spent_amount: string;
  remaining_amount: string;
  percent_used: string | null;
}

export interface YearBudgetView {
  year: number;
  currency: string;
  has_annual_plan: boolean;
  planned_income: string;
  ytd_planned_income: string;
  actual_income: string;
  budgeted: string;
  spent: string;
  remaining: string;
  unallocated: string;
  categories: YearBudgetCategory[];
}

export type GoalType = "emergency_fund" | "savings" | "down_payment" | "vacation" | "purchase" | "custom";
export type DebtType = "credit_card" | "auto" | "student" | "personal" | "mortgage" | "medical" | "other";
export type DebtStrategy = "avalanche" | "snowball" | "custom";

export interface FinancialGoal {
  id: number;
  name: string;
  goal_type: GoalType;
  target_amount: string;
  current_amount: string;
  remaining_amount: string;
  monthly_contribution: string;
  progress_pct: string;
  target_date: string | null;
  projected_date: string | null;
  priority: number;
  active: boolean;
  notes: string | null;
  linked_account: AccountSummary | null;
}

export interface FinancialGoalsResponse {
  currency: string;
  total_target: string;
  total_current: string;
  monthly_contributions: string;
  goals: FinancialGoal[];
}

export interface FinancialGoalWrite {
  name: string;
  goal_type: GoalType;
  target_amount: string;
  current_amount: string;
  monthly_contribution: string;
  target_date: string | null;
  linked_account_id: number | null;
  priority: number;
  active: boolean;
  notes: string | null;
}

export interface DebtItem {
  id: number;
  name: string;
  debt_type: DebtType;
  balance: string;
  apr: string;
  minimum_payment: string;
  extra_payment: string;
  strategy_priority: number;
  due_day: number | null;
  active: boolean;
  notes: string | null;
  linked_account: AccountSummary | null;
  minimum_payoff_date: string | null;
  planned_payoff_date: string | null;
  interest_saved: string;
}

export interface DebtsResponse {
  currency: string;
  strategy: DebtStrategy;
  monthly_extra_budget: string;
  total_balance: string;
  total_minimums: string;
  planned_monthly_payment: string;
  minimum_total_interest: string;
  planned_total_interest: string;
  interest_saved: string;
  minimum_debt_free_date: string | null;
  planned_debt_free_date: string | null;
  debts: DebtItem[];
}

export interface DebtWrite {
  name: string;
  debt_type: DebtType;
  balance: string;
  apr: string;
  minimum_payment: string;
  extra_payment: string;
  linked_account_id: number | null;
  strategy_priority: number;
  due_day: number | null;
  active: boolean;
  notes: string | null;
}

export interface ForecastHorizon {
  days: number;
  date: string;
  starting_cash: string;
  income: string;
  recurring_expenses: string;
  budget_reserve: string;
  debt_payments: string;
  goal_contributions: string;
  new_expenses: string;
  projected_balance: string;
  above_reserve: string;
}

export interface ForecastUpcoming {
  date: string;
  name: string;
  kind: "income" | "expense";
  amount: string;
}

export interface ForecastResponse {
  currency: string;
  as_of: string;
  cash_available: string;
  goal_reserves: string;
  spendable_cash: string;
  reserve_balance: string;
  include_budget_reserve: boolean;
  horizons: ForecastHorizon[];
  upcoming: ForecastUpcoming[];
}

export interface ForecastScenarioResponse {
  baseline: ForecastResponse;
  scenario: ForecastResponse;
  cash_impact_90_days: string;
  baseline_debt_free_date: string | null;
  scenario_debt_free_date: string | null;
  interest_saved: string;
}


export type InsightPriority = "critical" | "important" | "opportunity" | "info";
export type InsightStatus = "active" | "dismissed" | "resolved";

export interface InsightEvidence {
  label: string;
  value: string;
  detail: string | null;
}

export interface InsightItem {
  id: number;
  signal_type: string;
  category: string;
  priority: InsightPriority;
  score: number;
  status: InsightStatus;
  title: string;
  summary: string;
  recommendation: string | null;
  evidence: InsightEvidence[];
  action_route: string | null;
  first_seen_at: string;
  last_seen_at: string;
  dismissed_at: string | null;
  resolved_at: string | null;
}

export interface InsightsResponse {
  generated_at: string;
  active_count: number;
  dismissed_count: number;
  resolved_count: number;
  insights: InsightItem[];
}


export type AdvisorMode = "quick" | "analysis" | "scenario";
export type AdvisorConfidence = "high" | "medium" | "low";

export interface AdvisorStatus {
  available: boolean;
  enabled: boolean;
  store_history: boolean;
  provider: string;
  model: string;
}

export interface AdvisorFact {
  label: string;
  value: string;
  detail: string;
}

export interface AdvisorReply {
  mode: AdvisorMode;
  headline: string;
  answer: string;
  confidence: AdvisorConfidence;
  warnings: string[];
  suggested_questions: string[];
  facts: AdvisorFact[];
  proposal_id?: number | null;
}

export type AdvisorProposalStatus = "draft" | "applied" | "rejected" | "undone" | "expired";
export type AdvisorProposalActionType =
  | "budget_category_monthly_set"
  | "goal_monthly_contribution_set"
  | "debt_extra_payment_set"
  | "debt_strategy_set"
  | "forecast_reserve_set";

export interface AdvisorProposalImpact {
  label: string;
  before: string;
  after: string;
}

export interface AdvisorProposalAction {
  id: number;
  action_type: AdvisorProposalActionType;
  label: string;
  rationale: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface AdvisorProposal {
  id: number;
  conversation_id: number;
  status: AdvisorProposalStatus;
  title: string;
  summary: string;
  currency: string;
  preview: { impacts: AdvisorProposalImpact[] };
  actions: AdvisorProposalAction[];
  created_at: string;
  expires_at: string;
  applied_at: string | null;
  rejected_at: string | null;
  undone_at: string | null;
}

export interface AdvisorConversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AdvisorMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  response: AdvisorReply | null;
  created_at: string;
}

export interface AdvisorConversationList { conversations: AdvisorConversation[]; }
export interface AdvisorConversationDetail { conversation: AdvisorConversation; messages: AdvisorMessage[]; }


export interface FinancialSnapshot {
  snapshot_date: string;
  currency: string;
  net_worth: string;
  cash_available: string;
  planned_income: string;
  actual_income: string;
  budgeted: string;
  spent: string;
  safe_to_spend: string;
  planning_commitments: string;
  goal_reserves: string;
  total_goal_target: string;
  total_goal_current: string;
  monthly_goal_contributions: string;
  total_debt: string;
  planned_monthly_debt_payment: string;
  reserve_balance: string;
  projected_30_day: string;
  projected_60_day: string;
  projected_90_day: string;
  planned_debt_free_date: string | null;
  captured_at: string;
}

export interface ReportsOverview {
  generated_at: string;
  currency: string;
  current: FinancialSnapshot;
  history: FinancialSnapshot[];
}

export type ReportRangeKey = "30d" | "3m" | "6m" | "ytd" | "1y";

export interface ReportRange {
  key: ReportRangeKey;
  label: string;
  start: string;
  end: string;
  previous_start: string;
  previous_end: string;
  bucket: "day" | "month";
}

export interface ReportsSpendingSummary {
  income: string;
  spending: string;
  net_cash_flow: string;
  savings_rate: string | null;
  spending_change_amount: string;
  spending_change_pct: string | null;
  income_change_pct: string | null;
  net_cash_flow_change_pct: string | null;
  current_month_spending: string;
  projected_month_spending: string;
}

export interface ReportsCashFlowPoint { period: string; income: string; spending: string; net_cash_flow: string; }
export interface ReportsCategoryTrend { category_id: number | null; key: string; name: string; amount: string; previous_amount: string; change_amount: string; change_pct: string | null; transaction_count: number; }
export interface ReportsMerchant { name: string; category: string; amount: string; transaction_count: number; }
export interface ReportsRecurringSplit { recurring: string; discretionary: string; total: string; }

export interface ReportsSpending {
  generated_at: string;
  currency: string;
  range: ReportRange;
  summary: ReportsSpendingSummary;
  series: ReportsCashFlowPoint[];
  categories: ReportsCategoryTrend[];
  top_merchants: ReportsMerchant[];
  recurring: ReportsRecurringSplit;
}

export interface ReportsBudgetSummary {
  planned_income: string;
  ytd_planned_income: string;
  actual_income: string;
  budgeted: string;
  spent: string;
  remaining: string;
  unallocated: string;
  income_variance: string;
  budget_utilization_pct: string | null;
  projected_year_end_spend: string;
}

export interface ReportsBudgetMonth { month: string; source: string; planned_income: string; actual_income: string; budgeted: string; spent: string; remaining: string; utilization_pct: string | null; }
export interface ReportsBudgetCategory { category_id: number; key: string; name: string; planned_amount: string; ytd_planned_amount: string; spent_amount: string; remaining_amount: string; percent_used: string | null; ytd_variance: string; annual_variance: string; }

export interface ReportsBudget {
  generated_at: string;
  currency: string;
  range: ReportRange;
  year: number;
  has_annual_plan: boolean;
  summary: ReportsBudgetSummary;
  months: ReportsBudgetMonth[];
  categories: ReportsBudgetCategory[];
}

export interface ReportsGoalsDebtSummary {
  goal_target: string;
  goal_current: string;
  goal_remaining: string;
  goal_progress_pct: string | null;
  monthly_goal_contributions: string;
  goal_contributions_in_range: string;
  total_debt: string;
  planned_monthly_debt_payment: string;
  interest_saved: string;
  planned_debt_free_date: string | null;
  reserve_balance: string;
  projected_90_day: string;
  forecast_accuracy_pct: string | null;
}

export interface ReportsGoal {
  id: number;
  name: string;
  goal_type: string;
  target_amount: string;
  current_amount: string;
  remaining_amount: string;
  monthly_contribution: string;
  progress_pct: string;
  contributed_in_range: string;
  target_date: string | null;
  projected_date: string | null;
}

export interface ReportsDebt {
  id: number;
  name: string;
  debt_type: string;
  balance: string;
  apr: string;
  minimum_payment: string;
  extra_payment: string;
  planned_payment: string;
  planned_payoff_date: string | null;
  minimum_payoff_date: string | null;
  interest_saved: string;
}

export interface ReportsTrajectoryPoint {
  date: string;
  goal_current: string;
  goal_target: string;
  total_debt: string;
  cash_available: string;
  spendable_cash: string;
  safe_to_spend: string;
  reserve_balance: string;
  projected_90_day: string;
}

export interface ReportsForecastAccuracy {
  origin_date: string;
  horizon_days: 30 | 60 | 90;
  target_date: string;
  predicted_balance: string;
  actual_balance: string;
  error: string;
  accuracy_pct: string;
}

export interface ReportsGoalsDebt {
  generated_at: string;
  currency: string;
  range: ReportRange;
  summary: ReportsGoalsDebtSummary;
  goals: ReportsGoal[];
  debts: ReportsDebt[];
  trajectory: ReportsTrajectoryPoint[];
  forecast: ForecastHorizon[];
  accuracy: ReportsForecastAccuracy[];
}

export type ReportSectionKey = "overview" | "spending" | "budget" | "goals";
export type ReportExportFormat = "csv" | "pdf";

export interface SavedReport {
  id: number;
  name: string;
  range: ReportRangeKey;
  sections: ReportSectionKey[];
  created_at: string;
  updated_at: string;
}

export interface SavedReportList {
  reports: SavedReport[];
}

export interface ReportExport {
  id: number;
  saved_report_id: number | null;
  name: string;
  format: ReportExportFormat;
  range: ReportRangeKey;
  sections: ReportSectionKey[];
  content_sha256: string;
  file_size: number;
  created_at: string;
}

export interface ReportExportList {
  exports: ReportExport[];
}

export interface AdvisorReportContext {
  section: ReportSectionKey;
  range: ReportRangeKey;
  label: string;
}

export type OperationalStatus = "healthy" | "attention" | "failed" | "running" | "disabled";

export interface OperationalJobStatus {
  status: OperationalStatus;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_success_at: string | null;
  age_hours: number | null;
  error_code: string | null;
  summary: Record<string, unknown>;
}

export interface OperationsStatus {
  generated_at: string;
  overall: "healthy" | "attention";
  database: { status: "healthy" };
  migration: { status: "healthy" | "attention"; current: string | null; head: string };
  jobs: {
    database_backup: OperationalJobStatus;
    backup_verify: OperationalJobStatus;
    report_snapshot: OperationalJobStatus;
    plaid_sync: OperationalJobStatus;
    notifications: OperationalJobStatus;
    maintenance: OperationalJobStatus;
  };
  maintenance: {
    report_export_count: number;
    report_export_bytes: number;
    export_retention_days: number;
    export_max_per_user: number;
    auth_retention_days: number;
    audit_retention_days: number;
    minimum_free_bytes: number;
  };
  backup_storage: {
    path: string;
    archive_count: number;
    archive_bytes: number;
    free_bytes: number | null;
  };
  attention: string[];
}

export type DashboardCardId =
  | "net_worth" | "cash_available" | "income" | "spending" | "net_cash_flow" | "savings_rate"
  | "cash_flow" | "top_spending" | "ask_budget" | "budget" | "insights" | "recent_transactions"
  | "accounts" | "data_freshness";
export type DashboardCardSize = "small" | "medium" | "wide" | "large";
export type DashboardPreset = "everyday" | "minimal" | "planning" | "analytics" | "custom";
export interface DashboardCardPreference { id: DashboardCardId; size: DashboardCardSize; visible: boolean; }
export interface DashboardPreferences { cards: DashboardCardPreference[]; preset: DashboardPreset; onboarding_dismissed_at: string | null; }
export interface DashboardOnboardingTask { key: "account" | "income" | "budget" | "goal" | "insights"; label: string; description: string; route: string; complete: boolean; }
export interface DashboardOnboarding { tasks: DashboardOnboardingTask[]; completed: number; total: number; complete: boolean; dismissed: boolean; dismissed_at: string | null; }

export type NotificationSeverity = "info" | "opportunity" | "important" | "critical";
export interface BudgetNotification {
  id: number;
  type: string;
  severity: NotificationSeverity;
  title: string;
  body: string;
  action_route: string | null;
  data: Record<string, unknown>;
  occurred_at: string;
  read_at: string | null;
  dismissed_at: string | null;
  email_sent_at: string | null;
}
export interface NotificationList { unread_count: number; notifications: BudgetNotification[]; }
export interface NotificationCount { unread_count: number; }
export interface NotificationPreferences {
  in_app_enabled: boolean;
  email_enabled: boolean;
  email_delivery_available: boolean;
  spending_alerts: boolean;
  forecast_alerts: boolean;
  goal_milestones: boolean;
  recurring_changes: boolean;
  large_transaction_alerts: boolean;
  large_transaction_threshold: string;
  weekly_summary: boolean;
  monthly_summary: boolean;
}
