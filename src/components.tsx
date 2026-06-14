import type { ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDollarSign,
  FileSearch,
  Gavel,
  Loader2,
  Scale,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { AppKey, HealthState, ServiceHealth } from "./types";
import { appCopy } from "./api/tokens";

const iconMap = {
  dis: FileSearch,
  fci: CircleDollarSign,
  pip: ShieldCheck,
  lie: Scale,
};

export function AppHeader({
  active,
  onChange,
}: {
  active: AppKey;
  onChange: (app: AppKey) => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
              EA CTO AI OS
            </p>
            <h1 className="text-xl font-semibold text-slate-950">
              Command dashboards
            </h1>
          </div>
          <div className="rounded-md border border-slate-200 px-3 py-2 text-right">
            <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
              Local
            </p>
            <p className="text-sm font-semibold text-slate-900">Bangkok UTC+7</p>
          </div>
        </div>
        <nav className="grid grid-cols-4 gap-2">
          {(Object.keys(appCopy) as AppKey[]).map((key) => {
            const Icon = iconMap[key];
            const selected = active === key;
            return (
              <button
                key={key}
                className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-md border px-2 py-2 text-xs font-semibold transition sm:flex-row sm:justify-start sm:text-sm ${
                  selected
                    ? "border-slate-900 bg-slate-950 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                }`}
                type="button"
                onClick={() => onChange(key)}
                aria-pressed={selected}
                title={appCopy[key].title}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{appCopy[key].name}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

export function DashboardFrame({
  app,
  health,
  children,
}: {
  app: AppKey;
  health?: ServiceHealth;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:py-7">
      <section className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div
            className={`mb-3 h-1.5 w-16 rounded-full ${appCopy[app].accent}`}
          />
          <p className="text-sm font-medium text-slate-500">{appCopy[app].name}</p>
          <h2 className="text-2xl font-semibold text-slate-950 sm:text-3xl">
            {appCopy[app].title}
          </h2>
        </div>
        {health ? <HealthPill health={health} /> : <LoadingPill />}
      </section>
      {children}
    </main>
  );
}

export function HealthPill({ health }: { health: ServiceHealth }) {
  const Icon = health.state === "online" ? Wifi : WifiOff;
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm">
      <Icon className={`h-4 w-4 ${healthColor(health.state)}`} />
      <div>
        <p className="font-semibold text-slate-900">
          {health.state === "online" ? "Service online" : "Local fallback"}
        </p>
        <p className="text-xs text-slate-500">
          {health.latencyMs ? `${health.latencyMs} ms · ` : ""}
          {health.message}
        </p>
      </div>
    </div>
  );
}

function LoadingPill() {
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
      <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
      <span className="font-medium text-slate-700">Loading</span>
    </div>
  );
}

function healthColor(state: HealthState) {
  if (state === "online") return "text-emerald-600";
  if (state === "degraded") return "text-amber-600";
  return "text-rose-600";
}

export function MetricCard({
  label,
  value,
  tone = "slate",
  caption,
}: {
  label: string;
  value: string | number;
  tone?: "slate" | "green" | "amber" | "red";
  caption: string;
}) {
  const toneClass = {
    slate: "text-slate-950",
    green: "text-emerald-700",
    amber: "text-amber-700",
    red: "text-rose-700",
  }[tone];
  return (
    <article className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-2 text-3xl font-semibold ${toneClass}`}>{value}</p>
      <p className="mt-1 text-sm text-slate-500">{caption}</p>
    </article>
  );
}

export function Panel({
  title,
  icon,
  children,
  action,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="rounded-md border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="font-semibold text-slate-950">{title}</h3>
        </div>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toUpperCase();
  const style =
    normalized.includes("RED") ||
    normalized.includes("BLOCK") ||
    normalized.includes("ANOMALY")
      ? "bg-rose-50 text-rose-700 ring-rose-200"
      : normalized.includes("AMBER") ||
          normalized.includes("PENDING") ||
          normalized.includes("OPEN") ||
          normalized.includes("OUTLIER")
        ? "bg-amber-50 text-amber-700 ring-amber-200"
        : "bg-emerald-50 text-emerald-700 ring-emerald-200";
  return (
    <span className={`rounded px-2 py-1 text-xs font-semibold ring-1 ${style}`}>
      {value}
    </span>
  );
}

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-slate-300 bg-slate-50 text-center">
      <CheckCircle2 className="h-5 w-5 text-emerald-600" />
      <p className="text-sm font-medium text-slate-700">{label}</p>
    </div>
  );
}

export function RiskIcon({ risk }: { risk: "ok" | "warn" | "risk" }) {
  if (risk === "risk") return <AlertTriangle className="h-4 w-4 text-rose-600" />;
  if (risk === "warn") return <Gavel className="h-4 w-4 text-amber-600" />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
}
