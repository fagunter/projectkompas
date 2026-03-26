"""
ProjectKompas v2 — Maakbaarheidstool (Streamlit)

Screen 1: Project invoer + profiel
Screen 2: 3 KPI stoplichten (TVP / Klanteis / Budget) + risico-lijst

Run:  streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path
import html
from datetime import date, datetime, timedelta

import altair as alt
import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from build_features import (
    DATA_DIR,
    build_project_profiles,
    compute_peer_scores,
    kpi_budget,
    kpi_klanteis,
    kpi_tvp,
    normalize_pid,
    PEER_WEIGHTS,
)
from dummy_engine import generate_demo_backend, DEMO_N_PEERS, DEMO_N_RISKS
from utils.io_utils import read_uploaded_file

ROOT_DIR = Path(__file__).resolve().parent
LOGO_PATH = ROOT_DIR / "logo.png"
LOGO_SMALL_PATH = ROOT_DIR / "logo_small.png"

_page_cfg = {
    "page_title": "ProjectKompas",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}
if LOGO_SMALL_PATH.is_file():
    _page_cfg["page_icon"] = str(LOGO_SMALL_PATH)
elif LOGO_PATH.is_file():
    _page_cfg["page_icon"] = str(LOGO_PATH)
st.set_page_config(**_page_cfg)

PROFILES_PATH = DATA_DIR / "project_profiles.csv"
DUMMY_PROJECTDATA_PATH = DATA_DIR / "dummy_data" / "projectdata.xlsx"
# Bestandsnamen wijken af van de inhoud: scope staat in DummyRisicoLocatie.xlsx, locatie in DummyRisicos.xlsx
DUMMY_SCOPE_RISKS_PATH = DATA_DIR / "dummy_data" / "DummyRisicoLocatie.xlsx"
DUMMY_LOC_RISKS_PATH = DATA_DIR / "dummy_data" / "DummyRisicos.xlsx"

# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Projectprofielen laden\u2026")
def get_profiles() -> pd.DataFrame:
    if not PROFILES_PATH.exists():
        st.error("project_profiles.csv niet gevonden. Draai eerst `python build_features.py`.")
        st.stop()
    df = pd.read_csv(PROFILES_PATH, encoding="utf-8-sig")
    for col in ["Plandatum", "Klanteis"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner="Profielen met lijsten laden\u2026")
def get_profiles_full() -> pd.DataFrame:
    return build_project_profiles()


@st.cache_data(show_spinner="Dummy scope-risico's laden\u2026")
def _load_scope_risks() -> pd.DataFrame:
    if not DUMMY_SCOPE_RISKS_PATH.exists():
        return pd.DataFrame()
    df = pd.read_excel(DUMMY_SCOPE_RISKS_PATH, engine="openpyxl")
    df = df.rename(columns={"ScopeRisico": "Thema", "TESI-code": "TESI_code"})
    df["Categorie"] = "Locatie"
    df["Impact"] = pd.to_numeric(df["Impact"], errors="coerce")
    df["Kans"] = pd.to_numeric(df["Kans"], errors="coerce") / 100.0
    df["Risicoscore"] = df["Impact"] * df["Kans"]
    return df


@st.cache_data(show_spinner="Dummy locatie-risico's laden\u2026")
def _load_loc_risks() -> pd.DataFrame:
    if not DUMMY_LOC_RISKS_PATH.exists():
        return pd.DataFrame()
    df = pd.read_excel(DUMMY_LOC_RISKS_PATH, engine="openpyxl")
    df = df.rename(columns={"Locatierisico": "Thema"})
    df["Categorie"] = "Scope"
    df["Geo"] = df["Geo"].astype(str).str.zfill(3)
    df["Impact"] = pd.to_numeric(df["Impact"], errors="coerce")
    df["Kans"] = pd.to_numeric(df["Kans"], errors="coerce") / 100.0
    df["Risicoscore"] = df["Impact"] * df["Kans"]
    if "Risico" not in df.columns:
        if "Beschrijving" in df.columns:
            df["Risico"] = df["Beschrijving"]
        elif "Omschrijving" in df.columns:
            df["Risico"] = df["Omschrijving"]
        elif "Kilometrering" in df.columns:
            df["Risico"] = df["Kilometrering"]
        else:
            df["Risico"] = df["Thema"]
    return df


def get_dummy_risks(tesi_code: str | None = None, geo_code: str | None = None) -> pd.DataFrame:
    """Load all dummy risks (scope + locatie), no filtering."""
    scope = _load_scope_risks()
    loc = _load_loc_risks()

    parts = [df for df in [scope, loc] if not df.empty]
    if not parts:
        return pd.DataFrame(columns=["Categorie", "Thema", "Risico", "Impact", "Kans", "Risicoscore"])
    combined = pd.concat(parts, ignore_index=True)
    for col in ["Categorie", "Thema", "Risico", "Impact", "Kans", "Risicoscore"]:
        if col not in combined.columns:
            combined[col] = None
    return combined


@st.cache_data(show_spinner="Dummy projectdata laden\u2026")
def get_dummy_projectdata() -> pd.DataFrame:
    """Load the hand-crafted peer projects from dummy_data/projectdata.xlsx."""
    if not DUMMY_PROJECTDATA_PATH.exists():
        return pd.DataFrame()
    df = pd.read_excel(DUMMY_PROJECTDATA_PATH, engine="openpyxl")
    if "TVP-duur" in df.columns:
        df["total_tvp_hours"] = pd.to_timedelta(df["TVP-duur"], errors="coerce").dt.total_seconds() / 3600
    if "Plandatum" in df.columns and "Klanteis" in df.columns:
        df["Plandatum"] = pd.to_datetime(df["Plandatum"], errors="coerce")
        df["Klanteis"] = pd.to_datetime(df["Klanteis"], errors="coerce")
        df["slack_days"] = (df["Klanteis"] - df["Plandatum"]).dt.days
    if "Budget" in df.columns:
        df["Prognose eindstand"] = pd.to_numeric(df["Budget"], errors="coerce")
    if "Geo-code" in df.columns:
        df["primary_geo"] = df["Geo-code"].astype(str).str.zfill(3)
    return df


@st.cache_data(show_spinner="Spoortakcoordinaten ophalen\u2026", ttl=3600)
def get_geocode_coords(geocode: str) -> pd.DataFrame | None:
    """Fetch GPS coordinates for all km points along a geocode via openspoor."""
    try:
        from openspoor.transformers.TransformerGeocodeToCoordinates import (
            TransformerGeocodeToCoordinates,
        )
        km_vals = [float(i) * 0.5 for i in range(300)]
        df = pd.DataFrame({"geocode": [geocode] * len(km_vals), "geocode_km": km_vals})
        transformer = TransformerGeocodeToCoordinates("geocode", "geocode_km", "GPS")
        result = transformer.transform(df)
        valid = result.dropna(subset=["x", "y"]).copy()
        valid = valid.rename(columns={"x": "lat", "y": "lon"})
        if valid.empty:
            return None
        return valid[["geocode_km", "lat", "lon"]].sort_values("geocode_km").reset_index(drop=True)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

THEME = {
    "primary": "#b20a2f",
    "primary_dark": "#860013",
    "accent": "#264ae5",
    "text": "#2c2a3b",
    "text_muted": "#6c717e",
    "surface": "#ffffff",
    "surface_alt": "#f8f8f8",
    "surface_soft": "#fafafb",
    "border": "#ced0d3",
    "success": "#00822e",
    "warning": "#df8d13",
    "danger": "#d50000",
    "info": "#264ae5",
}

SIGNAL_COLOR = {
    "green": THEME["success"],
    "orange": THEME["warning"],
    "red": THEME["danger"],
    "grey": THEME["text_muted"],
}


def _render_geocode_map(geocode: str, height: int = 320) -> None:
    """Render an interactive folium map: spoortak als polyline (geen markers)."""
    coords = get_geocode_coords(geocode)
    if coords is None or coords.empty:
        st.caption(f"Geen kaartdata beschikbaar voor geocode {geocode}.")
        return

    points = list(zip(coords["lat"], coords["lon"]))
    center_lat = coords["lat"].mean()
    center_lon = coords["lon"].mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="CartoDB positron",
        attr=" ",
    )

    folium.TileLayer(
        tiles="https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png",
        attr=" ",
        name="Spoorwegen",
        overlay=True,
        opacity=0.6,
    ).add_to(m)

    m.get_root().html.add_child(folium.Element(
        '<style>.leaflet-tile-pane .leaflet-layer:last-child img{filter:opacity(0.8) saturate(1.4) brightness(1.15);}</style>'
    ))

    folium.PolyLine(
        points,
        color="#00e64d",
        weight=7,
        opacity=1.0,
    ).add_to(m)

    st_folium(m, width=None, height=height, returned_objects=[])


def _inject_theme() -> None:
    """Apply a ProRail-inspired visual layer on top of Streamlit."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');

        :root {{
            --pr-primary: {THEME["primary"]};
            --pr-primary-dark: {THEME["primary_dark"]};
            --pr-accent: {THEME["accent"]};
            --pr-text: {THEME["text"]};
            --pr-text-muted: {THEME["text_muted"]};
            --pr-surface: {THEME["surface"]};
            --pr-surface-alt: {THEME["surface_alt"]};
            --pr-surface-soft: {THEME["surface_soft"]};
            --pr-border: {THEME["border"]};
            --pr-success: {THEME["success"]};
            --pr-warning: {THEME["warning"]};
            --pr-danger: {THEME["danger"]};
        }}

        html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
            font-family: "Roboto", sans-serif;
            color: var(--pr-text);
        }}

        .stApp {{
            background: var(--pr-surface-alt);
            color: var(--pr-text);
        }}

        [data-testid="stSidebar"] {{
            background: var(--pr-surface);
            border-right: 1px solid var(--pr-border);
        }}

        [data-testid="stSidebar"] * {{
            color: var(--pr-text);
        }}

        h1, h2, h3, h4, h5, h6 {{
            color: var(--pr-text);
            font-weight: 700;
            letter-spacing: -0.02em;
        }}

        p, label, .stMarkdown, .stCaption {{
            color: var(--pr-text);
        }}

        .block-container {{
            padding-top: 2rem;
            padding-bottom: 2rem;
        }}

        hr {{
            border: 0;
            border-top: 1px solid var(--pr-border);
            margin: 1.25rem 0;
        }}

        [data-testid="metric-container"] {{
            background: var(--pr-surface);
            border: 1px solid var(--pr-border);
            border-radius: 5px;
            padding: 1rem 1.1rem;
            box-shadow: 0 1px 2px rgba(12, 18, 28, 0.04);
        }}

        [data-testid="metric-container"] [data-testid="stMetricLabel"] {{
            color: var(--pr-text-muted);
            font-weight: 500;
        }}

        [data-testid="metric-container"] [data-testid="stMetricValue"] {{
            color: var(--pr-text);
            font-weight: 700;
        }}

        .stButton > button,
        .stDownloadButton > button {{
            background: var(--pr-primary) !important;
            color: #fff !important;
            border: 1px solid var(--pr-primary) !important;
            border-radius: 5px;
            min-height: 2.75rem;
            font-weight: 600;
            transition: background-color 120ms ease, border-color 120ms ease;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover {{
            background: var(--pr-primary-dark) !important;
            border-color: var(--pr-primary-dark) !important;
            color: #fff !important;
        }}

        .stButton > button:focus,
        .stDownloadButton > button:focus {{
            box-shadow: 0 0 0 0.2rem rgba(178, 10, 47, 0.15);
        }}

        .stButton > button p,
        .stDownloadButton > button p {{
            color: #fff !important;
        }}

        div[data-baseweb="select"] > div,
        div[data-baseweb="base-input"] > div,
        .stDateInput > div > div {{
            background: var(--pr-surface);
            border-radius: 5px;
            border-color: var(--pr-border);
        }}

        div[role="radiogroup"] label[data-baseweb="radio"] {{
            background: var(--pr-surface);
            border: 1px solid var(--pr-border);
            border-radius: 5px;
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.5rem;
            width: 100%;
        }}

        div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) {{
            border-color: var(--pr-primary);
            background: #fceced;
        }}

        .stAlert {{
            border-radius: 5px;
            border: 1px solid var(--pr-border);
        }}

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {{
            background: var(--pr-surface);
            border: 1px solid var(--pr-border);
            border-radius: 5px;
            overflow: hidden;
        }}

        div[data-testid="stDataFrame"] [role="columnheader"] {{
            background: var(--pr-surface-soft);
            color: var(--pr-text);
            font-weight: 600;
        }}

        div[data-testid="stDataFrame"] [role="gridcell"] {{
            border-color: var(--pr-border);
        }}

        .pr-page-intro {{
            background: linear-gradient(90deg, rgba(178, 10, 47, 0.08), rgba(38, 74, 229, 0.04));
            border: 1px solid rgba(178, 10, 47, 0.12);
            border-radius: 5px;
            padding: 1rem 1.25rem;
            margin-bottom: 1.25rem;
        }}

        .pr-page-intro p {{
            margin: 0.35rem 0 0;
            color: var(--pr-text-muted);
        }}

        .pr-project-form-gap {{
            height: 0.75rem;
        }}

        /* Screen 1: classes added via JS since :has() is unsupported */
        .pr-project-row {{
            align-items: flex-start !important;
        }}
        .pr-project-left {{
            border-right: 1px solid var(--pr-border) !important;
            padding-right: 1.15rem !important;
            box-sizing: border-box !important;
        }}
        .pr-project-right {{
            padding-left: 1.15rem !important;
            box-sizing: border-box !important;
        }}

        .pr-project-split-marker {{
            display: none;
        }}

        .pr-left-guide {{
            margin: 0 0 0.85rem 0;
            padding: 0;
            background: none;
            border: none;
            border-radius: 0;
        }}
        .pr-left-guide p {{
            margin: 0.35rem 0 0;
            font-size: 0.88rem;
            line-height: 1.4;
            color: var(--pr-text-muted);
        }}

        /* Hide JS helper iframe */
        .pr-project-left iframe[height="0"] {{
            display: none !important;
        }}

        .pr-upload-success {{
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--pr-success);
            padding: 0.45rem 0.65rem;
            background: rgba(0, 130, 46, 0.07);
            border-radius: 5px;
            border: 1px solid rgba(0, 130, 46, 0.22);
            margin-top: 0.5rem;
            line-height: 1.35;
        }}

        .pr-form-section-label {{
            color: var(--pr-text-muted);
            text-transform: uppercase;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.07em;
            margin: 1.1rem 0 0.45rem;
            padding-bottom: 0.2rem;
            border-bottom: 1px solid var(--pr-border);
        }}
        .pr-form-section-label.pr-form-section-first {{
            margin-top: 0;
        }}

        .pr-section-label {{
            color: var(--pr-text-muted);
            text-transform: uppercase;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            margin-bottom: 0.25rem;
        }}

        .pr-kpi-card {{
            background: var(--pr-surface);
            border: 1px solid var(--pr-border);
            border-left: 4px solid var(--pr-primary);
            border-radius: 6px;
            padding: 1.1rem 1.35rem;
            margin-bottom: 1rem;
            box-shadow: 0 1px 3px rgba(12, 18, 28, 0.06);
            position: relative;
        }}

        .pr-kpi-card .pr-kpi-title {{
            margin: 0 0 0.6rem;
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--pr-text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .pr-kpi-card .pr-kpi-status {{
            display: flex;
            align-items: center;
            gap: 0.55rem;
            margin: 0 0 0.45rem;
        }}

        .pr-kpi-card .pr-kpi-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            flex-shrink: 0;
        }}

        .pr-kpi-card .pr-kpi-label {{
            font-size: 1.25rem;
            font-weight: 700;
            line-height: 1.2;
        }}

        .pr-kpi-card .pr-kpi-detail {{
            margin: 0;
            font-size: 0.85rem;
            color: var(--pr-text-muted);
            line-height: 1.45;
        }}

        /* ── Toetscriteria: compact rows ────────────────────── */
        .pr-toetscriteria {{
            font-size: 0.78rem;
        }}
        .pr-toetscriteria .pr-toets-q {{
            font-size: 0.78rem;
            line-height: 1.3;
            color: var(--pr-text);
            margin: 0;
            padding: 4px 0;
        }}
        .pr-toetscriteria .pr-toets-meta {{
            font-size: 0.72rem;
            color: var(--pr-text);
            line-height: 28px;
        }}
        .pr-toetscriteria .pr-toets-date {{
            font-size: 0.72rem;
            font-weight: 600;
            color: var(--pr-text);
            line-height: 28px;
        }}
        .pr-toetscriteria .pr-toets-empty {{
            font-size: 0.72rem;
            color: var(--pr-text-muted);
            line-height: 28px;
        }}

        /* Kill ALL extra vertical space inside .pr-toetscriteria rows */
        .pr-toetscriteria div[data-testid="stVerticalBlockBorderWrapper"],
        .pr-toetscriteria div[data-testid="stVerticalBlock"],
        .pr-toetscriteria div[data-testid="column"],
        .pr-toetscriteria div[data-testid="stElementContainer"] {{
            gap: 0 !important;
        }}
        .pr-toetscriteria div[data-testid="stHorizontalBlock"] {{
            gap: 0.35rem !important;
            align-items: center !important;
        }}

        /* Strip selectbox chrome to bare minimum */
        .pr-toetscriteria div[data-testid="stSelectbox"] {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        .pr-toetscriteria div[data-testid="stSelectbox"] > div {{
            padding-top: 0 !important;
        }}
        .pr-toetscriteria div[data-testid="stSelectbox"] label {{
            display: none !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] {{
            margin: 0 !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] > div {{
            min-height: 28px !important;
            max-height: 28px !important;
            padding: 0 6px !important;
            border-radius: 4px !important;
            font-size: 0.72rem !important;
            line-height: 28px !important;
            cursor: pointer !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] > div > div {{
            padding: 0 !important;
            line-height: 28px !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] span {{
            font-size: 0.72rem !important;
            line-height: 28px !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] svg {{
            width: 14px !important;
            height: 14px !important;
        }}
        .pr-toetscriteria div[data-baseweb="select"] input {{
            font-size: 0.72rem !important;
            height: 28px !important;
            padding: 0 !important;
        }}

        /* Compact separators between category groups */
        .pr-toetscriteria .pr-tc-cat-label {{
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--pr-primary);
            margin: 0.6rem 0 0.15rem;
            padding: 0;
        }}
        .pr-toetscriteria .pr-tc-cat-label:first-child {{
            margin-top: 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_euro(val) -> str:
    if pd.isna(val) or val is None:
        return "\u2014"
    return f"\u20ac {val:,.0f}".replace(",", ".")


def _fmt_date(val) -> str:
    if pd.isna(val) or val is None:
        return "\u2014"
    return pd.Timestamp(val).strftime("%d-%m-%Y")


def _fmt_signed_at(val) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "\u2014"
    try:
        if isinstance(val, date) and not isinstance(val, datetime):
            return val.strftime("%d-%m-%Y")
        return pd.Timestamp(val).strftime("%d-%m-%Y")
    except Exception:
        return "\u2014"


def _border_container():
    """st.container(border=True) when supported (Streamlit >= 1.33)."""
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _project_auto_panel():
    """Linkerkolom project-paneel zonder kaderlijn."""
    try:
        return st.container(border=False)
    except TypeError:
        return st.container()


def _signal_card(title: str, kpi_result: dict):
    """Render a modern KPI card with colored status indicator."""
    sig = kpi_result["signal"]
    color = SIGNAL_COLOR.get(sig, "#888")
    label = kpi_result["label"]
    st.markdown(
        f"""
        <div class="pr-kpi-card" style="border-left-color:{color};">
            <div class="pr-kpi-title">{title}</div>
            <div class="pr-kpi-status">
                <span class="pr-kpi-dot" style="background:{color};"></span>
                <span class="pr-kpi-label" style="color:{color};">{label}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _peer_distribution(
    peer_values: list[float],
    project_value: float | None,
    peer_median: float | None,
    x_label: str,
    peer_p25: float | None = None,
    peer_p75: float | None = None,
    invert: bool = False,
):
    """KDE chart with realistisch (P25–P75) / onrealistisch zones."""
    if not peer_values:
        return
    vals = [v for v in peer_values if v is not None and not np.isnan(v)]
    if len(vals) < 2:
        return

    if invert:
        vals = [-v for v in vals]
        if project_value is not None and not np.isnan(project_value):
            project_value = -project_value
        if peer_median is not None and not np.isnan(peer_median):
            peer_median = -peer_median
        if peer_p25 is not None and peer_p75 is not None:
            peer_p25, peer_p75 = -peer_p75, -peer_p25

    from scipy.stats import gaussian_kde
    kde = gaussian_kde(vals)

    x_min, x_max = min(vals), max(vals)
    pad = (x_max - x_min) * 0.15 or 1.0
    xs = np.linspace(x_min - pad, x_max + pad, 400)
    ys = kde(xs)

    # Fallback: compute P25/P75 from raw values if not provided
    if peer_p25 is None or peer_p75 is None or np.isnan(peer_p25) or np.isnan(peer_p75):
        s = pd.Series(vals)
        peer_p25 = float(s.quantile(0.25))
        peer_p75 = float(s.quantile(0.75))

    band_lo = peer_p25
    band_hi = peer_p75
    has_band = True

    CLR_OK = "#c3e6cb"
    CLR_RISK = "#f5c6cb"

    green_rows = []
    red_rows = []
    for xv, yv in zip(xs, ys):
        inside = band_lo <= xv <= band_hi
        if inside:
            green_rows.append({"value": xv, "density": yv})
            red_rows.append({"value": xv, "density": 0.0})
        else:
            green_rows.append({"value": xv, "density": 0.0})
            red_rows.append({"value": xv, "density": yv})

    x_enc = alt.X("value:Q", title=x_label)
    y_enc = alt.Y("density:Q", title="Aantal", axis=alt.Axis(labels=False, ticks=False))

    area_ok = (
        alt.Chart(pd.DataFrame(green_rows))
        .mark_area(opacity=0.5, interpolate="monotone", line=False, color=CLR_OK)
        .encode(x=x_enc, y=y_enc)
    )
    area_risk = (
        alt.Chart(pd.DataFrame(red_rows))
        .mark_area(opacity=0.45, interpolate="monotone", line=False, color=CLR_RISK)
        .encode(x=x_enc, y=y_enc)
    )

    outline_src = pd.DataFrame({"value": xs, "density": ys})
    outline = (
        alt.Chart(outline_src)
        .mark_line(strokeWidth=1.5, color=THEME["text_muted"], opacity=0.45, interpolate="monotone")
        .encode(x="value:Q", y="density:Q")
    )

    legend_src = pd.DataFrame([
        {"label": "Realistisch", "x": 0, "y": 0},
        {"label": "Onrealistisch", "x": 0, "y": 0},
    ])
    legend = (
        alt.Chart(legend_src)
        .mark_point(size=0, opacity=0)
        .encode(
            x=alt.value(0), y=alt.value(0),
            color=alt.Color("label:N",
                scale=alt.Scale(domain=["Realistisch", "Onrealistisch"],
                                range=[CLR_OK, CLR_RISK]),
                legend=alt.Legend(title=None, orient="top", direction="horizontal",
                                 labelFontSize=10, symbolType="square", symbolSize=100)),
        )
    )

    chart = area_risk + area_ok + outline + legend

    if project_value is not None and not pd.isna(project_value):
        rule_df = pd.DataFrame({"value": [float(project_value)]})
        rule = (
            alt.Chart(rule_df)
            .mark_rule(color=THEME["accent"], strokeWidth=2.5, strokeDash=[6, 3])
            .encode(x="value:Q")
        )
        label = (
            alt.Chart(rule_df)
            .mark_text(
                align="left", dx=5, dy=-8, fontSize=11,
                fontWeight="bold", color=THEME["accent"],
            )
            .encode(x="value:Q", text=alt.value("Dit project"))
        )
        chart = chart + rule + label

    st.altair_chart(
        chart.properties(height=260)
        .configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor=THEME["text_muted"],
            titleColor=THEME["text"],
            gridColor=THEME["border"],
            domainColor=THEME["border"],
            tickColor=THEME["border"],
        )
        .configure(background="transparent"),
        use_container_width=True,
    )


def _render_risk_spider(risks: pd.DataFrame):
    """Render a normalised (0–1) radar chart of average risk score per Thema."""
    if risks.empty:
        return

    theme_agg = (
        risks.groupby("Thema")
        .agg(gem_score=("Risicoscore", "mean"))
        .reset_index()
        .sort_values("Thema")
    )

    themes = theme_agg["Thema"].tolist()
    raw_scores = theme_agg["gem_score"].tolist()

    max_possible = max(raw_scores) if raw_scores else 1.0
    if max_possible == 0:
        max_possible = 1.0
    scores = [s / max_possible for s in raw_scores]

    n = len(themes)
    angles = [i / n * 2 * np.pi for i in range(n)]
    angles += angles[:1]
    scores += scores[:1]

    fig, ax = plt.subplots(figsize=(4.2, 4.2), subplot_kw={"polar": True})
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    ring_ticks = [0.25, 0.50, 0.75, 1.0]
    circle_theta = np.linspace(0, 2 * np.pi, 100)
    for ring_r in ring_ticks:
        ax.plot(circle_theta, [ring_r] * 100, color=THEME["border"], linewidth=0.6, alpha=0.5)

    for a in angles[:-1]:
        ax.plot([a, a], [0, 1.05], color=THEME["border"], linewidth=0.5, alpha=0.4)

    ax.fill(angles, scores, color=THEME["primary"], alpha=0.10)
    ax.plot(angles, scores, color=THEME["primary"], linewidth=1.8, solid_capstyle="round")
    ax.scatter(angles[:-1], scores[:-1], color=THEME["primary"], s=28, zorder=5, edgecolors="white", linewidths=0.8)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(
        themes, fontsize=7.5, fontweight=500, color=THEME["text"],
        fontfamily="Roboto, sans-serif",
    )

    ax.set_yticks(ring_ticks)
    ax.set_yticklabels([], fontsize=0)
    ax.set_ylim(0, 1.05)

    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.tick_params(axis="x", pad=14)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    plt.tight_layout(pad=1.5)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


# ---------------------------------------------------------------------------
# SCREEN 1 -- Project invoer
# ---------------------------------------------------------------------------

_FIELD_DEFAULTS: dict[str, object] = {
    "f_pid": "",
    "f_plandatum": None,
    "f_investeringskosten": 0.0,
    "f_btds": 0,
    "f_btd_uren": 0.0,
    "f_klanteis": None,
    "f_scope_delen": "",
    "f_scope_omvang": "",
    "f_locatie": "",
}


_F_TO_WIDGET = {
    "f_pid": "input_pid",
    "f_investeringskosten": "input_investeringskosten",
    "f_btds": "input_btds",
    "f_btd_uren": "input_btd_uren",
    "f_plandatum": "input_plandatum",
    "f_klanteis": "input_klanteis",
    "f_scope_delen": "input_scope_delen",
    "f_scope_omvang": "input_scope_omvang",
    "f_locatie": "input_locatie",
}


def _sync_f_to_widgets():
    """Seed widget keys from f_* values (only if unset).

    This avoids Streamlit warnings/errors caused by setting a widget key via
    session_state while also providing an explicit `value=` to the widget.
    """
    for f_key, w_key in _F_TO_WIDGET.items():
        if f_key in st.session_state:
            st.session_state.setdefault(w_key, st.session_state[f_key])


def _force_f_to_widgets():
    """Overwrite widget keys from f_* values (use in callbacks before render)."""
    for f_key, w_key in _F_TO_WIDGET.items():
        if f_key in st.session_state:
            st.session_state[w_key] = st.session_state[f_key]


def _autofill_from_pid(pid: str, profiles: pd.DataFrame) -> None:
    """Populate session-state form fields from a known ProjectID."""
    match = profiles[profiles["ProjectID"] == pid]
    if match.empty:
        st.warning(f"ProjectID '{pid}' niet gevonden in de data.")
        return
    row = match.iloc[0]
    st.session_state["f_pid"] = pid
    prognose = row.get("Prognose eindstand")
    st.session_state["f_investeringskosten"] = float(prognose) if pd.notna(prognose) else 0.0
    st.session_state["f_btds"] = int(row.get("n_tvps", 0))
    st.session_state["f_btd_uren"] = float(row.get("total_tvp_hours", 0))
    klanteis = row.get("Klanteis")
    st.session_state["f_klanteis"] = pd.Timestamp(klanteis).date() if pd.notna(klanteis) else None
    plandatum = row.get("Plandatum")
    st.session_state["f_plandatum"] = pd.Timestamp(plandatum).date() if pd.notna(plandatum) else None
    tesi = row.get("primary_tesi")
    st.session_state["f_scope_delen"] = str(tesi) if pd.notna(tesi) else ""
    cx = row.get("Complexiteit")
    st.session_state["f_scope_omvang"] = str(cx) if pd.notna(cx) else ""
    geo = row.get("primary_geo")
    gebied = row.get("Gebied")
    loc_parts = []
    if pd.notna(geo) and geo:
        loc_parts.append(str(geo))
    if pd.notna(gebied) and gebied:
        loc_parts.append(str(gebied))
    st.session_state["f_locatie"] = " / ".join(loc_parts) if loc_parts else ""
    st.session_state["_autofilled_pid"] = pid
    _force_f_to_widgets()


MONTH_MAP = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def _parse_startbeslissing(uploaded_file) -> bool:
    """Try to parse an Aanvraag Startbeslissing .xlsm and auto-fill fields.

    Returns True if the file was recognised as a startbeslissing document.
    """
    import datetime
    try:
        df = pd.read_excel(uploaded_file, sheet_name="Aanvraagformulier",
                           header=None, engine="openpyxl")
    except Exception:
        return False

    header_check = str(df.iloc[1, 1]) if len(df) > 1 and len(df.columns) > 1 else ""
    if "Startbeslissing" not in header_check and "Aanvraag" not in header_check:
        return False

    def cell(r, c):
        try:
            v = df.iloc[r, c]
            return v if pd.notna(v) else None
        except (IndexError, KeyError):
            return None

    def year_month_to_date(row_idx):
        year = cell(row_idx, 2)
        month_str = cell(row_idx, 5)
        if year is None:
            return None
        try:
            y = int(year)
        except (ValueError, TypeError):
            return None
        m = MONTH_MAP.get(str(month_str).strip().lower(), 1) if month_str else 1
        return datetime.date(y, m, 1)

    pid_from_name = uploaded_file.name.replace(".xlsm", "").replace(".xlsx", "")
    parts = pid_from_name.split("_", 1)
    pid = parts[1] if len(parts) > 1 else pid_from_name
    st.session_state["f_pid"] = pid

    projectnaam = cell(13, 2)
    if projectnaam:
        st.session_state["_project_naam"] = str(projectnaam)

    indiener = cell(9, 2)
    if indiener:
        st.session_state["_indiener"] = str(indiener).strip()

    prognose = cell(29, 2)
    if prognose is not None:
        try:
            st.session_state["f_investeringskosten"] = float(prognose)
        except (ValueError, TypeError):
            pass

    geo = cell(16, 4)
    gebied = cell(15, 2)
    loc_parts = []
    if geo is not None:
        loc_parts.append(str(int(geo)).zfill(3) if isinstance(geo, (int, float)) else str(geo))
    if gebied is not None:
        loc_parts.append(str(gebied))
    st.session_state["f_locatie"] = " / ".join(loc_parts) if loc_parts else ""

    # row 48 (pandas) = Excel row 49: "Start uitvoering verwacht"
    plandatum = year_month_to_date(48)
    if plandatum:
        st.session_state["f_plandatum"] = plandatum

    # row 49 (pandas) = Excel row 50: "Gewenste indienststellingsdatum"
    klanteis = year_month_to_date(49)
    if klanteis:
        st.session_state["f_klanteis"] = klanteis

    # Aantal TVP's → BTD's
    n_tvps = cell(50, 2)
    if n_tvps is not None:
        try:
            st.session_state["f_btds"] = int(n_tvps)
        except (ValueError, TypeError):
            pass

    # TVP-duur (uren) → BTD-duur
    tvp_duur = cell(51, 2)
    if tvp_duur is not None:
        try:
            st.session_state["f_btd_uren"] = float(tvp_duur)
        except (ValueError, TypeError):
            pass

    # Scope-delen (comma-separated TESI codes)
    scope_delen = cell(41, 2)
    if scope_delen is not None:
        st.session_state["f_scope_delen"] = str(scope_delen).strip()

    # Scope omvang (Complexiteit)
    scope_omvang = cell(42, 2)
    if scope_omvang is not None:
        st.session_state["f_scope_omvang"] = str(scope_omvang).strip()

    # Werkstroom / productiepoot for project description
    werkstroom = cell(17, 2)
    if werkstroom:
        st.session_state["_project_werkstroom"] = str(werkstroom).strip()
    productiepoot = cell(18, 2)
    if productiepoot:
        st.session_state["_project_productiepoot"] = str(productiepoot).strip()

    # Parse Toetscriteria sheet
    try:
        uploaded_file.seek(0)
        df_tc = pd.read_excel(uploaded_file, sheet_name="Toetscriteria",
                              header=None, engine="openpyxl")
        criteria = []
        for i in range(1, len(df_tc)):
            cat = df_tc.iloc[i, 0] if pd.notna(df_tc.iloc[i, 0]) else ""
            crit = df_tc.iloc[i, 1] if len(df_tc.columns) > 1 and pd.notna(df_tc.iloc[i, 1]) else ""
            stand = df_tc.iloc[i, 2] if len(df_tc.columns) > 2 and pd.notna(df_tc.iloc[i, 2]) else ""
            if crit:
                criteria.append({"categorie": str(cat), "criterium": str(crit), "stand": str(stand)})
        if criteria:
            st.session_state["_toetscriteria"] = criteria
    except Exception:
        pass

    st.session_state["_autofilled_pid"] = pid
    _sync_f_to_widgets()
    return True


def _autofill_from_upload(uploaded_file, profiles: pd.DataFrame) -> None:
    """Read an uploaded file, find ProjectID, and auto-fill fields."""
    fname = uploaded_file.name.lower()
    if fname.endswith(".xlsm") or "startbeslissing" in fname:
        if _parse_startbeslissing(uploaded_file):
            # Keep UI clean: no green success card here.
            return

    try:
        uploaded_file.seek(0)
        df = read_uploaded_file(uploaded_file)
    except Exception as e:
        st.error(f"Fout bij lezen bestand: {e}")
        return

    pid_col = None
    for candidate in ["ProjectID", "projectid", "Project ID", "project_id", "PROJECTID"]:
        if candidate in df.columns:
            pid_col = candidate
            break
    if pid_col is None:
        for col in df.columns:
            if "project" in col.lower() and "id" in col.lower():
                pid_col = col
                break

    if pid_col is None:
        st.error("Geen ProjectID-kolom gevonden in het bestand.")
        return

    pids = df[pid_col].dropna().astype(str).apply(normalize_pid).unique().tolist()
    if not pids:
        st.error("Geen ProjectIDs gevonden in het bestand.")
        return

    if len(pids) == 1:
        _autofill_from_pid(pids[0], profiles)
        st.success(f"Projectgegevens ingevuld voor **{pids[0]}**")
    else:
        st.session_state["_upload_pids"] = pids
        st.info(f"{len(pids)} projecten gevonden. Kies hieronder welk project je wilt laden.")


def _cb_process_upload():
    """on_click callback: runs BEFORE widgets render, so widget keys are set in time."""
    uploaded = st.session_state.get("project_upload")
    if not uploaded:
        return
    profiles = get_profiles()
    _autofill_from_upload(uploaded, profiles)
    _force_f_to_widgets()
    st.session_state["_upload_success"] = True


def _cb_load_upload_pid():
    """on_click callback for loading a chosen PID from multi-project upload."""
    chosen = st.session_state.get("upload_pid_choice")
    if not chosen:
        return
    profiles = get_profiles()
    _autofill_from_pid(chosen, profiles)
    st.session_state.pop("_upload_pids", None)


def screen_project():
    import streamlit.components.v1 as _comp_proj

    st.header("Projectgegevens")

    for key, default in _FIELD_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default

    _upload_ok = st.session_state.pop("_upload_success", False)

    st.markdown(
        '<div class="pr-project-form-gap" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    c_auto, c_fields = st.columns([3, 7])

    with c_auto:
        st.markdown(
            """<div class="pr-left-guide"><div class="pr-project-split-marker" aria-hidden="true"></div>
                <div class="pr-form-section-label pr-form-section-first">Instructie</div>
                <strong>Vul de projectgegevens in of upload een startbeslissing.</strong>
                <p>Vul rechts de velden handmatig in, of sleep hieronder een <strong>startbeslissing (startformulier)</strong> om de velden automatisch te laten vullen.
                Ondersteunde formaten zijn Excel (.xlsx, .xls, .xlsm) en CSV.
                Na upload klik je op <strong>Verwerk bestand</strong> en worden gegevens zoals kosten, planning, scope en buitendienststellingen automatisch overgenomen.</p>
            </div>""",
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "Upload",
            type=["xlsx", "xls", "xlsm", "csv"],
            label_visibility="collapsed",
            key="project_upload",
        )
        if uploaded:
            st.button(
                "Verwerk bestand",
                key="btn_process_upload",
                type="primary",
                on_click=_cb_process_upload,
                use_container_width=True,
            )

        upload_pids = st.session_state.get("_upload_pids")
        if upload_pids:
            chosen = st.selectbox(
                "Kies project uit bestand",
                options=upload_pids,
                key="upload_pid_choice",
            )
            st.button(
                "Laad dit project",
                key="btn_load_upload",
                on_click=_cb_load_upload_pid,
                use_container_width=True,
            )

        if _upload_ok:
            st.markdown(
                '<div class="pr-upload-success">✓ Velden ingevuld vanuit bestand</div>',
                unsafe_allow_html=True,
            )

        _comp_proj.html("""<script>
            (function() {
                function apply() {
                    var doc = window.parent.document;
                    var marker = doc.querySelector('.pr-project-split-marker');
                    if (!marker) return;
                    var col = marker;
                    while (col && col.parentElement) {
                        col = col.parentElement;
                        if (col.getAttribute && col.getAttribute('data-testid') === 'column') break;
                    }
                    if (!col) return;
                    col.classList.add('pr-project-left');
                    var row = col.parentElement;
                    if (row) row.classList.add('pr-project-row');
                    var right = col.nextElementSibling;
                    if (right) right.classList.add('pr-project-right');
                }
                apply();
                new MutationObserver(apply).observe(window.parent.document.body, {childList: true, subtree: true});
            })();
            </script>""", height=0)

    with c_fields:
        # Initialize widget keys from f_* (only once; does not overwrite edits)
        _sync_f_to_widgets()

        st.markdown(
            '<div class="pr-form-section-label pr-form-section-first">Identificatie & locatie</div>',
            unsafe_allow_html=True,
        )
        r_pid_l, r_pid_r = st.columns([2, 3])
        with r_pid_l:
            st.text_input(
                "ProjectID",
                key="input_pid",
                placeholder="bijv. M-003976",
            )
        with r_pid_r:
            locatie = st.text_input(
                "Locatie",
                key="input_locatie",
                help="Geo-code / gebied",
                placeholder="bijv. 092 / Randstad-Noord",
            )
        st.session_state["f_pid"] = st.session_state.get("input_pid", "")
        st.session_state["f_locatie"] = locatie

        st.markdown(
            '<div class="pr-form-section-label">Planning</div>',
            unsafe_allow_html=True,
        )
        r_plan_l, r_plan_r = st.columns(2)
        with r_plan_l:
            plandatum = st.date_input(
                "Plandatum",
                key="input_plandatum",
            )
            st.session_state["f_plandatum"] = plandatum
        with r_plan_r:
            klanteis = st.date_input(
                "Klanteis (opleverdatum)",
                key="input_klanteis",
            )
            st.session_state["f_klanteis"] = klanteis

        st.markdown(
            '<div class="pr-form-section-label">Scope</div>',
            unsafe_allow_html=True,
        )
        r_scope_l, r_scope_r = st.columns(2)
        with r_scope_l:
            scope_delen = st.text_input(
                "Scope delen (TESI code)",
                key="input_scope_delen",
                placeholder="bijv. C01.01",
            )
            st.session_state["f_scope_delen"] = scope_delen
        with r_scope_r:
            scope_omvang = st.selectbox(
                "Scope omvang (Complexiteit)",
                options=["", "Laag", "Midden", "Hoog", "Hoog+"],
                key="input_scope_omvang",
            )
            st.session_state["f_scope_omvang"] = scope_omvang

        st.markdown(
            '<div class="pr-form-section-label">Kosten & buitendienststellingen</div>',
            unsafe_allow_html=True,
        )
        r_k1, r_k2 = st.columns(2)
        with r_k1:
            inv = st.number_input(
                "Investeringskosten prognose (\u20ac)",
                min_value=0.0,
                step=10000.0,
                format="%.2f",
                key="input_investeringskosten",
            )
            st.session_state["f_investeringskosten"] = inv
        with r_k2:
            btds = st.number_input(
                "Aantal BTD's (buitendienststellingen)",
                min_value=0,
                step=1,
                key="input_btds",
            )
            st.session_state["f_btds"] = btds

        btd_uren = st.number_input(
            "Totale BTD-duur (uren)",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key="input_btd_uren",
        )
        st.session_state["f_btd_uren"] = btd_uren

        autofilled = st.session_state.get("_autofilled_pid")
        if autofilled and not _upload_ok:
            st.caption(f"Velden automatisch verrijkt vanuit **{autofilled}**")

    # --- Store active PID for screen 2 ---
    active = st.session_state.get("f_pid", "").strip()
    if active:
        st.session_state["active_pid"] = active

    st.divider()
    if st.button("Analyseer maakbaarheid", type="primary", key="btn_analyse", use_container_width=True):
        mode = st.session_state.get("mode", "Demo")
        if mode == "Live" and not active:
            st.error("Vul eerst een ProjectID in (Live mode).")
            return

        if mode == "Demo":
            required = [
                "f_plandatum",
                "f_klanteis",
                "f_scope_delen",
                "f_scope_omvang",
                "f_locatie",
            ]
            missing: list[str] = []
            for k in required:
                v = st.session_state.get(k)
                if k in ["f_scope_delen", "f_scope_omvang", "f_locatie"]:
                    if not v:
                        missing.append(k)
                else:
                    if v is None or (hasattr(v, "toordinal") and pd.isna(v)):
                        missing.append(k)
            if missing:
                st.error("Vul eerst de demo-velden in: " + ", ".join(missing))
                return

        st.session_state["wizard_step"] = 2
        st.rerun()


# ---------------------------------------------------------------------------
# SCREEN 2 -- Maakbaarheidsanalyse
# ---------------------------------------------------------------------------

def screen_analysis():
    import streamlit.components.v1 as _comp
    _comp.html("<script>window.parent.document.querySelector('section.main').scrollTo(0,0);</script>", height=0)
    st.header("Maakbaarheidsanalyse")
    st.markdown(
        """
        <div class="pr-page-intro">
            <div class="pr-section-label">Analyse</div>
            <strong>Vergelijk het geselecteerde project met soortgelijke projecten.</strong>
            <p>De KPI's, verdelingen en risico-overzichten zijn gestileerd als compacte besliskaarten met nadruk op status en context.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    profiles = get_profiles()

    mode = st.session_state.get("mode", "Demo")
    active_pid = st.session_state.get("active_pid", "")

    selected = ""
    proj: pd.Series
    peers: pd.DataFrame

    if mode == "Live" and active_pid:
        proj_match = profiles[profiles["ProjectID"] == active_pid]
        if proj_match.empty:
            st.error(f"ProjectID '{active_pid}' niet gevonden in de data.")
            return
        selected = active_pid
        proj = proj_match.iloc[0]
        peers = compute_peer_scores(proj, profiles)
    else:
        # Demo mode: use the wizard inputs and generate synthetic peers/risks
        loc = str(st.session_state.get("f_locatie") or "")
        geo_part = loc.split("/")[0].strip()

        geo = geo_part if geo_part else np.nan
        tesi = str(st.session_state.get("f_scope_delen") or "").strip()
        cx = st.session_state.get("f_scope_omvang")

        plandatum = st.session_state.get("f_plandatum")
        klanteis = st.session_state.get("f_klanteis")

        slack_days = None
        if plandatum is not None and klanteis is not None:
            try:
                slack_days = (pd.to_datetime(plandatum) - pd.to_datetime(klanteis)).days
            except Exception:
                slack_days = None

        invkosten = st.session_state.get("f_investeringskosten", 0.0)
        tvp_uren = st.session_state.get("f_btd_uren", 0.0)

        proj = pd.Series(
            {
                "ProjectID": "DEMO",
                "Complexiteit": cx,
                "Gebied": loc,
                "Marktsegment": np.nan,
                "Prognose eindstand": invkosten,
                "primary_geo": geo,
                "primary_tesi": tesi,
                "total_tvp_hours": tvp_uren,
                "slack_days": slack_days,
                "HaalbaarheidBoolean": np.nan,
            }
        )

        selected = "DEMO"
        dummy_peers = get_dummy_projectdata()
        if not dummy_peers.empty:
            peers = dummy_peers
        else:
            peers, _, _ = generate_demo_backend(
                project=proj,
                profiles=profiles,
                risks_all=pd.DataFrame(columns=["ProjectID"]),
                n_peers=DEMO_N_PEERS,
                n_risks=DEMO_N_RISKS,
            )

    st.markdown("---")

    geo_code = proj.get("primary_geo")
    has_geo = pd.notna(geo_code) and str(geo_code).strip() != ""

    if has_geo:
        col_proj, col_map = st.columns([2, 3])
    else:
        col_proj = st.container()
        col_map = None

    with col_proj:
        pid_display = st.session_state.get("f_pid", selected) or selected or "—"
        project_naam = st.session_state.get("_project_naam", "")

        st.metric("ProjectID", pid_display)
        st.metric("Projectomschrijving", project_naam if project_naam else "\u2014")

        cx_val = proj["Complexiteit"] if pd.notna(proj["Complexiteit"]) else "\u2014"
        gebied_val = proj["Gebied"] if pd.notna(proj["Gebied"]) else "\u2014"
        st.metric("Complexiteit", cx_val)
        st.metric("Gebied", gebied_val)
        st.metric("Prognose", _fmt_euro(proj.get("Prognose eindstand")))

        n_peers = len(peers)
        if not peers.empty:
            top_dims = []
            geo = proj.get("primary_geo")
            tesi = proj.get("primary_tesi")
            cx = proj.get("Complexiteit")
            if pd.notna(geo) and geo and "primary_geo" in peers.columns:
                n_geo = (peers["primary_geo"].astype(str) == str(geo)).sum()
                top_dims.append(f"Geo={geo}: {n_geo}")
            if pd.notna(tesi) and tesi and "primary_tesi" in peers.columns:
                n_tesi = (peers["primary_tesi"] == tesi).sum()
                top_dims.append(f"TESI={tesi}: {n_tesi}")
            if pd.notna(cx) and cx and "Complexiteit" in peers.columns:
                n_cx = (peers["Complexiteit"] == cx).sum()
                top_dims.append(f"Complexiteit={cx}: {n_cx}")
            dim_str = " | ".join(top_dims) if top_dims else ""
            st.caption(f"**{n_peers}** vergelijkbare projecten | {dim_str}")
        else:
            st.caption("Geen vergelijkbare projecten gevonden.")

    if col_map is not None:
        with col_map:
            st.markdown(
                '<div class="pr-section-label">Spoortak op de kaart</div>',
                unsafe_allow_html=True,
            )
            geo_str = str(geo_code).strip()
            st.caption(f"Geocode **{geo_str}** — rode lijn = projecttraject langs het spoor")
            _render_geocode_map(geo_str, height=480)

    st.markdown("---")

    # --- 3 KPI cards ---
    st.subheader("Maakbaarheids-KPIs")
    k1, k2, k3 = st.columns(3)

    tvp_result = kpi_tvp(proj, peers if not peers.empty else profiles)
    klanteis_result = kpi_klanteis(proj, peers if not peers.empty else profiles)
    budget_result = kpi_budget(proj, peers if not peers.empty else profiles)

    def _align_kpi(result: dict) -> dict:
        """Re-derive signal/label from P25–P75 of peer_values so card matches graph."""
        pv = [v for v in result.get("peer_values", []) if v is not None and not np.isnan(v)]
        proj_val = result.get("project_value")
        if len(pv) < 2 or proj_val is None or (isinstance(proj_val, float) and np.isnan(proj_val)):
            return result
        s = pd.Series(pv)
        p25, p75 = float(s.quantile(0.25)), float(s.quantile(0.75))
        result["peer_p25"] = p25
        result["peer_p75"] = p75
        inside = p25 <= proj_val <= p75
        result["signal"] = "green" if inside else "red"
        result["label"] = "Realistisch" if inside else "Onrealistisch"
        return result

    tvp_result = _align_kpi(tvp_result)
    klanteis_result = _align_kpi(klanteis_result)
    budget_result = _align_kpi(budget_result)

    with k1:
        _signal_card("TVP Inschatting", tvp_result)
        _peer_distribution(
            tvp_result.get("peer_values", []),
            tvp_result.get("project_value"),
            tvp_result.get("peer_median"),
            "TVP-uren",
            peer_p25=tvp_result.get("peer_p25"),
            peer_p75=tvp_result.get("peer_p75"),
        )

    with k2:
        _signal_card("Klanteis", klanteis_result)
        _peer_distribution(
            klanteis_result.get("peer_values", []),
            klanteis_result.get("project_value"),
            klanteis_result.get("peer_median"),
            "Uitloop (dagen)",
            peer_p25=klanteis_result.get("peer_p25"),
            peer_p75=klanteis_result.get("peer_p75"),
            invert=True,
        )

    with k3:
        _signal_card("Budget", budget_result)
        _peer_distribution(
            budget_result.get("peer_values", []),
            budget_result.get("project_value"),
            budget_result.get("peer_median"),
            "Prognose eindstand (\u20ac)",
            peer_p25=budget_result.get("peer_p25"),
            peer_p75=budget_result.get("peer_p75"),
        )

    # --- Risk overview ---
    st.markdown("---")
    st.subheader("Risico-overzicht")

    proj_tesi = str(proj.get("primary_tesi", "") or "").strip() or None
    proj_geo_risk = str(proj.get("primary_geo", "") or "").strip() or None
    dummy_risks = get_dummy_risks(tesi_code=proj_tesi, geo_code=proj_geo_risk)
    if not dummy_risks.empty:
        cat_filter = st.selectbox(
            "Filter op categorie",
            options=["Alle"] + sorted(dummy_risks["Categorie"].unique().tolist()),
            key="risk_cat_filter",
        )
        display_risks = dummy_risks if cat_filter == "Alle" else dummy_risks[dummy_risks["Categorie"] == cat_filter]

        col_spider, col_table = st.columns([1, 1.5])

        with col_spider:
            st.markdown(
                '<div class="pr-section-label">Risicoprofiel per thema</div>',
                unsafe_allow_html=True,
            )
            _render_risk_spider(display_risks)

        with col_table:
            st.markdown(
                '<div class="pr-section-label">Risicolijst</div>',
                unsafe_allow_html=True,
            )
            display_cols = ["Categorie", "Thema", "Risico", "Impact", "Kans", "Risicoscore"]
            st.dataframe(
                display_risks[display_cols].sort_values("Risicoscore", ascending=False),
                hide_index=True,
                use_container_width=True,
                height=520,
            )
    else:
        st.info("Geen risicodata beschikbaar.")

    # --- Toetscriteria (hidden for now) ---
    criteria = st.session_state.get("_toetscriteria")
    if False and criteria:
        def _tc_on_change(i: int) -> None:
            key = f"tc_stand_{i}"
            cur = st.session_state.get(key)
            if cur == "OK":
                st.session_state[f"tc_signed_at_{i}"] = date.today()
            else:
                st.session_state.pop(f"tc_signed_at_{i}", None)

        st.markdown("---")
        st.subheader("Toetscriteria")
        st.caption("Tekening en datum alleen bij stand **OK**.")
        STAND_OPTIONS = ["OK", "AANDACHT", "RISICO", "NIET OK"]
        pm = st.session_state.get("_indiener") or "Projectmanager"

        # Group by categorie while preserving the original Excel order
        groups: dict[str, list[tuple[int, dict]]] = {}
        for i, item in enumerate(criteria):
            cat = str(item.get("categorie", "") or "").strip() or "Overig"
            groups.setdefault(cat, []).append((i, item))

        st.markdown('<div class="pr-toetscriteria">', unsafe_allow_html=True)
        with _border_container():
            h1, h2, h3, h4 = st.columns([4, 1, 1.5, 0.9])
            h1.caption("Criterium")
            h2.caption("Stand")
            h3.caption("Getekend door")
            h4.caption("Datum")

            for cat, rows in groups.items():
                st.markdown(
                    f'<p class="pr-tc-cat-label">{html.escape(cat)}</p>',
                    unsafe_allow_html=True,
                )
                for i, item in rows:
                    stand_raw = str(item.get("stand", "") or "").upper().strip()
                    stand_norm = stand_raw if stand_raw in STAND_OPTIONS else "OK"
                    if stand_norm == "OK":
                        st.session_state.setdefault(f"tc_signed_at_{i}", date.today())

                    current = st.session_state.get(f"tc_stand_{i}", stand_norm)
                    idx = STAND_OPTIONS.index(current if current in STAND_OPTIONS else "OK")

                    c1, c2, c3, c4 = st.columns([4, 1, 1.5, 0.9])
                    c1.markdown(
                        f'<span class="pr-toets-q">{html.escape(str(item.get("criterium", "")))}</span>',
                        unsafe_allow_html=True,
                    )
                    with c2:
                        st.selectbox(
                            "Stand",
                            STAND_OPTIONS,
                            index=idx,
                            key=f"tc_stand_{i}",
                            label_visibility="collapsed",
                            on_change=_tc_on_change,
                            args=(i,),
                        )
                    current = st.session_state.get(f"tc_stand_{i}", stand_norm)
                    if current == "OK":
                        c3.markdown(
                            f'<span class="pr-toets-meta">{html.escape(f"{pm} (projectmanager)")}</span>',
                            unsafe_allow_html=True,
                        )
                        d = st.session_state.get(f"tc_signed_at_{i}")
                        c4.markdown(
                            f'<span class="pr-toets-date">{html.escape(_fmt_signed_at(d))}</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        c3.markdown('<span class="pr-toets-empty">—</span>', unsafe_allow_html=True)
                        c4.markdown('<span class="pr-toets-empty">—</span>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def main():
    _inject_theme()
    if LOGO_PATH.is_file():
        st.sidebar.image(str(LOGO_PATH), use_container_width=True)

    labels = {1: "Projectgegevens", 2: "Maakbaarheidsanalyse"}
    st.session_state.setdefault("wizard_step", 1)
    step = st.sidebar.radio(
        "Menu",
        [1, 2],
        index=min(int(st.session_state.get("wizard_step", 1)) - 1, 1),
        format_func=lambda s: labels[s],
    )
    st.session_state["wizard_step"] = int(step)

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<div style='font-size:11px;color:var(--pr-text-muted);'>Demo/Live</div>",
        unsafe_allow_html=True,
    )
    live_on = st.sidebar.toggle(
        "Live modus",
        value=st.session_state.get("mode", "Demo") == "Live",
        key="mode_live_switch",
        label_visibility="collapsed",
    )
    st.session_state["mode"] = "Live" if live_on else "Demo"

    if st.session_state["wizard_step"] == 1:
        screen_project()
    else:
        screen_analysis()

    _inject_copilot_chat()


COPILOT_URL = (
    "https://copilotstudio.preview.microsoft.com/environments/"
    "c4e0448c-c123-e9a0-bdd9-72af30cbc54f/bots/cr662_test2345678/"
    "webchat?__version__=2"
)


def _inject_copilot_chat() -> None:
    """Floating Copilot Studio chatbot popup (bottom-right corner).

    HTML/CSS is injected into the Streamlit page so positioning is reliable.
    JS is attached via a tiny component (st.markdown strips onclick attrs).
    """
    import streamlit.components.v1 as components

    # Crop the embedded experience to hide its own header (cross-origin safe).
    COPILOT_IFRAME_CROP_PX = 56

    st.markdown(
        f"""
        <style>
        #copilot-fab {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            width: 52px;
            height: 52px;
            border-radius: 50%;
            background: {THEME["primary"]};
            color: #fff;
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 14px rgba(0,0,0,0.25);
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 150ms ease, transform 200ms ease;
        }}
        #copilot-fab:hover {{
            background: {THEME["primary_dark"]};
            transform: scale(1.08);
        }}
        #copilot-fab svg {{
            width: 26px;
            height: 26px;
            fill: #fff;
        }}

        #copilot-panel {{
            display: none;
            position: fixed;
            bottom: 88px;
            right: 24px;
            width: 400px;
            height: 560px;
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0,0,0,0.22);
            z-index: 99998;
            background: #fff;
            border: 1px solid {THEME["border"]};
        }}
        #copilot-panel.cp-open {{
            display: block;
            animation: cpSlideUp 200ms ease;
        }}
        @keyframes cpSlideUp {{
            from {{ opacity: 0; transform: translateY(16px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}
        #copilot-viewport {{
            height: calc(100% - 42px);
            overflow: hidden;
            background: #fff;
        }}
        #copilot-panel iframe {{
            width: 100%;
            height: calc(100% - 42px + {COPILOT_IFRAME_CROP_PX}px);
            border: none;
            transform: translateY(-{COPILOT_IFRAME_CROP_PX}px);
        }}
        #copilot-hdr {{
            height: 42px;
            background: {THEME["primary"]};
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 14px;
        }}
        #copilot-hdr span {{
            color: #fff;
            font-size: 0.85rem;
            font-weight: 600;
            font-family: Roboto, sans-serif;
        }}
        #copilot-x {{
            background: none;
            border: none;
            color: rgba(255,255,255,0.8);
            font-size: 20px;
            cursor: pointer;
            padding: 0 4px;
            line-height: 1;
        }}
        #copilot-x:hover {{
            color: #fff;
        }}
        </style>

        <button id="copilot-fab" title="Chat assistent">
            <svg viewBox="0 0 24 24"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
        </button>

        <div id="copilot-panel">
            <div id="copilot-hdr">
                <span>ProjectKompas Assistent</span>
                <button id="copilot-x">&times;</button>
            </div>
            <div id="copilot-viewport">
                <iframe src="{COPILOT_URL}" loading="lazy"></iframe>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    components.html(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            var fab = doc.getElementById('copilot-fab');
            var panel = doc.getElementById('copilot-panel');
            var xbtn = doc.getElementById('copilot-x');
            if (!fab || !panel) return;

            // Avoid double-binding on reruns
            if (fab.dataset && fab.dataset.bound === "1") return;
            if (fab.dataset) fab.dataset.bound = "1";

            fab.addEventListener('click', function() {
                panel.classList.toggle('cp-open');
            });
            if (xbtn) {
                xbtn.addEventListener('click', function() {
                    panel.classList.remove('cp-open');
                });
            }
        })();
        </script>
        """,
        height=0,
        scrolling=False,
    )


if __name__ == "__main__":
    main()
