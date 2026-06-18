import { ThemeToggle } from "./components/ThemeToggle";

export default function Home() {
  return (
    <main className="relative min-h-screen bg-court-black">
      <div className="absolute right-6 top-6 z-10">
        <ThemeToggle />
      </div>
      <section className="mx-auto flex min-h-screen w-full max-w-6xl flex-col justify-center px-6 py-16">
        <div className="max-w-3xl">
          <p className="mb-5 inline-flex rounded-full border border-court-line/35 bg-court-line/10 px-4 py-2 text-sm font-semibold tracking-[0.08em] text-court-line">
            Draft code 24
          </p>
          <h1 className="text-5xl font-semibold leading-tight tracking-tight text-court-text sm:text-7xl">
            DraftMind
          </h1>
          <p className="mt-5 max-w-2xl text-2xl font-semibold text-court-text sm:text-3xl">
            NBA 选秀决策智能体
          </p>
          <p className="mt-6 max-w-2xl text-base leading-8 text-court-muted sm:text-lg">
            模拟球队经理，基于球队需求、候选新秀数据、球探报告和可解释评分，给出更像真实管理层的选秀推荐。
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <a
              href="/draft"
              className="rounded-full bg-court-line px-6 py-3 text-base font-semibold text-court-black transition active:scale-95"
            >
              开始模拟选秀
            </a>
            <a
              href="http://127.0.0.1:8000/api/health"
              className="rounded-full border border-court-border px-6 py-3 text-base font-semibold text-court-text transition hover:border-court-line/70 hover:text-court-line active:scale-95"
            >
              API Health
            </a>
          </div>
        </div>

        <div className="mt-16 grid gap-4 md:grid-cols-3">
          {[
            ["数据先行", "所有推荐先从结构化数据和评分引擎产生。"],
            ["规则兜底", "没有 API Key 时也能用 mock explanation 完整演示。"],
            ["Agent 解释", "AI 负责解释推荐、风险与备选，不凭空编数据。"],
          ].map(([title, body]) => (
            <article
              key={title}
              className="rounded-md border border-court-border bg-court-panel/80 p-5"
            >
              <h2 className="text-lg font-semibold text-court-line">{title}</h2>
              <p className="mt-3 text-sm leading-6 text-court-muted">{body}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
