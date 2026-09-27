import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronRight,
  Eye,
  FileText,
  LoaderCircle,
  Plus,
  Search,
  Send,
  Settings2,
} from "lucide-react";
import {
  workspaceApi,
  type AdminCase,
  type CaseContent,
} from "../workspace-api";
import { errorMessage } from "../api";
import type { TrainingConfig, TrainingPreview } from "../types";
import { Modal, money } from "./UI";
import "../admin-workspace.css";

const DEFAULT_CONTENT: CaseContent = {
  practice_model: "conversation",
  title: "Новые задачи перед запуском",
  description:
    "Клиент просит расширить проект. Согласуйте объём и срок, сохранив интересы обеих сторон.",
  briefing:
    "Вы представляете команду, которая готовит запуск сайта. В конце проекта заказчик просит добавить новые страницы. Обсудите, какие задачи действительно нужны к запуску, и предложите компромисс, который учитывает интересы обеих сторон.",
  objective:
    "Выяснить приоритет клиента, предложить компромисс и согласовать следующий шаг.",
  client_name: "Александр",
  company: "Вектор",
  opening:
    "Нам нужны дополнительные страницы к запуску. Можете включить их в проект и сохранить согласованную дату?",
  configuration: {
    industry: "digital",
    topic: "scope",
    difficulty: "standard",
    tone: "reserved",
    client_role: "project_lead",
    goal: "deadline",
    duration_minutes: 10,
    format: "text",
    response_seconds: 0,
  },
};
const INDUSTRIES = {
  digital: "Digital-услуги",
  it: "IT и автоматизация",
  consulting: "Консалтинг",
};
const TOPICS = { scope: "Сроки и объём", discount: "Цена и условия оплаты" };
const GOALS = {
  scope: {
    deadline: "Сохранить дату запуска",
    full_scope: "Получить весь объём",
  },
  discount: {
    budget: "Уложиться в общий бюджет",
    cashflow: "Снизить первый платёж",
  },
};
type Filter = "all" | AdminCase["status"];
type Confirmation =
  | { kind: "leave"; next: "list" | "new" }
  | { kind: "archive" }
  | { kind: "reload" }
  | { kind: "navigation"; proceed: () => void };
const freshContent = () => ({
  ...DEFAULT_CONTENT,
  configuration: { ...DEFAULT_CONTENT.configuration },
});
const normalizeContent = (content: CaseContent): CaseContent => ({
  ...content,
  practice_model: "conversation",
  title: content.title.trim(),
  description: content.description.trim(),
  briefing: content.briefing.trim(),
  objective: content.objective.trim(),
  client_name: content.client_name.trim(),
  company: content.company.trim(),
  opening: content.opening.trim(),
});
const sameContent = (a: CaseContent, b: CaseContent) =>
  Object.keys(a).every((key) =>
    key === "configuration"
      ? Object.entries(a.configuration).every(
          ([field, value]) =>
            b.configuration[field as keyof TrainingConfig] === value,
        )
      : a[key as keyof CaseContent] === b[key as keyof CaseContent],
  );
function statusLabel(item: AdminCase) {
  if (item.status === "archived") return "В архиве";
  if (item.status === "draft") return "Черновик";
  return item.has_unpublished_changes
    ? "Есть неопубликованные изменения"
    : "Опубликовано";
}
function dateLabel(value: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
  }).format(new Date(value));
}

export function AdminPage({ onPublished }: { onPublished: () => void }) {
  const [items, setItems] = useState<AdminCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<AdminCase | null>(null);
  const [content, setContent] = useState<CaseContent>(freshContent);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [preview, setPreview] = useState<TrainingPreview | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const inFlight = useRef(false);
  const allowNavigation = useRef(false);
  const createAction = useRef(crypto.randomUUID());
  const creationContent = useRef<CaseContent | null>(null);
  const alive = useRef(true);
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const loadedOnce = useRef(false);
  const dirty = selected
    ? !sameContent(content, selected.content)
    : !sameContent(content, DEFAULT_CONTENT);
  const needsConversationSave = Boolean(
    selected && selected.content.practice_model !== "conversation",
  );
  const needsSave = !selected || dirty || needsConversationSave;
  const unpublished =
    selected?.status !== "published" || selected.has_unpublished_changes;
  const filtered = items.filter(
    (item) =>
      (filter === "all" || item.status === filter) &&
      `${item.content.title} ${item.content.company}`
        .toLocaleLowerCase("ru-RU")
        .includes(search.toLocaleLowerCase("ru-RU").trim()),
  );

  async function loadItems() {
    setLoading(true);
    setError("");
    try {
      const data = await workspaceApi.adminCases();
      if (alive.current) setItems(data.items);
    } catch (cause) {
      if (alive.current) setError(errorMessage(cause));
    } finally {
      if (alive.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void loadItems();
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (loadedOnce.current) heading.current?.focus();
    loadedOnce.current = true;
  }, [editing, selected?.id]);
  useEffect(() => {
    if (!editing || !dirty) return;
    allowNavigation.current = false;
    const warn = (event: BeforeUnloadEvent) => {
      if (!allowNavigation.current) event.preventDefault();
    };
    const guardLink = (event: MouseEvent) => {
      if (
        allowNavigation.current ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor =
        event.target instanceof Element
          ? event.target.closest<HTMLAnchorElement>("a[href]")
          : null;
      if (
        !anchor ||
        anchor.hasAttribute("download") ||
        (anchor.target && anchor.target !== "_self")
      )
        return;
      const destination = new URL(anchor.href, window.location.href);
      if (
        destination.origin !== window.location.origin ||
        destination.pathname !== window.location.pathname ||
        destination.search !== window.location.search ||
        !destination.hash.startsWith("#/") ||
        destination.hash === window.location.hash
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      setConfirmation({
        kind: "navigation",
        proceed: () => {
          window.location.hash = destination.hash;
        },
      });
    };
    const guardAction = (event: Event) => {
      if (allowNavigation.current) return;
      const action = event as CustomEvent<{
        proceed?: () => void | Promise<void>;
      }>;
      if (typeof action.detail?.proceed !== "function") return;
      event.preventDefault();
      const proceed = action.detail.proceed;
      setConfirmation({
        kind: "navigation",
        proceed: () => {
          void (async () => {
            try {
              await proceed();
            } catch (cause) {
              if (alive.current) handleError(cause);
            } finally {
              allowNavigation.current = false;
            }
          })();
        },
      });
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", guardLink, true);
    window.addEventListener("posle:before-leave", guardAction);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", guardLink, true);
      window.removeEventListener("posle:before-leave", guardAction);
    };
  }, [editing, dirty]);

  function updateContent<K extends keyof CaseContent>(
    key: K,
    value: CaseContent[K],
  ) {
    setContent((current) => ({ ...current, [key]: value }));
    setPreview(null);
    setNotice("");
  }
  function updateConfig<K extends keyof TrainingConfig>(
    key: K,
    value: TrainingConfig[K],
  ) {
    const next = { ...content.configuration, [key]: value };
    if (key === "topic") next.goal = value === "scope" ? "deadline" : "budget";
    updateContent("configuration", next);
  }
  function openEditor(item: AdminCase | null) {
    setSelected(item);
    setContent(
      item
        ? { ...item.content, configuration: { ...item.content.configuration } }
        : freshContent(),
    );
    createAction.current = crypto.randomUUID();
    creationContent.current = null;
    setPreview(null);
    setError("");
    setNotice("");
    setConflict(false);
    setEditing(true);
  }
  function leave(next: "list" | "new") {
    if (dirty) {
      setConfirmation({ kind: "leave", next });
      return;
    }
    if (next === "new") openEditor(null);
    else {
      setEditing(false);
      setError("");
      setConflict(false);
    }
  }
  function putItem(item: AdminCase) {
    setItems((current) => [
      item,
      ...current.filter((entry) => entry.id !== item.id),
    ]);
    setSelected(item);
  }
  function handleError(cause: unknown) {
    const status =
      typeof cause === "object" && cause !== null && "status" in cause
        ? cause.status
        : undefined;
    const message = errorMessage(cause);
    if (
      !selected &&
      typeof status === "number" &&
      status >= 400 &&
      status < 500 &&
      status !== 409
    )
      creationContent.current = null;
    if (status === 409 || /верси|revision|conflict/i.test(message)) {
      setConflict(true);
      setError(
        "Эту ситуацию уже изменили. Ваши поля сохранены на экране. Загрузите актуальную версию перед следующей попыткой.",
      );
    } else setError(message);
  }
  async function run(name: string, action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (cause) {
      if (alive.current) handleError(cause);
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(null);
    }
  }
  function save() {
    if (!form.current?.reportValidity()) return;
    const submitted = normalizeContent(content);
    void run("save", async () => {
      if (!selected && !creationContent.current)
        creationContent.current = submitted;
      const response = selected
        ? await workspaceApi.saveCase(selected.id, selected.revision, submitted)
        : await workspaceApi.createCase(
            creationContent.current!,
            createAction.current,
          );
      if (!alive.current) return;
      putItem(response.item);
      // The create endpoint can replay an earlier successful request after a lost response.
      // Keep current text if the replayed draft differs, so the next save applies those edits.
      setContent(
        sameContent(response.item.content, submitted)
          ? response.item.content
          : submitted,
      );
      createAction.current = crypto.randomUUID();
      creationContent.current = null;
      setConflict(false);
      setNotice(
        sameContent(response.item.content, submitted)
          ? "Черновик сохранён. Чтобы показать его пользователям, нажмите «Опубликовать»."
          : "Ранее отправленный черновик восстановлен. Ваши последние изменения остались в редакторе — сохраните их ещё раз.",
      );
    });
  }
  function publish() {
    if (!selected || dirty || conflict || needsConversationSave) return;
    void run("publish", async () => {
      const response = await workspaceApi.publishCase(
        selected.id,
        selected.revision,
      );
      if (!alive.current) return;
      putItem(response.item);
      setContent(response.item.content);
      setNotice("Ситуация опубликована и доступна пользователям в каталоге.");
      onPublished();
    });
  }
  function unpublish() {
    if (!selected || dirty || conflict) return;
    void run("unpublish", async () => {
      const response = await workspaceApi.unpublishCase(
        selected.id,
        selected.revision,
      );
      if (!alive.current) return;
      putItem(response.item);
      setNotice("Ситуация снята с публикации. Начатые разговоры сохраняются.");
      onPublished();
    });
  }
  function archive() {
    if (!selected) return;
    void run("archive", async () => {
      const response = await workspaceApi.archiveCase(
        selected.id,
        selected.revision,
      );
      if (!alive.current) return;
      putItem(response.item);
      setConfirmation(null);
      setNotice("Ситуация перенесена в архив и скрыта из каталога.");
      onPublished();
    });
  }
  function loadCurrentVersion() {
    if (!selected) return;
    void run("reload", async () => {
      const data = await workspaceApi.adminCases();
      if (!alive.current) return;
      setItems(data.items);
      const current = data.items.find((item) => item.id === selected.id);
      if (!current)
        throw new Error(
          "Ситуация больше не доступна. Вернитесь к списку и обновите его.",
        );
      setSelected(current);
      setContent(current.content);
      setPreview(null);
      setConflict(false);
      setConfirmation(null);
      setNotice("Загружена актуальная версия ситуации.");
    });
  }
  function showPreview() {
    if (!form.current?.reportValidity()) return;
    void run("preview", async () => {
      const response = await workspaceApi.previewCase(
        normalizeContent(content),
      );
      if (alive.current) setPreview(response.preview);
    });
  }

  return (
    <div className="admin-workspace">
      <header className="admin-page-heading">
        <div>
          <p className="admin-kicker">Управление обучением</p>
          <h1 ref={heading} tabIndex={-1}>
            {editing
              ? selected
                ? "Редактор ситуации"
                : "Новая ситуация"
              : "Ситуации команды"}
          </h1>
          <p>
            {editing
              ? "Задайте контекст, настройте собеседника и опубликуйте тренировку."
              : "Готовьте ситуации под задачи команды. Пользователи увидят только опубликованные."}
          </p>
        </div>
        {!editing && (
          <button
            type="button"
            className="button primary"
            onClick={() => openEditor(null)}
            disabled={loading}
          >
            <Plus size={17} />
            Добавить ситуацию
          </button>
        )}
      </header>
      {notice && (
        <div className="admin-notice" role="status">
          <Check size={18} />
          <span>{notice}</span>
        </div>
      )}
      {error && (
        <div className="admin-error" role="alert">
          <p>{error}</p>
          {conflict && selected && (
            <button
              type="button"
              onClick={() => setConfirmation({ kind: "reload" })}
              disabled={Boolean(busy)}
            >
              Загрузить версию сервера
            </button>
          )}
          {!editing && (
            <button
              type="button"
              onClick={() => void loadItems()}
              disabled={loading}
            >
              Повторить загрузку
            </button>
          )}
        </div>
      )}
      {!editing ? (
        <>
          <div className="admin-list-tools">
            <div className="admin-filters" aria-label="Статус ситуаций">
              {(
                [
                  { value: "all", label: "Все" },
                  { value: "published", label: "Опубликованные" },
                  { value: "draft", label: "Черновики" },
                  { value: "archived", label: "Архив" },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label}
                  <span>
                    {value === "all"
                      ? items.length
                      : items.filter((item) => item.status === value).length}
                  </span>
                </button>
              ))}
            </div>
            <label className="admin-search">
              <Search size={17} aria-hidden="true" />
              <span className="sr-only">Поиск по названию или компании</span>
              <input
                type="search"
                placeholder="Найти ситуацию"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
          </div>
          {loading ? (
            <div className="admin-empty" role="status">
              <LoaderCircle className="spin" size={25} />
              <p>Загружаем ситуации…</p>
            </div>
          ) : filtered.length ? (
            <div className="admin-case-list">
              {filtered.map((item) => (
                <button
                  type="button"
                  className="admin-case-row"
                  key={item.id}
                  onClick={() => openEditor(item)}
                >
                  <span className="admin-case-icon">
                    <FileText size={22} />
                  </span>
                  <span className="admin-case-copy">
                    <span
                      className={`admin-status admin-status-${item.status}`}
                    >
                      {statusLabel(item)}
                    </span>
                    <strong>{item.content.title}</strong>
                    <span className="admin-case-description">
                      {item.content.description}
                    </span>
                    <span className="admin-case-meta">
                      {INDUSTRIES[item.content.configuration.industry]}
                      <span aria-hidden="true">·</span>
                      {item.content.configuration.duration_minutes} мин
                      <span aria-hidden="true">·</span>Обновлено{" "}
                      {dateLabel(item.updated_at)}
                    </span>
                  </span>
                  <ChevronRight
                    size={20}
                    className="admin-row-chevron"
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
          ) : (
            <div className="admin-empty">
              <FileText size={32} />
              <h2>
                {items.length
                  ? "Ничего не найдено"
                  : "Первая ситуация начинается здесь"}
              </h2>
              <p>
                {items.length
                  ? "Измените запрос или выберите другой статус."
                  : "Добавьте рабочий контекст и настройте клиента. Черновик будет виден только администраторам."}
              </p>
              {!items.length && (
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => openEditor(null)}
                >
                  <Plus size={16} />
                  Создать ситуацию
                </button>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="admin-editor-toolbar">
            <button
              type="button"
              className="admin-back"
              onClick={() => leave("list")}
              disabled={Boolean(busy)}
            >
              <ArrowLeft size={16} />
              Все ситуации
            </button>
            <div className="admin-editor-state">
              <span
                className={`admin-status admin-status-${selected?.status || "draft"}`}
              >
                {selected ? statusLabel(selected) : "Новый черновик"}
              </span>
              {dirty && <span className="admin-unsaved">Не сохранено</span>}
            </div>
          </div>
          {selected?.status === "published" && (dirty || unpublished) && (
            <p className="admin-publication-note">
              Пользователи пока видят ранее опубликованную версию. Новые
              изменения появятся после публикации.
            </p>
          )}
          {selected?.status === "archived" && (
            <p className="admin-publication-note">
              Ситуация в архиве. Её можно отредактировать и опубликовать снова.
            </p>
          )}
          <form
            ref={form}
            className="admin-editor"
            onSubmit={(event) => {
              event.preventDefault();
              save();
            }}
          >
            <fieldset className="admin-fields" disabled={Boolean(busy)}>
              <section
                className="admin-form-section"
                aria-labelledby="admin-story-title"
              >
                <div className="admin-section-title">
                  <span>01</span>
                  <h2 id="admin-story-title">История разговора</h2>
                </div>
                <label>
                  Название
                  <input
                    required
                    minLength={3}
                    maxLength={120}
                    value={content.title}
                    onChange={(event) =>
                      updateContent("title", event.target.value)
                    }
                    placeholder="Например, клиент просит скидку перед стартом"
                  />
                </label>
                <label>
                  Описание для каталога
                  <textarea
                    required
                    rows={2}
                    minLength={10}
                    maxLength={400}
                    value={content.description}
                    onChange={(event) =>
                      updateContent("description", event.target.value)
                    }
                  />
                  <span className="admin-field-hint">
                    Что предстоит отработать. Пользователь увидит этот текст до
                    начала.
                  </span>
                </label>
                <label>
                  Вводная для участника
                  <textarea
                    required
                    rows={4}
                    minLength={20}
                    maxLength={3000}
                    value={content.briefing}
                    onChange={(event) =>
                      updateContent("briefing", event.target.value)
                    }
                  />
                  <span className="admin-field-hint">
                    Роль участника, контекст и причина переговоров.
                  </span>
                </label>
                <label>
                  Задача участника
                  <textarea
                    required
                    rows={2}
                    minLength={10}
                    maxLength={1000}
                    value={content.objective}
                    onChange={(event) =>
                      updateContent("objective", event.target.value)
                    }
                  />
                </label>
              </section>
              <section
                className="admin-form-section"
                aria-labelledby="admin-client-title"
              >
                <div className="admin-section-title">
                  <span>02</span>
                  <h2 id="admin-client-title">Собеседник</h2>
                </div>
                <div className="admin-field-grid">
                  <label>
                    Имя клиента
                    <input
                      required
                      minLength={1}
                      maxLength={80}
                      value={content.client_name}
                      onChange={(event) =>
                        updateContent("client_name", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    Компания
                    <input
                      required
                      minLength={1}
                      maxLength={120}
                      value={content.company}
                      onChange={(event) =>
                        updateContent("company", event.target.value)
                      }
                    />
                  </label>
                </div>
                <label>
                  Первая реплика клиента
                  <textarea
                    required
                    rows={3}
                    minLength={10}
                    maxLength={1000}
                    value={content.opening}
                    onChange={(event) =>
                      updateContent("opening", event.target.value)
                    }
                  />
                  <span className="admin-field-hint">
                    С этой реплики начнётся каждая тренировка по ситуации.
                  </span>
                </label>
                <div className="admin-field-grid">
                  <label>
                    Должность
                    <select
                      value={content.configuration.client_role}
                      onChange={(event) =>
                        updateConfig(
                          "client_role",
                          event.target.value as TrainingConfig["client_role"],
                        )
                      }
                    >
                      <option value="project_lead">Руководитель проекта</option>
                      <option value="business_owner">Владелец бизнеса</option>
                      <option value="procurement">Менеджер по закупкам</option>
                    </select>
                  </label>
                  <label>
                    Манера общения
                    <select
                      value={content.configuration.tone}
                      onChange={(event) =>
                        updateConfig(
                          "tone",
                          event.target.value as TrainingConfig["tone"],
                        )
                      }
                    >
                      <option value="collaborative">Открытый</option>
                      <option value="reserved">Сдержанный</option>
                      <option value="pressing">Напористый</option>
                    </select>
                  </label>
                </div>
              </section>
              <section
                className="admin-form-section"
                aria-labelledby="admin-settings-title"
              >
                <div className="admin-section-title">
                  <span>03</span>
                  <h2 id="admin-settings-title">Настройки тренировки</h2>
                </div>
                <div className="admin-field-grid">
                  <label>
                    Отрасль
                    <select
                      value={content.configuration.industry}
                      onChange={(event) =>
                        updateConfig(
                          "industry",
                          event.target.value as TrainingConfig["industry"],
                        )
                      }
                    >
                      {Object.entries(INDUSTRIES).map(([value, label]) => (
                        <option value={value} key={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Тема
                    <select
                      value={content.configuration.topic}
                      onChange={(event) =>
                        updateConfig(
                          "topic",
                          event.target.value as TrainingConfig["topic"],
                        )
                      }
                    >
                      {Object.entries(TOPICS).map(([value, label]) => (
                        <option value={value} key={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Скрытый приоритет клиента
                  <select
                    value={content.configuration.goal}
                    onChange={(event) =>
                      updateConfig(
                        "goal",
                        event.target.value as TrainingConfig["goal"],
                      )
                    }
                  >
                    {Object.entries(GOALS[content.configuration.topic]).map(
                      ([value, label]) => (
                        <option value={value} key={value}>
                          {label}
                        </option>
                      ),
                    )}
                  </select>
                  <span className="admin-field-hint">
                    Участник должен выяснить его в разговоре.
                  </span>
                </label>
                <div className="admin-field-grid">
                  <label>
                    Сложность
                    <select
                      value={content.configuration.difficulty}
                      onChange={(event) =>
                        updateConfig(
                          "difficulty",
                          event.target.value as TrainingConfig["difficulty"],
                        )
                      }
                    >
                      <option value="standard">Обычная</option>
                      <option value="hard">Высокая</option>
                    </select>
                  </label>
                  <label>
                    Длительность
                    <select
                      value={content.configuration.duration_minutes}
                      onChange={(event) =>
                        updateConfig(
                          "duration_minutes",
                          Number(
                            event.target.value,
                          ) as TrainingConfig["duration_minutes"],
                        )
                      }
                    >
                      <option value={5}>5 минут</option>
                      <option value={10}>10 минут</option>
                      <option value={15}>15 минут</option>
                    </select>
                  </label>
                  <label>
                    Формат
                    <select
                      value={content.configuration.format}
                      onChange={(event) =>
                        updateConfig(
                          "format",
                          event.target.value as TrainingConfig["format"],
                        )
                      }
                    >
                      <option value="text">Переписка</option>
                      <option value="voice">Голос</option>
                    </select>
                  </label>
                  <label>
                    Время на ответ
                    <select
                      value={content.configuration.response_seconds}
                      onChange={(event) =>
                        updateConfig(
                          "response_seconds",
                          Number(
                            event.target.value,
                          ) as TrainingConfig["response_seconds"],
                        )
                      }
                    >
                      <option value={0}>Без таймера</option>
                      <option value={45}>45 секунд</option>
                    </select>
                  </label>
                </div>
              </section>
            </fieldset>
            <aside className="admin-editor-aside">
              <section
                className="admin-preview-panel"
                aria-labelledby="admin-preview-title"
              >
                <div className="admin-preview-heading">
                  <Eye size={19} />
                  <h2 id="admin-preview-title">Проверить перед публикацией</h2>
                </div>
                <p>
                  Посмотрите на ситуацию глазами участника: понятны ли задача,
                  роль клиента и повод для разговора.
                </p>
                <button
                  className="button secondary"
                  type="button"
                  onClick={showPreview}
                  disabled={Boolean(busy)}
                >
                  {busy === "preview" ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Settings2 size={16} />
                  )}
                  {preview ? "Обновить предпросмотр" : "Посмотреть бриф"}
                </button>
                {preview && (
                  <div className="admin-preview-content" aria-live="polite">
                    <h3>{preview.scenario.title}</h3>
                    <p className="admin-preview-story">
                      {preview.scenario.briefing}
                    </p>
                    <div className="admin-preview-objective">
                      <span>Задача участника</span>
                      <p>{preview.scenario.objective}</p>
                    </div>
                    <p className="admin-preview-client">
                      <strong>{preview.scenario.client_name}</strong>
                      <span>
                        {preview.scenario.client_role} ·{" "}
                        {preview.scenario.company}
                      </span>
                    </p>
                    {preview.scenario.constraints.length > 0 && (
                      <ul className="admin-preview-rules">
                        {preview.scenario.constraints
                          .slice(0, 3)
                          .map((constraint) => (
                            <li key={constraint}>{constraint}</li>
                          ))}
                      </ul>
                    )}
                    {preview.scenario.constraints.length > 3 && (
                      <details>
                        <summary>Дополнительные правила</summary>
                        <ul>
                          {preview.scenario.constraints
                            .slice(3)
                            .map((constraint) => (
                              <li key={constraint}>{constraint}</li>
                            ))}
                        </ul>
                      </details>
                    )}
                    {preview.scenario.practice_model !== "conversation" &&
                      preview.scenario.baseline && (
                        <details>
                          <summary>Условия сохранённого сценария</summary>
                          <dl className="admin-preview-terms">
                            <div>
                              <dt>Цена проекта</dt>
                              <dd>{money(preview.scenario.baseline.price)}</dd>
                            </div>
                            <div>
                              <dt>Срок</dt>
                              <dd>
                                {preview.scenario.baseline.deadline_days} дн.
                              </dd>
                            </div>
                            <div>
                              <dt>Объём работ</dt>
                              <dd>{preview.scenario.baseline.hours} ч</dd>
                            </div>
                            <div>
                              <dt>Ресурс команды</dt>
                              <dd>
                                {preview.scenario.baseline.daily_capacity}{" "}
                                ч/день
                              </dd>
                            </div>
                          </dl>
                          <p className="admin-preview-payment">
                            {preview.scenario.baseline.payment}
                          </p>
                          {preview.scenario.options.map((option) => (
                            <div
                              className="admin-preview-option"
                              key={option.id}
                            >
                              <strong>{option.label}</strong>
                              {option.terms && (
                                <span>
                                  {money(option.terms.price)} ·{" "}
                                  {option.terms.hours} ч ·{" "}
                                  {option.terms.deadline_days} дн.
                                </span>
                              )}
                              <p>{option.description}</p>
                            </div>
                          ))}
                        </details>
                      )}
                    <blockquote>
                      «{preview.scenario.opening || content.opening}»
                    </blockquote>
                  </div>
                )}
                <p className="admin-preview-caution">
                  Первая реплика должна соответствовать выбранной теме и цели
                  разговора.
                </p>
              </section>
              <section
                className="admin-publish-panel"
                aria-labelledby="admin-publish-title"
              >
                <h2 id="admin-publish-title">Готово для команды?</h2>
                <p>
                  {selected?.status === "published"
                    ? "Можно сохранить изменения как черновик или выпустить обновлённую версию."
                    : "Сначала сохраните черновик, затем опубликуйте его в каталоге."}
                </p>
                {needsConversationSave && (
                  <p className="admin-field-hint">
                    Сохраните ситуацию, чтобы перейти к тренировке диалога без
                    расчёта стоимости. Пользователи увидят новую версию только
                    после публикации.
                  </p>
                )}
                <button
                  className={`button ${needsSave ? "primary" : "secondary"}`}
                  type="submit"
                  disabled={
                    Boolean(busy) ||
                    conflict ||
                    Boolean(selected && !dirty && !needsConversationSave)
                  }
                >
                  {busy === "save" ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <FileText size={16} />
                  )}
                  {busy === "save" ? "Сохраняем…" : "Сохранить черновик"}
                </button>
                <button
                  className={`button ${needsSave ? "secondary" : "primary"}`}
                  type="button"
                  onClick={publish}
                  disabled={
                    Boolean(busy) ||
                    !selected ||
                    dirty ||
                    conflict ||
                    needsConversationSave ||
                    !unpublished
                  }
                >
                  {busy === "publish" ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Send size={16} />
                  )}
                  {busy === "publish"
                    ? "Публикуем…"
                    : selected?.status === "published"
                      ? "Опубликовать изменения"
                      : "Опубликовать"}
                </button>
                {dirty && selected && (
                  <span className="admin-field-hint">
                    Сохраните изменения, чтобы опубликовать их.
                  </span>
                )}
                {selected?.status === "published" && (
                  <button
                    className="admin-text-action"
                    type="button"
                    onClick={unpublish}
                    disabled={Boolean(busy) || dirty || conflict}
                  >
                    {busy === "unpublish"
                      ? "Снимаем с публикации…"
                      : "Снять с публикации"}
                  </button>
                )}
                {selected && selected.status !== "archived" && (
                  <button
                    className="admin-text-action admin-archive-action"
                    type="button"
                    onClick={() => setConfirmation({ kind: "archive" })}
                    disabled={Boolean(busy) || dirty || conflict}
                  >
                    <Archive size={15} />В архив
                  </button>
                )}
              </section>
              {selected && (
                <p className="admin-revision">
                  Версия {selected.revision} · обновлено{" "}
                  {dateLabel(selected.updated_at)}
                </p>
              )}
            </aside>
          </form>
        </>
      )}
      {confirmation && (
        <Modal
          title={
            confirmation.kind === "archive"
              ? "Перенести ситуацию в архив?"
              : confirmation.kind === "reload"
                ? "Загрузить версию сервера?"
                : "Оставить изменения несохранёнными?"
          }
          onClose={() => {
            if (!busy) setConfirmation(null);
          }}
        >
          <p className="admin-confirm-copy">
            {confirmation.kind === "archive"
              ? "Она исчезнет из каталога пользователей. Начатые разговоры останутся доступны. Позже ситуацию можно опубликовать снова."
              : confirmation.kind === "reload"
                ? "Поля редактора будут заменены последней сохранённой версией. Если хотите сохранить свои тексты, сначала скопируйте их."
                : "Изменения в редакторе будут потеряны. Вернитесь к редактированию, чтобы сохранить черновик."}
          </p>
          <div className="admin-confirm-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setConfirmation(null)}
              disabled={Boolean(busy)}
            >
              Остаться в редакторе
            </button>
            <button
              className="button primary"
              type="button"
              disabled={Boolean(busy)}
              onClick={() => {
                if (confirmation.kind === "archive") archive();
                else if (confirmation.kind === "reload") loadCurrentVersion();
                else if (confirmation.kind === "navigation") {
                  const proceed = confirmation.proceed;
                  allowNavigation.current = true;
                  setConfirmation(null);
                  proceed();
                } else {
                  const next = confirmation.next;
                  setConfirmation(null);
                  if (next === "new") openEditor(null);
                  else {
                    setEditing(false);
                    setError("");
                    setConflict(false);
                  }
                }
              }}
            >
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <ArrowUpRight size={16} />
              )}
              {confirmation.kind === "archive"
                ? "В архив"
                : confirmation.kind === "reload"
                  ? "Загрузить"
                  : "Не сохранять"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
