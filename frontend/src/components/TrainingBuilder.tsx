import { useEffect, useRef, useState } from "react";
import {
  ArrowDownRight,
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  Clock3,
  Layers3,
  LoaderCircle,
  MessageCircle,
  Mic,
  Minus,
  Plus,
  SlidersHorizontal,
  Target,
} from "lucide-react";
import { api, errorMessage } from "../api";
import {
  clearPendingTrainingStart,
  getPendingTrainingStart,
  readPendingTrainingStart,
  type PendingTrainingStart,
} from "../recovery";
import type {
  ReplyMode,
  RouteStageId,
  Session,
  TrainingConfig,
  TrainingPreview,
} from "../types";
import { ROUTE_STAGE_GUIDANCE } from "../progress-api";
import { money } from "./UI";
import "../builder-design.css";

const DEFAULTS: TrainingConfig = {
  industry: "digital",
  topic: "scope",
  difficulty: "standard",
  tone: "reserved",
  client_role: "project_lead",
  goal: "deadline",
  duration_minutes: 10,
  format: "text",
  response_seconds: 0,
};
const INDUSTRIES = [
  {
    id: "digital",
    label: "Digital-услуги",
    detail: "Сайты и запуск продуктов",
    short: "Digital",
  },
  {
    id: "it",
    label: "IT и автоматизация",
    detail: "CRM и рабочие процессы",
    short: "IT",
  },
  {
    id: "consulting",
    label: "Консалтинг",
    detail: "Аудит и рекомендации",
    short: "Консалтинг",
  },
] as const;
const ROLES = [
  {
    id: "project_lead",
    label: "Руководитель проекта",
    detail: "Защищает результат команды",
  },
  {
    id: "business_owner",
    label: "Владелец бизнеса",
    detail: "Принимает решение о расходах",
  },
  {
    id: "procurement",
    label: "Менеджер по закупкам",
    detail: "Согласует условия с заказчиком",
  },
] as const;
const TONES = [
  {
    id: "collaborative",
    label: "Открытый",
    detail: "Готов обсуждать варианты",
    icon: ArrowLeftRight,
  },
  {
    id: "reserved",
    label: "Сдержанный",
    detail: "Ждёт конкретики и ясности",
    icon: Minus,
  },
  {
    id: "pressing",
    label: "Напористый",
    detail: "Торопит и требует уступок",
    icon: ArrowUpRight,
  },
] as const;
const GOALS = {
  scope: [
    {
      id: "deadline",
      label: "Сохранить дату",
      detail: "Готов менять состав работ",
    },
    {
      id: "full_scope",
      label: "Получить весь объём",
      detail: "Готов обсуждать срок и цену",
    },
  ],
  discount: [
    {
      id: "budget",
      label: "Уложиться в бюджет",
      detail: "Ограничена вся сумма",
    },
    {
      id: "cashflow",
      label: "Снизить первый платёж",
      detail: "Полный объём по-прежнему нужен",
    },
  ],
} as const;
const STEPS = [
  { name: "Ситуация" },
  { name: "Собеседник" },
  { name: "Практика" },
];
const DRAFT_KEY = "posle:training-configuration:v1";
const MODE_KEY = "posle:training-mode:v1";
function initialMode(): "demo" | "live" {
  try {
    return sessionStorage.getItem(MODE_KEY) === "live" ? "live" : "demo";
  } catch {
    return "demo";
  }
}
function initialConfig(): TrainingConfig {
  try {
    const value = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
    if (!value) return DEFAULTS;
    const allowed: Record<keyof TrainingConfig, readonly (string | number)[]> =
      {
        industry: ["digital", "it", "consulting"],
        topic: ["scope", "discount"],
        difficulty: ["standard", "hard"],
        tone: ["collaborative", "reserved", "pressing"],
        client_role: ["project_lead", "business_owner", "procurement"],
        goal: ["deadline", "full_scope", "budget", "cashflow"],
        duration_minutes: [5, 10, 15],
        format: ["text", "voice"],
        response_seconds: [0, 45],
      };
    if (
      !Object.entries(allowed).every(([key, options]) =>
        options.includes(value[key]),
      )
    )
      return DEFAULTS;
    if (
      !GOALS[value.topic as TrainingConfig["topic"]].some(
        (goal) => goal.id === value.goal,
      )
    )
      return DEFAULTS;
    return Object.fromEntries(
      Object.keys(DEFAULTS).map((key) => [key, value[key]]),
    ) as TrainingConfig;
  } catch {
    return DEFAULTS;
  }
}

export function TrainingBuilder({
  identityKey,
  onStart,
  liveAvailable,
  liveReplyMode = "rules",
  routeStage,
}: {
  identityKey: string;
  onStart: (session: Session) => void;
  liveAvailable: boolean;
  liveReplyMode?: ReplyMode;
  routeStage?: RouteStageId | null;
}) {
  const [config, setConfig] = useState<TrainingConfig>(initialConfig);
  const [step, setStep] = useState(0);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<TrainingPreview | null>(null);
  const [mode, setMode] = useState<"demo" | "live">(() =>
    liveAvailable ? initialMode() : "demo",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pendingStart, setPendingStart] = useState(() =>
    readPendingTrainingStart(identityKey),
  );
  const inFlight = useRef(false);
  const panel = useRef<HTMLElement>(null);
  const homeTitle = useRef<HTMLHeadingElement>(null);
  const stepTitle = useRef<HTMLHeadingElement>(null);
  const previewTitle = useRef<HTMLHeadingElement>(null);
  const mounted = useRef(false);
  const currentPanel = `${editing}:${step}:${Boolean(preview)}`;
  const previousPanel = useRef(currentPanel);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem(MODE_KEY, mode);
    } catch {
      /* The current page still retains the selected mode. */
    }
  }, [mode]);
  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(config));
    } catch {
      /* Configuration still works without storage. */
    }
  }, [config]);
  useEffect(() => {
    if (previousPanel.current === currentPanel) return;
    previousPanel.current = currentPanel;
    (editing ? (preview ? previewTitle : stepTitle) : homeTitle).current?.focus(
      {
        preventScroll: true,
      },
    );
    if (editing) {
      panel.current?.scrollIntoView({ block: "start", behavior: "instant" });
    } else {
      homeTitle.current?.scrollIntoView({
        block: "center",
        behavior: "instant",
      });
    }
  }, [currentPanel, editing, preview]);
  function update(next: Partial<TrainingConfig>) {
    if (inFlight.current) return;
    setConfig((current) => ({ ...current, ...next }));
    setError("");
  }
  function preset(topic: "scope" | "discount", pressure = false) {
    if (inFlight.current) return;
    if (pendingStart) clearPendingTrainingStart(pendingStart);
    setPendingStart(null);
    setConfig({
      ...DEFAULTS,
      topic,
      goal: topic === "scope" ? "deadline" : "budget",
      ...(pressure
        ? {
            difficulty: "hard",
            tone: "pressing",
            response_seconds: 45 as const,
          }
        : {}),
    });
    setEditing(true);
    setStep(0);
    setPreview(null);
    setError("");
    panel.current?.scrollIntoView({ block: "start", behavior: "instant" });
  }
  async function assemble() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.trainingPreview(config);
      if (mounted.current) setPreview(result);
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function start(recovery?: PendingTrainingStart) {
    if (inFlight.current || (!recovery && (!preview || pendingStart))) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    const action =
      recovery ??
      getPendingTrainingStart(
        identityKey,
        preview!.configuration,
        mode,
        undefined,
        routeStage ?? undefined,
      );
    setPendingStart(action);
    try {
      const session = await api.trainingStart(
        action.configuration,
        action.mode,
        action.id,
        action.route_stage,
      );
      clearPendingTrainingStart(action);
      if (mounted.current) {
        setPendingStart(null);
        onStart(session);
      }
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function startFresh() {
    if (inFlight.current) return;
    if (pendingStart) clearPendingTrainingStart(pendingStart);
    setPendingStart(null);
    setError("");
    setPreview(null);
    setStep(0);
    setEditing(true);
  }
  const industry = INDUSTRIES.find((x) => x.id === config.industry)!;
  const role = ROLES.find((x) => x.id === config.client_role)!;
  const tone = TONES.find((x) => x.id === config.tone)!;
  const turnLimit = { 5: 8, 10: 16, 15: 24 }[config.duration_minutes];
  const selectedRouteStage = routeStage ?? pendingStart?.route_stage;

  return (
    <div className="training-builder">
      {selectedRouteStage && (
        <section
          className="builder-route-goal"
          aria-labelledby="builder-route-goal-title"
        >
          <span>ЦЕЛЬ ЭТАПА</span>
          <h2 id="builder-route-goal-title">
            {ROUTE_STAGE_GUIDANCE[selectedRouteStage].title}
          </h2>
          <p>{ROUTE_STAGE_GUIDANCE[selectedRouteStage].goal}</p>
          <small>Эта цель сохранится с попыткой и появится в её разборе.</small>
        </section>
      )}
      {pendingStart && !busy && (
        <section
          className="builder-recovery"
          aria-labelledby="builder-recovery-title"
        >
          <div>
            <h2 id="builder-recovery-title">Проверьте предыдущий запуск</h2>
            <p>
              Ответ сервера не получен. Можно восстановить ту попытку или
              настроить новый разговор. Если прежняя переписка уже создана, она
              останется в личном кабинете.
            </p>
          </div>
          <div className="builder-recovery-actions">
            <button
              className="builder-primary"
              onClick={() => void start(pendingStart)}
            >
              Восстановить запуск
            </button>
            <button className="button secondary" onClick={startFresh}>
              Настроить новый разговор
            </button>
          </div>
          {error && !editing && <p role="alert">{error}</p>}
        </section>
      )}
      {!editing ? (
        <>
          <header className="practice-hero">
            <div className="practice-hero-copy">
              <p className="practice-kicker">
                <span /> Студия переговоров
              </p>
              <h1 ref={homeTitle} tabIndex={-1}>
                <span>Сначала практика.</span>
                <em>Потом — сделка.</em>
              </h1>
              <p className="practice-intro">
                Отработайте сложный разговор с виртуальным клиентом — до
                реальной встречи.
              </p>
              <div className="practice-hero-actions">
                <button
                  className="builder-primary practice-start"
                  onClick={startFresh}
                >
                  Настроить разговор{" "}
                  <span>
                    <ArrowUpRight size={20} />
                  </span>
                </button>
              </div>
              <div className="practice-hero-details">
                <span>
                  <Clock3 size={15} /> 5–15 минут
                </span>
                <span>
                  <AudioLines size={17} /> Текст или голос
                </span>
              </div>
              <p className="practice-history-note">
                Здесь начинается новый разговор. Переписки и разборы — в{" "}
                <a href="#/progress">личном кабинете</a>.
              </p>
            </div>
            <div className="practice-art" aria-hidden="true">
              <div className="practice-art-orbit" />
              <img
                src="/artwork/dialogue-sculpture-v5.webp"
                alt=""
                width="900"
                height="900"
                fetchPriority="high"
              />
              <span className="practice-art-note">
                Разные позиции.
                <br />
                Общий язык.
              </span>
              <span className="practice-art-index">01 / ДИАЛОГ</span>
            </div>
          </header>
          <section
            className="builder-presets"
            aria-labelledby="practice-presets-title"
          >
            <div className="practice-section-heading">
              <h2 id="practice-presets-title">Знакомая ситуация?</h2>
              <p>Выберите, что хочется отработать</p>
            </div>
            <div className="builder-preset-list">
              <button
                className="practice-scenario scenario-discount"
                onClick={() => preset("discount")}
              >
                <span className="scenario-topline">
                  <span>01 / ЦЕНА</span>
                  <span className="scenario-symbol" aria-hidden="true">
                    <ArrowDownRight size={22} strokeWidth={1.5} />
                  </span>
                </span>
                <strong>
                  «Дорого.
                  <br />
                  Давайте дешевле»
                </strong>
                <span className="scenario-bottom">
                  <span>Отстоять ценность</span>
                  <ArrowUpRight size={20} aria-hidden="true" />
                </span>
              </button>
              <button
                className="practice-scenario scenario-scope"
                onClick={() => preset("scope")}
              >
                <span className="scenario-topline">
                  <span>02 / ГРАНИЦЫ</span>
                  <span className="scenario-symbol" aria-hidden="true">
                    <Plus size={22} strokeWidth={1.5} />
                  </span>
                </span>
                <strong>
                  «Ещё пару задач.
                  <br />
                  Срок тот же»
                </strong>
                <span className="scenario-bottom">
                  <span>Согласовать объём</span>
                  <ArrowUpRight size={20} aria-hidden="true" />
                </span>
              </button>
              <button
                className="practice-scenario scenario-pressure"
                onClick={() => preset("scope", true)}
              >
                <span className="scenario-topline">
                  <span>03 / ДАВЛЕНИЕ</span>
                  <span className="scenario-symbol" aria-hidden="true">
                    <ArrowUpRight size={22} strokeWidth={1.5} />
                  </span>
                </span>
                <strong>
                  «Мне нужен ответ.
                  <br />
                  Прямо сейчас»
                </strong>
                <span className="scenario-bottom">
                  <span>Ответить за 45 секунд</span>
                  <ArrowUpRight size={20} aria-hidden="true" />
                </span>
              </button>
            </div>
          </section>
        </>
      ) : (
        <>
          <h1 className="sr-only">Настройка тренировки</h1>
          <header className="builder-entry-bar" ref={panel}>
            <button
              className="builder-home-back"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              <ArrowLeft size={17} /> К выбору практики
            </button>
          </header>
          <section
            className="builder-workspace"
            aria-label="Конструктор тренировки"
          >
            {preview ? (
              <>
                <div className="builder-review-head">
                  <div>
                    <span className="builder-eyebrow">
                      <Check size={13} /> СЦЕНАРИЙ СОБРАН
                    </span>
                    <h2 ref={previewTitle} tabIndex={-1}>
                      Ваша встреча готова.
                    </h2>
                    <p>Бриф участника. Прочитайте задачу и начните разговор.</p>
                  </div>
                  <button
                    className="builder-edit"
                    disabled={busy}
                    onClick={() => {
                      setPreview(null);
                      setError("");
                    }}
                  >
                    <SlidersHorizontal size={16} /> Изменить настройки
                  </button>
                </div>
                <div className="builder-brief-grid">
                  <div className="builder-brief">
                    <div className="builder-brief-tags">
                      <span>{industry.label}</span>
                      <span>{config.duration_minutes} мин</span>
                      <span>
                        {config.format === "voice"
                          ? "Голосовая практика"
                          : "Переписка"}
                      </span>
                    </div>
                    <h3>{preview.scenario.title}</h3>
                    <p>{preview.scenario.briefing}</p>
                    <div className="builder-mission">
                      <Target size={19} />
                      <div>
                        <span>ВАША ЗАДАЧА</span>
                        <p>{preview.scenario.objective}</p>
                      </div>
                    </div>
                    {preview.scenario.practice_model === "conversation" &&
                      preview.scenario.constraints.length > 0 && (
                        <details className="builder-constraints">
                          <summary>Что учитывать в разговоре</summary>
                          <ul>
                            {preview.scenario.constraints.map((text) => (
                              <li key={text}>{text}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    {preview.scenario.practice_model !== "conversation" &&
                      preview.scenario.constraints.length > 0 && (
                        <section
                          className="builder-conversation-rules"
                          aria-label="Правила разговора"
                        >
                          <h4>Как пройти разговор</h4>
                          <ul>
                            {preview.scenario.constraints
                              .slice(0, 3)
                              .map((text) => (
                                <li key={text}>{text}</li>
                              ))}
                          </ul>
                        </section>
                      )}
                    {preview.scenario.practice_model !== "conversation" &&
                      preview.scenario.constraints.length > 3 && (
                        <details className="builder-constraints">
                          <summary>Дополнительные детали</summary>
                          <ul>
                            {preview.scenario.constraints
                              .slice(3)
                              .map((text) => (
                                <li key={text}>{text}</li>
                              ))}
                          </ul>
                        </details>
                      )}
                    {preview.scenario.practice_model !== "conversation" &&
                      preview.scenario.baseline && (
                        <details className="builder-constraints builder-legacy-details">
                          <summary>Условия сохранённого сценария</summary>
                          <dl className="builder-numbers">
                            <div>
                              <dt>Цена проекта</dt>
                              <dd>{money(preview.scenario.baseline.price)}</dd>
                            </div>
                            <div>
                              <dt>Объём</dt>
                              <dd>{preview.scenario.baseline.hours} ч</dd>
                            </div>
                            <div>
                              <dt>Срок проекта</dt>
                              <dd>
                                {preview.scenario.baseline.deadline_days} раб.
                                дн.
                              </dd>
                            </div>
                          </dl>
                        </details>
                      )}
                  </div>
                  <aside className="builder-ready">
                    <div
                      className={`builder-client-portrait tone-${config.tone}`}
                      aria-hidden="true"
                    >
                      <span>{preview.scenario.client_name.slice(0, 1)}</span>
                      <i />
                      <b>
                        {config.format === "voice" ? (
                          <AudioLines size={20} />
                        ) : (
                          <MessageCircle size={20} />
                        )}
                      </b>
                    </div>
                    <h3>{preview.scenario.client_name}</h3>
                    <p>
                      {preview.scenario.client_role}
                      <br />
                      {preview.scenario.company}
                    </p>
                    <span className="builder-client-tone">
                      {tone.label} стиль ·{" "}
                      {config.difficulty === "hard"
                        ? "С вызовом"
                        : "Обычная сложность"}
                    </span>
                    <div className="builder-ready-details">
                      <span>
                        <Clock3 size={15} /> Ориентир —{" "}
                        {config.duration_minutes} минут
                      </span>
                      <span>
                        <MessageCircle size={15} /> До {preview.max_turns}{" "}
                        реплик и предложений
                      </span>
                      {config.response_seconds > 0 && (
                        <span>
                          <AudioLines size={15} /> Темп ответа — 45 секунд
                        </span>
                      )}
                    </div>
                    {(liveAvailable || mode === "live") && (
                      <label className="builder-model-select">
                        Режим собеседника
                        <select
                          value={mode}
                          onChange={(event) =>
                            setMode(event.target.value as "demo" | "live")
                          }
                          disabled={busy}
                        >
                          <option value="demo">Сценарный деморежим</option>
                          <option value="live" disabled={!liveAvailable}>
                            {liveReplyMode === "generated"
                              ? "AI-собеседник"
                              : "С AI-анализом реплик"}
                          </option>
                        </select>
                      </label>
                    )}
                    {error && (
                      <p className="inline-error" role="alert">
                        {error}
                      </p>
                    )}
                    {mode === "live" && liveReplyMode === "generated" && (
                      <p className="builder-ready-note">
                        История разговора и бриф передаются внешнему AI-сервису.
                        Модель может ошибаться.
                      </p>
                    )}
                    <button
                      className="builder-primary"
                      disabled={busy}
                      onClick={() => void start(pendingStart ?? undefined)}
                    >
                      {busy ? (
                        <>
                          <LoaderCircle className="spin" size={18} />{" "}
                          Подготавливаем разговор…
                        </>
                      ) : (
                        <>
                          {pendingStart
                            ? "Восстановить запуск"
                            : "Начать тренировку"}
                          <ArrowUpRight size={20} />
                        </>
                      )}
                    </button>
                    <p className="builder-ready-note">
                      {mode === "demo"
                        ? "Пишите своими словами или используйте подсказки. В деморежиме ответы подготовлены заранее."
                        : liveReplyMode === "generated"
                          ? "Пишите своими словами: AI отвечает с учётом разговора."
                          : "Ответы подготовлены заранее; AI помогает разобрать реплики."}
                    </p>
                    {config.format === "voice" && (
                      <p className="builder-voice-note">
                        Микрофон включается по вашему нажатию. Если голос
                        недоступен, можно отвечать текстом.
                      </p>
                    )}
                  </aside>
                </div>
              </>
            ) : (
              <>
                <nav className="builder-steps" aria-label="Этапы настройки">
                  {STEPS.map((item, index) => (
                    <button
                      key={item.name}
                      disabled={busy}
                      className={`${step === index ? "is-active" : ""} ${step > index ? "is-done" : ""}`}
                      aria-current={step === index ? "step" : undefined}
                      onClick={() => {
                        setStep(index);
                        setError("");
                      }}
                    >
                      <span>
                        {step > index ? <Check size={15} /> : `0${index + 1}`}
                      </span>
                      <div>
                        <strong>{item.name}</strong>
                      </div>
                      <ChevronRight size={17} />
                    </button>
                  ))}
                </nav>
                <div className="builder-config-grid">
                  <div className="builder-fields">
                    <div className="builder-step-title">
                      <span>ШАГ 0{step + 1}</span>
                      <h2 ref={stepTitle} tabIndex={-1}>
                        {
                          [
                            "О чём будем договариваться?",
                            "Кто по другую сторону стола?",
                            "Как будем тренироваться?",
                          ][step]
                        }
                      </h2>
                      <p>
                        {
                          [
                            "Выберите рабочий контекст и навык, который хочется отработать.",
                            "Характер задаёт манеру разговора. Цель определяет, на что согласится клиент.",
                            "Формат и сложность независимы. Начните с комфортного темпа.",
                          ][step]
                        }
                      </p>
                    </div>
                    {step === 0 && (
                      <>
                        <fieldset className="builder-field">
                          <legend>Тема переговоров</legend>
                          <div className="builder-topic-options">
                            <button
                              className={`builder-topic ${config.topic === "scope" ? "selected" : ""}`}
                              aria-pressed={config.topic === "scope"}
                              disabled={busy}
                              onClick={() =>
                                update({ topic: "scope", goal: "deadline" })
                              }
                            >
                              <span className="builder-topic-icon">
                                <Layers3 size={23} />
                              </span>
                              <div>
                                <strong>Больше работы. Тот же срок.</strong>
                                <p>
                                  Клиент расширяет задачу. Договоритесь об
                                  объёме, который команда сможет выполнить.
                                </p>
                              </div>
                              <span className="choice-indicator">
                                {config.topic === "scope" && (
                                  <Check size={11} />
                                )}
                              </span>
                            </button>
                            <button
                              className={`builder-topic ${config.topic === "discount" ? "selected" : ""}`}
                              aria-pressed={config.topic === "discount"}
                              disabled={busy}
                              onClick={() =>
                                update({ topic: "discount", goal: "budget" })
                              }
                            >
                              <span className="builder-topic-icon">
                                <BriefcaseBusiness size={23} />
                              </span>
                              <div>
                                <strong>Меньше цена. Та же ценность.</strong>
                                <p>
                                  Клиент просит скидку. Выясните причину и
                                  предложите вариант, который устроит обе
                                  стороны.
                                </p>
                              </div>
                              <span className="choice-indicator">
                                {config.topic === "discount" && (
                                  <Check size={11} />
                                )}
                              </span>
                            </button>
                          </div>
                        </fieldset>
                        <fieldset className="builder-field">
                          <legend>Сфера вашей команды</legend>
                          <div className="builder-choice-grid thirds">
                            {INDUSTRIES.map((item) => (
                              <button
                                disabled={busy}
                                key={item.id}
                                className={`builder-choice ${config.industry === item.id ? "selected" : ""}`}
                                aria-pressed={config.industry === item.id}
                                onClick={() => update({ industry: item.id })}
                              >
                                <span className="choice-indicator">
                                  {config.industry === item.id && (
                                    <Check size={11} />
                                  )}
                                </span>
                                <strong>{item.label}</strong>
                                <small>{item.detail}</small>
                              </button>
                            ))}
                          </div>
                        </fieldset>
                      </>
                    )}
                    {step === 1 && (
                      <>
                        <label className="builder-select-label">
                          Роль клиента
                          <select
                            value={config.client_role}
                            onChange={(event) =>
                              update({
                                client_role: event.target
                                  .value as TrainingConfig["client_role"],
                              })
                            }
                            disabled={busy}
                          >
                            {ROLES.map((item) => (
                              <option value={item.id} key={item.id}>
                                {item.label}
                              </option>
                            ))}
                          </select>
                          <small>{role.detail}</small>
                        </label>
                        <fieldset className="builder-field">
                          <legend>
                            Цель клиента <span>Настройка наставника</span>
                          </legend>
                          <div className="builder-choice-grid halves">
                            {GOALS[config.topic].map((item) => (
                              <button
                                disabled={busy}
                                key={item.id}
                                className={`builder-choice ${config.goal === item.id ? "selected" : ""}`}
                                aria-pressed={config.goal === item.id}
                                onClick={() => update({ goal: item.id })}
                              >
                                <strong>{item.label}</strong>
                                <small>{item.detail}</small>
                              </button>
                            ))}
                          </div>
                        </fieldset>
                        <fieldset className="builder-field">
                          <legend>Манера общения</legend>
                          <div className="builder-choice-grid thirds">
                            {TONES.map((item) => (
                              <button
                                disabled={busy}
                                key={item.id}
                                className={`builder-choice tone-choice ${config.tone === item.id ? "selected" : ""}`}
                                aria-pressed={config.tone === item.id}
                                onClick={() => update({ tone: item.id })}
                              >
                                <span aria-hidden="true">
                                  <item.icon size={26} strokeWidth={1.5} />
                                </span>
                                <strong>{item.label}</strong>
                                <small>{item.detail}</small>
                              </button>
                            ))}
                          </div>
                        </fieldset>
                        <fieldset className="builder-field">
                          <legend>Сложность</legend>
                          <div className="builder-choice-grid halves">
                            <button
                              disabled={busy}
                              className={`builder-choice ${config.difficulty === "standard" ? "selected" : ""}`}
                              aria-pressed={config.difficulty === "standard"}
                              onClick={() => update({ difficulty: "standard" })}
                            >
                              <strong>Обычная</strong>
                              <small>Можно сразу обсуждать варианты</small>
                            </button>
                            <button
                              disabled={busy}
                              className={`builder-choice ${config.difficulty === "hard" ? "selected" : ""}`}
                              aria-pressed={config.difficulty === "hard"}
                              onClick={() => update({ difficulty: "hard" })}
                            >
                              <strong>С вызовом</strong>
                              <small>Сначала выясните интересы клиента</small>
                            </button>
                          </div>
                        </fieldset>
                      </>
                    )}
                    {step === 2 && (
                      <>
                        <fieldset className="builder-field">
                          <legend>Сколько времени на практику?</legend>
                          <div className="builder-choice-grid thirds time-choices">
                            {([5, 10, 15] as const).map((minutes) => (
                              <button
                                disabled={busy}
                                className={`builder-choice ${config.duration_minutes === minutes ? "selected" : ""}`}
                                key={minutes}
                                aria-pressed={
                                  config.duration_minutes === minutes
                                }
                                onClick={() =>
                                  update({ duration_minutes: minutes })
                                }
                              >
                                <strong>
                                  {minutes} <span>мин</span>
                                </strong>
                                <small>
                                  {minutes === 5
                                    ? "Короткий раунд"
                                    : minutes === 10
                                      ? "Рабочий разговор"
                                      : "Подробный разбор ситуации"}
                                </small>
                              </button>
                            ))}
                          </div>
                          <p className="builder-field-hint">
                            Ориентир по времени. До {turnLimit} ваших реплик и
                            предложений; завершение не происходит автоматически.
                          </p>
                        </fieldset>
                        <fieldset className="builder-field">
                          <legend>Формат разговора</legend>
                          <div className="builder-choice-grid halves format-choices">
                            <button
                              className={`builder-choice ${config.format === "text" ? "selected" : ""}`}
                              aria-pressed={config.format === "text"}
                              disabled={busy}
                              onClick={() => update({ format: "text" })}
                            >
                              <MessageCircle size={26} strokeWidth={1.6} />
                              <strong>Переписка</strong>
                              <small>Формулируйте мысль в своём темпе</small>
                            </button>
                            <button
                              className={`builder-choice ${config.format === "voice" ? "selected" : ""}`}
                              aria-pressed={config.format === "voice"}
                              disabled={busy}
                              onClick={() => update({ format: "voice" })}
                            >
                              <AudioLines size={26} strokeWidth={1.6} />
                              <strong>Голосовая практика</strong>
                              <small>Слушайте клиента. Отвечайте вслух.</small>
                              <span className="builder-beta">БЕТА</span>
                            </button>
                          </div>
                        </fieldset>
                        {config.format === "voice" && (
                          <div className="builder-voice-explainer">
                            <Mic size={19} />
                            <p>
                              Разговор по очереди: озвучка клиента и голосовой
                              ввод. Перед отправкой можно проверить текст. Нужен
                              совместимый браузер и микрофон; переписка всегда
                              доступна. Аудио может обрабатываться сервисом
                              браузера.
                            </p>
                          </div>
                        )}
                        <fieldset className="builder-field">
                          <legend>Темп ответа</legend>
                          <div className="builder-choice-grid halves">
                            <button
                              className={`builder-choice ${config.response_seconds === 0 ? "selected" : ""}`}
                              aria-pressed={config.response_seconds === 0}
                              disabled={busy}
                              onClick={() => update({ response_seconds: 0 })}
                            >
                              <strong>Без таймера</strong>
                              <small>Дайте себе время подумать</small>
                            </button>
                            <button
                              className={`builder-choice ${config.response_seconds === 45 ? "selected" : ""}`}
                              aria-pressed={config.response_seconds === 45}
                              disabled={busy}
                              onClick={() => update({ response_seconds: 45 })}
                            >
                              <strong>45 секунд на ответ</strong>
                              <small>Практика кратких формулировок</small>
                            </button>
                          </div>
                          <p className="builder-field-hint">
                            Таймер задаёт темп, но не отправляет ответ за вас и
                            не оценивает скорость как навык.
                          </p>
                        </fieldset>
                      </>
                    )}
                    {error && (
                      <p className="inline-error builder-error" role="alert">
                        {error}
                      </p>
                    )}
                    <div className="builder-actions">
                      {step > 0 ? (
                        <button
                          className="builder-back"
                          onClick={() => {
                            setStep(step - 1);
                            setError("");
                          }}
                          disabled={busy}
                        >
                          <ArrowLeft size={17} /> Назад
                        </button>
                      ) : (
                        <span className="builder-step-count">01 / 03</span>
                      )}
                      <button
                        className="builder-primary"
                        disabled={busy}
                        onClick={() =>
                          step < 2 ? setStep(step + 1) : void assemble()
                        }
                      >
                        {busy ? (
                          <>
                            <LoaderCircle size={18} className="spin" /> Собираем
                            бриф…
                          </>
                        ) : (
                          <>
                            {step < 2 ? "Продолжить" : "Собрать сценарий"}
                            <ArrowRight size={18} />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
