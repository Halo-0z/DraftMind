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

export type TeamNeedProfile = {
  id: number;
  team_id: number;
  year: number;
  horizon: string;
  source: string;
  need_confidence: number;
  need_center?: number | null;
  need_rim_protection?: number | null;
  need_defensive_rebounding?: number | null;
  need_spacing?: number | null;
  need_shooting_volume?: number | null;
  need_self_creation?: number | null;
  need_point_of_attack_defense?: number | null;
  need_nba_ready?: number | null;
  need_upside?: number | null;
  manual_override_reason?: string | null;
};

export type TeamNeedProfilePayload = {
  team_id: number;
  year: number;
  horizon?: string;
  need_center?: number;
  need_rim_protection?: number;
  need_defensive_rebounding?: number;
  need_spacing?: number;
  need_shooting_volume?: number;
  need_self_creation?: number;
  need_point_of_attack_defense?: number;
  need_nba_ready?: number;
  need_upside?: number;
  need_confidence?: number;
  manual_override_reason?: string;
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
  scouting_fit_score?: number | null;
  scouting_fit_positives?: string[] | null;
  scouting_fit_risks?: string[] | null;
  ranking_sort_score?: number | null;
  scouting_tiebreaker_applied?: boolean;
  scouting_tiebreaker_delta?: number;
  projection_expected_pick?: number | null;
  projection_draft_range_min?: number | null;
  projection_draft_range_max?: number | null;
  projection_tier?: number | null;
  projection_confidence?: number | null;
  projection_source?: string | null;
  projection_notes?: string | null;
  team_projection_type?: string | null;
  team_projection_confidence?: number | null;
  team_projection_notes?: string | null;
  prediction_range_score?: number | null;
  prediction_tier_score?: number | null;
  prediction_team_projection_score?: number | null;
  prediction_confidence_weight?: number | null;
  prediction_shadow_score?: number | null;
  prediction_shadow_rank?: number | null;
  prediction_shadow_delta?: number | null;
  prediction_calibration_notes?: string[] | null;
  prediction_sort_score?: number | null;
  prediction_selection_rank?: number | null;
  prediction_selection_delta?: number | null;
  prediction_selection_applied?: boolean;
  prediction_selection_notes?: string[] | null;
  market_expected_pick?: number | null;
  draftmind_selected_pick?: number | null;
  market_pick_delta?: number | null;
  market_alignment_label?: string | null;
  market_alignment_notes?: string[] | null;
  candidate_source?: string | null;
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
  evaluate_trades?: boolean;
  include_scouting_diagnostics?: boolean;
  use_scouting_tiebreaker?: boolean;
  include_projection_diagnostics?: boolean;
  include_prediction_shadow?: boolean;
  use_prediction_calibration?: boolean;
  // Phase 3: user-override / locked picks.  Each entry pins a specific
  // pick_no to a specific prospect.  The backend (Phase 2) also accepts
  // a free-text `prospect_name` fallback, but the MVP frontend only
  // exposes the prospect_id dropdown — name-based free-text input is
  // left as a follow-up enhancement.  We do NOT remove or rename the
  // backend's prospect_name capability here.
  locked_picks?: LockedPick[] | null;
};

export type LockedPick = {
  pick_no: number;
  prospect_id?: number | null;
  prospect_name?: string | null;
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

export async function getTeamScoutingProfile(
  teamId: number,
  year: number,
  horizon = "next_season",
): Promise<TeamNeedProfile | null> {
  const query = new URLSearchParams({
    team_id: String(teamId),
    year: String(year),
    horizon,
  });
  const response = await fetch(
    `${API_BASE_URL}/api/scouting/team-profiles?${query.toString()}`,
    {
      headers: {
        "Content-Type": "application/json",
      },
    },
  );

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<TeamNeedProfile>;
}

export function saveTeamScoutingProfile(
  payload: TeamNeedProfilePayload,
): Promise<TeamNeedProfile> {
  return request<TeamNeedProfile>("/api/scouting/team-profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getProspects(year = 2026): Promise<Prospect[]> {
  return request<Prospect[]>(`/api/prospects?year=${year}`);
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
