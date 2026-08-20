import { useState, type FocusEvent, type InputHTMLAttributes } from "react";
import { formatMoneyInput, normalizeMoneyInput } from "../lib/format";

type MoneyInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange" | "inputMode"> & {
  value?: string | number | null;
  defaultValue?: string | number | null;
  onValueChange?: (value: string) => void;
  locale?: string;
};

export function MoneyInput({ value, defaultValue, onValueChange, locale, onFocus, onBlur, ...props }: MoneyInputProps) {
  const controlled = value !== undefined;
  const [internalValue, setInternalValue] = useState(() => normalizeMoneyInput(String(defaultValue ?? "")));
  const [editingValue, setEditingValue] = useState<string | null>(null);
  const canonicalValue = controlled ? String(value ?? "") : internalValue;
  const displayedValue = editingValue ?? formatMoneyInput(canonicalValue, locale);

  const focus = (event: FocusEvent<HTMLInputElement>) => {
    setEditingValue(formatMoneyInput(canonicalValue, locale));
    onFocus?.(event);
  };
  const blur = (event: FocusEvent<HTMLInputElement>) => {
    setEditingValue(null);
    onBlur?.(event);
  };

  return (
    <input
      {...props}
      inputMode="decimal"
      value={displayedValue}
      onFocus={focus}
      onBlur={blur}
      onChange={(event) => {
        const nextValue = normalizeMoneyInput(event.target.value);
        setEditingValue(event.target.value);
        if (!controlled) setInternalValue(nextValue);
        onValueChange?.(nextValue);
      }}
    />
  );
}
