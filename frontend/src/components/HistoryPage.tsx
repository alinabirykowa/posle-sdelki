import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  GitCompareArrows,
  History,
  Play,
} from "lucide-react";
import type { Session } from "../types";
import {
  assistanceCategory,
  assistanceLabel,
  sameTrainingContext,
  trainingSummary,
} from "../training";
import { Modal, money, plural } from "./UI";
import "../review-design.css";
const date = (iso: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));

export function HistoryPage({
  sessions,
  loading,
  error,
  onRefresh,
  onOpen,
  onPractice,
  authenticated = false,
}: {
  sessions: Session[];
  loading: boolean;
  error: string;
  onRefresh: () => Promise<void>;
  onOpen: (s: Session) => void;
  onPractice: () => void;
  authenticated?: boolean;
}) {
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [compare, setCompare] = useState(false);
  const unavailableEmpty = sessions.length === 0 && (loading || !!error);
  const completedCount = sessions.filter(
    (s) => s.status === "completed",
  ).length;
  const activeCount = sessions.filter((s) => s.status === "active").length;
  const selectedSessions = sessions.filter((s) => selected.includes(s.id));
  const visible = sessions.filter(
    (s) => filter === "all" || s.status === filter,
  );
  function toggle(id: string) {
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((x) => x !== id)
        : [...previous, id].slice(-2),
    );
  }
  return (
    <div className="history-page page-enter">
      <a href="#/progress" className="back-link">
        <ArrowLeft size={16} aria-hidden="true" /> Личный кабинет
      </a>
      <div className="page-eyebrow">
        <span>ВАША ПРАКТИКА</span>
        <span>
          {authenticated
            ? "СОХРАНЕНО В ВАШЕМ АККАУНТЕ"
            : "СОХРАНЕНО В ЭТОМ БРАУЗЕРЕ"}
        </span>
      </div>
      <div className="history-heading">
        <div>
          <h1>Мои разговоры</h1>
          <p>
            Вернитесь к разговору, сравните подходы и выберите, что
            потренировать в следующий раз.
          </p>
        </div>
        {!unavailableEmpty && (
          <dl className="history-counts" aria-label="Ваши попытки">
            <div>
              <dt>
                {plural(completedCount, ["разбор", "разбора", "разборов"])}
              </dt>
              <dd>{String(completedCount).padStart(2, "0")}</dd>
            </div>
            <div>
              <dt>в процессе</dt>
              <dd>{String(activeCount).padStart(2, "0")}</dd>
            </div>
          </dl>
        )}
      </div>
      {loading && (
        <p className="history-hint" role="status">
          {sessions.length ? "Обновляем историю…" : "Загружаем ваши попытки…"}
        </p>
      )}
      {error && (
        <div className="history-load-notice" role="alert">
          <p>
            <strong>Не удалось загрузить историю</strong>
            {error}
            {sessions.length > 0 && (
              <span>Ниже — данные последней успешной загрузки.</span>
            )}
          </p>
          <button className="button secondary" onClick={() => void onRefresh()}>
            Повторить загрузку
          </button>
        </div>
      )}
      {!unavailableEmpty && (
        <div className="history-toolbar">
          <div className="segmented">
            <button
              className={filter === "all" ? "selected" : ""}
              aria-pressed={filter === "all"}
              onClick={() => setFilter("all")}
            >
              Все
            </button>
            <button
              className={filter === "completed" ? "selected" : ""}
              aria-pressed={filter === "completed"}
              onClick={() => setFilter("completed")}
            >
              С разбором
            </button>
            <button
              className={filter === "active" ? "selected" : ""}
              aria-pressed={filter === "active"}
              onClick={() => setFilter("active")}
            >
              В процессе
            </button>
          </div>
          <button
            className="button secondary"
            disabled={selected.length !== 2}
            onClick={() => setCompare(true)}
          >
            <GitCompareArrows size={17} />
            Сравнить {selected.length > 0 && `(${selected.length}/2)`}
          </button>
        </div>
      )}
      {sessions.length > 0 && (
        <p className="history-hint">
          Для сравнения отметьте две завершённые попытки с одинаковыми
          настройками и использованием подсказок. Попытки до появления учёта
          помощи доступны для просмотра, без сравнения. Здесь показаны последние
          30 разговоров.{" "}
          {authenticated
            ? "История доступна после входа с любого устройства."
            : "История хранится для этого браузера."}
        </p>
      )}
      {unavailableEmpty ? null : visible.length === 0 ? (
        <div className="history-empty">
          <div className="empty-history-art">
            <History size={37} />
            <span>01</span>
          </div>
          <h2>
            {sessions.length === 0
              ? "Ваша первая попытка впереди"
              : "Здесь пока нет попыток"}
          </h2>
          <p>
            {sessions.length === 0
              ? "Настройте деловой разговор под свою задачу, договоритесь об условиях и посмотрите, что будет после сделки."
              : "Выберите другой фильтр или начните новый разговор."}
          </p>
          <button className="button primary" onClick={onPractice}>
            Перейти к практике
            <ArrowUpRight size={18} />
          </button>
        </div>
      ) : (
        <div className="history-list" aria-label="Сохранённые попытки">
          {visible.map((session) => {
            const finished = session.status === "completed";
            const selectable =
              finished &&
              assistanceCategory(session) !== "unknown" &&
              (selected.length === 0 ||
                selected.includes(session.id) ||
                (selected.length < 2 &&
                  !!selectedSessions[0] &&
                  sameTrainingContext(session, selectedSessions[0])));
            return (
              <article
                className={`history-row ${selected.includes(session.id) ? "is-selected" : ""}`}
                key={session.id}
              >
                <label
                  className="compare-check"
                  title={
                    selectable
                      ? "Выбрать для сравнения"
                      : "Нужна завершённая попытка с теми же настройками и учётом подсказок"
                  }
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(session.id)}
                    disabled={!selectable}
                    onChange={() => toggle(session.id)}
                    aria-label={`Сравнить: ${session.scenario.title}, ${date(session.created_at)}`}
                  />
                </label>
                <div
                  className={`history-case-icon ${session.scenario.id}`}
                  aria-hidden="true"
                >
                  {session.scenario.id === "scope" ? (
                    <ArrowUpRight size={28} />
                  ) : (
                    "₽"
                  )}
                </div>
                <div className="history-row-title">
                  <strong>{session.scenario.title}</strong>
                  <span>
                    {date(session.created_at)} ·{" "}
                    {session.difficulty === "hard" ? "С вызовом" : "Обычная"} ·{" "}
                    {session.mode === "demo" ? "Демо" : "AI"}
                  </span>
                  <span>{assistanceLabel(session)}</span>
                  {session.training_config && (
                    <span className="history-training-context">
                      {trainingSummary(session)}
                    </span>
                  )}
                </div>
                <span
                  className={`history-status ${session.feedback?.outcome || "active"}`}
                >
                  {!finished ? (
                    <>
                      <Clock3 size={13} />В процессе
                    </>
                  ) : session.feedback?.outcome === "agreement" ? (
                    <>
                      <Check size={13} />
                      Договорились
                    </>
                  ) : session.feedback?.outcome === "feasible" ? (
                    <>
                      <Check size={13} />
                      Выполнимо
                    </>
                  ) : session.feedback?.outcome === "infeasible" ? (
                    "Есть противоречие"
                  ) : (
                    "Диалог сохранён"
                  )}
                </span>
                <button
                  className="history-open"
                  onClick={() => onOpen(session)}
                >
                  {finished ? "Разбор" : "Продолжить"}
                  {finished ? <ArrowRight size={17} /> : <Play size={15} />}
                </button>
              </article>
            );
          })}
        </div>
      )}
      {compare && selectedSessions.length === 2 && (
        <Modal
          title="Два подхода. Одни условия."
          onClose={() => setCompare(false)}
          wide
        >
          <p className="modal-description">
            {selectedSessions[0].scenario.title}. Исходные условия и настройки
            тренировки совпадают.
          </p>
          {selectedSessions[0].training_config && (
            <p className="comparison-training-context">
              {trainingSummary(selectedSessions[0])}
            </p>
          )}
          <div className="comparison-grid">
            {selectedSessions.map((session, i) => (
              <div className="comparison-column" key={session.id}>
                <div className="eyebrow">
                  ПОПЫТКА {i + 1} · {date(session.created_at)}
                </div>
                <h3>{session.feedback?.title}</h3>
                <p>{session.proposal?.label || "Без предложения"}</p>
                {session.scenario.practice_model === "conversation" ? (
                  <dl>
                    {(session.feedback?.behaviors || []).map((behavior) => (
                      <div key={behavior.id}>
                        <dt>{behavior.label}</dt>
                        <dd>
                          {behavior.status === "observed"
                            ? "Есть пример"
                            : "Пока нет примера"}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : session.feedback?.outcome === "no_agreement" ? (
                  <div className="compare-no-deal">
                    Соглашение не заключено. Результат исполнения не
                    рассчитывается.
                  </div>
                ) : (
                  <dl>
                    <div>
                      <dt>Согласованный объём</dt>
                      <dd>{session.feedback?.metrics?.required_hours} ч</dd>
                    </div>
                    <div>
                      <dt>Расчётная длительность</dt>
                      <dd>{session.feedback?.metrics?.required_days} дн.</dd>
                    </div>
                    <div>
                      <dt>После прямых затрат</dt>
                      <dd>
                        {money(session.feedback?.metrics?.contribution || 0)}
                      </dd>
                    </div>
                  </dl>
                )}
                <div className="comparison-tip">
                  {session.feedback?.next_step}
                </div>
                <button
                  className="button secondary full"
                  onClick={() => {
                    setCompare(false);
                    onOpen(session);
                  }}
                >
                  Открыть разбор
                  <ArrowRight size={16} />
                </button>
              </div>
            ))}
          </div>
          <p className="fine-print">
            Сравниваем только эти разговоры. Отдельная попытка не определяет ваш
            уровень навыка.
          </p>
        </Modal>
      )}
    </div>
  );
}
