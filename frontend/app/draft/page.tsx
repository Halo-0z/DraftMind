"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AgentAskResponse,
  askAgent,
  getProspects,
  getRecommendation,
  getTeamPicks,
  getTeamRoster,
  getTeams,
  LockedPick,
  NewsArticle,
  Prospect,
  Recommendation,
  refreshNews,
  RosterPlayer,
  ScoreBreakdown,
  searchNews,
  simulateDraft,
  Simulation,
  SimulatedPick,
  Team,
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
  const [news, setNews] = useState<NewsArticle[]>([]);
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
        rounds: 1,
        limit: 30,
        evaluate_trades: true,
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

          <RosterPanel isLoading={isLoadingRoster} roster={roster} />

          <div className="mt-5 rounded-md border border-white/10 bg-court-panel p-5">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-court-muted">
              Full board
            </p>
            <p className="mt-3 text-sm leading-6 text-court-muted">
              按选秀顺位逐签模拟，已选球员会从后续候选池移除。
            </p>

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

function SimulationBoard({ simulation }: { simulation: Simulation }) {
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
                        if (isMarketContext) {
                          return (
                            <li
                              key={line}
                              className="flex items-start gap-2 border-l-2 border-amber-300/40 bg-amber-300/[0.05] py-1 pl-3 pr-2"
                            >
                              <span className="mt-0.5 inline-block shrink-0 rounded border border-amber-300/40 bg-amber-300/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-200">
                                只读市场上下文
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
                    <p>
                      Live board:{" "}
                      {pick.candidate_board
                        .slice(0, 5)
                        .map(
                          (candidate) =>
                            `${candidate.prospect.name} (${candidate.scores.final_score})`,
                        )
                        .join(", ")}
                    </p>
                  </div>
                </details>
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
            来自 ESPN、Sportando、虎扑篮球资讯等权威数据源；聚焦交易/选秀/伤病动态，供 GM 决策参考。
          </p>
        </div>
        <button
          className="h-11 rounded-md border border-court-line/50 bg-court-black px-4 text-sm font-black text-court-line transition hover:border-court-line hover:bg-court-line hover:text-court-black disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isRefreshing}
          onClick={onRefresh}
          type="button"
        >
          {isRefreshing ? "刷新中..." : "刷新新闻"}
        </button>
      </div>

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
    </section>
  );
}
