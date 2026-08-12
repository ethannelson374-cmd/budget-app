export type ThemePreference = "light" | "dark" | "system";
export type PayFrequency = "weekly" | "biweekly" | "semimonthly" | "monthly" | "annual";
export type TransactionKind = "income" | "expense" | "transfer" | "refund";

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
  account_type: string;
  account_subtype: string | null;
  mask: string | null;
  current_balance: string;
  available_balance: string | null;
  credit_limit: string | null;
  currency: string;
  last_synced_at: string | null;
}

export interface TransactionItem {
  id: number;
  posted_date: string;
  authorized_date: string | null;
  merchant: string | null;
  description: string;
  amount: string;
  kind: TransactionKind;
  pending: boolean;
  account: {
    id: number;
    name: string;
    display_name?: string;
    mask: string | null;
    currency: string;
  };
  category: Pick<Category, "id" | "key" | "name"> | null;
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
