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
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  settings: UserSettings;
}

export interface AuthSession {
  user: AuthUser;
  csrf_token: string;
}

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
  last_error_code: string | null;
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
