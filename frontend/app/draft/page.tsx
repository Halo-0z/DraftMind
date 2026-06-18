"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AgentAskResponse,
  askAgent,
  EvidenceCitation,
  PickEvidencePackage,
  PickExplanation,
  RetrievedEvidence,
  fetchPickEvidence,
  fetchPickExplanationMock,
  getProspects,
  getRecommendation,
  getTeamScoutingProfile,
  getTeamPicks,
  getTeamRoster,
  getTeams,
  LockedPick,
  NewsArticle,
  Prospect,
  RankedProspect,
  Recommendation,
  refreshNews,
  RosterPlayer,
  ScoreBreakdown,
  searchNews,
  saveTeamScoutingProfile,
  simulateDraft,
  Simulation,
  SimulatedPick,
  Team,
  TeamNeedProfile,
  TeamNeedProfilePayload,
  TeamPick,
} from "@/lib/api";

// Phase 3: locked pick marker — kept in one place so future backend
// wording tweaks need only this constant to be updated.
const LOCKED_PICK_LOG_MARKER = "This pick was locked by user override.";

function isPickLocked(pick: SimulatedPick): boolean {
  return pick.decision_log.some((line) => line.includes(LOCKED_PICK_LOG_MARKER));
}

// Phase 3: backend error format can be a string, an array of objects
// (FastAPI validation errors), a {detail: {...}} object, or just plain
// text.  We surface a single human-readable line for the user.
function formatApiError(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : String(err);
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return `${fallback} ${detail}`;
      if (Array.isArray(detail)) {
        const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
        if (first?.msg) {
          return `${fallback} ${first.msg}`;
        }
      }
      if (detail && typeof detail === "object") {
        try {
          return `${fallback} ${JSON.stringify(detail)}`;
        } catch {
          return fallback;
        }
      }
    }
  } catch {
    // raw wasn't JSON; fall through to plain text handling.
  }
  return `${fallback} ${raw}`;
}

const scoreLabels: Array<[keyof ScoreBreakdown, string]> = [
  ["talent_score", "天赋"],
  ["fit_score", "适配"],
  ["pick_value_score", "签位价值"],
  ["risk_penalty", "风险"],
  ["final_score", "综合"],
];

const SCOUTING_LABELS: Record<string, string> = {
  rim_protection_fit: "补护框",
  defensive_rebounding_fit: "补防守篮板",
  offensive_rebounding_fit: "补进攻篮板",
  spacing_fit: "补空间",
  shooting_volume_fit: "补三分产量",
  movement_shooting_fit: "补无球投射",
  self_creation_fit: "补持球创造",
  secondary_creation_fit: "补二传/副攻",
  playmaking_fit: "补组织",
  rim_pressure_fit: "补篮筐压力",
  finishing_fit: "补终结",
  point_of_attack_fit: "补外线领防",
  switchability_fit: "补换防",
  team_defense_fit: "补团队防守",
  physicality_fit: "补对抗",
  nba_readiness_fit: "即战力适配",
  upside_fit: "长期上限",
  center_depth_fit: "补中锋深度",
  big_depth_fit: "补内线深度",
  wing_depth_fit: "补侧翼深度",
  size_fit: "补尺寸",
  spacing_risk: "空间风险",
  defense_risk: "防守风险",
  readiness_risk: "即战力风险",
  medical_risk: "医疗风险",
  foul_risk: "犯规风险",
  size_risk: "尺寸/对抗风险",
};

const CANDIDATE_SOURCE_LABELS: Record<string, string> = {
  ranking_top: "原排名 Top",
  prediction_shadow_top: "影子排名关注",
  team_projection_match: "球队预测信号",
};

const TEAM_PROFILE_FIELDS = [
  { key: "need_center", label: "中锋深度" },
  { key: "need_rim_protection", label: "护框" },
  { key: "need_defensive_rebounding", label: "防守篮板" },
  { key: "need_spacing", label: "空间" },
  { key: "need_shooting_volume", label: "三分产量" },
  { key: "need_self_creation", label: "持球创造" },
  { key: "need_point_of_attack_defense", label: "外线领防" },
  { key: "need_nba_ready", label: "即战力" },
  { key: "need_upside", label: "长期上限" },
] as const;

type TeamProfileFieldKey = (typeof TEAM_PROFILE_FIELDS)[number]["key"];
type TeamProfileForm = Record<TeamProfileFieldKey, string>;

const EMPTY_TEAM_PROFILE_FORM: TeamProfileForm = {
  need_center: "",
  need_rim_protection: "",
  need_defensive_rebounding: "",
  need_spacing: "",
  need_shooting_volume: "",
  need_self_creation: "",
  need_point_of_attack_defense: "",
  need_nba_ready: "",
  need_upside: "",
};

function teamProfileToForm(profile: TeamNeedProfile | null): TeamProfileForm {
  if (!profile) {
    return { ...EMPTY_TEAM_PROFILE_FORM };
  }

  return TEAM_PROFILE_FIELDS.reduce<TeamProfileForm>(
    (form, { key }) => ({
      ...form,
      [key]:
        profile[key] === null || profile[key] === undefined
          ? ""
          : String(profile[key]),
    }),
    { ...EMPTY_TEAM_PROFILE_FORM },
  );
}

function scoutingLabel(key: string): string {
  return SCOUTING_LABELS[key] ?? key.replaceAll("_", " ");
}

function hasScoutingDiagnostics(player: RankedProspect): boolean {
  return player.scouting_fit_score !== undefined && player.scouting_fit_score !== null;
}

function hasProjectionDiagnostics(player: RankedProspect): boolean {
  return (
    player.projection_expected_pick !== undefined &&
    player.projection_expected_pick !== null
  ) || (
      player.team_projection_type !== undefined &&
      player.team_projection_type !== null
    ) || hasPredictionShadow(player) || (
      player.prediction_sort_score !== undefined &&
      player.prediction_sort_score !== null
    ) || (
      player.market_alignment_label !== undefined &&
      player.market_alignment_label !== null
    );
}

function hasPredictionShadow(player: RankedProspect): boolean {
  return (
    player.prediction_shadow_score !== undefined &&
    player.prediction_shadow_score !== null
  );
}

function percent(value: number | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
}

function formatProjectionSource(source: string): string {
  const labels: Record<string, string> = {
    manual_projection: "手动预测",
    seed_projection: "示例预测",
    consensus_reference: "媒体参考",
    manual_prediction: "手动倾向",
    team_report: "球队报道",
    workout_signal: "试训信号",
    consensus_mock: "媒体模拟",
  };
  return labels[source] ?? source.replaceAll("_", " ");
}

function marketAlignmentLabel(label: string): string {
  const labels: Record<string, string> = {
    高于市场: "比行情预测更早被选",
    明显高于市场: "明显比行情预测更早被选",
    低于市场: "比行情预测更晚被选",
    明显低于市场: "明显比行情预测更晚被选",
    一致: "基本一致",
    接近: "接近行情预测",
    无市场参考: "暂无外部预测",
  };
  return labels[label] ?? label;
}

function formatShadowDelta(delta: number | null | undefined): string | null {
  if (delta === null || delta === undefined) {
    return null;
  }
  if (delta > 0) {
    return `+${delta}`;
  }
  return String(delta);
}

function formatMarketDelta(delta: number | null | undefined): string | null {
  if (delta === null || delta === undefined) {
    return null;
  }
  if (delta === 0) {
    return "同顺位";
  }
  return delta < 0 ? `早 ${Math.abs(delta)} 位` : `晚 ${delta} 位`;
}

function candidateSourceLabel(source: string | null | undefined): string | null {
  if (!source || source === "ranking_top") {
    return null;
  }
  return CANDIDATE_SOURCE_LABELS[source] ?? source.replaceAll("_", " ");
}

function diagnosticsWarnings(player: RankedProspect): string[] {
  return player.diagnostics_warnings ?? [];
}

export default function DraftPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [teamId, setTeamId] = useState<number | null>(null);
  const [pick, setPick] = useState(8);
  const [question, setQuestion] = useState("为什么不选第一个备选球员？");
  const [recommendation, setRecommendation] = useState<Recommendation | null>(
    null,
  );
  const [roster, setRoster] = useState<RosterPlayer[]>([]);
  const [teamPicks, setTeamPicks] = useState<TeamPick[]>([]);
  // When true, the user is overriding the auto-filled real pick to
  // simulate a trade up/down.  While off, the pick input is read-only
  // and reflects the team's real 2026 first-round slot.
  const [isPickOverridden, setIsPickOverridden] = useState(false);
  const [agentAnswer, setAgentAnswer] = useState<AgentAskResponse | null>(null);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [simulationRounds, setSimulationRounds] = useState<1 | 2>(1);
  const [showScoutingDiagnostics, setShowScoutingDiagnostics] = useState(false);
  const [useScoutingTiebreaker, setUseScoutingTiebreaker] = useState(false);
  // Phase 6B: default DraftMind into "real draft prediction" mode — show
  // the prediction shadow and let predictions actually inform the
  // simulation.  These are *frontend* defaults only; the backend
  // SimulateRequest default for use_prediction_calibration stays False
  // for backwards compatibility.
  const [showPredictionShadow, setShowPredictionShadow] = useState(true);
  const [usePredictionCalibration, setUsePredictionCalibration] = useState(true);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [teamProfile, setTeamProfile] = useState<TeamNeedProfile | null>(null);
  const [teamProfileForm, setTeamProfileForm] = useState<TeamProfileForm>(
    EMPTY_TEAM_PROFILE_FORM,
  );
  const [teamProfileReason, setTeamProfileReason] = useState("");
  const [isTeamProfileLoading, setIsTeamProfileLoading] = useState(false);
  const [isTeamProfileSaving, setIsTeamProfileSaving] = useState(false);
  const [teamProfileStatus, setTeamProfileStatus] = useState<string | null>(null);
  const [teamProfileError, setTeamProfileError] = useState<string | null>(null);
  // Phase 3: locked-picks / user-override.  Each entry is one row in
  // the sidebar UI.  prospect_id is required for the MVP dropdown;
  // prospect_name is left null and is not exposed in this version.
  const [lockedPicks, setLockedPicks] = useState<LockedPick[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [isLoadingTeams, setIsLoadingTeams] = useState(true);
  const [isLoadingRoster, setIsLoadingRoster] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAskingAgent, setIsAskingAgent] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isRefreshingNews, setIsRefreshingNews] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    getTeams()
      .then((nextTeams) => {
        if (!isMounted) {
          return;
        }
        setTeams(nextTeams);
        setTeamId(nextTeams[0]?.id ?? null);
      })
      .catch(() => {
        if (isMounted) {
          setError("无法连接球队数据接口，请确认后端正在运行。");
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoadingTeams(false);
        }
      });

    // Auto-load news on mount — no language filter so both ESPN (en) and
    // Hupu (zh) results are returned.  The backend search_articles will
    // auto-fallback from zh → all when zh yields nothing.
    searchNews({ limit: 5 })
      .then((res) => {
        if (isMounted) {
          setNews(res.articles);
        }
      })
      .catch((err) => {
        console.warn("[news] initial auto-load failed:", err);
      });

    // Phase 3: also load the prospect board so the locked-pick dropdown
    // can populate.  Backend returns Prospect[] directly.
    getProspects(2026)
      .then((nextProspects) => {
        if (isMounted) {
          setProspects(nextProspects);
        }
      })
      .catch(() => {
        if (isMounted) {
          setProspects([]);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === teamId) ?? null,
    [teams, teamId],
  );

  useEffect(() => {
    if (teamId === null) {
      setTeamProfile(null);
      setTeamProfileForm({ ...EMPTY_TEAM_PROFILE_FORM });
      setTeamProfileReason("");
      setTeamProfileStatus(null);
      setTeamProfileError(null);
      return;
    }

    let isMounted = true;
    setIsTeamProfileLoading(true);
    setTeamProfileStatus(null);
    setTeamProfileError(null);

    getTeamScoutingProfile(teamId, 2026, "next_season")
      .then((profile) => {
        if (!isMounted) {
          return;
        }
        setTeamProfile(profile);
        setTeamProfileForm(teamProfileToForm(profile));
        setTeamProfileReason(profile?.manual_override_reason ?? "");
        setTeamProfileStatus(
          profile ? null : "尚未创建 profile，保存后会创建 manual profile。",
        );
      })
      .catch(() => {
        if (isMounted) {
          setTeamProfile(null);
          setTeamProfileForm({ ...EMPTY_TEAM_PROFILE_FORM });
          setTeamProfileReason("");
          setTeamProfileError("加载球队球探需求 Profile 失败。");
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsTeamProfileLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [teamId]);

  useEffect(() => {
    if (teamId === null) {
      setRoster([]);
      return;
    }

    let isMounted = true;
    setIsLoadingRoster(true);

    getTeamRoster(teamId)
      .then((nextRoster) => {
        if (isMounted) {
          setRoster(nextRoster);
        }
      })
      .catch(() => {
        if (isMounted) {
          setRoster([]);
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoadingRoster(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [teamId]);

  // Whenever the team changes, pull the picks it owns in 2026 and
  // auto-fill the pick slot with the earliest (first-round) selection.
  // Switching teams also clears any previous trade what-if override
  // — the new team has its own real slot.
  useEffect(() => {
    if (teamId === null) {
      setTeamPicks([]);
      return;
    }

    let isMounted = true;
    getTeamPicks(teamId, 2026)
      .then((picks) => {
        if (!isMounted) {
          return;
        }
        setTeamPicks(picks);
        setIsPickOverridden(false);
        if (picks.length > 0) {
          setPick(picks[0].pick_no);
        }
      })
      .catch(() => {
        if (isMounted) {
          setTeamPicks([]);
          setIsPickOverridden(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [teamId]);

  const selectedPick = useMemo(
    () => teamPicks.find((p) => p.pick_no === pick) ?? null,
    [teamPicks, pick],
  );
  const simulationPickLimit = simulationRounds === 1 ? 30 : 60;

  function updateTeamProfileField(key: TeamProfileFieldKey, value: string) {
    setTeamProfileForm((form) => ({
      ...form,
      [key]: value,
    }));
    setTeamProfileStatus(null);
    setTeamProfileError(null);
  }

  async function handleSaveTeamProfile() {
    if (teamId === null) {
      setTeamProfileError("请选择球队。");
      return;
    }

    const payload: TeamNeedProfilePayload = {
      team_id: teamId,
      year: 2026,
      horizon: "next_season",
      need_confidence: 1.0,
    };

    for (const { key, label } of TEAM_PROFILE_FIELDS) {
      const rawValue = teamProfileForm[key].trim();
      if (rawValue.length === 0) {
        continue;
      }
      const value = Number(rawValue);
      if (!Number.isFinite(value) || value < 1 || value > 10) {
        setTeamProfileError(`${label} 必须在 1-10 之间，或留空。`);
        return;
      }
      (payload as Record<TeamProfileFieldKey, number | undefined>)[key] = value;
    }

    const trimmedReason = teamProfileReason.trim();
    if (trimmedReason.length > 0) {
      payload.manual_override_reason = trimmedReason;
    }

    setIsTeamProfileSaving(true);
    setTeamProfileError(null);
    setTeamProfileStatus(null);

    try {
      const saved = await saveTeamScoutingProfile(payload);
      setTeamProfile(saved);
      setTeamProfileForm(teamProfileToForm(saved));
      setTeamProfileReason(saved.manual_override_reason ?? "");
      setTeamProfileStatus("已保存 manual profile。");
    } catch (err) {
      setTeamProfileError(formatApiError(err, "保存球队球探需求 Profile 失败。"));
    } finally {
      setIsTeamProfileSaving(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (teamId === null) {
      setError("请选择球队。");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const result = await getRecommendation({
        year: 2026,
        team_id: teamId,
        pick,
        mode: "gm_decision",
      });
      setRecommendation(result);
      setAgentAnswer(null);
      setQuestion(
        result.alternatives[0]
          ? `为什么不选 ${result.alternatives[0].prospect.name}？`
          : "请解释这次推荐。",
      );
      // Auto-load related news for the recommended prospect.
      // No language filter — backend auto-falls back from zh → all.
      try {
        const newsResult = await searchNews({
          prospect: result.recommended_player.prospect.name,
          team: result.team.abbr,
          limit: 5,
        });
        if (newsResult.articles.length > 0) {
          setNews(newsResult.articles);
        } else {
          const fallback = await searchNews({ limit: 5 });
          setNews(fallback.articles);
        }
      } catch {
        // News is best-effort, do not block recommendation.
      }
    } catch {
      setError("生成推荐失败，请检查后端服务或数据库 seed 状态。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleAskAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (teamId === null) {
      setError("请选择球队。");
      return;
    }

    setIsAskingAgent(true);
    setError(null);

    try {
      const result = await askAgent({
        year: 2026,
        team_id: teamId,
        pick,
        mode: "gm_decision",
        question,
      });
      setAgentAnswer(result);
    } catch {
      setError("Agent 追问失败，请确认后端 /api/agent/ask 可用。");
    } finally {
      setIsAskingAgent(false);
    }
  }

  async function handleSimulateDraft() {
    setIsSimulating(true);
    setError(null);

    // Phase 3: client-side pre-validation.  We do this before sending
    // so the user sees immediate, friendly errors instead of waiting
    // for a roundtrip 400 from the backend.
    const seenPick = new Set<number>();
    const seenProspect = new Set<number>();
    const cleaned: LockedPick[] = [];
    for (const lp of lockedPicks) {
      if (!Number.isInteger(lp.pick_no) || lp.pick_no < 1 || lp.pick_no > 60) {
        setError(`锁定 pick #${lp.pick_no} 越界，应在 1-60 之间。`);
        setIsSimulating(false);
        return;
      }
      if (lp.pick_no > simulationPickLimit) {
        continue;
      }
      if (seenPick.has(lp.pick_no)) {
        setError(`pick #${lp.pick_no} 被重复锁定，请合并后再试。`);
        setIsSimulating(false);
        return;
      }
      if (lp.prospect_id == null) {
        setError(`pick #${lp.pick_no} 必须先选择一名 prospect。`);
        setIsSimulating(false);
        return;
      }
      if (seenProspect.has(lp.prospect_id)) {
        setError("同一个球员不能被锁定到多个顺位。");
        setIsSimulating(false);
        return;
      }
      seenPick.add(lp.pick_no);
      seenProspect.add(lp.prospect_id);
      cleaned.push({ pick_no: lp.pick_no, prospect_id: lp.prospect_id });
    }

    try {
      const result = await simulateDraft({
        year: 2026,
        rounds: simulationRounds,
        limit: simulationPickLimit,
        evaluate_trades: true,
        include_scouting_diagnostics:
          showScoutingDiagnostics || useScoutingTiebreaker,
        use_scouting_tiebreaker: useScoutingTiebreaker,
        include_projection_diagnostics:
          showPredictionShadow || usePredictionCalibration,
        include_prediction_shadow:
          showPredictionShadow || usePredictionCalibration,
        use_prediction_calibration: usePredictionCalibration,
        // Send an empty array (not undefined) so the backend treats the
        // request as the same shape either way.  `undefined` also works
        // because the field is Optional, but explicit is clearer.
        locked_picks: cleaned.length > 0 ? cleaned : undefined,
      });
      setSimulation(result);
    } catch (err) {
      setError(formatApiError(err, "模拟选秀失败，请检查后端服务或 draft_order 数据。"));
    } finally {
      setIsSimulating(false);
    }
  }

  async function handleRefreshNews() {
    console.log("[news] handleRefreshNews clicked", { hasRecommendation: !!recommendation });
    setIsRefreshingNews(true);
    setError(null);
    try {
      console.log("[news] calling refreshNews(8) ...");
      const result = await refreshNews(8);
      console.log("[news] refreshNews returned:", result);
      if (recommendation) {
        // Try a prospect-specific search first; fall back to general feed.
        const filtered = await searchNews({
          prospect: recommendation.recommended_player.prospect.name,
          team: recommendation.team.abbr,
          limit: 5,
        });
        if (filtered.articles.length > 0) {
          setNews(filtered.articles);
        } else {
          setNews(result.articles);
        }
      } else {
        setNews(result.articles);
      }
    } catch (err) {
      // Even on failure, keep whatever the last successful fetch returned
      // so the user does not see a destructive red error for a non-fatal
      // background refresh.  The backend already logs the real cause.
      console.warn("news refresh failed:", err);
    } finally {
      setIsRefreshingNews(false);
    }
  }

  return (
    <main className="min-h-screen bg-court-black text-court-text">
      <section className="mx-auto grid min-h-screen w-full max-w-7xl gap-8 px-5 py-8 lg:grid-cols-[360px_1fr] lg:px-8">
        <aside className="aside-scroll lg:sticky lg:top-8 lg:h-[calc(100vh-4rem)] lg:overflow-y-auto lg:pr-2">
          <a
            className="inline-flex text-sm font-semibold text-court-line transition hover:text-[#c8ff75]"
            href="/"
          >
            Back
          </a>

          <div className="mt-8">
            <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
              Draft code 24
            </p>
            <h1 className="mt-4 text-4xl font-black leading-tight sm:text-5xl">
              选秀推荐台
            </h1>
            <p className="mt-4 text-sm leading-7 text-court-muted">
              DraftMind 会先计算候选人的天赋、球队适配、签位价值和风险，再输出管理层视角的排序。
            </p>
          </div>

          <form
            className="mt-8 rounded-md border border-white/10 bg-court-panel p-5"
            onSubmit={handleSubmit}
          >
            <label className="block text-sm font-bold text-court-muted">
              球队
              <select
                className="mt-2 h-12 w-full rounded-md border border-white/10 bg-court-black px-3 text-base font-bold text-court-text outline-none transition focus:border-court-line"
                disabled={isLoadingTeams || teams.length === 0}
                value={teamId ?? ""}
                onChange={(event) => setTeamId(Number(event.target.value))}
              >
                {teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.abbr} · {team.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="mt-5 block text-sm font-bold text-court-muted">
              <span className="flex items-center justify-between gap-3">
                <span>签位</span>
                {teamPicks.length > 0 ? (
                  <button
                    className="text-[11px] font-black uppercase tracking-[0.16em] text-court-line transition hover:text-[#c8ff75] disabled:opacity-50"
                    disabled={isPickOverridden}
                    onClick={() => setIsPickOverridden(true)}
                    type="button"
                  >
                    模拟交易
                  </button>
                ) : null}
              </span>
              <input
                className={`mt-2 h-12 w-full rounded-md border bg-court-black px-3 text-base font-bold text-court-text outline-none transition focus:border-court-line ${isPickOverridden
                  ? "border-court-line/60"
                  : "border-white/10 text-court-muted"
                  }`}
                max={60}
                min={1}
                readOnly={!isPickOverridden}
                type="number"
                value={pick}
                onChange={(event) => {
                  setIsPickOverridden(true);
                  setPick(Number(event.target.value));
                }}
              />
              {selectedPick ? (
                <p className="mt-2 text-xs leading-5 text-court-muted">
                  {selectedTeam?.abbr ?? "--"} 真实首签
                  {selectedPick.original_team
                    ? ` · 来自 ${selectedPick.original_team}`
                    : ""}
                  {selectedPick.notes ? ` · ${selectedPick.notes}` : ""}
                </p>
              ) : teamPicks.length === 0 && teamId !== null ? (
                <p className="mt-2 text-xs leading-5 text-court-muted">
                  暂无 2026 真实签位数据。已启用手动模式，可直接输入签位。
                </p>
              ) : isPickOverridden ? (
                <p className="mt-2 text-xs leading-5 text-court-muted">
                  手动模式：输入任意签位以模拟交易后场景。
                  <button
                    className="ml-2 font-black uppercase tracking-[0.16em] text-court-line transition hover:text-[#c8ff75]"
                    onClick={() => {
                      setIsPickOverridden(false);
                      if (teamPicks[0]) {
                        setPick(teamPicks[0].pick_no);
                      }
                    }}
                    type="button"
                  >
                    恢复真实签位
                  </button>
                </p>
              ) : null}
            </label>

            {teamPicks.length > 1 ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-black uppercase tracking-[0.16em] text-court-muted">
                  该队其他签位
                </span>
                {teamPicks.map((teamPick) => (
                  <button
                    className={`h-8 rounded-full border px-3 text-xs font-black transition ${teamPick.pick_no === pick
                      ? "border-court-line bg-court-line text-court-black"
                      : "border-white/15 bg-court-black text-court-text hover:border-court-line/60"
                      }`}
                    key={teamPick.pick_no}
                    onClick={() => {
                      setPick(teamPick.pick_no);
                      // Picking from the team's real slot list counts as
                      // staying within the real pick world — clear the
                      // trade override.
                      setIsPickOverridden(false);
                    }}
                    type="button"
                  >
                    #{teamPick.pick_no}
                    {teamPick.original_team
                      ? ` · ${teamPick.original_team}`
                      : ""}
                  </button>
                ))}
              </div>
            ) : null}

            <button
              className="mt-6 h-12 w-full rounded-md bg-court-line text-base font-black text-court-black shadow-glow transition hover:bg-[#c0ff5c] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSubmitting || isLoadingTeams || teamId === null}
              type="submit"
            >
              {isSubmitting ? "计算中..." : "生成推荐"}
            </button>

            {error ? (
              <p className="mt-4 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {error}
              </p>
            ) : null}
          </form>

          <div className="mt-5 rounded-md border border-white/10 bg-white/[0.03] p-5">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
              Current board
            </p>
            <div className="mt-4 flex items-end justify-between gap-4">
              <div>
                <p className="text-2xl font-black text-court-line">
                  {selectedTeam?.abbr ?? "--"}
                </p>
                <p className="mt-1 text-sm text-court-muted">
                  Pick #{pick || "--"} · NBA ID{" "}
                  {selectedTeam?.nba_team_id ?? "--"}
                </p>
                <p className="mt-1 text-xs font-bold text-court-line">
                  {isPickOverridden
                    ? "what-if 模拟"
                    : selectedPick?.original_team
                      ? `来自 ${selectedPick.original_team}`
                      : selectedPick
                        ? "本队原签"
                        : "暂无该队 2026 签位数据"}
                </p>
              </div>
              <div className="text-right text-sm text-court-muted">
                <p>{selectedTeam?.conference ?? "Conference"}</p>
                <p>{selectedTeam?.division ?? "Division"}</p>
              </div>
            </div>
          </div>

          <TeamScoutingProfileEditor
            error={teamProfileError}
            form={teamProfileForm}
            isLoading={isTeamProfileLoading}
            isSaving={isTeamProfileSaving}
            onFieldChange={updateTeamProfileField}
            onReasonChange={(value) => {
              setTeamProfileReason(value);
              setTeamProfileStatus(null);
              setTeamProfileError(null);
            }}
            onSave={handleSaveTeamProfile}
            profile={teamProfile}
            reason={teamProfileReason}
            status={teamProfileStatus}
            team={selectedTeam}
          />

          <RosterPanel isLoading={isLoadingRoster} roster={roster} />

          <div className="mt-5 rounded-md border border-white/10 bg-court-panel p-5">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
              Full board
            </p>
            <p className="mt-3 text-sm leading-6 text-court-muted">
              按选秀顺位逐签模拟，已选球员会从后续候选池移除。
            </p>

            <div className="mt-5">
              <p className="text-[11px] font-black uppercase tracking-[0.16em] text-court-line">
                模拟范围
              </p>
              <div className="mt-3 grid grid-cols-2 overflow-hidden rounded-md border border-white/10 bg-court-black">
                {[
                  { label: "第一轮", rounds: 1 as const, detail: "30 picks" },
                  { label: "两轮", rounds: 2 as const, detail: "60 picks" },
                ].map((option) => {
                  const isActive = simulationRounds === option.rounds;
                  return (
                    <button
                      aria-pressed={isActive}
                      className={`h-12 px-3 text-sm font-black transition ${isActive
                        ? "bg-court-line text-court-black"
                        : "text-court-muted hover:bg-white/[0.04] hover:text-court-line"
                        }`}
                      key={option.rounds}
                      onClick={() => setSimulationRounds(option.rounds)}
                      type="button"
                    >
                      <span>{option.label}</span>
                      <span className="ml-2 text-xs opacity-75">
                        {option.detail}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs leading-5 text-court-muted">
                当前将模拟 {simulationRounds === 1 ? "第一轮" : "两轮"} ·{" "}
                {simulationPickLimit} picks；超出范围的锁定签会保留在表单中，但不会发送到本次模拟。
              </p>
            </div>

            <div className="mt-5 rounded-md border border-white/10 bg-court-black/55 p-4">
              <p className="text-[11px] font-black uppercase tracking-[0.16em] text-court-line">
                球探适配
              </p>
              <div className="mt-3 grid gap-3">
                <label className="flex cursor-pointer items-start gap-3 rounded-md border border-white/10 bg-white/[0.025] p-3 transition hover:border-court-line/50">
                  <input
                    checked={showScoutingDiagnostics}
                    className="mt-1 h-4 w-4 accent-court-line"
                    onChange={(event) => {
                      const next = event.target.checked;
                      setShowScoutingDiagnostics(next);
                      if (!next) {
                        setUseScoutingTiebreaker(false);
                      }
                    }}
                    type="checkbox"
                  />
                  <span>
                    <span className="block text-sm font-black text-court-text">
                      显示球探适配诊断
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-court-muted">
                      仅显示适配标签和风险，不改变选人结果。
                    </span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-md border border-amber-300/20 bg-amber-300/[0.035] p-3 transition hover:border-amber-300/50">
                  <input
                    checked={useScoutingTiebreaker}
                    className="mt-1 h-4 w-4 accent-amber-300"
                    onChange={(event) => {
                      const next = event.target.checked;
                      setUseScoutingTiebreaker(next);
                      if (next) {
                        setShowScoutingDiagnostics(true);
                      }
                    }}
                    type="checkbox"
                  />
                  <span>
                    <span className="block text-sm font-black text-court-text">
                      启用同档适配打破平局
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-court-muted">
                      可能在同档小分差时选择更符合短板的球员；final_score 不会被改写。
                    </span>
                  </span>
                </label>
              </div>
            </div>

            <div className="mt-5 rounded-md border border-white/10 bg-court-black/55 p-4">
              <p className="text-[11px] font-black uppercase tracking-[0.16em] text-court-line">
                预测信息
              </p>
              <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-md border border-sky-300/20 bg-sky-300/[0.035] p-3 transition hover:border-sky-300/50">
                <input
                  checked={showPredictionShadow}
                  className="mt-1 h-4 w-4 accent-sky-300"
                  onChange={(event) => setShowPredictionShadow(event.target.checked)}
                  type="checkbox"
                />
                <span>
                  <span className="block text-sm font-black text-court-text">
                    显示预测参考
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-court-muted">
                    只显示预测顺位、选秀区间和球队倾向，帮助你判断模型为什么这么排；不会改变模拟选人结果。
                  </span>
                </span>
              </label>
              <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-md border border-fuchsia-300/25 bg-fuchsia-300/[0.04] p-3 transition hover:border-fuchsia-300/55">
                <input
                  checked={usePredictionCalibration}
                  className="mt-1 h-4 w-4 accent-fuchsia-300"
                  onChange={(event) => {
                    const next = event.target.checked;
                    setUsePredictionCalibration(next);
                    if (next) {
                      setShowPredictionShadow(true);
                    }
                  }}
                  type="checkbox"
                />
                <span>
                  <span className="block text-sm font-black text-court-text">
                    用预测信息辅助选人
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-court-muted">
                    打开后，系统会把预测顺位、选秀区间和球队倾向纳入自动选人；关闭时仍按原评分选人。它不会直接照搬媒体模拟榜。
                  </span>
                </span>
              </label>
            </div>

            {/* Phase 3: locked picks / user override editor.
                MVP uses a prospect_id dropdown.  Backend also supports
                prospect_name free-text matching, but the UI does not
                expose that to avoid name typos during demo. */}
            <div className="mt-5">
              <div className="flex items-end justify-between gap-3">
                <p className="text-[11px] font-black uppercase tracking-[0.16em] text-court-line">
                  手动锁定 picks
                </p>
                <button
                  className="h-8 rounded-md border border-court-line/50 px-3 text-[11px] font-black uppercase tracking-[0.16em] text-court-line transition hover:border-court-line hover:bg-court-line hover:text-court-black disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={prospects.length === 0}
                  onClick={() => {
                    setLockedPicks((arr) => [
                      ...arr,
                      { pick_no: 1, prospect_id: null },
                    ]);
                  }}
                  type="button"
                >
                  + 添加锁定
                </button>
              </div>

              {lockedPicks.length === 0 ? (
                <p className="mt-3 text-xs leading-5 text-court-muted">
                  未锁定任何顺位，将使用自动模拟。后端也支持按
                  prospect_name 锁定，但本阶段 UI 暂未暴露。
                </p>
              ) : (
                <div className="mt-3 grid gap-2">
                  {lockedPicks.map((lp, idx) => (
                    <div
                      className="grid grid-cols-[68px_1fr_32px] items-center gap-2"
                      key={`locked-${idx}`}
                    >
                      <input
                        aria-label="locked pick number"
                        className="h-9 rounded-md border border-white/10 bg-court-black px-2 text-sm font-bold text-court-text outline-none transition focus:border-court-line"
                        max={60}
                        min={1}
                        type="number"
                        value={lp.pick_no}
                        onChange={(event) => {
                          const next = Number(event.target.value);
                          setLockedPicks((arr) =>
                            arr.map((row, i) =>
                              i === idx
                                ? { ...row, pick_no: Number.isFinite(next) ? next : 1 }
                                : row,
                            ),
                          );
                        }}
                      />
                      <select
                        aria-label="locked prospect"
                        className="h-9 rounded-md border border-white/10 bg-court-black px-2 text-sm font-semibold text-court-text outline-none transition focus:border-court-line"
                        disabled={prospects.length === 0}
                        value={lp.prospect_id == null ? "" : String(lp.prospect_id)}
                        onChange={(event) => {
                          const raw = event.target.value;
                          const value = raw === "" ? null : Number(raw);
                          setLockedPicks((arr) =>
                            arr.map((row, i) =>
                              i === idx ? { ...row, prospect_id: value } : row,
                            ),
                          );
                        }}
                      >
                        <option value="">选择 prospect</option>
                        {prospects.map((p) => (
                          <option key={p.id} value={String(p.id)}>
                            #{p.id} · {p.name} · {p.position} · UP {p.upside_score}
                          </option>
                        ))}
                      </select>
                      <button
                        aria-label="remove locked pick"
                        className="h-9 rounded-md border border-white/15 bg-court-black text-sm font-black text-court-muted transition hover:border-red-300/60 hover:text-red-200"
                        onClick={() => {
                          setLockedPicks((arr) => arr.filter((_, i) => i !== idx));
                        }}
                        type="button"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <button
              className="mt-5 h-11 w-full rounded-md border border-court-line/50 bg-court-black text-sm font-black text-court-line transition hover:border-court-line hover:bg-court-line hover:text-court-black disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSimulating}
              onClick={handleSimulateDraft}
              type="button"
            >
              {isSimulating ? "模拟中..." : "模拟完整顺位"}
            </button>
          </div>
        </aside>

        <section className="grid min-w-0 gap-5">
          {recommendation ? (
            <RecommendationPanel recommendation={recommendation} />
          ) : (
            <EmptyState />
          )}
          {recommendation ? (
            <AgentPanel
              answer={agentAnswer}
              isAsking={isAskingAgent}
              onAsk={handleAskAgent}
              question={question}
              setQuestion={setQuestion}
            />
          ) : null}
          <NewsPanel
            articles={news}
            isRefreshing={isRefreshingNews}
            onRefresh={handleRefreshNews}
            prospectName={recommendation?.recommended_player.prospect.name ?? null}
          />
          {simulation ? <SimulationBoard simulation={simulation} /> : null}
        </section>
      </section>
    </main>
  );
}

function EmptyState() {
  return (
    <div className="flex min-h-[520px] items-center justify-center rounded-md border border-dashed border-white/15 bg-white/[0.02] p-8 text-center">
      <div>
        <p className="text-6xl font-black text-court-line">24</p>
        <h2 className="mt-5 text-2xl font-black">等待交卷</h2>
        <p className="mt-3 max-w-md text-sm leading-7 text-court-muted">
          选择球队和签位后，系统会生成推荐球员、评分拆解、风险和前三备选。
        </p>
      </div>
    </div>
  );
}

function RecommendationPanel({
  recommendation,
}: {
  recommendation: Recommendation;
}) {
  const player = recommendation.recommended_player;

  return (
    <div className="grid gap-5">
      <article className="rounded-md border border-court-line/40 bg-[linear-gradient(135deg,rgba(163,255,36,0.14),rgba(16,20,16,0.96)_38%,rgba(16,20,16,0.94))] p-5 shadow-glow sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
              Recommended pick
            </p>
            <h2 className="mt-3 text-4xl font-black leading-tight sm:text-6xl">
              {player.prospect.name}
            </h2>
            <p className="mt-3 text-lg font-bold text-court-muted">
              {player.prospect.position} · {player.prospect.height} ·{" "}
              {player.prospect.school_or_league}
            </p>
          </div>
          <div className="rounded-md border border-white/15 bg-court-black/70 px-5 py-4 text-right">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
              Final score
            </p>
            <p className="mt-1 text-5xl font-black text-court-line">
              {player.scores.final_score}
            </p>
          </div>
        </div>

        <div className="mt-7 grid gap-4 lg:grid-cols-[1fr_280px]">
          <div className="grid gap-3">
            {scoreLabels.map(([key, label]) => (
              <ScoreBar
                key={key}
                label={label}
                tone={key === "risk_penalty" ? "risk" : "score"}
                value={player.scores[key]}
              />
            ))}
          </div>

          <div className="rounded-md border border-white/10 bg-court-black/70 p-4">
            <p className="text-sm font-black text-court-line">基础数据</p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <Metric label="PPG" value={player.prospect.ppg} />
              <Metric label="RPG" value={player.prospect.rpg} />
              <Metric label="APG" value={player.prospect.apg} />
              <Metric label="3P%" value={player.prospect.three_pct} />
              <Metric label="UP" value={player.prospect.upside_score} />
              <Metric label="RISK" value={player.prospect.risk_score} />
            </div>
          </div>
        </div>

        <ProjectionPredictionDiagnostics player={player} />
      </article>

      <div className="grid gap-5 xl:grid-cols-2">
        <InsightList title="推荐理由" items={player.reasons} />
        <InsightList title="风险提示" items={player.risks} />
      </div>

      <section className="rounded-md border border-white/10 bg-court-panel p-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
              Alternatives
            </p>
            <h3 className="mt-2 text-2xl font-black">备选球员</h3>
          </div>
          <p className="text-sm font-bold text-court-muted">
            {recommendation.team.abbr} · Pick #{recommendation.pick}
          </p>
        </div>

        <div className="mt-5 grid gap-3 lg:grid-cols-3">
          {recommendation.alternatives.map((alternative, index) => (
            <article
              className="rounded-md border border-white/10 bg-court-black/70 p-4"
              key={alternative.prospect.id}
            >
              <p className="text-sm font-black text-court-line">
                #{index + 2}
              </p>
              <h4 className="mt-2 min-h-14 text-xl font-black leading-tight">
                {alternative.prospect.name}
              </h4>
              <p className="text-sm font-bold text-court-muted">
                {alternative.prospect.position} · {alternative.prospect.archetype}
              </p>
              <div className="mt-4">
                <ScoreBar
                  label="综合"
                  value={alternative.scores.final_score}
                />
              </div>
              <ProjectionPredictionDiagnostics compact player={alternative} />
              <p className="mt-4 text-sm leading-6 text-court-muted">
                {alternative.reasons[0] ?? "综合评分接近推荐球员"}
              </p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function ScoreBar({
  label,
  value,
  tone = "score",
}: {
  label: string;
  value: number;
  tone?: "score" | "risk";
}) {
  const width = `${Math.max(0, Math.min(100, value))}%`;

  return (
    <div>
      <div className="flex items-center justify-between gap-4 text-sm font-bold">
        <span className="text-court-muted">{label}</span>
        <span className={tone === "risk" ? "text-red-200" : "text-court-text"}>
          {value}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={
            tone === "risk"
              ? "h-full rounded-full bg-red-300"
              : "h-full rounded-full bg-court-line"
          }
          style={{ width }}
        />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
      <p className="text-xs font-bold text-court-muted">{label}</p>
      <p className="mt-1 text-lg font-black text-court-text">{value}</p>
    </div>
  );
}

function InsightList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="rounded-md border border-white/10 bg-court-panel p-5">
      <h3 className="text-xl font-black text-court-line">{title}</h3>
      <ul className="mt-4 grid gap-3">
        {items.map((item) => (
          <li
            className="rounded-md border border-white/10 bg-court-black/70 px-4 py-3 text-sm leading-6 text-court-text"
            key={item}
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AgentPanel({
  answer,
  isAsking,
  onAsk,
  question,
  setQuestion,
}: {
  answer: AgentAskResponse | null;
  isAsking: boolean;
  onAsk: (event: FormEvent<HTMLFormElement>) => void;
  question: string;
  setQuestion: (value: string) => void;
}) {
  return (
    <section className="rounded-md border border-white/10 bg-court-panel p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
            Draft agent
          </p>
          <h3 className="mt-2 text-2xl font-black">Agent 追问</h3>
        </div>
        <p className="text-sm font-bold text-court-muted">
          {answer
            ? `${answer.provider} · ${answer.model}${answer.is_mock ? " · mock" : ""}`
            : "ranking first"}
        </p>
      </div>

      <form className="mt-5 grid gap-3 sm:grid-cols-[1fr_132px]" onSubmit={onAsk}>
        <input
          className="h-12 rounded-md border border-white/10 bg-court-black px-4 text-sm font-semibold text-court-text outline-none transition placeholder:text-court-muted focus:border-court-line"
          maxLength={500}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="问：为什么不选另一个球员？最大风险是什么？"
        />
        <button
          className="h-12 rounded-md bg-court-line px-5 text-sm font-black text-court-black shadow-glow transition hover:bg-[#c0ff5c] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isAsking || question.trim().length === 0}
          type="submit"
        >
          {isAsking ? "分析中..." : "追问"}
        </button>
      </form>

      {answer ? (
        <div className="mt-5 grid gap-4">
          <div className="rounded-md border border-court-line/30 bg-court-black/70 p-4">
            <p className="text-sm font-black text-court-line">GM 总结</p>
            <p className="mt-2 text-sm leading-7 text-court-text">
              {answer.explanation.gm_summary}
            </p>
          </div>
          <div className="rounded-md border border-white/10 bg-court-black/70 p-4">
            <p className="text-sm font-black text-court-line">追问回答</p>
            <p className="mt-2 text-sm leading-7 text-court-text">
              {answer.explanation.follow_up_answer}
            </p>
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <MiniList
              items={answer.explanation.recommendation_reasons}
              title="理由"
            />
            <MiniList items={answer.explanation.risks} title="风险" />
            <MiniList items={answer.explanation.alternatives} title="备选" />
          </div>
          {answer.rag_context ? (
            <details className="rounded-md border border-white/10 bg-court-black/70 p-4 text-sm leading-6 text-court-muted">
              <summary className="cursor-pointer text-xs font-black uppercase tracking-[0.16em] text-court-line">
                RAG 上下文 · {answer.rag_context.length} 字符 · 真实可引用的新闻 / 球探报告
              </summary>
              <pre className="mt-3 whitespace-pre-wrap text-xs text-court-muted">
                {answer.rag_context}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function TeamScoutingProfileEditor({
  error,
  form,
  isLoading,
  isSaving,
  onFieldChange,
  onReasonChange,
  onSave,
  profile,
  reason,
  status,
  team,
}: {
  error: string | null;
  form: TeamProfileForm;
  isLoading: boolean;
  isSaving: boolean;
  onFieldChange: (key: TeamProfileFieldKey, value: string) => void;
  onReasonChange: (value: string) => void;
  onSave: () => void;
  profile: TeamNeedProfile | null;
  reason: string;
  status: string | null;
  team: Team | null;
}) {
  return (
    <section className="mt-5 rounded-md border border-white/10 bg-court-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
            Team scouting needs
          </p>
          <h2 className="mt-2 text-lg font-black">球队球探需求 Profile</h2>
        </div>
        {profile ? (
          <div className="text-right text-xs font-bold text-court-muted">
            <p className="text-court-line">{profile.source}</p>
            <p>{Math.round(profile.need_confidence * 100)}% confidence</p>
          </div>
        ) : null}
      </div>

      <p className="mt-3 text-xs leading-5 text-court-muted">
        这些需求只会用于 scouting fit 诊断和显式开启的同档适配打破平局；不会直接改写 final_score。
      </p>
      <p className="mt-2 text-xs leading-5 text-court-muted">
        Profile 会影响球探适配标签；只有启用“同档适配打破平局”时，才可能影响同档小分差选择。
      </p>

      {isLoading ? (
        <p className="mt-4 rounded-md border border-white/10 bg-court-black/60 px-3 py-3 text-sm text-court-muted">
          正在读取 {team?.abbr ?? "球队"} profile...
        </p>
      ) : (
        <div className="mt-4 grid gap-4">
          <div className="grid grid-cols-2 gap-3">
            {TEAM_PROFILE_FIELDS.map(({ key, label }) => (
              <label
                className="block text-xs font-bold text-court-muted"
                key={key}
              >
                {label}
                <input
                  className="mt-1 h-10 w-full rounded-md border border-white/10 bg-court-black px-3 text-sm font-black text-court-text outline-none transition placeholder:text-court-muted focus:border-court-line"
                  inputMode="decimal"
                  max={10}
                  min={1}
                  placeholder="1-10"
                  type="number"
                  value={form[key]}
                  onChange={(event) => onFieldChange(key, event.target.value)}
                />
              </label>
            ))}
          </div>

          <label className="block text-xs font-bold text-court-muted">
            手动说明
            <textarea
              className="mt-1 min-h-20 w-full resize-y rounded-md border border-white/10 bg-court-black px-3 py-2 text-sm font-semibold leading-6 text-court-text outline-none transition placeholder:text-court-muted focus:border-court-line"
              maxLength={500}
              placeholder="例如：manual profile: contender needing rim protection, rebounding, spacing, and NBA-ready contributors."
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
            />
          </label>

          {status ? (
            <p className="rounded-md border border-court-line/30 bg-court-line/10 px-3 py-2 text-xs leading-5 text-court-line">
              {status}
            </p>
          ) : null}

          {error ? (
            <p className="rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-200">
              {error}
            </p>
          ) : null}

          <button
            className="h-11 rounded-md border border-court-line/50 bg-court-black px-4 text-sm font-black text-court-line transition hover:border-court-line hover:bg-court-line hover:text-court-black disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSaving || team === null}
            onClick={onSave}
            type="button"
          >
            {isSaving ? "保存中..." : "保存 Profile"}
          </button>
        </div>
      )}
    </section>
  );
}

function RosterPanel({
  isLoading,
  roster,
}: {
  isLoading: boolean;
  roster: RosterPlayer[];
}) {
  return (
    <section className="mt-5 rounded-md border border-white/10 bg-court-panel p-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
            NBA roster cache
          </p>
          <h2 className="mt-2 text-lg font-black">当前阵容</h2>
        </div>
        <p className="text-sm font-bold text-court-line">
          {isLoading ? "..." : `${roster.length} 人`}
        </p>
      </div>

      <div className="mt-4 max-h-72 overflow-y-auto rounded-md border border-white/10">
        {isLoading ? (
          <p className="px-3 py-4 text-sm text-court-muted">读取 NBA roster...</p>
        ) : roster.length > 0 ? (
          roster.map((player) => (
            <article
              className="grid grid-cols-[1fr_44px] gap-3 border-t border-white/10 px-3 py-3 first:border-t-0"
              key={player.id}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-black text-court-text">
                  {player.player_name}
                </p>
                <p className="mt-1 truncate text-xs font-bold text-court-muted">
                  {player.position ?? "--"} · {player.height ?? "--"} ·{" "}
                  {player.school ?? "--"}
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm font-black text-court-line">
                  {player.jersey ? `#${player.jersey}` : "--"}
                </p>
                <p className="mt-1 text-xs font-bold text-court-muted">
                  {player.age ?? "--"}
                </p>
              </div>
            </article>
          ))
        ) : (
          <p className="px-3 py-4 text-sm leading-6 text-court-muted">
            暂无缓存阵容。可运行 import_nba_rosters.py 导入 NBA.com 数据。
          </p>
        )}
      </div>
    </section>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border border-white/10 bg-court-black/70 p-4">
      <p className="text-sm font-black text-court-line">{title}</p>
      <ul className="mt-3 grid gap-2">
        {items.slice(0, 3).map((item) => (
          <li className="text-sm leading-6 text-court-muted" key={item}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScoutingDiagnostics({
  player,
  compact = false,
}: {
  player: RankedProspect;
  compact?: boolean;
}) {
  if (!hasScoutingDiagnostics(player)) {
    return null;
  }

  const positives = (player.scouting_fit_positives ?? []).slice(0, compact ? 2 : 4);
  const risks = (player.scouting_fit_risks ?? []).slice(0, compact ? 0 : 3);
  const score =
    player.scouting_fit_score === null || player.scouting_fit_score === undefined
      ? null
      : player.scouting_fit_score.toFixed(1);

  return (
    <div
      className={
        compact
          ? "mt-2 flex flex-wrap items-center gap-1.5"
          : "mt-3 flex flex-wrap items-center gap-2"
      }
    >
      {score ? (
        <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
          适配 {score}/10
        </span>
      ) : null}
      {player.scouting_tiebreaker_applied ? (
        <span className="inline-flex items-center rounded-md border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-[11px] font-black text-amber-200">
          同档适配打破平局
        </span>
      ) : null}
      {positives.map((key) => (
        <span
          className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text"
          key={key}
        >
          {scoutingLabel(key)}
        </span>
      ))}
      {risks.map((key) => (
        <span
          className="inline-flex items-center rounded-md border border-red-300/30 bg-red-300/10 px-2 py-1 text-[11px] font-bold text-red-100"
          key={key}
        >
          {scoutingLabel(key)}
        </span>
      ))}
    </div>
  );
}

function ProjectionPredictionDiagnostics({
  player,
  compact = false,
}: {
  player: RankedProspect;
  compact?: boolean;
}) {
  if (!hasProjectionDiagnostics(player)) {
    return null;
  }

  const confidence = percent(player.projection_confidence);
  const teamConfidence = percent(player.team_projection_confidence);
  const shadowDelta = formatShadowDelta(player.prediction_shadow_delta);
  const marketDelta = formatMarketDelta(player.market_pick_delta);
  const notes = [
    ...(player.prediction_calibration_notes ?? []),
    ...(player.prediction_selection_notes ?? []),
  ].slice(
    0,
    compact ? 1 : 3,
  );
  const uniqueNotes = Array.from(new Set(notes));

  return (
    <div
      className={
        compact
          ? "mt-2 grid gap-1.5"
          : "mt-4 rounded-md border border-sky-300/20 bg-sky-300/[0.035] p-3"
      }
    >
      {!compact ? (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-black uppercase tracking-[0.16em] text-sky-200">
              预测参考
            </p>
            <p className="mt-1 text-xs leading-5 text-court-muted">
              预测参考只展示顺位区间和球队倾向，不会改变模拟选人结果。
            </p>
          </div>
          {hasPredictionShadow(player) ? (
            <span className="rounded-md border border-sky-300/30 bg-sky-300/10 px-2 py-1 text-xs font-black text-sky-100">
              Shadow {player.prediction_shadow_score?.toFixed(1)}
            </span>
          ) : null}
          {player.prediction_sort_score !== undefined &&
            player.prediction_sort_score !== null ? (
            <span className="rounded-md border border-fuchsia-300/30 bg-fuchsia-300/10 px-2 py-1 text-xs font-black text-fuchsia-100">
              预测辅助分 {player.prediction_sort_score.toFixed(1)}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-1.5">
        {player.projection_expected_pick ? (
          <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
            预测顺位 #{player.projection_expected_pick}
          </span>
        ) : null}
        {player.projection_draft_range_min && player.projection_draft_range_max ? (
          <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
            选秀区间 {player.projection_draft_range_min}-{player.projection_draft_range_max}
          </span>
        ) : null}
        {player.projection_tier ? (
          <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
            档位 {player.projection_tier}
          </span>
        ) : null}
        {player.market_alignment_label ? (
          <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
            选秀行情{" "}
            {player.market_expected_pick
              ? `外部预测 #${player.market_expected_pick}`
              : "暂无外部预测"}
            {player.draftmind_selected_pick
              ? ` · DraftMind #${player.draftmind_selected_pick}`
              : ""}
            {marketDelta ? ` · ${marketDelta}` : ""} ·{" "}
            {marketAlignmentLabel(player.market_alignment_label)}
          </span>
        ) : null}
        {confidence ? (
          <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
            预测可信度 {confidence}
          </span>
        ) : null}
        {player.projection_source ? (
          <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
            {formatProjectionSource(player.projection_source)}
          </span>
        ) : null}
        {player.team_projection_type ? (
          <span className="inline-flex items-center rounded-md border border-sky-300/30 bg-sky-300/10 px-2 py-1 text-[11px] font-black text-sky-100">
            球队倾向 {formatProjectionSource(player.team_projection_type)}
            {teamConfidence ? ` · ${teamConfidence}` : ""}
          </span>
        ) : null}
        {player.prediction_shadow_rank ? (
          <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
            参考排序 #{player.prediction_shadow_rank}
          </span>
        ) : null}
        {shadowDelta ? (
          <span
            className={`inline-flex items-center rounded-md border px-2 py-1 text-[11px] font-black ${(player.prediction_shadow_delta ?? 0) >= 0
              ? "border-court-line/30 bg-court-line/10 text-court-line"
              : "border-amber-300/30 bg-amber-300/10 text-amber-100"
              }`}
            title="+3 表示参考排序比原候选排序高 3 位。"
          >
            排序变化 {shadowDelta}
          </span>
        ) : null}
        {player.prediction_selection_rank ? (
          <span className="inline-flex items-center rounded-md border border-fuchsia-300/30 bg-fuchsia-300/10 px-2 py-1 text-[11px] font-black text-fuchsia-100">
            预测排序 #{player.prediction_selection_rank}
          </span>
        ) : null}
        {player.prediction_selection_applied ? (
          <span className="inline-flex items-center rounded-md border border-fuchsia-300/40 bg-fuchsia-300/15 px-2 py-1 text-[11px] font-black text-fuchsia-100">
            本次因预测信息被选中
          </span>
        ) : null}
      </div>

      {!compact &&
        player.prediction_sort_score !== undefined &&
        player.prediction_sort_score !== null ? (
        <p className="mt-2 text-[11px] leading-5 text-court-muted">
          预测辅助分只用于“用预测信息辅助选人”模式，不会改写原始评分。
        </p>
      ) : null}

      {!compact && player.market_alignment_notes?.length ? (
        <p className="mt-2 text-[11px] leading-5 text-court-muted">
          {player.market_alignment_notes[0]}
        </p>
      ) : null}

      {!compact && hasPredictionShadow(player) ? (
        <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] font-bold text-court-muted sm:grid-cols-4">
          <span>区间 {player.prediction_range_score?.toFixed(1) ?? "--"}</span>
          <span>档位 {player.prediction_tier_score?.toFixed(1) ?? "--"}</span>
          <span>
            球队 {player.prediction_team_projection_score?.toFixed(1) ?? "--"}
          </span>
          <span>
            权重 {percent(player.prediction_confidence_weight) ?? "--"}
          </span>
        </div>
      ) : null}

      {uniqueNotes.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {uniqueNotes.map((note, index) => (
            <span
              className="inline-flex items-center rounded-md border border-sky-300/20 bg-sky-300/[0.06] px-2 py-1 text-[11px] font-bold text-sky-100"
              key={`${note}-${index}`}
            >
              {note}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RiskDiagnosticsWarnings({
  warnings,
  compact = false,
}: {
  warnings: string[];
  compact?: boolean;
}) {
  if (warnings.length === 0) {
    return null;
  }

  if (compact) {
    return (
      <div className="mt-2 grid gap-1">
        {warnings.map((warning, index) => (
          <p
            className="rounded-md border border-amber-300/30 bg-amber-300/[0.07] px-2 py-1 text-[11px] font-bold leading-5 text-amber-100"
            key={`${warning}-${index}`}
          >
            风险：{warning}
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-md border border-amber-300/30 bg-amber-300/[0.07] p-3">
      <p className="text-[11px] font-black uppercase tracking-[0.16em] text-amber-200">
        风险提示
      </p>
      <ul className="mt-2 grid gap-1.5 text-xs font-bold leading-5 text-amber-100">
        {warnings.map((warning, index) => (
          <li className="flex gap-2" key={`${warning}-${index}`}>
            <span aria-hidden="true" className="text-amber-300">
              -
            </span>
            <span>{warning}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CandidateBoardPreview({
  candidates,
}: {
  candidates: RankedProspect[];
}) {
  return (
    <div className="grid gap-2">
      <p className="text-xs font-black uppercase tracking-[0.12em] text-court-line">
        Live board
      </p>
      <div className="grid gap-2">
        {candidates.map((candidate) => {
          const sourceLabel = candidateSourceLabel(candidate.candidate_source);
          return (
            <div
              className="rounded-md border border-white/10 bg-white/[0.025] px-3 py-2"
              key={candidate.prospect.id}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-sm font-bold text-court-text">
                    {candidate.prospect.name}
                  </span>
                  {sourceLabel ? (
                    <span className="rounded-md border border-sky-300/30 bg-sky-300/10 px-1.5 py-0.5 text-[10px] font-black text-sky-100">
                      {sourceLabel}
                    </span>
                  ) : null}
                </div>
                <span className="text-xs font-black text-court-muted">
                  Final {candidate.scores.final_score}
                </span>
              </div>
              <ScoutingDiagnostics compact player={candidate} />
              <ProjectionPredictionDiagnostics compact player={candidate} />
              <RiskDiagnosticsWarnings
                compact
                warnings={diagnosticsWarnings(candidate)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SimulationBoard({ simulation }: { simulation: Simulation }) {
  const missingWarnings = simulation.market_top30_missing_warnings ?? [];

  return (
    <section className="rounded-md border border-white/10 bg-court-panel p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
            Simulated board
          </p>
          <h3 className="mt-2 text-2xl font-black">完整顺位模拟</h3>
        </div>
        <p className="text-sm font-bold text-court-muted">
          {simulation.year} · {simulation.total_picks} picks
        </p>
      </div>
      <p className="mt-3 text-sm leading-6 text-court-muted">
        {simulation.source ?? "Draft order source unavailable"} · 每一签都会重新计算实时可选候选池，并记录交易评估。
      </p>

      {missingWarnings.length > 0 ? (
        <div className="mt-5 rounded-md border border-amber-300/30 bg-amber-300/[0.07] p-4">
          <p className="text-xs font-black uppercase tracking-[0.16em] text-amber-200">
            选秀行情 Top-30 未选中提示
          </p>
          <ul className="mt-3 grid gap-1.5 text-sm font-bold leading-6 text-amber-100">
            {missingWarnings.map((warning, index) => (
              <li className="flex gap-2" key={`${warning}-${index}`}>
                <span aria-hidden="true" className="text-amber-300">
                  -
                </span>
                <span>{warning}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 overflow-hidden rounded-md border border-white/10">
        <div className="grid grid-cols-[64px_82px_1fr_72px] bg-white/[0.04] px-4 py-3 text-xs font-black uppercase tracking-[0.16em] text-court-muted">
          <span>Pick</span>
          <span>Team</span>
          <span>Player</span>
          <span className="text-right">Score</span>
        </div>

        <div className="max-h-[620px] overflow-y-auto">
          {simulation.picks.map((pick) => {
            const locked = isPickLocked(pick);
            return (
              <article
                className="border-t border-white/10 px-4 py-4 transition hover:bg-white/[0.03]"
                key={pick.pick}
              >
                <div className="grid grid-cols-[64px_82px_1fr_72px] items-center gap-0">
                  <p className="flex items-center text-lg font-black text-court-line">
                    #{pick.pick}
                    {locked ? (
                      <span
                        className="ml-2 inline-flex items-center gap-1 rounded-md border border-amber-300/40 bg-amber-300/10 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-[0.12em] text-amber-200"
                        title="This pick was locked by user override"
                      >
                        手动锁定
                      </span>
                    ) : null}
                  </p>
                  <p className="text-base font-black">{pick.team.abbr}</p>
                  <div className="min-w-0">
                    <p className="truncate text-base font-black">
                      {pick.selected_player.prospect.name}
                    </p>
                    <p className="mt-1 truncate text-xs font-bold text-court-muted">
                      {pick.selected_player.prospect.position} ·{" "}
                      {pick.selected_player.prospect.archetype}
                      {pick.draft_order_note ? ` · ${pick.draft_order_note}` : ""}
                    </p>
                  </div>
                  <p className="text-right text-lg font-black text-court-text">
                    {pick.selected_player.scores.final_score}
                  </p>
                </div>
                <div className="mt-2 sm:ml-[146px]">
                  <ScoutingDiagnostics player={pick.selected_player} />
                  <ProjectionPredictionDiagnostics player={pick.selected_player} />
                  <RiskDiagnosticsWarnings
                    warnings={diagnosticsWarnings(pick.selected_player)}
                  />
                </div>
                <details className="mt-3 rounded-md border border-white/10 bg-court-black/60 px-3 py-2">
                  <summary className="cursor-pointer text-xs font-black uppercase tracking-[0.12em] text-court-line">
                    Agent process · {pick.trade_evaluation.action} ·{" "}
                    {Math.round(pick.trade_evaluation.probability * 100)}%
                  </summary>
                  <div className="mt-3 grid gap-3 text-sm leading-6 text-court-muted">
                    <p>{pick.trade_evaluation.rationale}</p>
                    <ul className="grid gap-2">
                      {pick.decision_log.map((line) => {
                        // Phase 6A-B: a "Market context:" line is a
                        // *read-only* observation, not a GM decision
                        // input.  Visually separate it so the reader
                        // doesn't mistake cached news for a ranking
                        // / trade nudge.  Detection is purely on the
                        // "Market context:" prefix written by
                        // simulation_service._format_market_line().
                        const isMarketContext = line.startsWith(
                          "Market context:",
                        );
                        const isScoutingTiebreaker = line.startsWith(
                          "Scouting fit tie-breaker applied:",
                        );
                        if (isMarketContext) {
                          return (
                            <li
                              key={line}
                              className="flex items-start gap-2 border-l-2 border-amber-300/40 bg-amber-300/[0.05] py-1 pl-3 pr-2"
                            >
                              <span className="mt-0.5 inline-block shrink-0 rounded border border-amber-300/40 bg-amber-300/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-200">
                                只读选秀行情
                              </span>
                              <span className="text-court-muted/90">
                                {line}
                              </span>
                            </li>
                          );
                        }
                        if (isScoutingTiebreaker) {
                          return (
                            <li
                              key={line}
                              className="flex items-start gap-2 border-l-2 border-court-line/50 bg-court-line/[0.06] py-1 pl-3 pr-2"
                            >
                              <span className="mt-0.5 inline-block shrink-0 rounded border border-court-line/40 bg-court-line/10 px-1.5 py-0.5 text-[10px] font-bold text-court-line">
                                同档适配
                              </span>
                              <span className="text-court-muted/90">
                                {line}
                              </span>
                            </li>
                          );
                        }
                        return <li key={line}>{line}</li>;
                      })}
                    </ul>
                    <CandidateBoardPreview candidates={pick.candidate_board} />
                  </div>
                </details>
                <EvidencePanel pick={pick} simulation={simulation} />
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function formatPublishedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function NewsPanel({
  articles,
  isRefreshing,
  onRefresh,
  prospectName,
}: {
  articles: NewsArticle[];
  isRefreshing: boolean;
  onRefresh: () => void;
  prospectName: string | null;
}) {
  const [isNewsExpanded, setIsNewsExpanded] = useState(true);

  return (
    <section className="rounded-md border border-white/10 bg-court-panel p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.22em] text-court-line">
            News context
          </p>
          <h3 className="mt-2 text-2xl font-black">
            相关新闻{prospectName ? ` · ${prospectName}` : ""}
          </h3>
          <p className="mt-2 text-sm leading-6 text-court-muted">
            展示相关新闻资讯；进入模拟决策日志的选秀上下文会经过更严格筛选。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            aria-expanded={isNewsExpanded}
            aria-label={isNewsExpanded ? "收起相关新闻" : "展开相关新闻"}
            className="h-11 rounded-md border border-white/15 bg-court-black px-3 text-sm font-black text-court-muted transition hover:border-court-line/60 hover:text-court-line"
            onClick={() => setIsNewsExpanded((value) => !value)}
            type="button"
          >
            <span aria-hidden="true" className="mr-1">
              {isNewsExpanded ? "▾" : "▸"}
            </span>
            {isNewsExpanded ? "收起" : `展开 · ${articles.length}`}
          </button>
          <button
            className="h-11 rounded-md border border-court-line/50 bg-court-black px-4 text-sm font-black text-court-line transition hover:border-court-line hover:bg-court-line hover:text-court-black disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isRefreshing}
            onClick={onRefresh}
            type="button"
          >
            {isRefreshing ? "刷新中..." : "刷新新闻"}
          </button>
        </div>
      </div>

      {isNewsExpanded ? (
        <div className="mt-5 grid gap-3">
          {articles.length === 0 ? (
            <p className="rounded-md border border-dashed border-white/15 bg-white/[0.02] px-4 py-6 text-sm leading-6 text-court-muted">
              暂未抓到与该球员 / 球队相关的新闻。点击「刷新新闻」从中文 RSS 源拉取。
            </p>
          ) : (
            articles.map((article) => (
              <a
                className="block rounded-md border border-white/10 bg-court-black/70 p-4 transition hover:border-court-line/60 hover:bg-court-black"
                href={article.url}
                key={article.id}
                rel="noreferrer"
                target="_blank"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-bold uppercase tracking-[0.16em] text-court-muted">
                  <span>
                    {article.source} · {article.language === "zh" ? "中文" : "EN"}
                  </span>
                  <span>{formatPublishedAt(article.published_at)}</span>
                </div>
                <p className="mt-2 text-base font-black leading-snug text-court-text">
                  {article.title}
                </p>
                {article.summary ? (
                  <p className="mt-2 text-sm leading-6 text-court-muted">
                    {article.summary}
                  </p>
                ) : null}
              </a>
            ))
          )}
        </div>
      ) : null}
    </section>
  );
}

// RAG-v0-M2.9: Read-only Evidence panel.
// This panel calls POST /api/evidence/pick with manual_notes=[] and displays
// the returned PickEvidencePackage.  It is display-only — it never feeds back
// into ranking, scoring, or selection.  Manual-note-sourced evidence is
// explicitly tagged as "只读证据，不参与评分".
type EvidenceState = {
  loading: boolean;
  error?: string;
  data?: PickEvidencePackage;
};

function EvidencePanel({
  pick,
  simulation,
}: {
  pick: SimulatedPick;
  simulation: Simulation;
}) {
  const [state, setState] = useState<EvidenceState>({ loading: false });
  const [isOpen, setIsOpen] = useState(false);

  async function handleLoadEvidence() {
    if (state.data || state.loading) {
      setIsOpen((value) => !value);
      return;
    }
    setState({ loading: true });
    try {
      const evidence = await fetchPickEvidence(simulation, pick);
      setState({ loading: false, data: evidence });
      setIsOpen(true);
    } catch (err) {
      setState({
        loading: false,
        error: formatApiError(err, "加载证据包失败。"),
      });
      setIsOpen(true);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-sky-300/20 bg-sky-300/[0.035] px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-black uppercase tracking-[0.16em] text-sky-200">
          Evidence 证据面板
        </p>
        <button
          className="h-8 rounded-md border border-sky-300/40 bg-court-black px-3 text-[11px] font-black uppercase tracking-[0.12em] text-sky-100 transition hover:border-sky-300 hover:bg-sky-300/10 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={state.loading}
          onClick={handleLoadEvidence}
          type="button"
        >
          {state.loading
            ? "加载中..."
            : state.data
              ? isOpen
                ? "隐藏证据"
                : "查看证据"
              : "查看证据"}
        </button>
      </div>
      <p className="mt-1 text-[11px] leading-5 text-court-muted">
        这些内容只用于解释当前已锁定的选择，不参与选人、评分或排序。
      </p>

      {isOpen && state.error ? (
        <p className="mt-2 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-200">
          {state.error}
        </p>
      ) : null}

      {isOpen && state.data ? (
        <ExplanationPanel evidence={state.data} />
      ) : null}

      {isOpen && state.data ? (
        <EvidencePackageView evidence={state.data} />
      ) : null}
    </div>
  );
}

function EvidencePackageView({ evidence }: { evidence: PickEvidencePackage }) {
  const ranking = evidence.ranking_evidence;
  const market = evidence.market_evidence;
  const risk = evidence.risk_evidence;
  const conflict = evidence.conflict_evidence;
  const sufficiency = evidence.evidence_sufficiency;

  return (
    <div className="mt-3 grid gap-3 text-xs leading-5 text-court-muted">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
          决策已锁定
        </span>
        <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
          LLM 可改写决策：否
        </span>
        <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
          决策来源：{evidence.decision_source}
        </span>
      </div>

      {ranking ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
            Ranking Evidence
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {ranking.final_score !== undefined && ranking.final_score !== null ? (
              <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
                Final {ranking.final_score}
              </span>
            ) : null}
            {ranking.prediction_sort_score !== undefined &&
              ranking.prediction_sort_score !== null ? (
              <span className="inline-flex items-center rounded-md border border-fuchsia-300/30 bg-fuchsia-300/10 px-2 py-1 text-[11px] font-black text-fuchsia-100">
                预测辅助分 {ranking.prediction_sort_score}
              </span>
            ) : null}
            {ranking.rank_in_available_pool !== undefined &&
              ranking.rank_in_available_pool !== null ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                候选池排名 #{ranking.rank_in_available_pool}
              </span>
            ) : null}
            {ranking.score_gap_to_next !== undefined &&
              ranking.score_gap_to_next !== null ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                分差 {ranking.score_gap_to_next}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {market ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
            选秀行情
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {market.expected_pick !== undefined && market.expected_pick !== null ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                外部预测 #{market.expected_pick}
              </span>
            ) : null}
            {market.selected_pick !== undefined && market.selected_pick !== null ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                实际选择 #{market.selected_pick}
              </span>
            ) : null}
            {market.market_pick_delta !== undefined &&
              market.market_pick_delta !== null ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                与行情差异 {formatMarketDelta(market.market_pick_delta) ?? market.market_pick_delta}
              </span>
            ) : null}
            {market.alignment_label ? (
              <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
                {marketAlignmentLabel(market.alignment_label)}
              </span>
            ) : null}
          </div>
          {market.alignment_notes && market.alignment_notes.length > 0 ? (
            <p className="mt-2 text-[11px] leading-5 text-court-muted">
              {market.alignment_notes[0]}
            </p>
          ) : null}
        </div>
      ) : null}

      {risk && (risk.risk_flags?.length || risk.diagnostics_warnings?.length) ? (
        <div className="rounded-md border border-amber-300/30 bg-amber-300/[0.07] p-3">
          <p className="text-[11px] font-black uppercase tracking-[0.12em] text-amber-200">
            Risk Evidence
          </p>
          <ul className="mt-2 grid gap-1 text-[11px] font-bold leading-5 text-amber-100">
            {(risk.risk_flags ?? []).map((flag, index) => (
              <li key={`flag-${index}`}>· {flag}</li>
            ))}
            {(risk.diagnostics_warnings ?? []).map((warning, index) => (
              <li key={`warn-${index}`}>· {warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {conflict && (conflict.market_delta_conflict || conflict.notes?.length) ? (
        <div className="rounded-md border border-red-300/30 bg-red-300/[0.07] p-3">
          <p className="text-[11px] font-black uppercase tracking-[0.12em] text-red-200">
            Conflict Evidence
          </p>
          <ul className="mt-2 grid gap-1 text-[11px] font-bold leading-5 text-red-100">
            {conflict.market_delta_conflict ? (
              <li>· 与行情差异触发冲突阈值</li>
            ) : null}
            {(conflict.notes ?? []).map((note, index) => (
              <li key={`conflict-${index}`}>· {note}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {sufficiency ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
            Evidence Sufficiency
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {sufficiency.level ? (
              <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
                等级 {sufficiency.level}
              </span>
            ) : null}
            {sufficiency.missing_fields && sufficiency.missing_fields.length > 0 ? (
              <span className="inline-flex items-center rounded-md border border-amber-300/30 bg-amber-300/10 px-2 py-1 text-[11px] font-bold text-amber-100">
                缺失字段 {sufficiency.missing_fields.length}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      <RetrievedEvidenceList items={evidence.retrieved_evidence} />
      <CitationList citations={evidence.citations} />
    </div>
  );
}

function RetrievedEvidenceList({ items }: { items: RetrievedEvidence[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
        <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
          Retrieved Evidence
        </p>
        <p className="mt-2 text-[11px] leading-5 text-court-muted">
          暂无人工备注或外部检索证据；当前仅展示结构化证据。
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
      <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
        Retrieved Evidence
      </p>
      <div className="mt-2 grid gap-2">
        {items.map((item, index) => {
          const isManualNote = item.source_type === "manual_note";
          return (
            <div
              className="rounded-md border border-white/10 bg-white/[0.025] p-2"
              key={`retrieved-${index}`}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                {isManualNote ? (
                  <span className="inline-flex items-center rounded-md border border-fuchsia-300/40 bg-fuchsia-300/10 px-2 py-0.5 text-[10px] font-black text-fuchsia-100">
                    人工备注｜只读证据，不参与评分
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-bold text-court-text">
                    {item.source_type}
                  </span>
                )}
                {item.confidence !== undefined && item.confidence !== null ? (
                  <span className="text-[10px] font-bold text-court-muted">
                    可信度 {Math.round(item.confidence * 100)}%
                  </span>
                ) : null}
                {item.date ? (
                  <span className="text-[10px] font-bold text-court-muted">
                    {item.date}
                  </span>
                ) : null}
              </div>
              {item.title ? (
                <p className="mt-1 text-[11px] font-black text-court-text">
                  {item.title}
                </p>
              ) : null}
              <p className="mt-1 text-[11px] leading-5 text-court-muted">
                {item.excerpt}
              </p>
              {item.relevance_reason ? (
                <p className="mt-1 text-[10px] leading-4 text-court-muted/80">
                  相关性：{item.relevance_reason}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CitationList({ citations }: { citations: EvidenceCitation[] }) {
  if (citations.length === 0) {
    return null;
  }

  return (
    <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
      <p className="text-[11px] font-black uppercase tracking-[0.12em] text-court-line">
        Citations
      </p>
      <div className="mt-2 grid gap-1.5">
        {citations.map((citation, index) => {
          const isManualNote =
            citation.evidence_source_type === "manual_note";
          return (
            <div
              className="flex flex-wrap items-center gap-1.5 text-[10px] font-bold"
              key={`citation-${index}`}
            >
              {isManualNote ? (
                <span className="inline-flex items-center rounded-md border border-fuchsia-300/40 bg-fuchsia-300/10 px-2 py-0.5 text-[10px] font-black text-fuchsia-100">
                  人工备注｜只读证据，不参与评分
                </span>
              ) : (
                <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-bold text-court-text">
                  {citation.evidence_source_type ?? citation.source_type ?? "source"}
                </span>
              )}
              {citation.title ? (
                <span className="text-court-text">{citation.title}</span>
              ) : null}
              {citation.author ? (
                <span className="text-court-muted">· {citation.author}</span>
              ) : null}
              {citation.date ? (
                <span className="text-court-muted">· {citation.date}</span>
              ) : null}
              {citation.url ? (
                <a
                  className="text-sky-200 underline-offset-2 hover:underline"
                  href={citation.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  来源
                </a>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// RAG-v0-M3.2-A: Read-only mock explanation panel.
// This panel calls ONLY POST /api/evidence/pick/explanation/mock — never the
// real explanation endpoint.  The explanation is display-only: it never
// feeds back into ranking / scoring / selection.  If the mock call fails,
// we surface an error and do NOT fall back to the real endpoint or re-run
// simulation.  The panel is intentionally not a chat box — there is no
// prompt input and no toggle to enable a real provider.
type ExplanationState = {
  loading: boolean;
  error?: string;
  data?: PickExplanation;
};

// RAG-v0-M3.2-D: User-facing copy polish.  These constants and helpers only
// affect the *display* layer — backend data, schema, endpoints, and types are
// not touched.  Technical terms that leak through the mock explanation text
// are sanitized to plain Chinese for the user; the underlying API payload
// keeps its original snake_case field names.
const EXPLANATION_SAFETY_TEXT =
  "这段说明只用于帮助你理解本次选择，不会改变选中的球员、评分或排序结果。";

const EXPLANATION_SAFETY_NOTE_TEXT =
  "当前为稳定演示解释，不调用真实 AI 服务。";

// Display-only translation for technical terms that may appear in the mock
// explanation text.  We do NOT modify the backend payload — this is a pure
// display sanitize.  Word boundaries (\b) prevent partial replacements
// inside other identifiers (e.g. "provider_foo" stays intact).
const EXPLANATION_TERM_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\bPickEvidencePackage\b/g, "当前证据包"],
  [/\bprediction_sort_score\b/g, "预测参考分"],
  [/\bfinal_score\b/g, "综合评分"],
  [/\bmock explanation\b/gi, "稳定演示解释"],
  [/\bLLM\b/g, "解释模型"],
  [/\bprovider\b/g, "AI 服务"],
  [/明显高于市场/g, "明显比行情预测更早被选"],
  [/高于市场/g, "比行情预测更早被选"],
  [/明显低于市场/g, "明显比行情预测更晚被选"],
  [/低于市场/g, "比行情预测更晚被选"],
  [/市场预计/g, "外部预测"],
  [/市场偏差/g, "与行情差异"],
  [/市场顺位偏差/g, "与行情差异"],
  [/市场参考/g, "选秀行情"],
  [/市场上下文/g, "选秀行情"],
];

function sanitizeExplanationText(text: string): string {
  let result = text;
  for (const [pattern, replacement] of EXPLANATION_TERM_REPLACEMENTS) {
    result = result.replace(pattern, replacement);
  }
  return result;
}

// Friendly display titles for known citation_refs source_ids.  These are
// display labels only — they do NOT fabricate citation metadata.  If a ref
// matches a real citation, the matched citation's title takes priority over
// this friendly label.  If a ref is unmatched, the friendly label (when
// available) is shown as the main label, with "未匹配到来源详情" as a
// secondary notice and the raw ref kept as weak small text.
const CITATION_REF_FRIENDLY_TITLES: Record<string, string> = {
  consensus_reference: "球员选秀预测",
  market_projection: "球员选秀预测",
  consensus_mock: "球队选择预测",
  team_projection: "球队选择预测",
};

function ExplanationPanel({ evidence }: { evidence: PickEvidencePackage }) {
  const [state, setState] = useState<ExplanationState>({ loading: false });

  async function handleGenerateExplanation() {
    if (state.loading) {
      return;
    }
    setState({ loading: true });
    try {
      const explanation = await fetchPickExplanationMock(evidence);
      setState({ loading: false, data: explanation });
    } catch (err) {
      setState({
        loading: false,
        error: formatApiError(
          err,
          "解释生成失败；已保留结构化证据包，选人结果不受影响。",
        ),
      });
    }
  }

  return (
    <div className="mt-3 rounded-md border border-fuchsia-300/25 bg-fuchsia-300/[0.04] px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-black uppercase tracking-[0.16em] text-fuchsia-200">
          选人解释
          <span className="ml-1.5 text-[10px] font-bold text-fuchsia-200/60">
            Explanation
          </span>
        </p>
        <button
          className="h-8 rounded-md border border-fuchsia-300/40 bg-court-black px-3 text-[11px] font-black uppercase tracking-[0.12em] text-fuchsia-100 transition hover:border-fuchsia-300 hover:bg-fuchsia-300/10 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={state.loading || state.data !== undefined}
          onClick={handleGenerateExplanation}
          type="button"
        >
          {state.loading
            ? "正在生成解释..."
            : state.data
              ? "已生成解释"
              : "生成解释"}
        </button>
      </div>
      <p className="mt-1 text-[11px] leading-5 text-court-muted">
        点击「生成解释」查看本次选择的简明说明。当前解释为稳定演示版本，不调用真实 AI 服务，也不会改变选人结果。
      </p>

      {state.loading ? (
        <p className="mt-2 rounded-md border border-white/10 bg-court-black/60 px-3 py-2 text-xs leading-5 text-court-muted">
          正在生成解释...
        </p>
      ) : null}

      {!state.loading && state.error ? (
        <p className="mt-2 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-200">
          {state.error}
        </p>
      ) : null}

      {!state.loading && !state.error && !state.data ? (
        <p className="mt-2 rounded-md border border-white/10 bg-court-black/60 px-3 py-2 text-xs leading-5 text-court-muted">
          还没有生成解释。点击「生成解释」查看为什么选择这名球员。
        </p>
      ) : null}

      {!state.loading && state.data ? (
        <ExplanationView explanation={state.data} citations={evidence.citations} />
      ) : null}
    </div>
  );
}

function ExplanationView({
  explanation,
  citations,
}: {
  explanation: PickExplanation;
  citations: EvidenceCitation[];
}) {
  // Build a lookup keyed by source_id / title / url so a citation_ref can
  // match an existing citation via any of these three fields.  We never
  // fabricate citations: if a ref doesn't match any key, we show the raw
  // ref string plus an explicit "未匹配 citation metadata" notice.
  const citationLookup = new Map<string, EvidenceCitation>();
  for (const citation of citations) {
    if (citation.source_id) {
      citationLookup.set(citation.source_id, citation);
    }
    if (citation.title) {
      citationLookup.set(citation.title, citation);
    }
    if (citation.url) {
      citationLookup.set(citation.url, citation);
    }
  }

  return (
    <div className="mt-3 grid gap-3 text-xs leading-5 text-court-muted">
      {/* Lock badges — always shown, decision boundary is fixed.
          RAG-v0-M3.2-D: copy is now user-facing; technical phrasing
          like "LLM 可改写决策：否" is removed. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center rounded-md border border-court-line/30 bg-court-line/10 px-2 py-1 text-[11px] font-black text-court-line">
          结果已锁定
        </span>
        <span className="inline-flex items-center rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-bold text-court-text">
          不会改选人
        </span>
        <span className="inline-flex items-center rounded-md border border-fuchsia-300/30 bg-fuchsia-300/10 px-2 py-1 text-[11px] font-black text-fuchsia-100">
          稳定演示解释
        </span>
      </div>

      {/* Summary — top of the explanation. */}
      <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
        <p className="text-[11px] font-black tracking-[0.12em] text-court-line">
          为什么选他
          <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
            Summary
          </span>
        </p>
        <p className="mt-2 text-xs leading-6 text-court-text">
          {sanitizeExplanationText(explanation.summary)}
        </p>
      </div>

      {/* Key reasons — list. */}
      {explanation.key_reasons.length > 0 ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black tracking-[0.12em] text-court-line">
            主要原因
            <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
              Key Reasons
            </span>
          </p>
          <ul className="mt-2 grid gap-1.5">
            {explanation.key_reasons.map((reason, index) => (
              <li
                className="flex gap-2 text-[11px] leading-5 text-court-text"
                key={`reason-${index}`}
              >
                <span aria-hidden="true" className="text-court-line">
                  ·
                </span>
                <span>{sanitizeExplanationText(reason)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Market context — only if present. */}
      {explanation.market_context ? (
        <div className="rounded-md border border-sky-300/20 bg-sky-300/[0.05] p-3">
          <p className="text-[11px] font-black tracking-[0.12em] text-sky-200">
            选秀行情
            <span className="ml-1.5 text-[10px] font-bold text-sky-200/60">
              Draft Outlook
            </span>
          </p>
          <p className="mt-2 text-[11px] leading-5 text-court-text">
            {sanitizeExplanationText(explanation.market_context)}
          </p>
        </div>
      ) : null}

      {/* Risk summary — warning style if present. */}
      {explanation.risk_summary ? (
        <div className="rounded-md border border-amber-300/30 bg-amber-300/[0.07] p-3">
          <p className="text-[11px] font-black tracking-[0.12em] text-amber-200">
            风险提示
            <span className="ml-1.5 text-[10px] font-bold text-amber-200/60">
              Risk Summary
            </span>
          </p>
          <p className="mt-2 text-[11px] leading-5 text-amber-100">
            {sanitizeExplanationText(explanation.risk_summary)}
          </p>
        </div>
      ) : null}

      {/* Evidence notes — list. */}
      {explanation.evidence_notes.length > 0 ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black tracking-[0.12em] text-court-line">
            补充依据
            <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
              Evidence Notes
            </span>
          </p>
          <ul className="mt-2 grid gap-1.5">
            {explanation.evidence_notes.map((note, index) => (
              <li
                className="flex gap-2 text-[11px] leading-5 text-court-text"
                key={`note-${index}`}
              >
                <span aria-hidden="true" className="text-court-line">
                  ·
                </span>
                <span>{sanitizeExplanationText(note)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Limitations — must always show; fallback text if empty. */}
      <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
        <p className="text-[11px] font-black tracking-[0.12em] text-court-line">
          需要注意
          <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
            Limitations
          </span>
        </p>
        {explanation.limitations.length > 0 ? (
          <ul className="mt-2 grid gap-1.5">
            {explanation.limitations.map((limitation, index) => (
              <li
                className="flex gap-2 text-[11px] leading-5 text-court-text"
                key={`limitation-${index}`}
              >
                <span aria-hidden="true" className="text-amber-300">
                  ·
                </span>
                <span>{sanitizeExplanationText(limitation)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[11px] leading-5 text-court-muted">
            暂无额外注意事项。
          </p>
        )}
      </div>

      {/* Citation refs — user-friendly "参考依据".
          RAG-v0-M3.2-D: priority is the matched citation's title (or a
          friendly display label for known source_ids).  The raw source_id
          is kept as weak small text ("来源标识：...") so it is still
          available for debugging without dominating the UI.  Unmatched
          refs never fabricate a title/url — they show "未匹配到来源详情"
          plus the raw ref as weak small text. */}
      {explanation.citation_refs.length > 0 ? (
        <div className="rounded-md border border-white/10 bg-court-black/60 p-3">
          <p className="text-[11px] font-black tracking-[0.12em] text-court-line">
            参考依据
            <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
              Citation Refs
            </span>
          </p>
          <div className="mt-2 grid gap-2">
            {explanation.citation_refs.map((ref, index) => {
              const matched = citationLookup.get(ref);
              const friendlyTitle = CITATION_REF_FRIENDLY_TITLES[ref];
              const displayTitle = matched?.title ?? friendlyTitle ?? null;
              const isUnmatched = !matched;
              return (
                <div
                  className="flex flex-col gap-0.5 text-[11px] leading-5"
                  key={`ref-${index}`}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    {displayTitle ? (
                      <span className="font-black text-court-text">
                        {displayTitle}
                      </span>
                    ) : null}
                    {matched?.url ? (
                      <a
                        className="text-sky-200 underline-offset-2 hover:underline"
                        href={matched.url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        查看来源
                      </a>
                    ) : null}
                    {isUnmatched ? (
                      <span className="text-[10px] font-bold text-amber-300/80">
                        未匹配到来源详情
                      </span>
                    ) : null}
                  </div>
                  <span className="text-[10px] font-bold text-court-muted/70">
                    来源标识：{ref}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Fixed safety notice — always shown.
          RAG-v0-M3.2-D: copy is user-facing; the "不会改变选中的球员、
          评分或排序" guarantee is preserved verbatim in meaning. */}
      <div className="rounded-md border border-court-line/30 bg-court-line/[0.06] p-3">
        <p className="text-[10px] font-black tracking-[0.16em] text-court-line">
          说明
          <span className="ml-1.5 text-[10px] font-bold text-court-line/60">
            Safety
          </span>
        </p>
        <p className="mt-1 text-[11px] leading-5 text-court-text">
          {EXPLANATION_SAFETY_TEXT}
        </p>
        <p className="mt-2 text-[11px] leading-5 text-fuchsia-100">
          {EXPLANATION_SAFETY_NOTE_TEXT}
        </p>
      </div>
    </div>
  );
}
