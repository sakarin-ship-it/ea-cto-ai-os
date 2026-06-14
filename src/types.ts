export type AppKey = "dis" | "fci" | "pip" | "lie";

export type HealthState = "online" | "degraded" | "offline";

export interface ServiceHealth {
  state: HealthState;
  latencyMs?: number;
  message: string;
}

export interface DocumentRecord {
  id: number;
  filename: string;
  doc_type: string | null;
  confidence: number | null;
  status: string;
  page_count: number | null;
  created_at: string;
}

export interface ObligationRecord {
  id: number;
  document_id: number;
  description: string;
  due_date: string | null;
  responsible_party: string | null;
  status: string;
}

export interface AnomalyRecord {
  id: number;
  entity_type: string;
  entity_id: number;
  score: number;
  features: Record<string, unknown>;
}

export interface AuditEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  actor: string;
  entry_hash: string;
  created_at: string;
}

export interface PipPackageScore {
  bid_id: number;
  evaluator_id: string;
  weighted_total: number;
  is_outlier: boolean;
  z_score: number;
}

export interface LieReview {
  contract_id: string;
  title: string;
  score: number;
  rag: "GREEN" | "AMBER" | "RED";
  reviewer_level: "CTO_CFO" | "LEGAL_COUNSEL" | "EXTERNAL_LAWYER";
  gaps: string[];
  due_date: string;
}
