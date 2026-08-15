import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

type ToastTone = "success" | "info" | "warning" | "error";
interface ToastItem { id: number; tone: ToastTone; message: string; }
interface ToastContextValue { pushToast: (message: string, tone?: ToastTone) => void; }
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const pushToast = useCallback((message: string, tone: ToastTone = "info") => {
    const id = nextId.current++;
    setItems((current) => [...current.slice(-3), { id, tone, message }]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4200);
  }, []);
  const value = useMemo(() => ({ pushToast }), [pushToast]);
  return <ToastContext.Provider value={value}>{children}<div className="toast-stack" aria-live="polite">{items.map((item) => <div key={item.id} className={`toast toast-${item.tone}`} role={item.tone === "error" ? "alert" : "status"}><span>{item.message}</span><button type="button" aria-label="Dismiss notification" onClick={() => setItems((current) => current.filter((entry) => entry.id !== item.id))}>×</button></div>)}</div></ToastContext.Provider>;
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
