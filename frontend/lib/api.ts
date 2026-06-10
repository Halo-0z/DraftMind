// Default to a relative path so the request goes through the Next.js
// dev server proxy (configured in next.config.ts -> rewrites).  This
// keeps the browser on a same-origin request and avoids CORS errors.
// Set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 to bypass the proxy.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export type Team = {
  id: number;
  name: string;
  abbr: string;
  nba_team_id: number | null;
  city: string | null;
  conference: string;
  division: string;
};

export type TeamPick = {
  pick_no: number;
  original_team: string | null;
  notes: string | null;
};

export type RosterPlayer = {
  id: number;
  season: string;
  nba_player_id: number | null;
  player_name: string;
  position: string | null;
  age: number | null;
  height: string | null;
  weight: number | null;
  jersey: string | null;
  experience: string | null;
  school: string | null;
};

export type Prospect = {
  id: number;
  year: number;
  name: string;
  position: string;
  age: number;
  height: string;
  weight: number;
  school_or_league: string;
  ppg: number;
  rpg: number;
  apg: number;
  fg_pct: number;
  three_pct: number;
  ft_pct: number;
  stocks: number;
  archetype: string;
  upside_score: number;
  risk_score: number;
};

export type ScoreBreakdown = {
  talent_score: number;
  fit_score: number;
  pick_value_score: number;
  risk_penalty: number;
  final_score: number;
};

export type RankedProspect = {
  prospect: Prospect;
  scores: ScoreBreakdown;
  reasons: string[];
  risks: string[];
};

export type Recommendation = {
  year: number;
  pick: number;
  mode: string;
  team: Team;
  recommended_player: RankedProspect;
  alternatives: RankedProspect[];
};

export type RecommendPayload = {
  year: number;
  team_id: number;
  pick: number;
  mode: string;
};

export type SimulatedPick = {
  pick: number;
  team: Team;
  original_team: string | null;
  draft_order_note: string | null;
  selected_player: RankedProspect;
  alternatives: RankedProspect[];
  candidate_board: RankedProspect[];
  trade_evaluation: {
    action: string;
    probability: number;
    rationale: string;
    executed: boolean;
  };
  decision_log: string[];
};

export type Simulation = {
  year: number;
  rounds: number;
  total_picks: number;
  source: string | null;
  picks: SimulatedPick[];
};

export type SimulatePayload = {
  year: number;
  rounds: number;
  limit: number;
};

export type AgentExplanation = {
  recommendation_reasons: string[];
  risks: string[];
  alternatives: string[];
  gm_summary: string;
  follow_up_answer: string;
};

export type AgentAskResponse = {
  recommendation: Recommendation;
  explanation: AgentExplanation;
  provider: string;
  model: string;
  is_mock: boolean;
  rag_context?: string;
};

export type AgentAskPayload = {
  year: number;
  team_id: number;
  pick: number;
  mode: string;
  question: string;
};

export type NewsArticle = {
  id: number;
  source: string;
  title: string;
  summary: string;
  url: string;
  author: string | null;
  language: string;
  published_at: string;
  fetched_at: string;
  body_excerpt: string;
  prospect_names: string;
  team_abbrs: string;
};

export type NewsSearchResponse = {
  query: string;
  total: number;
  articles: NewsArticle[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getTeams(): Promise<Team[]> {
  return request<Team[]>("/api/teams");
}

export function getTeamRoster(
  teamId: number,
  season = "2025-26",
): Promise<RosterPlayer[]> {
  return request<RosterPlayer[]>(
    `/api/teams/${teamId}/roster?season=${encodeURIComponent(season)}`,
  );
}

export function getTeamPicks(
  teamId: number,
  year = 2026,
): Promise<TeamPick[]> {
  return request<TeamPick[]>(
    `/api/teams/${teamId}/picks?year=${year}`,
  );
}

export function getRecommendation(
  payload: RecommendPayload,
): Promise<Recommendation> {
  return request<Recommendation>("/api/recommend", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function simulateDraft(payload: SimulatePayload): Promise<Simulation> {
  return request<Simulation>("/api/simulate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function askAgent(payload: AgentAskPayload): Promise<AgentAskResponse> {
  return request<AgentAskResponse>("/api/agent/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function searchNews(params: {
  prospect?: string;
  team?: string;
  keyword?: string;
  language?: string;
  refresh?: boolean;
  limit?: number;
}): Promise<NewsSearchResponse> {
  const query = new URLSearchParams();
  if (params.prospect) query.set("prospect", params.prospect);
  if (params.team) query.set("team", params.team);
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.language) query.set("language", params.language);
  if (params.refresh) query.set("refresh", "true");
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<NewsSearchResponse>(`/api/news${suffix}`);
}

export function refreshNews(limit = 8): Promise<NewsSearchResponse> {
  return request<NewsSearchResponse>(`/api/news/refresh?limit=${limit}`, {
    method: "POST",
  });
}
