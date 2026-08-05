from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st


CATEGORY_COLORS = {
    "Території можливих бойових дій": "#3B82F6",
    "Території активних бойових дій": "#DC2626",
    "Території активних бойових дій, на яких функціонують державні електронні інформаційні ресурси": "#F59E0B",
    "Тимчасово окуповані території": "#581C87",
}
DEFAULT_CATEGORY_COLOR = "#64748B"


def _format_date(value: object, empty: str = "не зазначено") -> str:
    timestamp = pd.to_datetime(value, errors="coerce")
    return empty if pd.isna(timestamp) else timestamp.strftime("%d.%m.%Y")


def _prepare_display_table(data: pd.DataFrame) -> pd.DataFrame:
    table = data.copy()
    table["status_from"] = pd.to_datetime(table["status_from"], errors="coerce").dt.strftime(
        "%d.%m.%Y"
    ).fillna("не зазначено")
    table["status_to"] = pd.to_datetime(table["status_to"], errors="coerce").dt.strftime(
        "%d.%m.%Y"
    ).fillna("чинний / не зазначено")
    table["loaded_at"] = pd.to_datetime(table["loaded_at"], errors="coerce").dt.strftime(
        "%d.%m.%Y %H:%M"
    ).fillna("")
    visible = [
        "full_code",
        "hromada_code_7",
        "territory_name",
        "oblast",
        "rayon",
        "category",
        "status_from",
        "status_to",
        "loaded_at",
    ]
    table = table[[column for column in visible if column in table.columns]]
    return table.rename(
        columns={
            "full_code": "Повний код",
            "hromada_code_7": "Код громади",
            "territory_name": "Назва території",
            "oblast": "Область",
            "rayon": "Район",
            "category": "Категорія",
            "status_from": "Початок статусу",
            "status_to": "Кінець статусу",
            "loaded_at": "Завантажено в базу",
        }
    )


def _search_history(data: pd.DataFrame, search_text: str) -> pd.DataFrame:
    search_columns = ("territory_name", "full_code", "hromada_code_7", "rayon", "oblast")
    mask = pd.Series(False, index=data.index)
    for column in search_columns:
        if column in data.columns:
            mask = mask | data[column].astype(str).str.contains(
                search_text,
                case=False,
                na=False,
                regex=False,
            )
    return data[mask].sort_values(["territory_name", "status_from", "status_to"], na_position="last")


def _territory_options(history: pd.DataFrame) -> tuple[list[str], dict[str, tuple[str, str, str, str]]]:
    options: dict[str, tuple[str, str, str, str]] = {}
    unique_rows = history[
        ["full_code", "territory_name", "oblast", "rayon"]
    ].drop_duplicates()
    for _, row in unique_rows.iterrows():
        full_code = str(row.get("full_code") or "")
        territory = str(row.get("territory_name") or "Без назви")
        oblast = str(row.get("oblast") or "")
        rayon = str(row.get("rayon") or "")
        label = f"{territory} — {rayon}, {oblast} · {full_code}"
        options[label] = (full_code, territory, oblast, rayon)
    return sorted(options), options


def _select_territory(history: pd.DataFrame, key: tuple[str, str, str, str]) -> pd.DataFrame:
    full_code, territory, oblast, rayon = key
    selected = history[
        (history["full_code"].astype(str) == full_code)
        & (history["territory_name"].astype(str) == territory)
        & (history["oblast"].astype(str) == oblast)
        & (history["rayon"].astype(str) == rayon)
    ].copy()
    return selected.sort_values(["status_from", "status_to"], na_position="last")


def _timeline_frame(history: pd.DataFrame) -> pd.DataFrame:
    timeline = history.copy()
    timeline["status_from"] = pd.to_datetime(timeline["status_from"], errors="coerce")
    timeline["status_to"] = pd.to_datetime(timeline["status_to"], errors="coerce")
    timeline = timeline[timeline["status_from"].notna()].copy()
    if timeline.empty:
        return timeline

    today = pd.Timestamp.today().normalize()
    timeline["is_open"] = timeline["status_to"].isna()
    timeline["plot_end"] = timeline["status_to"].fillna(today)
    timeline.loc[timeline["plot_end"] < timeline["status_from"], "plot_end"] = (
        timeline.loc[timeline["plot_end"] < timeline["status_from"], "status_from"]
    )
    # Додаємо один день, оскільки дата завершення в офіційному переліку включна.
    timeline["plot_end_exclusive"] = timeline["plot_end"] + pd.Timedelta(days=1)
    timeline["duration_days"] = (
        timeline["plot_end"] - timeline["status_from"]
    ).dt.days.add(1).clip(lower=1)
    timeline["Період"] = timeline.apply(
        lambda row: (
            f"{row['status_from'].strftime('%d.%m.%Y')} — "
            + ("чинний" if row["is_open"] else row["status_to"].strftime("%d.%m.%Y"))
        ),
        axis=1,
    )
    timeline["Тривалість"] = timeline["duration_days"].apply(lambda days: f"{int(days)} дн.")
    timeline["Шлях"] = "Статус"
    return timeline


def _render_timeline_chart(timeline: pd.DataFrame) -> None:
    categories = timeline["category"].dropna().astype(str).unique().tolist()
    colors = [CATEGORY_COLORS.get(category, DEFAULT_CATEGORY_COLOR) for category in categories]

    bars = (
        alt.Chart(timeline)
        .mark_bar(cornerRadius=7, height=42)
        .encode(
            x=alt.X(
                "status_from:T",
                title="Час",
                axis=alt.Axis(format="%m.%Y", labelAngle=0),
            ),
            x2="plot_end_exclusive:T",
            y=alt.Y("Шлях:N", title=None, axis=None),
            color=alt.Color(
                "category:N",
                title="Категорія",
                scale=alt.Scale(domain=categories, range=colors),
            ),
            tooltip=[
                alt.Tooltip("territory_name:N", title="Територія"),
                alt.Tooltip("category:N", title="Статус"),
                alt.Tooltip("Період:N", title="Період"),
                alt.Tooltip("Тривалість:N", title="Тривалість"),
                alt.Tooltip("full_code:N", title="Код"),
            ],
        )
    )

    starts = (
        alt.Chart(timeline)
        .mark_point(filled=True, size=95, color="#0F172A", stroke="white", strokeWidth=1.5)
        .encode(x="status_from:T", y=alt.Y("Шлях:N", axis=None), tooltip=["Період:N"])
    )

    chart = (bars + starts).properties(height=145).interactive()
    st.altair_chart(chart, use_container_width=True)
    st.caption("Наведіть курсор на сегмент для деталей. Шкалу можна наближати й пересувати.")


def _transition_note(previous: pd.Series, current: pd.Series) -> str | None:
    previous_to = pd.to_datetime(previous.get("status_to"), errors="coerce")
    current_from = pd.to_datetime(current.get("status_from"), errors="coerce")
    if pd.isna(previous_to) or pd.isna(current_from):
        return None
    difference = (current_from - previous_to).days
    if difference == 1:
        return "Наступний статус почався одразу після завершення попереднього."
    if difference > 1:
        return f"Між статусами є проміжок {difference - 1} дн."
    return f"Періоди перетинаються на {abs(difference) + 1} дн."


def _render_path_steps(timeline: pd.DataFrame) -> None:
    st.markdown("#### Послідовність переходів")
    records = list(timeline.iterrows())
    for position, (_, row) in enumerate(records, start=1):
        color = CATEGORY_COLORS.get(str(row.get("category")), DEFAULT_CATEGORY_COLOR)
        end_text = "чинний" if bool(row.get("is_open")) else _format_date(row.get("status_to"))
        category = html.escape(str(row.get("category") or "Статус не зазначено"))
        start_text = _format_date(row.get("status_from"))
        duration = int(row.get("duration_days") or 0)
        systems_value = row.get("systems_functioning") if "systems_functioning" in row.index else None
        systems_text = ""
        if systems_value not in (None, "", "nan") and not pd.isna(systems_value):
            systems_text = f" · Системи: {html.escape(str(systems_value))}"

        st.markdown(
            f"""
            <div style="border-left:6px solid {color};padding:.8rem 1rem;margin:.45rem 0;
                        border-radius:12px;background:#F8FAFC;border-top:1px solid #E2E8F0;
                        border-right:1px solid #E2E8F0;border-bottom:1px solid #E2E8F0;">
              <div style="font-size:.82rem;color:#64748B;font-weight:700;">ЕТАП {position}</div>
              <div style="font-size:1.02rem;font-weight:700;color:#0F172A;margin:.15rem 0;">{category}</div>
              <div style="color:#334155;">{start_text} — {end_text} · {duration} дн.{systems_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if position < len(records):
            note = _transition_note(row, records[position][1])
            transition_text = "↓ Перехід до наступного статусу"
            if note:
                transition_text += f" · {note}"
            st.caption(transition_text)


def _render_interactive_history(history: pd.DataFrame) -> None:
    labels, options = _territory_options(history)
    if not labels:
        st.info("Не вдалося сформувати перелік територій для інтерактивного перегляду.")
        return

    selected_label = st.selectbox(
        "Оберіть конкретну територію",
        labels,
        key="interactive_history_territory",
    )
    selected = _select_territory(history, options[selected_label])
    timeline = _timeline_frame(selected)
    if timeline.empty:
        st.warning("Для вибраної території немає коректно визначених дат початку статусів.")
        return

    first = timeline.iloc[0]
    latest = timeline.iloc[-1]
    current_rows = timeline[timeline["is_open"]]
    current_status = (
        str(current_rows.iloc[-1]["category"])
        if not current_rows.empty
        else f"Останній: {latest['category']}"
    )
    total_days = int(timeline["duration_days"].sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Етапів", len(timeline))
    m2.metric("Переходів", max(len(timeline) - 1, 0))
    m3.metric("Початок історії", _format_date(first["status_from"]))
    m4.metric("Сумарно у статусах", f"{total_days:,} дн.".replace(",", " "))

    st.markdown(
        f"**Поточний стан:** {html.escape(current_status)}  \n"
        f"**Код:** `{html.escape(str(first.get('full_code') or ''))}`"
    )
    _render_timeline_chart(timeline)
    _render_path_steps(timeline)

    with st.expander("Показати табличні дані вибраної території"):
        st.dataframe(_prepare_display_table(selected), use_container_width=True, hide_index=True)


def _render_document_history(document_history: pd.DataFrame) -> None:
    with st.expander("Збережені редакції документа"):
        display_history = document_history.copy()
        display_history["base_document_date"] = pd.to_datetime(
            display_history["base_document_date"], errors="coerce"
        ).dt.strftime("%d.%m.%Y")
        display_history["edition_date"] = pd.to_datetime(
            display_history["edition_date"], errors="coerce"
        ).dt.strftime("%d.%m.%Y").fillna("не визначена")
        display_history["loaded_at"] = pd.to_datetime(
            display_history["loaded_at"], errors="coerce"
        ).dt.strftime("%d.%m.%Y %H:%M")
        st.dataframe(
            display_history.rename(
                columns={
                    "id": "ID",
                    "base_document_number": "Номер наказу",
                    "base_document_date": "Дата наказу",
                    "edition_date": "Дата редакції",
                    "row_count": "Записів",
                    "loaded_at": "Завантажено",
                    "source_page_url": "Сторінка джерела",
                    "source_file_url": "Файл джерела",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


def render_history_tab(data: pd.DataFrame, document_history: pd.DataFrame) -> None:
    st.subheader("Історія статусу території в поточній редакції")
    history_search = st.text_input(
        "Назва території, району, області або код",
        key="history_search",
    )
    if not history_search:
        st.info("Введіть назву або код.")
        _render_document_history(document_history)
        return

    history = _search_history(data, history_search)
    st.metric("Знайдено записів", len(history))
    if history.empty:
        st.warning("За цим запитом нічого не знайдено.")
        _render_document_history(document_history)
        return

    mode = st.radio(
        "Формат відображення",
        ["Табличний", "Інтерактивний шлях"],
        horizontal=True,
        key="history_view_mode",
    )
    if mode == "Табличний":
        st.dataframe(_prepare_display_table(history), use_container_width=True, hide_index=True)
    else:
        _render_interactive_history(history)

    _render_document_history(document_history)
