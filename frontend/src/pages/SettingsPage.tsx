import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys, useSetupOptions } from "../api/queries";
import type { CategorySelection, PayFrequency, ThemePreference, UserSettings } from "../api/types";
import { useTheme } from "../theme/ThemeContext";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState } from "../components/States";
import { useAuth } from "../auth/AuthContext";

function getTimezones(current: string): string[] {
  const values = (Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC"];
  return Array.from(new Set([current, "UTC", ...values]));
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: queryKeys.settings, queryFn: () => apiRequest<UserSettings>("/settings") });
  const categories = useQuery({ queryKey: queryKeys.categories, queryFn: () => apiRequest<CategorySelection>("/categories/selection") });
  const options = useSetupOptions();

  return (
    <div className="page-container settings-page">
      <PageHeader title="Settings" description="Manage your preferences and spending categories." />
      {(settings.isPending || categories.isPending || options.isPending) && <LoadingState label="Loading settings" />}
      {(settings.isError || categories.isError || options.isError) && <ErrorState message="Settings could not be loaded." onRetry={() => { void settings.refetch(); void categories.refetch(); void options.refetch(); }} />}
      {settings.data && categories.data && options.data && <SettingsForms key={`${settings.data.currency}-${settings.data.timezone}-${categories.data.categories.map((item) => `${item.id}:${item.enabled}`).join(",")}`} initialSettings={settings.data} initialCategories={categories.data} currencies={options.data.currencies} payFrequencies={options.data.pay_frequencies} />}
    </div>
  );
}

function SettingsForms({ initialSettings, initialCategories, currencies, payFrequencies }: { initialSettings: UserSettings; initialCategories: CategorySelection; currencies: Array<{ code: string; name: string }>; payFrequencies: Array<{ value: PayFrequency; label: string }> }) {
  const queryClient = useQueryClient();
  const { setPreference } = useTheme();
  const { sessionGeneration, isSessionCurrent } = useAuth();
  const [currency, setCurrency] = useState(initialSettings.currency);
  const [timezone, setTimezone] = useState(initialSettings.timezone);
  const [theme, setTheme] = useState<ThemePreference>(initialSettings.theme);
  const [annualIncome, setAnnualIncome] = useState(initialSettings.annual_gross_income ?? "");
  const [payFrequency, setPayFrequency] = useState<PayFrequency | "">(initialSettings.pay_frequency ?? "");
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
    saveSettings.mutate({ currency, timezone, theme, annual_gross_income: annualIncome || null, pay_frequency: payFrequency || null });
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

      <form className="panel form-stack settings-form" onSubmit={submitCategories}>
        <div className="panel-heading"><div><span className="eyebrow">Organization</span><h2>Spending categories</h2></div></div>
        {(categoryError || categoriesMessage) && <div className={`inline-alert${categoryError ? "" : " success"}`} role="status">{categoryError?.message ?? categoriesMessage}</div>}
        <fieldset className="settings-categories"><legend className="sr-only">Enabled spending categories</legend>{initialCategories.categories.map((category) => { const checked = enabledCategories.includes(category.key); const required = category.key === "other"; return <label key={category.id}><input type="checkbox" checked={checked} disabled={required} onChange={() => setEnabledCategories((current) => checked ? current.filter((key) => key !== category.key) : [...current, category.key])} /><span><strong>{category.name}</strong><small>{required ? "Always enabled fallback" : category.group}</small></span></label>; })}</fieldset>
        <div className="form-actions end"><button className="button primary" type="submit" disabled={saveCategories.isPending}>{saveCategories.isPending ? "Saving…" : "Save categories"}</button></div>
      </form>
    </div>
  );
}
