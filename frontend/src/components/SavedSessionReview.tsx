import { useEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage } from "../api";
import type { Session } from "../types";
import { Loading } from "./UI";
import { SessionReview } from "./SessionReview";
import { ResultView } from "./ResultView";

export function SavedSessionReview({
  id,
  onRetry,
  onPractice,
  onContinue,
}: {
  id: string;
  onRetry: (id: string) => void | Promise<void>;
  onPractice: () => void;
  onContinue: (id: string) => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    let alive = true;
    let refreshing = false;
    let latestStatus: Session["status"] | null = null;
    mounted.current = true;
    setLoading(true);
    setSession(null);
    setError("");

    async function refresh() {
      if (!alive || refreshing || document.visibilityState !== "visible")
        return;
      refreshing = true;
      try {
        const value = await api.session(id);
        if (!alive) return;
        latestStatus = value.status;
        setSession(value);
        setError("");
      } catch (cause) {
        if (!alive) return;
        // A revoked or missing session must not remain visible as cached data.
        if (cause instanceof ApiError && [401, 403, 404].includes(cause.status))
          setSession(null);
        setError(errorMessage(cause));
      } finally {
        refreshing = false;
        if (alive) setLoading(false);
      }
    }
    const onReturn = () => {
      if (latestStatus !== "completed") void refresh();
    };
    void refresh();
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      alive = false;
      mounted.current = false;
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [id, reload]);
  async function retry() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await onRetry(id);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  if (loading) return <Loading label="Открываем сохранённый разбор…" />;
  if (!session)
    return (
      <section className="progress-error" role="alert">
        <h2>Не получилось открыть разбор</h2>
        <p>{error}</p>
        <button type="button" onClick={() => setReload((value) => value + 1)}>
          Повторить загрузку
        </button>
        <p>
          <a href="#/progress">К моему прогрессу</a>
        </p>
      </section>
    );
  if (session.status !== "completed")
    return (
      <section className="progress-next">
        <div>
          <h2>Этот разговор ещё идёт</h2>
          <p>Разбор появится, когда вы завершите попытку.</p>
          {error && (
            <p role="status">
              Не удалось обновить состояние разговора. {error}
            </p>
          )}
        </div>
        <button className="button primary" onClick={() => onContinue(id)}>
          Продолжить разговор
        </button>
      </section>
    );
  if (session.scenario.practice_model !== "conversation")
    return (
      <section className="cabinet-legacy-review">
        <p>Сохранённый разбор прежнего формата тренировки.</p>
        <ResultView
          embedded
          session={session}
          busy={busy}
          error={error}
          onRetry={() => void retry()}
        />
      </section>
    );
  return (
    <SessionReview
      session={session}
      busy={busy}
      error={error}
      onRetry={() => void retry()}
      onPractice={onPractice}
    />
  );
}
