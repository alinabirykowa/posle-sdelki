import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  Clock3,
  Flag,
  Info,
  RotateCcw,
  TrendingDown,
  Wallet,
} from "lucide-react";
import type { Session } from "../types";
import { assistanceLabel, trainingSummary } from "../training";
import { money, number, plural } from "./UI";
import { TermsSummary } from "./SessionPage";
import { UtteranceReviewCards } from "./UtteranceReviewCards";
import "../review-design.css";
import "../mentor-design.css";

export function ResultView({
  session,
  busy,
  error,
  onRetry,
  embedded = false,
}: {
  session: Session;
  busy: boolean;
  error: string;
  onRetry: () => void;
  embedded?: boolean;
}) {
  const feedback = session.feedback;
  if (!feedback)
    return (
      <div className="error-state">
        <h1>Разбор ещё не готов</h1>
        <p>Обновите страницу, чтобы получить сохранённый результат.</p>
        <a href="#/history" className="button secondary">
          Мои попытки
        </a>
      </div>
    );
  const metrics = feedback.metrics;
  const agreed = feedback.outcome !== "no_agreement";
  const success =
    feedback.outcome === "feasible" || feedback.outcome === "agreement";
  const conversationPractice =
    session.scenario.practice_model === "conversation";
  const maxHours = Math.max(
    metrics?.required_hours || 0,
    metrics?.available_hours || 0,
    1,
  );
  const capacityWidth = ((metrics?.available_hours || 0) / maxHours) * 100;
  const workloadWidth = ((metrics?.required_hours || 0) / maxHours) * 100;
  const Heading = embedded ? "h2" : "h1";
  return (
    <div className="result-page page-enter">
      <div className="session-nav">
        <a href="#/" className="back-link">
          <ArrowLeft size={16} />К практике
        </a>
        <span className="saved-label">
          <CheckCheck size={15} />
          Разбор сохранён
        </span>
      </div>
      <section className={`result-hero ${feedback.outcome}`}>
        <div className="result-hero-copy">
          <div className="eyebrow">
            <span className="report-status-dot" />
            РАЗГОВОР ЗАВЕРШЁН · ВАШ РАЗБОР
          </div>
          <Heading>{feedback.title}</Heading>
          <p>{feedback.summary}</p>
          <span className="practice-assistance">
            {assistanceLabel(session)}
          </span>
          <div className="result-meta">
            <span>{session.scenario.title}</span>
            <span>·</span>
            <span>
              {session.turns}{" "}
              {plural(session.turns, ["реплика", "реплики", "реплик"])}
            </span>
          </div>
          {session.training_config && (
            <div className="result-training-context">
              {trainingSummary(session)}
              <span>
                {session.difficulty === "hard"
                  ? "Сложный уровень"
                  : "Обычный уровень"}
                {session.training_config.response_seconds > 0 &&
                  ` · ${session.training_config.response_seconds} сек на ответ`}
              </span>
            </div>
          )}
        </div>
        <div className="report-outcome" aria-hidden="true">
          <span className="report-outcome-kicker">РЕЗУЛЬТАТ РЕШЕНИЯ</span>
          {success ? (
            <Check size={56} strokeWidth={1.7} />
          ) : agreed ? (
            <span className="report-outcome-warning">!</span>
          ) : (
            <Flag size={48} strokeWidth={1.7} />
          )}
          <div className="report-outcome-label">
            {success
              ? conversationPractice
                ? "Договорились"
                : "Можно выполнить"
              : agreed
                ? "Есть противоречие"
                : "Без соглашения"}
          </div>
        </div>
      </section>
      <UtteranceReviewCards session={session} />
      {agreed && metrics && (
        <>
          <section
            className="result-metrics"
            aria-label="Последствия договорённости"
          >
            <article>
              <div className="metric-title">
                <Clock3 size={17} />
                01 / Срок
              </div>
              <strong className={metrics.delay_days > 0 ? "risk-text" : ""}>
                {metrics.delay_days > 0
                  ? `+${number(metrics.delay_days)}`
                  : "В срок"}
                {metrics.delay_days > 0 && <span> раб. дн.</span>}
              </strong>
              <p>
                {metrics.delay_days > 0
                  ? "не хватает при заданной мощности"
                  : `нужно ${number(metrics.required_days)} из ${session.proposal?.terms?.deadline_days} рабочих дней`}
              </p>
            </article>
            <article>
              <div className="metric-title">
                <TrendingDown size={17} />
                02 / Объём работы
              </div>
              <strong>
                {number(metrics.required_hours)}
                <span> часов</span>
              </strong>
              <p>
                {number(metrics.available_hours)} часов доступно до обещанной
                даты
              </p>
            </article>
            <article>
              <div className="metric-title">
                <Wallet size={17} />
                03 / После прямых затрат
              </div>
              <strong
                className={
                  metrics.contribution < (metrics.minimum_contribution || 0)
                    ? "risk-text"
                    : ""
                }
              >
                {money(metrics.contribution)}
              </strong>
              <p>
                исходно {money(metrics.baseline_contribution)} · не чистая
                прибыль
              </p>
            </article>
          </section>
          <section className="execution-section">
            <div className="section-heading">
              <div>
                <div className="eyebrow subtle">ПРОВЕРКА РЕАЛЬНОСТЬЮ</div>
                <h2>Поместится ли обещанное?</h2>
              </div>
              <span
                className={`result-chip ${metrics.feasible ? "good" : "bad"}`}
              >
                {metrics.feasible ? (
                  <>
                    <Check size={15} />
                    Условия выполнимы
                  </>
                ) : (
                  "Нужен другой пакет"
                )}
              </span>
            </div>
            <div className="execution-chart">
              <div className="chart-row">
                <span>Ресурс команды</span>
                <div className="chart-track">
                  <div
                    className="chart-bar capacity"
                    style={{ width: `${capacityWidth}%` }}
                  >
                    {number(metrics.available_hours)} ч
                  </div>
                </div>
              </div>
              <div className="chart-row">
                <span>Ваше обязательство</span>
                <div className="chart-track">
                  <div
                    className={`chart-bar workload ${metrics.overflow_hours > 0 ? "overflow" : ""}`}
                    style={{ width: `${workloadWidth}%` }}
                  >
                    {number(metrics.required_hours)} ч
                  </div>
                </div>
              </div>
              <div className="chart-legend">
                <span>
                  <i className="capacity-key" />
                  Доступно до срока
                </span>
                <span>
                  <i
                    className={
                      metrics.overflow_hours > 0 ? "over-key" : "work-key"
                    }
                  />
                  Согласованный объём
                </span>
              </div>
            </div>
            {metrics.violation_reasons &&
              metrics.violation_reasons.length > 0 && (
                <div className="violations">
                  {metrics.violation_reasons.map((reason) => (
                    <p key={reason}>
                      <Info size={17} />
                      {reason}
                    </p>
                  ))}
                </div>
              )}
            <p className="fine-print">
              Учебная модель: трудоёмкость и мощность заданы в брифе. Расчёт не
              учитывает налоги, накладные расходы и неопределённость реального
              проекта.
            </p>
          </section>
        </>
      )}
      {!conversationPractice && (
        <section className="moments-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow subtle">ОТ РЕПЛИКИ К РЕЗУЛЬТАТУ</div>
              <h2>Что повлияло на результат</h2>
            </div>
            <span className="section-note">
              Конкретные решения вместо общей оценки
            </span>
          </div>
          <div className="moment-grid">
            {feedback.moments.map((moment, i) => (
              <article className="moment-card" key={`${moment.title}-${i}`}>
                <span className="moment-number">0{i + 1}</span>
                <h3>{moment.title}</h3>
                <blockquote>«{moment.quote}»</blockquote>
                <p>{moment.explanation}</p>
              </article>
            ))}
          </div>
          {feedback.moments.length === 0 && (
            <div className="empty-moments">
              <MessageIcon />
              <p>
                Разговор был коротким. Попробуйте задать клиенту вопрос и
                обсудить условия — так в разборе появятся конкретные эпизоды.
              </p>
            </div>
          )}
        </section>
      )}
      {feedback.behaviors && (
        <section
          className="behavior-section"
          aria-label="Переговорные действия"
        >
          <div className="section-heading">
            <div>
              <div className="eyebrow subtle">ПО НАБЛЮДАЕМЫМ ДЕЙСТВИЯМ</div>
              <h2>Разбор ваших действий</h2>
            </div>
          </div>
          <p className="fine-print">
            Смотрим только на эту попытку. Отсутствие примера не означает, что
            вы не владеете навыком.
          </p>
          <div className="behavior-list">
            {feedback.behaviors.map((behavior) => (
              <article className="behavior-row" key={behavior.id}>
                <div className="behavior-heading">
                  <h3>{behavior.label}</h3>
                  <span className={`behavior-status ${behavior.status}`}>
                    {behavior.status === "observed"
                      ? "Есть пример"
                      : "Пока нет примера"}
                  </span>
                </div>
                <p>{behavior.explanation}</p>
                {behavior.evidence.map((evidence) => (
                  <blockquote key={`${evidence.message_id}-${evidence.quote}`}>
                    «{evidence.quote}»
                  </blockquote>
                ))}
              </article>
            ))}
          </div>
        </section>
      )}
      <section className="next-step">
        <div className="next-spark" aria-hidden="true">
          <ArrowUpRight size={28} strokeWidth={1.6} />
        </div>
        <div>
          <span className="eyebrow">ОДНО ДЕЙСТВИЕ ДЛЯ СЛЕДУЮЩЕЙ ПОПЫТКИ</span>
          <h3>{feedback.next_step}</h3>
          <p>
            Повтор начнётся с тех же условий. Измените подход и сравните
            результат в разделе «Мой прогресс». Попытки с подсказками и без них
            учитываются отдельно.
          </p>
        </div>
        <button className="button primary" disabled={busy} onClick={onRetry}>
          <RotateCcw size={17} />
          {busy ? "Готовим попытку…" : "Попробовать иначе"}
        </button>
      </section>
      {session.proposal && agreed && (
        <details className="result-details">
          <summary>
            Зафиксированные условия
            <ChevronIcon />
          </summary>
          <div>
            {session.proposal.terms ? (
              <>
                <TermsSummary terms={session.proposal.terms} />
                <p>{session.proposal.terms.scope}</p>
              </>
            ) : (
              <>
                <h3>{session.proposal.label}</h3>
                <p>{session.proposal.description || session.proposal.reason}</p>
              </>
            )}
          </div>
        </details>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <footer className="page-footer">
        <a href="#/progress">
          Мой прогресс <ArrowUpRight size={16} />
        </a>
        <a href="#/">
          Настроить тренировку <ArrowRight size={16} />
        </a>
      </footer>
    </div>
  );
}
function ChevronIcon() {
  return <span aria-hidden="true">＋</span>;
}
function MessageIcon() {
  return (
    <span className="empty-icon" aria-hidden="true">
      …
    </span>
  );
}
