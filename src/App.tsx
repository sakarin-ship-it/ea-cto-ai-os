import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  ClipboardCheck,
  FileText,
  Gauge,
  Hash,
  Landmark,
  ListChecks,
  LockKeyhole,
  Search,
  ShieldAlert,
  Signature,
} from "lucide-react";
import { apiClient } from "./api/client";
import {
  AppHeader,
  DashboardFrame,
  EmptyState,
  MetricCard,
  Panel,
  RiskIcon,
  StatusBadge,
} from "./components";
import type {
  AnomalyRecord,
  AppKey,
  AuditEntry,
  DocumentRecord,
  LieReview,
  ObligationRecord,
  PipPackageScore,
  ServiceHealth,
} from "./types";

interface DashboardData {
  dis?: {
    documents: DocumentRecord[];
    obligations: ObligationRecord[];
    health: ServiceHealth;
  };
  fci?: {
    anomalies: AnomalyRecord[];
    auditLog: AuditEntry[];
    health: ServiceHealth;
  };
  pip?: {
    scores: PipPackageScore[];
    auditLog: AuditEntry[];
    health: ServiceHealth;
  };
  lie?: {
    reviews: LieReview[];
    health: ServiceHealth;
  };
}

export function App() {
  const [active, setActive] = useState<AppKey>("dis");
  const [data, setData] = useState<DashboardData>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const loaders = {
      dis: apiClient.dis,
      fci: apiClient.fci,
      pip: apiClient.pip,
      lie: apiClient.lie,
    };
    const loader = loaders[active];

    loader().then((result) => {
      if (!cancelled) {
        setData((current) => ({ ...current, [active]: result }));
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [active]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <AppHeader active={active} onChange={setActive} />
      {active === "dis" && <DisDashboard data={data.dis} loading={loading} />}
      {active === "fci" && <FciDashboard data={data.fci} loading={loading} />}
      {active === "pip" && <PipDashboard data={data.pip} loading={loading} />}
      {active === "lie" && <LieDashboard data={data.lie} loading={loading} />}
    </div>
  );
}

function DisDashboard({
  data,
  loading,
}: {
  data?: DashboardData["dis"];
  loading: boolean;
}) {
  const documents = data?.documents ?? [];
  const obligations = data?.obligations ?? [];
  const pending = documents.filter((doc) => doc.status.includes("PENDING")).length;
  const sensitive = documents.filter((doc) =>
    ["DOC-05", "DOC-06", "DOC-07", "DOC-09"].includes(doc.doc_type ?? ""),
  ).length;

  return (
    <DashboardFrame app="dis" health={data?.health}>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="Documents"
          value={loading ? "..." : documents.length}
          caption="Indexed or awaiting review"
        />
        <MetricCard
          label="Sensitive docs"
          value={loading ? "..." : sensitive}
          tone="amber"
          caption="Must stay local via LM Studio"
        />
        <MetricCard
          label="Review queue"
          value={loading ? "..." : pending}
          tone={pending ? "amber" : "green"}
          caption="Low-confidence classifications"
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_0.85fr]">
        <Panel title="Document queue" icon={<FileText className="h-4 w-4" />}>
          <div className="space-y-3">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="rounded-md border border-slate-200 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-slate-950">
                      {doc.filename}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {doc.doc_type ?? "Unclassified"} · {doc.page_count ?? 0} pages
                    </p>
                  </div>
                  <StatusBadge value={doc.status} />
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded bg-slate-100">
                  <div
                    className="h-full rounded bg-[#1f7a8c]"
                    style={{ width: `${Math.round((doc.confidence ?? 0) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel
          title="Obligations"
          icon={<ListChecks className="h-4 w-4" />}
          action={<StatusBadge value={`${obligations.length} open`} />}
        >
          <div className="space-y-3">
            {obligations.map((item) => (
              <div key={item.id} className="flex gap-3 rounded-md bg-slate-50 p-3">
                <RiskIcon risk="warn" />
                <div>
                  <p className="font-medium text-slate-900">{item.description}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {item.responsible_party ?? "Unassigned"} · due {item.due_date}
                  </p>
                </div>
              </div>
            ))}
            {!obligations.length && <EmptyState label="No obligations due" />}
          </div>
        </Panel>
      </div>
    </DashboardFrame>
  );
}

function FciDashboard({
  data,
  loading,
}: {
  data?: DashboardData["fci"];
  loading: boolean;
}) {
  const anomalies = data?.anomalies ?? [];
  const audit = data?.auditLog ?? [];
  const paymentBlocks = audit.filter((entry) => entry.entity_type === "payment").length;
  const highRisk = anomalies.filter((a) => a.score >= 0.8).length;

  return (
    <DashboardFrame app="fci" health={data?.health}>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="TAC gate"
          value={loading ? "..." : paymentBlocks}
          tone={paymentBlocks ? "amber" : "green"}
          caption="Payment actions recently checked"
        />
        <MetricCard
          label="Anomalies"
          value={loading ? "..." : anomalies.length}
          tone={highRisk ? "red" : "green"}
          caption={`${highRisk} high-risk finance flags`}
        />
        <MetricCard
          label="Audit chain"
          value={loading ? "..." : audit.length}
          caption="Immutable rows sampled"
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Panel title="Control gates" icon={<LockKeyhole className="h-4 w-4" />}>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              ["TAC signed", "Required before milestone payment", "ok"],
              ["3-way match", "PO, GRN, invoice tolerance", "warn"],
              ["LD accrual", "Integer satang only", "ok"],
              ["FX source", "BOT mid-rate monitor", "ok"],
            ].map(([title, caption, risk]) => (
              <div key={title} className="rounded-md border border-slate-200 p-3">
                <div className="flex items-center gap-2">
                  <RiskIcon risk={risk as "ok" | "warn" | "risk"} />
                  <p className="font-semibold text-slate-950">{title}</p>
                </div>
                <p className="mt-1 text-sm text-slate-500">{caption}</p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Anomaly radar" icon={<ShieldAlert className="h-4 w-4" />}>
          <div className="space-y-3">
            {anomalies.map((item) => (
              <div key={item.id} className="rounded-md bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-semibold text-slate-950">
                    {item.entity_type} #{item.entity_id}
                  </p>
                  <StatusBadge value={`${Math.round(item.score * 100)} risk`} />
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  {String(item.features.reason ?? "Feature variance detected")}
                </p>
              </div>
            ))}
          </div>
        </Panel>
        <AuditPanel entries={audit} />
      </div>
    </DashboardFrame>
  );
}

function PipDashboard({
  data,
  loading,
}: {
  data?: DashboardData["pip"];
  loading: boolean;
}) {
  const scores = data?.scores ?? [];
  const audit = data?.auditLog ?? [];
  const outliers = scores.filter((score) => score.is_outlier).length;
  const topScore = scores.reduce((max, score) => Math.max(max, score.weighted_total), 0);

  return (
    <DashboardFrame app="pip" health={data?.health}>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="Bid scores"
          value={loading ? "..." : scores.length}
          caption="Blind evaluator rollup"
        />
        <MetricCard
          label="Top weighted"
          value={loading ? "..." : topScore}
          tone="green"
          caption="Best visible aggregate"
        />
        <MetricCard
          label="Outliers"
          value={loading ? "..." : outliers}
          tone={outliers ? "amber" : "green"}
          caption="Needs reviewer attention"
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Tender board" icon={<ClipboardCheck className="h-4 w-4" />}>
          <div className="space-y-3">
            {scores.map((score) => (
              <div key={`${score.bid_id}-${score.evaluator_id}`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="font-semibold text-slate-950">
                    Bid #{score.bid_id} · {score.evaluator_id}
                  </p>
                  <StatusBadge value={score.is_outlier ? "OUTLIER" : "CLEAR"} />
                </div>
                <div className="h-3 overflow-hidden rounded bg-slate-100">
                  <div
                    className="h-full rounded bg-[#b54708]"
                    style={{ width: `${score.weighted_total}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  z-score {score.z_score.toFixed(2)}
                </p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Procurement controls" icon={<Landmark className="h-4 w-4" />}>
          <div className="space-y-3">
            {[
              ["Supplier DBD", "Registration + status verification", "ok"],
              ["ALB compliance", "Bid-level compliance scan", "warn"],
              ["Tier-1 auto-select", "Lowest compliant bid path", "ok"],
              ["Award fallback", "Expiry and rejection handling", "ok"],
            ].map(([title, caption, risk]) => (
              <div key={title} className="flex gap-3 rounded-md bg-slate-50 p-3">
                <RiskIcon risk={risk as "ok" | "warn" | "risk"} />
                <div>
                  <p className="font-medium text-slate-900">{title}</p>
                  <p className="text-sm text-slate-500">{caption}</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
        <AuditPanel entries={audit} />
      </div>
    </DashboardFrame>
  );
}

function LieDashboard({
  data,
  loading,
}: {
  data?: DashboardData["lie"];
  loading: boolean;
}) {
  const reviews = data?.reviews ?? [];
  const critical = reviews.filter((item) => item.rag === "RED").length;
  const avgRisk = useMemo(() => {
    if (!reviews.length) return 0;
    return Math.round(
      reviews.reduce((sum, item) => sum + item.score, 0) / reviews.length,
    );
  }, [reviews]);

  return (
    <DashboardFrame app="lie" health={data?.health}>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label="Reviews"
          value={loading ? "..." : reviews.length}
          caption="Contracts in legal queue"
        />
        <MetricCard
          label="Critical"
          value={loading ? "..." : critical}
          tone={critical ? "red" : "green"}
          caption="External counsel path"
        />
        <MetricCard
          label="Average risk"
          value={loading ? "..." : avgRisk}
          tone={avgRisk > 60 ? "red" : avgRisk > 30 ? "amber" : "green"}
          caption="Review engine score"
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Contract reviews" icon={<ScaleIcon />}>
          <div className="space-y-3">
            {reviews.map((review) => (
              <div
                key={review.contract_id}
                className="rounded-md border border-slate-200 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-950">{review.title}</p>
                    <p className="mt-1 text-sm text-slate-500">
                      {review.contract_id} · {review.reviewer_level}
                    </p>
                  </div>
                  <StatusBadge value={review.rag} />
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <Gauge className="h-4 w-4 text-slate-500" />
                  <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100">
                    <div
                      className={`h-full rounded ${
                        review.score > 60
                          ? "bg-rose-600"
                          : review.score > 30
                            ? "bg-amber-600"
                            : "bg-emerald-600"
                      }`}
                      style={{ width: `${review.score}%` }}
                    />
                  </div>
                  <span className="w-8 text-right text-sm font-semibold">
                    {review.score}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Clause watch" icon={<Signature className="h-4 w-4" />}>
          <div className="space-y-3">
            {reviews.flatMap((review) =>
              review.gaps.map((gap) => (
                <div
                  key={`${review.contract_id}-${gap}`}
                  className="flex gap-3 rounded-md bg-slate-50 p-3"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                  <div>
                    <p className="font-medium text-slate-900">{gap}</p>
                    <p className="text-sm text-slate-500">
                      {review.contract_id} · due {review.due_date}
                    </p>
                  </div>
                </div>
              )),
            )}
            {!reviews.some((review) => review.gaps.length) && (
              <EmptyState label="No clause gaps found" />
            )}
          </div>
        </Panel>
      </div>
    </DashboardFrame>
  );
}

function AuditPanel({ entries }: { entries: AuditEntry[] }) {
  return (
    <Panel title="Audit trail" icon={<Hash className="h-4 w-4" />}>
      <div className="space-y-3">
        {entries.map((entry) => (
          <div key={entry.id} className="rounded-md bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold text-slate-950">{entry.action}</p>
              <p className="text-xs font-medium text-slate-500">#{entry.id}</p>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {entry.entity_type} {entry.entity_id} · {entry.actor}
            </p>
            <p className="mt-2 truncate font-mono text-xs text-slate-500">
              {entry.entry_hash}
            </p>
          </div>
        ))}
        {!entries.length && <EmptyState label="No audit entries available" />}
      </div>
    </Panel>
  );
}

function ScaleIcon() {
  return <Banknote className="h-4 w-4" />;
}
