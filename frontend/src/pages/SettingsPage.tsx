import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys, useSetupOptions } from "../api/queries";
import type { AdvisorStatus, CategorySelection, PayFrequency, ThemePreference, TransactionRuleCreate, TransactionRulesResponse, UserSettings } from "../api/types";
import { useTheme } from "../theme/ThemeContext";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState } from "../components/States";
import { useAuth } from "../auth/AuthContext";
import { SecuritySettings } from "../components/SecuritySettings";
import { OperationsStatusCard } from "../components/OperationsStatusCard";

function getTimezones(current: string): string[] {
  const values = (Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC"];
  return Array.from(new Set([current, "UTC", ...values]));
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: queryKeys.settings, queryFn: () => apiRequest<UserSettings>("/settings") });
  const categories = useQuery({ queryKey: queryKeys.categories, queryFn: () => apiRequest<CategorySelection>("/categories/selection") });
  const options = useSetupOptions();
  const rules = useQuery({ queryKey: queryKeys.transactionRules, queryFn: () => apiRequest<TransactionRulesResponse>("/transaction-rules") });
  const advisorStatus = useQuery({ queryKey: queryKeys.advisorStatus, queryFn: () => apiRequest<AdvisorStatus>("/advisor/status") });

  return (
    <div className="page-container settings-page">
      <PageHeader title="Settings" description="Manage your preferences and spending categories." />
      {(settings.isPending || categories.isPending || options.isPending || rules.isPending || advisorStatus.isPending) && <LoadingState label="Loading settings" />}
      {(settings.isError || categories.isError || options.isError || rules.isError || advisorStatus.isError) && <ErrorState message="Settings could not be loaded." onRetry={() => { void settings.refetch(); void categories.refetch(); void options.refetch(); void rules.refetch(); void advisorStatus.refetch(); }} />}
      {settings.data && categories.data && options.data && rules.data && advisorStatus.data && <SettingsForms key={`${settings.data.currency}-${settings.data.timezone}-${settings.data.advisor_enabled}-${settings.data.advisor_store_history}-${categories.data.categories.map((item) => `${item.id}:${item.enabled}`).join(",")}`} initialSettings={settings.data} initialCategories={categories.data} initialRules={rules.data} advisorStatus={advisorStatus.data} currencies={options.data.currencies} payFrequencies={options.data.pay_frequencies} />}
      <SecuritySettings />
      <OperationsStatusCard />
    </div>
  );
}

function SettingsForms({ initialSettings, initialCategories, initialRules, advisorStatus, currencies, payFrequencies }: { initialSettings: UserSettings; initialCategories: CategorySelection; initialRules: TransactionRulesResponse; advisorStatus: AdvisorStatus; currencies: Array<{ code: string; name: string }>; payFrequencies: Array<{ value: PayFrequency; label: string }> }) {
  const queryClient = useQueryClient();
  const { setPreference } = useTheme();
  const { sessionGeneration, isSessionCurrent } = useAuth();
  const [currency, setCurrency] = useState(initialSettings.currency);
  const [timezone, setTimezone] = useState(initialSettings.timezone);
  const [theme, setTheme] = useState<ThemePreference>(initialSettings.theme);
  const [annualIncome, setAnnualIncome] = useState(initialSettings.annual_gross_income ?? "");
  const [payFrequency, setPayFrequency] = useState<PayFrequency | "">(initialSettings.pay_frequency ?? "");
  const [advisorEnabled, setAdvisorEnabled] = useState(initialSettings.advisor_enabled);
  const [shareMerchants, setShareMerchants] = useState(initialSettings.advisor_share_merchants);
  const [includeDescriptions, setIncludeDescriptions] = useState(initialSettings.advisor_include_descriptions);
  const [storeAdvisorHistory, setStoreAdvisorHistory] = useState(initialSettings.advisor_store_history);
  const [advisorMessage, setAdvisorMessage] = useState<string | null>(null);
  const [enabledCategories, setEnabledCategories] = useState(() => Array.from(new Set([
    ...initialCategories.categories.filter((category) => category.enabled).map((category) => category.key),
    ...(initialCategories.categories.some((category) => category.key === "other") ? ["other"] : []),
  ])));
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [categoriesMessage, setCategoriesMessage] = useState<string | null>(null);

  const saveSettings = useMutation({
    mutationFn: (payload: UserSettings) => apiRequest<UserSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: (saved) => {
      if (!isSessionCurrent(sessionGeneration)) return;
      queryClient.setQueryData(queryKeys.settings, saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.advisorStatus });
      setPreference(saved.theme);
      setSettingsMessage("Preferences saved.");
    },
  });
  const saveCategories = useMutation({
    mutationFn: (category_keys: string[]) => apiRequest<CategorySelection>("/categories/selection", { method: "PUT", body: JSON.stringify({ category_keys }) }),
    onSuccess: (saved) => {
      if (!isSessionCurrent(sessionGeneration)) return;
      queryClient.setQueryData(queryKeys.categories, saved);
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setCategoriesMessage("Categories saved.");
    },
  });


  const deleteAdvisorHistory = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/advisor/conversations", { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.advisorConversations });
      setAdvisorMessage("Advisor history deleted.");
    },
  });

  const createRule = useMutation({
    mutationFn: (payload: TransactionRuleCreate) => apiRequest<TransactionRulesResponse>("/transaction-rules", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: (saved) => {
      if (!isSessionCurrent(sessionGeneration)) return;
      queryClient.setQueryData(queryKeys.transactionRules, saved);
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.recurring });
    },
  });
  const deleteRule = useMutation({
    mutationFn: (id: number) => apiRequest<TransactionRulesResponse>(`/transaction-rules/${id}`, { method: "DELETE" }),
    onSuccess: (saved) => {
      if (!isSessionCurrent(sessionGeneration)) return;
      queryClient.setQueryData(queryKeys.transactionRules, saved);
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.recurring });
    },
  });

  const submitRule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = (key: string) => String(data.get(key) ?? "").trim();
    const category = text("category_id");
    const kind = text("kind_override");
    const excludeAction = text("exclude_action");
    createRule.mutate({
      name: text("name"),
      match_field: text("match_field") as "merchant" | "description" | "either",
      pattern: text("pattern"),
      category_id: category ? Number(category) : null,
      display_merchant: text("display_merchant") || null,
      kind_override: (kind || null) as TransactionRuleCreate["kind_override"],
      excluded_from_spending: excludeAction === "exclude" ? true : excludeAction === "include" ? false : null,
      priority: Number(text("priority") || "100"),
      enabled: true,
    }, { onSuccess: () => form.reset() });
  };

  const submitSettings = (event: FormEvent) => {
    event.preventDefault();
    setSettingsMessage(null);
    if (annualIncome && (!/^\d+(\.\d{1,4})?$/.test(annualIncome) || Number(annualIncome) < 0)) {
      setSettingsMessage("Enter a valid positive annual income.");
      return;
    }
    if (annualIncome && !payFrequency) {
      setSettingsMessage("Choose a pay frequency when annual income is provided.");
      return;
    }
    saveSettings.mutate({
      currency, timezone, theme, annual_gross_income: annualIncome || null, pay_frequency: payFrequency || null,
      advisor_enabled: advisorEnabled, advisor_share_merchants: shareMerchants,
      advisor_include_descriptions: includeDescriptions, advisor_store_history: storeAdvisorHistory,
    });
  };
  const submitCategories = (event: FormEvent) => {
    event.preventDefault();
    setCategoriesMessage(null);
    if (!enabledCategories.length) { setCategoriesMessage("Keep at least one category enabled."); return; }
    saveCategories.mutate(enabledCategories);
  };

  const settingsError = saveSettings.error instanceof ApiError ? saveSettings.error : null;
  const categoryError = saveCategories.error instanceof ApiError ? saveCategories.error : null;
  return (
    <div className="settings-grid">
      <form className="panel form-stack settings-form" onSubmit={submitSettings}>
        <div className="panel-heading"><div><span className="eyebrow">Profile</span><h2>Financial preferences</h2></div></div>
        {(settingsError || settingsMessage) && <div className={`inline-alert${settingsError ? "" : " success"}`} role="status">{settingsError?.message ?? settingsMessage}</div>}
        <div className="form-grid two-columns">
          <label>Currency<select value={currency} onChange={(event) => setCurrency(event.target.value)}>{currencies.map((item) => <option value={item.code} key={item.code}>{item.code} — {item.name}</option>)}</select></label>
          <label>Timezone<select value={timezone} onChange={(event) => setTimezone(event.target.value)}>{getTimezones(initialSettings.timezone).map((zone) => <option key={zone}>{zone}</option>)}</select></label>
          <label>Annual gross income <span className="optional">Optional</span><input inputMode="decimal" value={annualIncome} onChange={(event) => setAnnualIncome(event.target.value)} /></label>
          <label>Pay frequency <span className="optional">Optional</span><select value={payFrequency} onChange={(event) => setPayFrequency(event.target.value as PayFrequency | "")}><option value="">Not set</option>{payFrequencies.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        </div>
        <fieldset className="theme-picker"><legend>Appearance</legend>{(["system", "light", "dark"] as ThemePreference[]).map((value) => <label key={value} className={theme === value ? "selected" : ""}><input type="radio" name="settings-theme" value={value} checked={theme === value} onChange={() => setTheme(value)} /><span>{value.charAt(0).toUpperCase() + value.slice(1)}</span></label>)}</fieldset>
        <div className="form-actions end"><button className="button primary" type="submit" disabled={saveSettings.isPending}>{saveSettings.isPending ? "Saving…" : "Save preferences"}</button></div>
      </form>

      <section className="panel form-stack settings-form advisor-settings-panel">
        <div className="panel-heading"><div><span className="eyebrow">AI Advisor</span><h2>Ask Budget privacy</h2><p>The AI explains Budget's calculations. These controls decide what context can leave your server.</p></div><span className={`advisor-status-pill${advisorStatus.available ? " ready" : ""}`}>{advisorStatus.available ? `${advisorStatus.provider} · ${advisorStatus.model}` : "Provider not configured"}</span></div>
        {advisorMessage && <div className="inline-alert success" role="status">{advisorMessage}</div>}
        <div className="advisor-setting-list">
          <label><span><strong>Enable Ask Budget</strong><small>Allow the read-only AI Advisor to answer financial questions.</small></span><input type="checkbox" checked={advisorEnabled} onChange={(event) => setAdvisorEnabled(event.target.checked)} /></label>
          <label><span><strong>Share merchant names</strong><small>Off by default. When disabled, merchant-specific insight context is redacted.</small></span><input type="checkbox" checked={shareMerchants} onChange={(event) => { setShareMerchants(event.target.checked); if (!event.target.checked) setIncludeDescriptions(false); }} /></label>
          <label className={!shareMerchants ? "disabled-setting" : ""}><span><strong>Include transaction descriptions</strong><small>Only used for merchant analysis when merchant sharing is enabled.</small></span><input type="checkbox" disabled={!shareMerchants} checked={includeDescriptions} onChange={(event) => setIncludeDescriptions(event.target.checked)} /></label>
          <label><span><strong>Store Advisor conversations</strong><small>When off, Ask Budget works as a private session and does not keep messages in Budget.</small></span><input type="checkbox" checked={storeAdvisorHistory} onChange={(event) => setStoreAdvisorHistory(event.target.checked)} /></label>
        </div>
        <div className="form-actions spread"><button className="button danger" type="button" disabled={deleteAdvisorHistory.isPending} onClick={() => { if (window.confirm("Delete all saved Ask Budget conversations?")) deleteAdvisorHistory.mutate(); }}>{deleteAdvisorHistory.isPending ? "Deleting…" : "Delete Advisor history"}</button><small>Save preferences above to apply privacy changes.</small></div>
      </section>

      <form className="panel form-stack settings-form" onSubmit={submitCategories}>
        <div className="panel-heading"><div><span className="eyebrow">Organization</span><h2>Spending categories</h2></div></div>
        {(categoryError || categoriesMessage) && <div className={`inline-alert${categoryError ? "" : " success"}`} role="status">{categoryError?.message ?? categoriesMessage}</div>}
        <fieldset className="settings-categories"><legend className="sr-only">Enabled spending categories</legend>{initialCategories.categories.map((category) => { const checked = enabledCategories.includes(category.key); const required = category.key === "other"; return <label key={category.id}><input type="checkbox" checked={checked} disabled={required} onChange={() => setEnabledCategories((current) => checked ? current.filter((key) => key !== category.key) : [...current, category.key])} /><span><strong>{category.name}</strong><small>{required ? "Always enabled fallback" : category.group}</small></span></label>; })}</fieldset>
        <div className="form-actions end"><button className="button primary" type="submit" disabled={saveCategories.isPending}>{saveCategories.isPending ? "Saving…" : "Save categories"}</button></div>
      </form>

      <section className="panel form-stack settings-form rules-panel">
        <div className="panel-heading"><div><span className="eyebrow">Automation</span><h2>Transaction rules</h2><p>Apply merchant names, categories, types, or spending exclusions to matching Plaid transactions.</p></div></div>
        {(createRule.isError || deleteRule.isError) && <div className="inline-alert" role="alert">{(createRule.error instanceof ApiError ? createRule.error.message : deleteRule.error instanceof ApiError ? deleteRule.error.message : "The rule could not be saved.")}</div>}
        <form className="form-stack rule-form" onSubmit={submitRule}>
          <div className="form-grid two-columns">
            <label>Rule name<input name="name" required maxLength={120} placeholder="Walmart groceries" /></label>
            <label>Match text<input name="pattern" required maxLength={160} placeholder="WM SUPERCENTER" /></label>
            <label>Match in<select name="match_field" defaultValue="either"><option value="either">Merchant or description</option><option value="merchant">Merchant</option><option value="description">Description</option></select></label>
            <label>Category<select name="category_id" defaultValue=""><option value="">No category change</option>{initialCategories.categories.filter((category) => category.enabled).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            <label>Display merchant <span className="optional">Optional</span><input name="display_merchant" maxLength={160} placeholder="Walmart" /></label>
            <label>Type<select name="kind_override" defaultValue=""><option value="">No type change</option><option value="expense">Expense</option><option value="income">Income</option><option value="refund">Refund</option><option value="transfer">Transfer</option></select></label>
            <label>Spending treatment<select name="exclude_action" defaultValue=""><option value="">No change</option><option value="exclude">Exclude from spending</option><option value="include">Include in spending</option></select></label>
            <label>Priority<input name="priority" type="number" min="0" max="10000" defaultValue="100" /><small>Lower numbers run first.</small></label>
          </div>
          <div className="form-actions end"><button className="button primary" type="submit" disabled={createRule.isPending}>{createRule.isPending ? "Creating…" : "Create rule"}</button></div>
        </form>
        <div className="rule-list">
          {initialRules.rules.length ? initialRules.rules.map((rule) => <article className="rule-row" key={rule.id}><div><strong>{rule.name}</strong><span>{rule.match_field}: “{rule.pattern}”</span><small>{[rule.display_merchant && `Merchant → ${rule.display_merchant}`, rule.category && `Category → ${rule.category.name}`, rule.kind_override && `Type → ${rule.kind_override}`, rule.excluded_from_spending === true && "Excluded from spending", rule.excluded_from_spending === false && "Included in spending"].filter(Boolean).join(" · ")}</small></div><button className="button danger" type="button" disabled={deleteRule.isPending} onClick={() => { if (window.confirm(`Delete ${rule.name}?`)) deleteRule.mutate(rule.id); }}>Delete</button></article>) : <p className="muted-copy">No rules yet. Create one to normalize future and existing Plaid transactions.</p>}
        </div>
      </section>
    </div>
  );
}
