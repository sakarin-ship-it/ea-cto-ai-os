import type {
  AnomalyRecord,
  AppKey,
  AuditEntry,
  DocumentRecord,
  LieReview,
  ObligationRecord,
  PipPackageScore,
  ServiceHealth,
} from "../types";
import { mockData } from "./mockData";

type Json = Record<string, unknown> | Record<string, unknown>[];

const serviceBase: Record<AppKey, string> = {
  dis: import.meta.env.VITE_EA_DIS_URL ?? "http://127.0.0.1:8001",
  fci: import.meta.env.VITE_EA_FCI_URL ?? "http://127.0.0.1:8002",
  pip: import.meta.env.VITE_EA_PIP_URL ?? "http://127.0.0.1:8003",
  lie: import.meta.env.VITE_EA_LIE_URL ?? "http://127.0.0.1:8004",
};

const tokenKey: Record<AppKey, string> = {
  dis: "VITE_EA_DIS_TOKEN",
  fci: "VITE_EA_FCI_TOKEN",
  pip: "VITE_EA_PIP_TOKEN",
  lie: "VITE_EA_LIE_TOKEN",
};

async function request<T>(app: AppKey, path: string, fallback: T): Promise<T> {
  const token = import.meta.env[tokenKey[app]] as string | undefined;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 1200);

  try {
    const res = await fetch(`${serviceBase[app]}${path}`, {
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!res.ok) {
      return fallback;
    }
    return (await res.json()) as T;
  } catch {
    return fallback;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function measureHealth(app: AppKey, path: string): Promise<ServiceHealth> {
  const started = performance.now();
  try {
    await request<Json>(app, path, {});
    return {
      state: "online",
      latencyMs: Math.round(performance.now() - started),
      message: `${serviceBase[app]} responding`,
    };
  } catch {
    return {
      state: "degraded",
      message: "Using local dashboard data",
    };
  }
}

export const apiClient = {
  serviceBase,
  async dis() {
    const [documents, obligations, health] = await Promise.all([
      request<DocumentRecord[]>("dis", "/documents", mockData.documents),
      request<ObligationRecord[]>("dis", "/obligations", mockData.obligations),
      measureHealth("dis", "/documents"),
    ]);
    return { documents, obligations, health };
  },
  async fci() {
    const [anomalies, auditLog, health] = await Promise.all([
      request<AnomalyRecord[]>("fci", "/anomalies?limit=6", mockData.anomalies),
      request<AuditEntry[]>("fci", "/audit_log?limit=8", mockData.fciAudit),
      measureHealth("fci", "/audit_log?limit=1"),
    ]);
    return { anomalies, auditLog, health };
  },
  async pip() {
    const [scores, auditLog, health] = await Promise.all([
      request<{ scores: PipPackageScore[] }>(
        "pip",
        "/packages/1/scores/aggregate",
        { scores: mockData.packageScores },
      ),
      request<{ entries: AuditEntry[] }>("pip", "/audit_log?limit=8", {
        entries: mockData.pipAudit,
      }),
      measureHealth("pip", "/audit_log?limit=1"),
    ]);
    return { scores: scores.scores, auditLog: auditLog.entries, health };
  },
  async lie() {
    return {
      reviews: mockData.lieReviews as LieReview[],
      health: {
        state: "degraded",
        message: "Library mode: FastAPI surface not present yet",
      } satisfies ServiceHealth,
    };
  },
};
