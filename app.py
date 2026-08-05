from __future__ import annotations

import html
import os
from pathlib import Path

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

from src.database import create_database_engine
from src.history_view import render_history_tab
from src.territory_service import (
    load_current_territories,
    load_document_history,
    load_latest_changes,
    load_latest_document,
)

st.set_page_config(
    page_title="Моніторинг територій",
    page_icon="🇺🇦",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 1.2rem;}
.hero {padding: 1.35rem 1.55rem; border-radius: 20px; background: linear-gradient(135deg,#0f172a 0%,#1e3a8a 58%,#0f766e 100%); color:white; margin-bottom:1rem; box-shadow:0 12px 28px rgba(15,23,42,.16);}
.hero h1 {margin:0 0 .45rem 0; font-size:2rem; line-height:1.15;}
.hero p {margin:0; opacity:.92; font-size:1rem;}
.source-card,.map-note,.insight-card {padding:.95rem 1.1rem; border-radius:16px; border:1px solid rgba(148,163,184,.3); background:rgba(248,250,252,.92); margin:.7rem 0 1rem 0;}
.map-note {background:rgba(239,246,255,.86); color:#1e3a8a;}
.small-note {color:#64748b; font-size:.9rem;}
.footer {margin-top:2.2rem; padding:1rem 0 .3rem; border-top:1px solid rgba(148,163,184,.35); color:#64748b; text-align:center; font-size:.9rem;}
div[data-testid="stMetric"] {background:rgba(248,250,252,.92); border:1px solid rgba(148,163,184,.28); border-radius:16px; padding:.7rem .85rem;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
st.markdown(
    """
    <div class="hero">
      <h1>Моніторинг територій бойових дій та тимчасово окупованих територій</h1>
      <p>Технічне відображення офіційного переліку за областями, районами, громадами, категоріями та датами дії статусу.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


def resolve_database_url() -> str | None:
    env_value = os.getenv("DATABASE_URL", "").strip()
    if env_value:
        return env_value
    try:
        secret_value = str(st.secrets.get("DATABASE_URL", "")).strip()
    except Exception:
        secret_value = ""
    return secret_value or None


@st.cache_resource
def get_engine(database_url: str):
    return create_database_engine(database_url)


@st.cache_data(ttl=600)
def cached_latest_document(database_url: str) -> pd.DataFrame:
    return load_latest_document(get_engine(database_url))


@st.cache_data(ttl=600)
def cached_territories(database_url: str) -> pd.DataFrame:
    return load_current_territories(get_engine(database_url))


@st.cache_data(ttl=600)
def cached_changes(database_url: str) -> pd.DataFrame:
    return load_latest_changes(get_engine(database_url))


@st.cache_data(ttl=600)
def cached_document_history(database_url: str) -> pd.DataFrame:
    return load_document_history(get_engine(database_url))


def normalize_oblast_name(value: object) -> str | None:
    if pd.isna(value):
        return None
    normalized = str(value).strip().lower()
    normalized = normalized.replace("область", "").replace("м.", "")
    return " ".join(normalized.split())


@st.cache_data
def load_oblast_centers() -> dict[str, dict[str, object]]:
    path = Path(__file__).parent / "data" / "oblast_centers.csv"
    frame = pd.read_csv(path)
    return {
        row["oblast_key"]: {
            "label": row["oblast_label"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
        }
        for _, row in frame.iterrows()
    }


CATEGORY_COLORS = {
    "Території можливих бойових дій": [59, 130, 246, 165],
    "Території активних бойових дій": [220, 38, 38, 185],
    "Території активних бойових дій, на яких функціонують державні електронні інформаційні ресурси": [245, 158, 11, 180],
    "Тимчасово окуповані території": [88, 28, 135, 180],
}
DEFAULT_COLOR = [15, 118, 110, 165]


def dominant_category(values: pd.Series) -> str:
    return values.value_counts().idxmax() if not values.empty else "Немає даних"


def build_oblast_map_data(data: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "oblast",
        "lat",
        "lon",
        "records",
        "communities",
        "dominant_category",
        "radius",
        "color",
    ]
    if data.empty:
        return pd.DataFrame(columns=columns)

    centers = load_oblast_centers()
    prepared = data.assign(oblast_key=data["oblast"].apply(normalize_oblast_name))
    grouped = (
        prepared.groupby("oblast_key", dropna=True)
        .agg(
            records=("territory_name", "size"),
            communities=("hromada_code_7", "nunique"),
            dominant_category=("category", dominant_category),
        )
        .reset_index()
    )
    max_records = max(int(grouped["records"].max()), 1)
    rows = []
    for _, row in grouped.iterrows():
        coords = centers.get(row["oblast_key"])
        if not coords:
            continue
        records = int(row["records"])
        category = str(row["dominant_category"])
        rows.append(
            {
                "oblast": coords["label"],
                "lat": coords["lat"],
                "lon": coords["lon"],
                "records": records,
                "communities": int(row["communities"]),
                "dominant_category": category,
                "radius": 16000 + int(records / max_records * 52000),
                "color": CATEGORY_COLORS.get(category, DEFAULT_COLOR),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("records", ascending=False)


def simplify_hromada_name(value: object) -> str:
    lowered = str(value).strip().lower()
    for item in (
        "територіальна громада",
        "міська громада",
        "селищна громада",
        "сільська громада",
        "громада",
    ):
        lowered = lowered.replace(item, "")
    return " ".join(lowered.split())


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_hromada(territory_name: str, oblast: str) -> dict[str, float] | None:
    query = ", ".join(
        filter(None, [simplify_hromada_name(territory_name), str(oblast), "Україна"])
    )
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 0},
            headers={"User-Agent": "territories-monitor/2.0"},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except Exception:
        return None
    if not result:
        return None
    return {"lat": float(result[0]["lat"]), "lon": float(result[0]["lon"])}


def selected_hromada_points(selected: list[str], source: pd.DataFrame) -> pd.DataFrame:
    columns = ["territory_name", "oblast", "rayon", "category", "lat", "lon", "radius"]
    if not selected:
        return pd.DataFrame(columns=columns)
    rows = []
    subset = source[source["territory_name"].isin(selected)].drop_duplicates(
        ["territory_name", "oblast", "rayon"]
    )
    for _, row in subset.iterrows():
        point = geocode_hromada(str(row["territory_name"]), str(row["oblast"]))
        if point:
            rows.append(
                {
                    **row[["territory_name", "oblast", "rayon", "category"]].to_dict(),
                    **point,
                    "radius": 8500,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def prepare_display_table(data: pd.DataFrame) -> pd.DataFrame:
    table = data.copy()
    table["status_from"] = table["status_from"].dt.strftime("%d.%m.%Y").fillna("не зазначено")
    table["status_to"] = table["status_to"].dt.strftime("%d.%m.%Y").fillna(
        "чинний / не зазначено"
    )
    table["loaded_at"] = table["loaded_at"].dt.strftime("%d.%m.%Y %H:%M").fillna("")
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


def render_map(map_data: pd.DataFrame, points: pd.DataFrame) -> None:
    if map_data.empty and points.empty:
        return
    center = points if not points.empty else map_data
    layers = []
    if not map_data.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=map_data,
                get_position="[lon, lat]",
                get_radius="radius",
                get_fill_color="color",
                pickable=True,
                auto_highlight=True,
            )
        )
    if not points.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=points,
                get_position="[lon, lat]",
                get_radius="radius",
                get_fill_color=[255, 255, 255, 235],
                get_line_color=[15, 23, 42, 255],
                line_width_min_pixels=2,
                stroked=True,
                filled=True,
                pickable=True,
            )
        )
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=float(center["lat"].mean()),
            longitude=float(center["lon"].mean()),
            zoom=7 if not points.empty else (5 if len(map_data) > 1 else 6),
        ),
        tooltip={
            "html": "<b>{oblast}</b><br/>Записів: {records}<br/>Громад: {communities}<br/>{dominant_category}<br/><br/><b>{territory_name}</b><br/>{rayon}<br/>{category}",
            "style": {"backgroundColor": "#0f172a", "color": "white"},
        },
        map_style=None,
    )
    st.pydeck_chart(deck, use_container_width=True)


def change_payload(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


database_url = resolve_database_url()
if not database_url:
    st.error("Базу даних ще не підключено.")
    st.code(
        'DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"',
        language="toml",
    )
    st.info(
        "Для локального запуску додайте значення до .streamlit/secrets.toml. "
        "Для Streamlit Community Cloud воно додається в налаштуваннях застосунку."
    )
    st.stop()

try:
    latest_doc = cached_latest_document(database_url)
    df = cached_territories(database_url)
    changes = cached_changes(database_url)
    document_history = cached_document_history(database_url)
except Exception as exc:
    st.error(
        "Не вдалося прочитати базу даних. Перевірте DATABASE_URL та чи виконано sql/schema.sql."
    )
    st.exception(exc)
    st.stop()

if latest_doc.empty or df.empty:
    st.warning(
        "Схему створено, але дані ще не завантажені. Запустіть workflow Update territories "
        "або команду python run_parser.py."
    )
    st.stop()

doc = latest_doc.iloc[0]
edition = pd.to_datetime(doc.get("edition_date"), errors="coerce")
base_date = pd.to_datetime(doc.get("base_document_date"), errors="coerce")
loaded = pd.to_datetime(doc.get("loaded_at"), errors="coerce")
source_page_url = html.escape(str(doc.get("source_page_url", "")), quote=True)
source_name = html.escape(str(doc.get("source_name", "")))
base_number = html.escape(str(doc.get("base_document_number", "")))

edition_text = edition.strftime("%d.%m.%Y") if not pd.isna(edition) else "не визначена"
base_date_text = base_date.strftime("%d.%m.%Y") if not pd.isna(base_date) else "не визначена"
loaded_text = loaded.strftime("%d.%m.%Y %H:%M") if not pd.isna(loaded) else "не визначено"

st.markdown(
    f"""
    <div class="source-card">
      <b>Джерело:</b> {source_name}<br>
      <b>Базовий наказ:</b> №{base_number} від {base_date_text}<br>
      <b>Редакція переліку:</b> {edition_text}<br>
      <b>Завантажено до бази:</b> {loaded_text}<br>
      <a href="{source_page_url}" target="_blank">Відкрити офіційний документ</a>
    </div>
    """,
    unsafe_allow_html=True,
)

open_statuses = int(df["status_to"].isna().sum())
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Записів у редакції", f"{len(df):,}".replace(",", " "))
kpi2.metric("Областей", df["oblast"].dropna().nunique())
kpi3.metric("Районів", df["rayon"].dropna().nunique())
kpi4.metric("Без кінцевої дати", f"{open_statuses:,}".replace(",", " "))

with st.expander("Що показує моніторинг"):
    st.write(
        "Система відображає технічне представлення офіційного переліку. Для юридичного "
        "використання результат потрібно звіряти з офіційним текстом документа. Історія "
        "редакцій у базі не замінює офіційні редакції нормативно-правового акта."
    )

st.sidebar.header("Параметри перегляду")
selected_date = pd.to_datetime(st.sidebar.date_input("Дата", value=pd.Timestamp.today()))

oblasts = ["Усі"] + sorted(df["oblast"].dropna().unique().tolist())
selected_oblast = st.sidebar.selectbox("Область", oblasts)

rayon_source = df if selected_oblast == "Усі" else df[df["oblast"] == selected_oblast]
rayons = ["Усі"] + sorted(rayon_source["rayon"].dropna().unique().tolist())
selected_rayon = st.sidebar.selectbox("Район", rayons)

categories = ["Усі"] + sorted(df["category"].dropna().unique().tolist())
selected_category = st.sidebar.selectbox("Категорія", categories)
search_text = st.sidebar.text_input("Пошук території або коду")

filtered = df[
    (df["status_from"].isna() | (df["status_from"] <= selected_date))
    & (df["status_to"].isna() | (df["status_to"] >= selected_date))
].copy()
if selected_oblast != "Усі":
    filtered = filtered[filtered["oblast"] == selected_oblast]
if selected_rayon != "Усі":
    filtered = filtered[filtered["rayon"] == selected_rayon]
if selected_category != "Усі":
    filtered = filtered[filtered["category"] == selected_category]
if search_text:
    mask = (
        filtered["territory_name"].str.contains(search_text, case=False, na=False)
        | filtered["full_code"].str.contains(search_text, case=False, na=False)
        | filtered["hromada_code_7"].astype(str).str.contains(search_text, case=False, na=False)
    )
    filtered = filtered[mask]

map_data = build_oblast_map_data(filtered)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Станом на дату", "Історія статусу", "Останні зміни", "Аналітика", "Карта"]
)

with tab1:
    st.subheader("Станом на дату")
    st.caption(f"Показано записи, чинні станом на {selected_date.strftime('%d.%m.%Y')}.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Записів", f"{len(filtered):,}".replace(",", " "))
    c2.metric("Областей", filtered["oblast"].dropna().nunique())
    c3.metric("Категорій", filtered["category"].dropna().nunique())
    st.dataframe(prepare_display_table(filtered), use_container_width=True, hide_index=True)
    st.download_button(
        "Завантажити CSV",
        data=filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"territories_{selected_date.strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
    )

with tab2:
    render_history_tab(df, document_history)

with tab3:
    st.subheader("Зміни відносно попередньої завантаженої редакції")
    if changes.empty:
        st.info("Для останньої редакції немає зафіксованих змін або це перше завантаження.")
    else:
        counts = changes["change_type"].value_counts()
        a, r, m = st.columns(3)
        a.metric("Додано", int(counts.get("ADDED", 0)))
        r.metric("Вилучено", int(counts.get("REMOVED", 0)))
        m.metric("Змінено", int(counts.get("MODIFIED", 0)))

        change_type = st.selectbox(
            "Тип зміни",
            ["Усі", "ADDED", "REMOVED", "MODIFIED"],
            format_func=lambda value: {
                "Усі": "Усі",
                "ADDED": "Додано",
                "REMOVED": "Вилучено",
                "MODIFIED": "Змінено",
            }[value],
        )
        visible_changes = changes if change_type == "Усі" else changes[changes["change_type"] == change_type]
        rows = []
        for _, change in visible_changes.iterrows():
            before = change_payload(change["before_data"])
            after = change_payload(change["after_data"])
            source = after or before
            rows.append(
                {
                    "Тип": {"ADDED": "Додано", "REMOVED": "Вилучено", "MODIFIED": "Змінено"}.get(change["change_type"], change["change_type"]),
                    "Повний код": source.get("full_code"),
                    "Територія": source.get("territory_name"),
                    "Область": source.get("oblast"),
                    "Район": source.get("rayon"),
                    "Категорія": source.get("category"),
                    "Було — кінець": before.get("status_to"),
                    "Стало — кінець": after.get("status_to"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Аналітичний зріз")
    if filtered.empty:
        st.info("Для обраних фільтрів немає даних.")
    else:
        category_stats = filtered.groupby("category").size().reset_index(name="Кількість записів")
        category_stats = category_stats.sort_values("Кількість записів", ascending=False)
        oblast_stats = filtered.groupby("oblast").size().reset_index(name="Кількість записів")
        oblast_stats = oblast_stats.sort_values("Кількість записів", ascending=False)
        left, right = st.columns(2)
        with left:
            st.write("Розподіл за категоріями")
            st.bar_chart(category_stats, x="category", y="Кількість записів")
        with right:
            st.write("Області з найбільшою кількістю записів")
            st.dataframe(oblast_stats.head(10), use_container_width=True, hide_index=True)

with tab5:
    st.subheader("Карта та просторовий зріз")
    st.markdown(
        """
        <div class="map-note">Карта показує оглядову концентрацію записів за областями. Межі громад не відображаються; світлі точки громад визначаються автоматичним пошуком координат за назвою.</div>
        """,
        unsafe_allow_html=True,
    )
    if filtered.empty:
        st.info("Для обраних фільтрів немає даних.")
    else:
        options = sorted(filtered["territory_name"].dropna().unique().tolist())
        selected = st.multiselect(
            "Підсвітити громади",
            options,
            max_selections=5,
        )
        points = selected_hromada_points(selected, filtered)
        missing = sorted(set(selected) - set(points["territory_name"].tolist())) if selected else []
        if missing:
            st.caption("Не знайдено координати для: " + ", ".join(missing))
        render_map(map_data, points)

        if not map_data.empty:
            top = map_data.iloc[0]
            total = int(map_data["records"].sum())
            share = round(int(top["records"]) / total * 100, 1) if total else 0
            st.markdown(
                f"""
                <div class="insight-card"><b>Короткий висновок.</b><br>Найбільша концентрація записів у вибірці припадає на <b>{html.escape(str(top['oblast']))}</b> — {int(top['records'])} записів, або {share}% вибірки.</div>
                """,
                unsafe_allow_html=True,
            )

st.markdown(
    """
    <div class="footer">Створено Єфремовим Арсеном<br>Інструмент для зручного перегляду офіційних даних.</div>
    """,
    unsafe_allow_html=True,
)
