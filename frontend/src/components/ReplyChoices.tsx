import { useEffect, useId, useState } from "react";
import {
  ArrowDownLeft,
  MessageCircle,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import type { ReplyChoice } from "../types";
import "../reply-choices.css";

const groups = [
  { id: "explore", label: "Выяснить детали", icon: Search },
  { id: "respond", label: "Ответить клиенту", icon: MessageCircle },
  { id: "negotiate", label: "Обсудить вариант", icon: SlidersHorizontal },
] as const;

export type ChoiceResult = "added" | "existing" | "limit";

export function ReplyChoices({
  choices,
  suggestions,
  hint,
  contextKey,
  disabled,
  onChoose,
}: {
  choices?: ReplyChoice[];
  suggestions: string[];
  hint?: string;
  contextKey?: string;
  disabled: boolean;
  onChoose: (text: string) => ChoiceResult;
}) {
  const titleId = useId();
  const optionsId = useId();
  const [group, setGroup] = useState<ReplyChoice["group"]>("explore");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const availableGroups = groups.filter((item) =>
    choices?.some((choice) => choice.group === item.id),
  );
  const activeGroup = availableGroups.some((item) => item.id === group)
    ? group
    : availableGroups[0]?.id;
  const hasGroups = availableGroups.length > 0;
  const visibleChoices: ReplyChoice[] = hasGroups
    ? (choices || []).filter((choice) => choice.group === activeGroup)
    : suggestions.slice(0, 3).map((text, index) => ({
        id: `legacy-${index}`,
        group: "explore",
        label: text,
        text,
      }));

  useEffect(() => {
    setSelectedId(null);
    setNotice("");
  }, [contextKey]);

  if (!visibleChoices.length) return null;

  function choose(choice: ReplyChoice) {
    const result = onChoose(choice.text);
    setSelectedId(result === "limit" ? null : choice.id);
    setNotice(
      result === "limit"
        ? "В черновике недостаточно места. Сократите его, чтобы добавить реплику. Лимит — 2000 знаков."
        : result === "existing"
          ? "Эта реплика уже есть в черновике. Можно изменить её перед отправкой."
          : "Реплика добавлена в черновик. Проверьте и измените её перед отправкой.",
    );
  }

  return (
    <section className="reply-choices" aria-labelledby={titleId}>
      <div className="reply-choices-heading">
        <h2 id={titleId}>Как продолжим разговор?</h2>
        <span>Идеи для вашей реплики</span>
      </div>
      {hint && <p className="reply-choices-context">{hint}</p>}
      {hasGroups && (
        <div
          className="reply-groups"
          role="group"
          aria-label="Направление разговора"
        >
          {availableGroups.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              key={id}
              aria-pressed={id === activeGroup}
              aria-controls={optionsId}
              disabled={disabled}
              onClick={() => setGroup(id)}
            >
              <Icon size={14} aria-hidden="true" />
              <span>{label}</span>
              <small>
                {choices?.filter((choice) => choice.group === id).length}
              </small>
            </button>
          ))}
        </div>
      )}
      <div className="reply-options" id={optionsId}>
        {visibleChoices.map((choice) => (
          <button
            type="button"
            className={
              selectedId === choice.id
                ? "reply-option selected"
                : "reply-option"
            }
            key={choice.id}
            disabled={disabled}
            onClick={() => choose(choice)}
            aria-label={`${choice.label}. Добавить реплику в черновик`}
          >
            <span>{choice.label}</span>
            <ArrowDownLeft size={15} aria-hidden="true" />
          </button>
        ))}
      </div>
      <p
        className={`reply-choices-note ${notice ? "has-notice" : ""}`}
        role="status"
      >
        {notice ||
          "Нажмите на идею — реплика появится в поле ответа. Можно отредактировать её или написать свою."}
      </p>
    </section>
  );
}
