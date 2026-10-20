"use client";

import { useId, useState } from "react";

import { useCardSearch } from "@/hooks/use-card-search";
import { MAX_CARD_NAMES } from "@/lib/api";
import type { FormatName } from "@/lib/types";

type Props = {
  label: string;
  help?: string;
  format: FormatName | null;
  values: string[];
  onChange: (values: string[]) => void;
  /** Used in accessible names, e.g. "include" → "Remove Lightning Bolt from include list". */
  listNoun: string;
};

/**
 * A list of card names with name autocomplete (ARIA combobox). Enter adds the
 * highlighted suggestion, or the typed text when nothing matches (the backend
 * reports unknown names back in the deck's provenance).
 */
export function CardListInput({ label, help, format, values, onChange, listNoun }: Props) {
  const id = useId();
  const inputId = `${id}-input`;
  const listboxId = `${id}-listbox`;
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [focused, setFocused] = useState(false);
  const { results, loading } = useCardSearch(query, format, focused);
  const suggestions = results.filter((card) => !values.some((value) => value.toLowerCase() === card.name.toLowerCase())).slice(0, 8);
  const expanded = focused && query.trim().length >= 2 && suggestions.length > 0;
  const full = values.length >= MAX_CARD_NAMES;

  function add(name: string) {
    const trimmed = name.trim();
    if (!trimmed || full) return;
    if (!values.some((value) => value.toLowerCase() === trimmed.toLowerCase())) onChange([...values, trimmed]);
    setQuery("");
    setActiveIndex(0);
  }

  return (
    <div className="card-list-input">
      <label className="label" htmlFor={inputId}>{label}</label>
      {help ? <p className="muted field-help">{help}</p> : null}
      {values.length ? (
        <ul className="chips selected-card-chips" aria-label={`${label} (${values.length})`}>
          {values.map((value) => (
            <li key={value}>
              <button
                type="button"
                className="chip chip-removable"
                aria-label={`Remove ${value} from ${listNoun} list`}
                onClick={() => onChange(values.filter((item) => item !== value))}
              >
                {value} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="combobox">
        <input
          id={inputId}
          className="input"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={expanded ? `${listboxId}-${activeIndex}` : undefined}
          value={query}
          disabled={full}
          placeholder={full ? `Limit of ${MAX_CARD_NAMES} cards reached` : "Type a card name"}
          onFocus={() => setFocused(true)}
          // Delay so a click on a suggestion lands before the list closes.
          onBlur={() => setTimeout(() => setFocused(false), 150)}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" && expanded) {
              event.preventDefault();
              setActiveIndex((index) => Math.min(index + 1, suggestions.length - 1));
            } else if (event.key === "ArrowUp" && expanded) {
              event.preventDefault();
              setActiveIndex((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              add(expanded ? suggestions[activeIndex]?.name ?? query : query);
            } else if (event.key === "Escape" && query) {
              event.stopPropagation();
              setQuery("");
            }
          }}
        />
        {expanded ? (
          <ul id={listboxId} role="listbox" className="combobox-list" aria-label={`${label} suggestions`}>
            {suggestions.map((card, index) => (
              <li
                key={card.name}
                id={`${listboxId}-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                className={`combobox-option ${index === activeIndex ? "active" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => add(card.name)}
              >
                <span>{card.name}</span>
                <span className="muted">{card.type_line}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {focused && loading && query.trim().length >= 2 ? <p className="muted field-help">Searching…</p> : null}
      </div>
    </div>
  );
}
