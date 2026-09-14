export interface HealthInfo {
  status: string;
  app: string;
  version: string;
  database: string;
  llm: { provider?: string; mode?: string; model?: string | null; note?: string };
  embeddings: { provider?: string; model?: string; dimension?: number; semantic?: boolean };
  vector_store: { backend?: string; vectors?: number; dimension?: number };
}

let cached: HealthInfo | null = null;

export async function health(): Promise<HealthInfo | null> {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return cached;
    cached = (await res.json()) as HealthInfo;
    return cached;
  } catch {
    return cached;
  }
}
