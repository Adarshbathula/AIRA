// Typed mirrors of the FastAPI Pydantic schemas (app/schemas/*).

export type Role = "admin" | "user";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface IncidentAnalysis {
  service: string | null;
  error: string | null;
  environment: string | null;
  event: string | null;
  category: string;
  severity: string;
  symptoms: string[];
  keywords: string[];
  confidence: number;
}

export interface RetrievedChunk {
  chunk_ref: string;
  document_id: number | null;
  document_no: string | null;
  citation: string;
  document_name: string;
  category: string;
  service: string | null;
  section: string | null;
  page: number | null;
  text: string;
  score: number;
}

export interface GraderResult {
  quality: "GOOD" | "FAIR" | "POOR";
  score: number;
  signals: Record<string, unknown>;
  feedback: string;
}

export interface SimilarIncident {
  public_id: string;
  title: string;
  service: string | null;
  severity: string | null;
  similarity: number;
  root_cause: string | null;
  resolution: string | null;
  outcome: string;
  created_at: string | null;
}

export type CauseStatus = "CONFIRMED" | "PROBABLE" | "POSSIBLE" | "INSUFFICIENT_EVIDENCE";

export interface Cause {
  label: string;
  description: string;
  status: CauseStatus;
  probability: "High" | "Medium" | "Low";
  evidence: string[];
}

export type EvidenceStatus = "SUPPORTED" | "PARTIALLY_SUPPORTED" | "INSUFFICIENT";

export interface TroubleshootingStep {
  step: string;
  evidence: string[];
  evidence_status: EvidenceStatus;
  source_categories: string[];
  priority: number;
}

export interface EvidenceClaim {
  claim: string;
  kind: "recommendation" | "root_cause" | "summary";
  evidence: string[];
  status: EvidenceStatus;
  detail?: string | null;
}

export interface ConfidenceBreakdown {
  retrieval_quality: number;
  supporting_documents: number;
  evidence_consistency: number;
  similar_incidents: number;
  grader_score: number;
  evidence_validation: number;
  notes: string[];
}

export interface RetrievalInfo {
  attempts: number;
  queries: string[];
  grader: GraderResult | null;
  scores: number[];
  documents_used: string[];
}

export interface NodeTrace {
  node: string;
  status: "ok" | "retry" | "fail" | "skipped";
  ms: number;
  detail?: string | null;
}

export interface AIResponse {
  incident_id: number;
  public_id: string;
  conversation_id: number | null;
  analysis: IncidentAnalysis;
  final_text: string;
  summary: string;
  root_causes: Cause[];
  troubleshooting: TroubleshootingStep[];
  similar_incidents: SimilarIncident[];
  evidence: RetrievedChunk[];
  evidence_claims: EvidenceClaim[];
  evidence_status: EvidenceStatus;
  cause_taxonomy: string;
  confidence_score: number;
  confidence_label: string;
  confidence_breakdown: ConfidenceBreakdown;
  retrieval: RetrievalInfo;
  retrieval_quality: "GOOD" | "FAIR" | "POOR";
  retrieval_attempts: number;
  supporting_document_count: number;
  insufficient_evidence: boolean;
  llm_used: boolean;
  embedding_backend: string;
  trace: NodeTrace[];
  timestamp: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  incident_id: number | null;
}

export interface ChatResponse {
  conversation_id: number;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  ai: AIResponse;
}

export interface IncidentSummary {
  id: number;
  public_id: string;
  service: string | null;
  category: string | null;
  severity: string | null;
  description: string;
  probable_root_cause: string | null;
  confidence_score: number;
  retrieval_quality: string;
  retrieval_attempts: number;
  supporting_document_count: number;
  evidence_status: string;
  resolution_status: string;
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  incident_count: number;
  last_incident: IncidentSummary | null;
}

export interface ConversationDetail {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
  incidents: IncidentSummary[];
}

export interface DocumentItem {
  id: number;
  document_no: string;
  name: string;
  title: string | null;
  type: string;
  category: string;
  service: string | null;
  department: string | null;
  author: string | null;
  version: string | null;
  file_size: number;
  page_count: number | null;
  created_at: string;
  chunk_count: number;
  citation_label: string;
}

export interface DocumentDetail extends DocumentItem {
  metadata_json: Record<string, unknown> | null;
  chunks: { chunk_ref: string; index: number; section: string | null; page: number | null; tokens: number; preview: string }[];
}

export interface DashboardOverview {
  role: Role;
  total_incidents: number;
  incidents_last_7_days: number;
  avg_confidence: number;
  good_retrieval_pct: number;
  avg_retrieval_attempts: number;
  resolved_incidents: number;
  insufficient_evidence: number;
  high_severity: number;
  documents: number;
  document_chunks: number;
  users: number | null;
}

export interface IncidentDashboard {
  trends: { days: number; series: { date: string; incidents: number; avg_confidence: number }[] };
  recent: {
    id: number; public_id: string; description: string; service: string | null; severity: string | null;
    category: string | null; confidence_score: number; retrieval_quality: string; evidence_status: string;
    resolution_status: string; created_at: string | null;
  }[];
  top_services: { service: string; count: number; avg_confidence: number }[];
}

export interface RootCauseStats {
  total: number;
  distribution: { label: string; count: number; pct: number }[];
}

export interface ConfidenceDist {
  total: number;
  avg: number;
  buckets: { bucket: string; count: number }[];
}

export interface RetrievalStats {
  total: number;
  avg_retrieval_attempts: number;
  avg_confidence: number;
  avg_supporting_documents: number;
  good_pct: number;
  poor_pct: number;
}

export interface DocumentsStats {
  total: number;
  total_chunks: number;
  by_type: { type: string; count: number }[];
  by_category: { category: string; count: number }[];
  top_services: { service: string; count: number }[];
}

export interface UsageStats {
  most_referenced: { document_no: string; name: string; category: string; service: string | null; references: number }[];
  by_category: Record<string, number>;
  runbooks: { document_no: string; name: string; service: string | null; references: number; access: number }[];
  sops: { document_no: string; name: string; service: string | null; references: number; access: number }[];
  rcas: { document_no: string; name: string; service: string | null; references: number; access: number }[];
}

export interface SystemStats {
  total_incidents: number;
  resolved: number;
  high_severity: number;
  users: number;
  conversations: number;
  messages: number;
  documents: number;
}

export interface AuditEntry {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string | null;
}

export interface KnowledgeSearchResult {
  query: string;
  chunks: RetrievedChunk[];
  by_category: Record<string, number>;
  took_ms: number;
}
