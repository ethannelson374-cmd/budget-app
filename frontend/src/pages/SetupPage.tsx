import { useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys, useSetupOptions } from "../api/queries";
import type { AuthSession, PayFrequency, SetupOptions, SetupRequest, SetupStatus, ThemePreference } from "../api/types";
import { Brand } from "../components/Brand";
import { ErrorState, LoadingState } from "../components/States";
import { Icon } from "../components/Icon";
import { useAuth } from "../auth/AuthContext";

const steps = ["Owner account", "Preferences", "Categories"];

function availableTimezones(): string[] {
  const current = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const values = (Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC"];
  return Array.from(new Set([current, "UTC", ...values]));
}

export function SetupPage({ status }: { status: SetupStatus }) {
  const options = useSetupOptions(!status.initialized);
  if (options.isPending) return <SetupFrame><LoadingState label="Preparing setup" /></SetupFrame>;
  if (options.isError) return <SetupFrame><ErrorState message="Setup options could not be loaded." onRetry={() => void options.refetch()} /></SetupFrame>;
  return <SetupWizard options={options.data} bootstrapRequired={status.bootstrap_required} />;
}

function SetupFrame({ children }: { children: React.ReactNode }) {
  return (
    <main className="auth-page setup-page">
      <div className="auth-shell setup-shell">
        <div className="auth-brand"><Brand linked={false} /><p>Your financial home base, private by design.</p></div>
        {children}
      </div>
    </main>
  );
}

export function SetupWizard({ options, bootstrapRequired }: { options: SetupOptions; bootstrapRequired: boolean }) {
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [bootstrapToken, setBootstrapToken] = useState("");
  const [currency, setCurrency] = useState(options.currencies.some((item) => item.code === "USD") ? "USD" : (options.currencies[0]?.code ?? "USD"));
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [theme, setTheme] = useState<ThemePreference>("system");
  const [annualIncome, setAnnualIncome] = useState("");
  const [payFrequency, setPayFrequency] = useState<PayFrequency | "">("");
  const [categoryKeys, setCategoryKeys] = useState(() => options.default_categories.filter((category) => category.selected_by_default).map((category) => category.key));
  const [formError, setFormError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const timezones = useMemo(availableTimezones, []);

  const nextFromOwner = (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (password !== passwordConfirm) {
      setFormError("The passwords do not match.");
      return;
    }
    if (password.length < 12 || password.length > 128) {
      setFormError("Use a password between 12 and 128 characters.");
      return;
    }
    if (bootstrapRequired && bootstrapToken.length === 0) {
      setFormError("Enter the bootstrap token supplied by the server administrator.");
      return;
    }
    setStep(1);
  };

  const nextFromPreferences = (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (annualIncome && (!/^\d+(\.\d{1,4})?$/.test(annualIncome) || Number(annualIncome) < 0)) {
      setFormError("Annual income must be a positive number with no more than four decimal places.");
      return;
    }
    if (annualIncome && !payFrequency) {
      setFormError("Choose a pay frequency when annual income is provided.");
      return;
    }
    setStep(2);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setRequestError(null);
    if (categoryKeys.length === 0) {
      setFormError("Select at least one category.");
      return;
    }
    const tokenForRequest = bootstrapToken;
    const payload: SetupRequest = {
      username,
      email,
      password,
      currency,
      timezone,
      theme,
      annual_gross_income: annualIncome || null,
      pay_frequency: payFrequency || null,
      category_keys: categoryKeys,
    };

    // Credentials are deliberately never handed to TanStack Query. Clear the
    // form state before network I/O so neither browser storage nor a mutation
    // cache can retain the bootstrap token or password after submission.
    setBootstrapToken("");
    setPassword("");
    setPasswordConfirm("");
    setSubmitting(true);
    try {
      const session = await apiRequest<AuthSession>("/setup", {
        method: "POST",
        headers: tokenForRequest ? { "X-Bootstrap-Token": tokenForRequest } : undefined,
        body: JSON.stringify(payload),
      });
      establishSession(session);
      queryClient.setQueryData<SetupStatus>(queryKeys.setup, (current) => ({
        initialized: true,
        demo_mode: current?.demo_mode ?? false,
        bootstrap_required: false,
      }));
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setRequestError(caught instanceof ApiError ? caught : new ApiError("Setup could not be completed.", { status: 0 }));
      setStep(0);
    } finally {
      setBootstrapToken("");
      setPassword("");
      setPasswordConfirm("");
      setSubmitting(false);
    }
  };

  const error = requestError;

  return (
    <section className="auth-card setup-card" aria-labelledby="setup-title">
      <div className="setup-heading">
        <span className="eyebrow">First-time setup</span>
        <h1 id="setup-title">Make Budget yours</h1>
        <p>Three quick steps. You can change your preferences later.</p>
      </div>
      <ol className="stepper" aria-label="Setup progress">
        {steps.map((label, index) => <li key={label} className={index === step ? "current" : index < step ? "complete" : ""} aria-current={index === step ? "step" : undefined}><span>{index < step ? <Icon name="check" /> : index + 1}</span><strong>{label}</strong></li>)}
      </ol>

      {(formError || error) && <div className="inline-alert" role="alert">{formError ?? error?.message}{error?.requestId && <span>Request ID: {error.requestId}</span>}</div>}

      {step === 0 && (
        <form onSubmit={nextFromOwner} className="form-stack">
          <div className="form-grid two-columns">
            <label>Username<input required minLength={3} maxLength={64} autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>Email address<input required type="email" maxLength={254} autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          </div>
          <div className="form-grid two-columns">
            <label>Password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><small>12–128 characters. Spaces are kept.</small></label>
            <label>Confirm password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} /></label>
          </div>
          {bootstrapRequired && <label>Bootstrap token<input required type="password" autoComplete="off" spellCheck={false} value={bootstrapToken} onChange={(event) => setBootstrapToken(event.target.value)} data-lpignore="true" /><small>Provided by your server administrator. It is sent once and never saved by this app.</small></label>}
          <div className="form-actions end"><button className="button primary" type="submit">Continue <Icon name="arrow-right" /></button></div>
        </form>
      )}

      {step === 1 && (
        <form onSubmit={nextFromPreferences} className="form-stack">
          <div className="form-grid two-columns">
            <label>Currency<select required value={currency} onChange={(event) => setCurrency(event.target.value)}>{options.currencies.map((item) => <option key={item.code} value={item.code}>{item.code} — {item.name}</option>)}</select></label>
            <label>Timezone<select required value={timezone} onChange={(event) => setTimezone(event.target.value)}>{timezones.map((zone) => <option key={zone}>{zone}</option>)}</select></label>
          </div>
          <div className="form-grid two-columns">
            <label>Annual gross income <span className="optional">Optional</span><input inputMode="decimal" placeholder="75000" value={annualIncome} onChange={(event) => setAnnualIncome(event.target.value)} /></label>
            <label>Pay frequency <span className="optional">Optional</span><select value={payFrequency} onChange={(event) => setPayFrequency(event.target.value as PayFrequency | "")}><option value="">Not set</option>{options.pay_frequencies.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          </div>
          <fieldset className="theme-picker"><legend>Appearance</legend>{(["system", "light", "dark"] as ThemePreference[]).map((value) => <label key={value} className={theme === value ? "selected" : ""}><input type="radio" name="setup-theme" value={value} checked={theme === value} onChange={() => setTheme(value)} /><span>{value.charAt(0).toUpperCase() + value.slice(1)}</span></label>)}</fieldset>
          <div className="form-actions"><button className="button ghost" type="button" onClick={() => setStep(0)}>Back</button><button className="button primary" type="submit">Continue <Icon name="arrow-right" /></button></div>
        </form>
      )}

      {step === 2 && (
        <form onSubmit={submit} className="form-stack">
          <fieldset className="category-picker"><legend>Choose the categories you use</legend><p>These organize your spending. “Other” remains available as a safe fallback.</p>
            <div className="category-options">{options.default_categories.map((category) => {
              const checked = categoryKeys.includes(category.key);
              const required = category.key === "other";
              return <label key={category.key} className={checked ? "selected" : ""}><input type="checkbox" checked={checked} disabled={required} onChange={() => setCategoryKeys((current) => checked ? current.filter((key) => key !== category.key) : [...current, category.key])} /><span><strong>{category.name}</strong><small>{required ? "Always enabled fallback" : category.group}</small></span><Icon name="check" /></label>;
            })}</div>
          </fieldset>
          <div className="form-actions"><button className="button ghost" type="button" onClick={() => setStep(1)}>Back</button><button className="button primary" type="submit" disabled={submitting}>{submitting ? "Creating your account…" : "Finish setup"}</button></div>
        </form>
      )}
    </section>
  );
}
