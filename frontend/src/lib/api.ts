const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100"

// ── Domain types ──────────────────────────────────────────────────────────────

export interface ToolCall {
  tool_name: string
  arguments?: Record<string, unknown>
}

export interface SubTask {
  id: string
  description: string
  tool_calls: ToolCall[]
}

export interface ExecutionPlan {
  task_id: string
  subtasks: SubTask[]
  reasoning?: string
}

export interface ToolResult {
  tool_name: string
  arguments?: Record<string, unknown>
  output: string
  error?: string | null
  latency_ms: number
}

export interface AgentResult {
  task_id: string
  answer: string
  sources?: string[]
  tool_results?: ToolResult[]
}

export interface ReviewResult {
  task_id: string
  verdict: string
  notes?: string
}

export interface ApprovalRequest {
  run_id: string
  task_id: string
  reason: string
  high_risk_tools: string[]
  status: string
  created_at: string
}

export interface TraceSpan {
  id: string
  run_id: string
  parent_id?: string | null
  name: string
  data: Record<string, unknown>
  started_at: string
  ended_at?: string | null
  duration_ms?: number | null
}

export interface RunSummary {
  id: string
  status: string
  created_at: string
  question: string
}

export interface RunDetail {
  id: string
  task: { id: string; question: string; context?: Record<string, unknown> }
  status: string
  plan?: ExecutionPlan | null
  result?: AgentResult | null
  review?: ReviewResult | null
  approval?: ApprovalRequest | null
  spans: TraceSpan[]
}

export interface HealthResponse {
  status: string
  api: string
  ollama: "online" | "offline"
  version: string
}

// ── API error ─────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: string,
  ) {
    super(message)
  }
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 10_000,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    })
    if (!res.ok) {
      let detail: string | undefined
      try {
        detail = ((await res.json()) as { detail?: string }).detail
      } catch {}
      throw new ApiError(res.status, detail ?? res.statusText, detail)
    }
    return res.json() as Promise<T>
  } finally {
    clearTimeout(timer)
  }
}

// ── Public API functions ──────────────────────────────────────────────────────

export const api = {
  health(): Promise<HealthResponse> {
    return apiFetch<HealthResponse>("/health")
  },

  listRuns(): Promise<RunSummary[]> {
    return apiFetch<RunSummary[]>("/runs")
  },

  getRun(id: string): Promise<RunDetail> {
    return apiFetch<RunDetail>(`/runs/${id}`)
  },

  createRun(question: string): Promise<{ run_id: string; status: string }> {
    return apiFetch("/run", { method: "POST", body: JSON.stringify({ question }) }, 5_000)
  },

  approveRun(
    id: string,
    decision: "accept" | "reject" | "modify",
    note = "",
  ): Promise<{ ok: boolean; run_id: string; message: string }> {
    return apiFetch(`/runs/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    })
  },

  streamRun(id: string): EventSource {
    return new EventSource(`${API}/runs/${id}/stream`)
  },
}
