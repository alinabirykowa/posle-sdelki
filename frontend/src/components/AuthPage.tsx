import { useState } from "react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import { errorMessage } from "../api";
import { workspaceApi, type Account } from "../workspace-api";

export function AuthPage({
  adminEntry = false,
  onSuccess,
}: {
  adminEntry?: boolean;
  onSuccess: (user: Account) => void;
}) {
  const [register, setRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = register
        ? await workspaceApi.register(username.trim(), name.trim(), password)
        : await workspaceApi.login(username.trim(), password);
      setPassword("");
      onSuccess(result.user);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="account-page page-enter">
      <div className="account-intro">
        <span className="workspace-eyebrow">
          {adminEntry ? "ДЛЯ АДМИНИСТРАТОРА" : "ЛИЧНОЕ ПРОСТРАНСТВО"}
        </span>
        <h1>
          {adminEntry ? (
            <>
              Задайте контекст.
              <br />
              <em>Дайте практику.</em>
            </>
          ) : (
            <>
              Каждый разговор —<br />
              <em>шаг вперёд.</em>
            </>
          )}
        </h1>
        <p>
          {adminEntry
            ? "Создавайте ситуации, настраивайте собеседника и публикуйте задания для участников."
            : "Проходите ситуации из каталога и возвращайтесь к своим разговорам с любого устройства."}
        </p>
        <div className="account-path" aria-hidden="true">
          <span>Ситуация</span>
          <ArrowRight size={16} />
          <span>Разговор</span>
          <ArrowRight size={16} />
          <span>Разбор</span>
        </div>
        <div className="account-note">
          <ShieldCheck size={21} />
          <p>
            {adminEntry
              ? "Доступ выдаёт владелец проекта. Обычная регистрация создаёт аккаунт участника."
              : "История сохраняется в вашем аккаунте. Разговоры, начатые без входа, остаются отдельно в этом браузере."}
          </p>
        </div>
      </div>
      <div className="account-card">
        <div className="account-card-heading">
          <LockKeyhole size={22} />
          <span>
            {adminEntry ? "КАБИНЕТ АДМИНИСТРАТОРА" : "ПОСЛЕ СДЕЛКИ / ВХОД"}
          </span>
        </div>
        <h2>{register ? "Приятно познакомиться" : "Продолжим практику?"}</h2>
        <p>
          {register
            ? "Создайте аккаунт участника — это бесплатно."
            : "Введите логин и пароль своего аккаунта."}
        </p>
        {!adminEntry && (
          <div className="account-tabs" aria-label="Вход или регистрация">
            <button
              type="button"
              aria-pressed={!register}
              disabled={busy}
              onClick={() => {
                setRegister(false);
                setError("");
                setPassword("");
              }}
            >
              Войти
            </button>
            <button
              type="button"
              aria-pressed={register}
              disabled={busy}
              onClick={() => {
                setRegister(true);
                setError("");
                setPassword("");
              }}
            >
              Создать аккаунт
            </button>
          </div>
        )}
        <form onSubmit={submit}>
          {register && (
            <label className="account-field">
              Как вас зовут
              <input
                name="name"
                autoComplete="name"
                required
                maxLength={80}
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={busy}
                placeholder="Например, Алина"
              />
            </label>
          )}
          <label className="account-field">
            Логин
            <input
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={register ? 3 : 1}
              maxLength={80}
              pattern={register ? "[a-zA-Z0-9._@+\\-]+" : undefined}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={busy}
              placeholder="your.name"
              aria-describedby={register ? "username-hint" : undefined}
            />
          </label>
          {register && (
            <p className="account-field-hint" id="username-hint">
              От 3 символов: латинские буквы, цифры, . _ @ + −
            </p>
          )}
          <label className="account-field" htmlFor="account-password">
            Пароль
          </label>
          <div className="account-password">
            <input
              id="account-password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete={register ? "new-password" : "current-password"}
              required
              minLength={register ? 10 : 1}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
              placeholder={register ? "Не меньше 10 символов" : "Ваш пароль"}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? <EyeOff size={19} /> : <Eye size={19} />}
            </button>
          </div>
          {error && (
            <p className="workspace-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="button primary full" disabled={busy}>
            {busy ? "Подождите…" : register ? "Создать аккаунт" : "Войти"}
            <ArrowRight size={18} />
          </button>
        </form>
        <p className="account-entry-link">
          {adminEntry ? (
            <a href="#/login">
              Я участник <ArrowRight size={14} aria-hidden="true" />
            </a>
          ) : (
            <a href="#/admin">
              Вход для администратора{" "}
              <ArrowRight size={14} aria-hidden="true" />
            </a>
          )}
        </p>
      </div>
    </section>
  );
}
