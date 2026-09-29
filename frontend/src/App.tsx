import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  LogOut,
  Sparkles,
} from "lucide-react";
import { api, errorMessage } from "./api";
import type { ReplyMode, RouteStageId, Session } from "./types";
import { Brand, Loading, Modal } from "./components/UI";
import { SessionPage } from "./components/SessionPage";
import { HistoryPage } from "./components/HistoryPage";
import { TrainingBuilder } from "./components/TrainingBuilder";
import { AuthPage } from "./components/AuthPage";
import { AdminPage } from "./components/AdminPage";
import { CatalogPage } from "./components/CatalogPage";
import { ProgressPage } from "./components/ProgressPage";
import { pendingActions } from "./recovery";
import { progressRoute, sessionDestination } from "./navigation";
import { workspaceApi, type Account } from "./workspace-api";
import "./account-workspace.css";

const readRoute = () => window.location.hash.slice(1) || "/";
function navigate(path: string, replace = false) {
  if (replace) window.location.replace(`#${path}`);
  else window.location.hash = path;
  window.scrollTo({ top: 0, behavior: "instant" });
}

export function App() {
  const [route, setRoute] = useState(readRoute);
  const acceptedRoute = useRef(readRoute());
  const approvedNavigation = useRef(false);
  const navigationSequence = useRef(0);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState("");
  const refreshRequest = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [liveAvailable, setLiveAvailable] = useState(false);
  const [liveReplyMode, setLiveReplyMode] = useState<ReplyMode>("rules");
  const [help, setHelp] = useState(false);
  const [user, setUser] = useState<Account | null>(null);
  const identity = useRef<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [catalogVersion, setCatalogVersion] = useState(0);
  const [practiceRouteStage, setPracticeRouteStage] =
    useState<RouteStageId | null>(null);
  const authRequest = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++refreshRequest.current;
    // Saved conversations belong to the cabinet; practice needs no history.
    if (acceptedRoute.current !== "/history") return;
    setSessionsLoading(true);
    setSessionsError("");
    try {
      const data = await api.sessions();
      if (request === refreshRequest.current) setSessions(data.sessions);
    } catch (e) {
      if (request === refreshRequest.current) setSessionsError(errorMessage(e));
    } finally {
      if (request === refreshRequest.current) setSessionsLoading(false);
    }
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.scenarios();
      setLiveAvailable(data.live_available);
      setLiveReplyMode(data.live_reply_mode ?? "rules");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);
  const acceptAccount = useCallback(
    (account: Account | null) => {
      const nextIdentity = account ? `${account.id}:${account.role}` : "guest";
      const changed = identity.current !== nextIdentity;
      identity.current = nextIdentity;
      setUser(account);
      if (changed) {
        ++refreshRequest.current;
        setSessions([]);
        setSessionsError("");
        void refresh();
      }
    },
    [refresh],
  );
  const loadAccount = useCallback(async () => {
    const request = ++authRequest.current;
    setAuthError("");
    try {
      const result = await workspaceApi.me();
      if (request === authRequest.current) acceptAccount(result.user);
    } catch (e) {
      if (request === authRequest.current) setAuthError(errorMessage(e));
    } finally {
      if (request === authRequest.current) setAuthLoading(false);
    }
  }, [acceptAccount]);
  function signedIn(account: Account) {
    ++authRequest.current;
    acceptAccount(account);
    setAuthError("");
    setLogoutError("");
    navigate(
      route === "/admin" && account.role === "admin" ? "/admin" : "/catalog",
    );
  }
  async function logout(confirmed = false) {
    if (logoutBusy) return;
    if (
      !confirmed &&
      !window.dispatchEvent(
        new CustomEvent("posle:before-leave", {
          cancelable: true,
          detail: { proceed: () => logout(true) },
        }),
      )
    )
      return;
    setLogoutBusy(true);
    setLogoutError("");
    ++authRequest.current;
    try {
      await workspaceApi.logout();
      acceptAccount(null);
      navigate("/login");
    } catch (e) {
      setLogoutError(errorMessage(e));
    } finally {
      setLogoutBusy(false);
    }
  }
  useEffect(() => {
    void load();
    void loadAccount();
  }, [load, loadAccount]);
  useEffect(() => {
    const sync = () => {
      if (document.visibilityState === "visible" && !logoutBusy)
        void loadAccount();
    };
    window.addEventListener("focus", sync);
    const timer = window.setInterval(sync, 60_000);
    return () => {
      window.removeEventListener("focus", sync);
      window.clearInterval(timer);
    };
  }, [loadAccount, logoutBusy]);
  useEffect(() => {
    const handler = () => {
      const nextRoute = readRoute();
      if (nextRoute === acceptedRoute.current) return;
      if (
        !approvedNavigation.current &&
        !window.dispatchEvent(
          new CustomEvent("posle:before-leave", {
            cancelable: true,
            detail: {
              proceed: () => {
                approvedNavigation.current = true;
                window.history.back();
              },
            },
          }),
        )
      ) {
        // A hash history traversal cannot be cancelled. Restore the editor
        // before rendering another route; its destination stays one step back.
        window.history.pushState(null, "", `#${acceptedRoute.current}`);
        return;
      }
      approvedNavigation.current = false;
      navigationSequence.current += 1;
      acceptedRoute.current = nextRoute;
      setRoute(nextRoute);
      void refresh();
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, [refresh]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [route]);
  const history = route === "/history";
  const progress = progressRoute(route);
  const sessionId = route.startsWith("/session/") ? route.split("/")[2] : null;
  const openSession = (session: Session) => {
    if (session.route_stage) setPracticeRouteStage(null);
    void refresh();
    navigate(sessionDestination(session));
  };
  function startRoutePractice(stage: RouteStageId | null) {
    setPracticeRouteStage(stage);
    navigate("/");
  }
  function startGeneralPractice() {
    setPracticeRouteStage(null);
    navigate("/");
  }
  async function retryFromCabinet(id: string) {
    const owner = identity.current;
    const navigation = navigationSequence.current;
    const key = `pending-retry:${id}`;
    const pending = pendingActions.get(key, "retry");
    const next = await api.retry(id, pending.id);
    pendingActions.clear(key, pending.id);
    if (owner === identity.current && navigation === navigationSequence.current)
      openSession(next);
  }

  return (
    <div className={`app-shell studio-app ${sessionId ? "in-session" : ""}`}>
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus({ preventScroll: true });
          document
            .getElementById("main")
            ?.scrollIntoView({ block: "start", behavior: "instant" });
        }}
      >
        К основному содержимому
      </a>
      <header className="studio-header">
        <div className="studio-header-inner">
          <a
            className="studio-logo"
            href="#/"
            aria-label="После сделки — главная"
          >
            <Brand />
          </a>
          <nav className="studio-nav" aria-label="Основная навигация">
            <a
              href="#/"
              className={route === "/" || sessionId ? "is-current" : ""}
              aria-current={route === "/" ? "page" : undefined}
            >
              Практика
            </a>
            <a
              href="#/catalog"
              className={route === "/catalog" ? "is-current" : ""}
              aria-current={route === "/catalog" ? "page" : undefined}
            >
              Ситуации
            </a>
            <a
              href="#/progress"
              className={history || progress.active ? "is-current" : ""}
              aria-current={progress.active ? "page" : undefined}
            >
              Личный кабинет
            </a>
            {user?.role === "admin" && (
              <a
                href="#/admin"
                className={route === "/admin" ? "is-current" : ""}
                aria-current={route === "/admin" ? "page" : undefined}
              >
                Управление
              </a>
            )}
          </nav>
          <div className="account-header">
            {!authLoading && user ? (
              <>
                <span className="account-avatar" aria-hidden="true">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </span>
                <div className="account-identity">
                  <strong title={user.display_name}>{user.display_name}</strong>
                  <span>
                    {user.role === "admin" ? "Администратор" : "Участник"}
                  </span>
                </div>
                <button
                  className="icon-button"
                  aria-label="Выйти из аккаунта"
                  title="Выйти"
                  disabled={logoutBusy}
                  onClick={() => void logout()}
                >
                  <LogOut size={18} />
                </button>
              </>
            ) : !authLoading && !authError ? (
              <a href="#/login" className="account-signin">
                Войти <ArrowUpRight size={16} aria-hidden="true" />
              </a>
            ) : null}
          </div>
        </div>
      </header>
      <main id="main" className="studio-main" tabIndex={-1}>
        {authError && identity.current !== null && (
          <div
            className="history-load-notice account-action-error"
            role="status"
          >
            <p>
              <strong>Не удалось обновить состояние входа</strong>
              {authError} Введённый текст остаётся в редакторе.
            </p>
            <button
              className="button secondary"
              onClick={() => void loadAccount()}
            >
              Проверить вход
            </button>
          </div>
        )}
        {logoutError && (
          <p className="workspace-error account-action-error" role="alert">
            Не удалось выйти. {logoutError}
          </p>
        )}
        {authLoading ? (
          <Loading label="Открываем ваш кабинет…" />
        ) : authError && identity.current === null ? (
          <div className="error-state">
            <h1>Не удалось проверить вход</h1>
            <p>{authError}</p>
            <button
              className="button primary"
              onClick={() => void loadAccount()}
            >
              Повторить <ArrowRight size={17} />
            </button>
          </div>
        ) : route === "/login" ? (
          user ? (
            <div className="workspace-access">
              <span className="workspace-eyebrow">ВЫ УЖЕ ВОШЛИ</span>
              <h1>{user.display_name}, добро пожаловать.</h1>
              <p>
                Ваш аккаунт: {user.username}.{" "}
                {user.role === "admin"
                  ? "Вам доступно управление ситуациями."
                  : "Выберите ситуацию и начните практику."}
              </p>
              <a
                className="button primary"
                href={user.role === "admin" ? "#/admin" : "#/catalog"}
              >
                {user.role === "admin"
                  ? "Открыть управление"
                  : "Открыть ситуации"}
                <ArrowRight size={17} />
              </a>
            </div>
          ) : (
            <AuthPage key="participant" onSuccess={signedIn} />
          )
        ) : route === "/admin" ? (
          !user ? (
            <AuthPage key="admin" adminEntry onSuccess={signedIn} />
          ) : user.role !== "admin" ? (
            <div className="workspace-access">
              <h1>Раздел для администратора</h1>
              <p>
                Вы вошли как участник. Опубликованные задания находятся в
                каталоге ситуаций.
              </p>
              <a href="#/catalog" className="button primary">
                Перейти к ситуациям <ArrowRight size={17} />
              </a>
            </div>
          ) : (
            <AdminPage
              key={user.id}
              onPublished={() => setCatalogVersion((value) => value + 1)}
            />
          )
        ) : loading ? (
          <Loading />
        ) : error ? (
          <div className="error-state">
            <h1>Не удалось открыть пространство</h1>
            <p>{error}</p>
            <button className="button primary" onClick={() => void load()}>
              Попробовать ещё раз <ArrowRight size={17} />
            </button>
          </div>
        ) : route === "/catalog" ? (
          <CatalogPage
            key={user?.id ?? "guest"}
            user={user}
            liveAvailable={liveAvailable}
            liveReplyMode={liveReplyMode}
            onStart={openSession}
            onLogin={() => navigate("/login")}
            refreshKey={catalogVersion}
          />
        ) : sessionId ? (
          <SessionPage
            key={`${user?.id ?? "guest"}:${sessionId}`}
            id={sessionId}
            onComplete={(session) => {
              const expectedOwner = user ? `${user.id}:${user.role}` : "guest";
              if (
                identity.current === expectedOwner &&
                acceptedRoute.current === `/session/${session.id}`
              )
                navigate(sessionDestination(session), true);
            }}
            onRefresh={refresh}
            onHelp={() => setHelp(true)}
          />
        ) : progress.active ? (
          <ProgressPage
            key={user?.id ?? "guest"}
            identityKey={user?.id ?? "guest"}
            authenticated={!!user}
            reviewId={progress.reviewId}
            onReview={(id) => navigate(`/progress/${encodeURIComponent(id)}`)}
            onOpen={(id) => navigate(`/session/${id}`)}
            onPractice={startGeneralPractice}
            onRoutePractice={startRoutePractice}
            onRetry={retryFromCabinet}
          />
        ) : history ? (
          <HistoryPage
            key={user?.id ?? "guest"}
            authenticated={!!user}
            sessions={sessions}
            loading={sessionsLoading}
            error={sessionsError}
            onRefresh={refresh}
            onOpen={openSession}
            onPractice={() => navigate("/")}
          />
        ) : (
          <>
            <div className="catalog-entry">
              <strong>Практика по готовому брифу</strong>
              <span>Ситуации, опубликованные администратором</span>
              <a href="#/catalog">
                В каталог <ArrowRight size={15} />
              </a>
            </div>
            <TrainingBuilder
              key={user?.id ?? "guest"}
              identityKey={user?.id ?? "guest"}
              onStart={openSession}
              liveAvailable={liveAvailable}
              liveReplyMode={liveReplyMode}
              routeStage={practiceRouteStage}
            />
          </>
        )}
      </main>
      <footer className="studio-footer">
        <Brand small />
        <span>Учебный тренажёр переговоров · ЛЦТ 2026</span>
        <button onClick={() => setHelp(true)}>
          О проекте <ArrowRight size={15} />
        </button>
      </footer>
      {help && (
        <Modal title="Практика с последствиями" onClose={() => setHelp(false)}>
          <div className="help-content">
            <p className="lead">
              После сделки — место для практики деловых переговоров. Попробуйте
              разные подходы перед настоящим разговором.
            </p>
            <div className="help-step">
              <span>01</span>
              <div>
                <h3>Соберите контекст</h3>
                <p>
                  Наставник или участник выбирает сферу, тему, роль, цель и тон
                  клиента. Конструктор собирает бриф из проверенных сценарных
                  вариантов. Длительность, формат и сложность настраиваются
                  отдельно.
                </p>
              </div>
            </div>
            <div className="help-step">
              <span>02</span>
              <div>
                <h3>Потренируйтесь в разговоре</h3>
                <p>
                  Пишите своими словами или отвечайте голосом. Выясните, что
                  важно собеседнику, объясните свою позицию и предложите
                  решение. Когда договоритесь, подведите итог.
                </p>
              </div>
            </div>
            <div className="help-step">
              <span>03</span>
              <div>
                <h3>Посмотрите, что получилось</h3>
                <p>
                  Разбор покажет конкретные реплики, проявленные навыки и
                  следующий шаг для практики. Разумный отказ тоже может быть
                  результатом.
                </p>
              </div>
            </div>
            <div className="info-panel">
              <Sparkles size={19} />
              <div>
                <strong>Режимы собеседника</strong>
                <p>
                  Демо работает на подготовленных сценариях и доступно сразу. В
                  режиме «AI-анализ» модель понимает смысл реплик, а ответы
                  следуют правилам кейса. В режиме «AI-собеседник» модель также
                  формулирует ответы с учётом разговора. Режим указан в
                  тренировке; AI доступен после подключения сервиса.
                </p>
                <p>
                  При использовании AI реплики обрабатывает внешний сервис.
                  Модель может ошибаться. Условия сделки фиксируются в карточке
                  предложения, и переписка сама по себе их не меняет.
                </p>
              </div>
            </div>
            <p className="fine-print">
              Ситуации учебные. Разбор относится к конкретному разговору и не
              оценивает вашу личность. После входа история сохраняется в
              аккаунте. Гостевые разговоры остаются в этом браузере отдельно.
              Администратор создаёт ситуации и публикует их в общем каталоге для
              участников. Голосовая практика использует возможности браузера.
            </p>
            <button
              className="button primary full"
              onClick={() => setHelp(false)}
            >
              Понятно, начинаем <Check size={18} />
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
