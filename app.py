"""
Sportech IB · Dashboard  —  Redesigned UI/UX
A production-grade SaaS analytics platform for brand portfolio management.
"""

import re
import unicodedata
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import firebase_admin
from firebase_admin import credentials, db

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & GLOBAL STYLES
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Sportech IB · Dashboard",
    page_icon="🏍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

/* ── Design tokens ── */
:root {
    --bg:          #0A0D14;
    --surface:     #111827;
    --surface-2:   #1C2333;
    --surface-3:   #242E42;
    --border:      #2A3548;
    --border-light:#354060;
    --accent:      #3B82F6;
    --accent-dim:  #1E3A5F;
    --accent-glow: rgba(59,130,246,0.15);
    --green:       #22C55E;
    --green-dim:   #14532D;
    --red:         #EF4444;
    --red-dim:     #450A0A;
    --amber:       #F59E0B;
    --amber-dim:   #431C00;
    --text-1:      #F1F5F9;
    --text-2:      #94A3B8;
    --text-3:      #64748B;
    --font:        'DM Sans', system-ui, sans-serif;
    --font-mono:   'DM Mono', monospace;
    --radius:      10px;
    --radius-lg:   16px;
    --shadow:      0 4px 24px rgba(0,0,0,0.4);
    --shadow-sm:   0 2px 8px rgba(0,0,0,0.3);
}

/* ── Base reset ── */
html, body, [class*="css"], .stApp {
    font-family: var(--font) !important;
    background-color: var(--bg) !important;
    color: var(--text-1) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer { visibility: hidden; }
header {
    background: transparent !important;
}
[data-testid="collapsedControl"] {
    display: block !important;
}
.stDeployButton { display: none; }
.block-container { padding: 2rem 2.5rem 3rem !important; max-width: 100% !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * { font-family: var(--font) !important; }
[data-testid="stSidebar"] .stRadio > label { display: none; }
[data-testid="stSidebar"] .stRadio > div {
    display: flex;
    flex-direction: column;
    gap: 2px;
}
[data-testid="stSidebar"] .stRadio > div > label {
    border-radius: var(--radius) !important;
    padding: 10px 14px !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: var(--text-2) !important;
    cursor: pointer;
    transition: all 0.15s ease;
    border: 1px solid transparent;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: var(--surface-2) !important;
    color: var(--text-1) !important;
    border-color: var(--border) !important;
}
[data-testid="stSidebar"] .stRadio > div > label[data-baseweb="radio"] input:checked ~ div {
    color: var(--accent) !important;
}

/* Active nav item */
[data-testid="stSidebar"] .stRadio [aria-checked="true"] + div {
    background: var(--accent-glow) !important;
    border-color: var(--accent-dim) !important;
    color: var(--accent) !important;
}

/* ── Page title ── */
.page-header {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 2rem;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
}
.page-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text-1);
    letter-spacing: -0.02em;
    margin: 0;
}
.page-subtitle {
    font-size: 0.875rem;
    color: var(--text-3);
    margin: 0;
}

/* ── KPI cards ── */
.kpi-grid {
    display: grid;
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.kpi-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s ease;
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent);
    opacity: 0;
    transition: opacity 0.2s ease;
}
.kpi-card:hover { border-color: var(--border-light); }
.kpi-card:hover::before { opacity: 1; }
.kpi-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-3);
    margin-bottom: 0.5rem;
}
.kpi-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text-1);
    letter-spacing: -0.03em;
    line-height: 1;
    margin-bottom: 0.375rem;
    font-family: var(--font-mono);
}
.kpi-delta { font-size: 0.8rem; font-weight: 500; display: flex; align-items: center; gap: 4px; }
.kpi-delta.pos { color: var(--green); }
.kpi-delta.neg { color: var(--red); }
.kpi-delta.neu { color: var(--text-3); }
.kpi-help { font-size: 0.72rem; color: var(--text-3); margin-top: 0.25rem; }

/* ── Section headers ── */
.section-label {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-3);
    margin: 2rem 0 1rem;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* ── Filter tag pills ── */
.filter-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 1.5rem;
    align-items: center;
}
.filter-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: var(--accent-dim);
    color: var(--accent);
    border: 1px solid rgba(59,130,246,0.3);
    border-radius: 100px;
    padding: 3px 10px;
    font-size: 0.75rem;
    font-weight: 600;
}
.filter-all {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--text-3);
    font-size: 0.75rem;
}

/* ── Status badges ── */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 100px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.badge-new    { background: var(--green-dim);  color: var(--green); }
.badge-std    { background: var(--accent-dim); color: var(--accent); }
.badge-out    { background: #1F1F1F;           color: var(--text-3); }

/* ── Alert / info boxes ── */
.alert {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 16px;
    border-radius: var(--radius);
    font-size: 0.82rem;
    margin-bottom: 1rem;
}
.alert-warn { background: var(--amber-dim); border: 1px solid rgba(245,158,11,0.3); color: #FDE68A; }
.alert-info { background: var(--accent-dim); border: 1px solid rgba(59,130,246,0.3); color: #BFDBFE; }
.alert-success { background: var(--green-dim); border: 1px solid rgba(34,197,94,0.3); color: #BBF7D0; }
.alert-error { background: var(--red-dim); border: 1px solid rgba(239,68,68,0.3); color: #FECACA; }

/* ── Streamlit overrides ── */
/* Metrics */
[data-testid="stMetric"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    padding: 1.1rem 1.25rem !important;
}
[data-testid="stMetricLabel"] { color: var(--text-3) !important; font-size: 0.75rem !important; font-weight: 600 !important; text-transform: uppercase; letter-spacing: 0.06em; }
[data-testid="stMetricValue"] { color: var(--text-1) !important; font-family: var(--font-mono) !important; }
[data-testid="stMetricDelta"] svg { display: none; }

/* Buttons */
.stButton > button {
    background: var(--accent) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--radius) !important;
    font-family: var(--font) !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    padding: 0.6rem 1.2rem !important;
    transition: all 0.15s ease !important;
    box-shadow: 0 0 0 0 transparent;
}
.stButton > button:hover {
    background: #2563EB !important;
    box-shadow: 0 0 20px rgba(59,130,246,0.3) !important;
    transform: translateY(-1px) !important;
}
.stButton > button:disabled {
    background: var(--surface-3) !important;
    color: var(--text-3) !important;
}

/* Select boxes */
.stSelectbox [data-baseweb="select"], .stMultiSelect [data-baseweb="select"] {
    background-color: var(--surface-2) !important;
    border-color: var(--border) !important;
    border-radius: var(--radius) !important;
    color: var(--text-1) !important;
}

/* DataFrames */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    overflow: hidden !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    color: var(--text-2) !important;
}

/* File uploader */
[data-testid="stFileUploader"] {
    background: var(--surface-2) !important;
    border: 1px dashed var(--border-light) !important;
    border-radius: var(--radius) !important;
}

/* Dividers */
hr { border-color: var(--border) !important; margin: 1.5rem 0 !important; }

/* Plotly charts dark background */
.js-plotly-plot .plotly { background: transparent !important; }

/* Data editor */
[data-testid="stDataEditor"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}

/* Success / warning / error Streamlit callouts */
[data-testid="stNotification"] {
    border-radius: var(--radius) !important;
}

/* Sidebar section headers */
.sidebar-section {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-3);
    padding: 0.75rem 0 0.25rem;
    margin-top: 0.5rem;
}

/* Upload status dot */
.upload-dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}
.dot-ok  { background: var(--green); box-shadow: 0 0 6px var(--green); }
.dot-miss { background: var(--text-3); }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
STATUS_OPTIONS = ["NEW", "STANDARD", "PHASE OUT"]
FAMILY_OPTIONS = ["2 WHEELS", "FREE TIME", "OUTDOOR TECH", "UNCLASSIFIED"]
MONTH_BUDGET_COLS = [f"Budget {MONTHS_ES[i]}" for i in range(1, 13)]

FAMILY_COLORS = {
    "2 WHEELS":     "#3B82F6",
    "FREE TIME":    "#22C55E",
    "OUTDOOR TECH": "#F59E0B",
    "UNCLASSIFIED": "#64748B",
}

# Dark-mode Plotly template
CHART_TEMPLATE = dict(
    plot_bgcolor="#111827",
    paper_bgcolor="#111827",
    font=dict(family="DM Sans, system-ui, sans-serif", color="#94A3B8", size=12),
    colorway=["#3B82F6", "#22C55E", "#F59E0B", "#64748B", "#A78BFA", "#F472B6"],
    xaxis=dict(gridcolor="#1C2333", zeroline=False, linecolor="#2A3548", tickcolor="#64748B"),
    yaxis=dict(gridcolor="#1C2333", zeroline=False, linecolor="#2A3548", tickcolor="#64748B"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
    margin=dict(t=60, b=40, l=50, r=20),
    hoverlabel=dict(bgcolor="#1C2333", bordercolor="#2A3548", font=dict(color="#F1F5F9")),
)


# ══════════════════════════════════════════════════════════════════════════════
# PURE HELPER FUNCTIONS (unchanged logic)
# ══════════════════════════════════════════════════════════════════════════════

def pct_delta(current: float, base: float) -> float:
    if base == 0:
        return 0.0 if current == 0 else np.nan
    return (current / base) - 1


def safe_ratio(num: float, den: float) -> float:
    if den == 0:
        return np.nan
    return num / den


def color_negative(value: float) -> str:
    if pd.isna(value):
        return "color: #64748B"
    return "color: #EF4444; font-weight: 700" if value < 0 else "color: #22C55E; font-weight: 700"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return 255, 255, 255
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)


def _interpolate_hex(start: str, end: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    s, e = _hex_to_rgb(start), _hex_to_rgb(end)
    mixed = tuple(int(round(a + (b - a) * ratio)) for a, b in zip(s, e))
    return _rgb_to_hex(mixed)


def _contrast_text_color(bg_hex: str) -> str:
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111827" if luminance > 0.6 else "#F1F5F9"


def style_gradient_fallback(series: pd.Series, low_color: str, high_color: str) -> pd.Series:
    valid = series.dropna()
    if valid.empty:
        return pd.Series([""] * len(series), index=series.index)
    min_val, max_val = valid.min(), valid.max()
    span = max_val - min_val
    styles = []
    for v in series:
        if pd.isna(v):
            styles.append("")
            continue
        ratio = 0.5 if span == 0 else (v - min_val) / span
        bg = _interpolate_hex(low_color, high_color, ratio)
        fg = _contrast_text_color(bg)
        styles.append(f"background-color: {bg}; color: {fg};")
    return pd.Series(styles, index=series.index)


def _normalize_col(col):
    return re.sub(r"\s+", "_", str(col).strip().lower())


def _normalize_text(col):
    text = str(col).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text)


def _normalize_brand(value):
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _first_existing(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _get_series(df: pd.DataFrame, column: str) -> pd.Series:
    values = df[column]
    if isinstance(values, pd.DataFrame):
        return values.iloc[:, 0]
    return values


def _auto_short_name(brand: str) -> str:
    text = str(brand)
    text = re.sub(r"^\s*\d+\s*-\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(familia|famlia)\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^A-Za-z\s]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    if not cleaned:
        return "BRAND"
    tokens = cleaned.split()
    return tokens[0][:12] if len(tokens) == 1 else " ".join(tokens[:2])[:18]


def _to_plain_dict(value):
    if isinstance(value, dict):
        return {k: _to_plain_dict(v) for k, v in value.items()}
    if hasattr(value, "items"):
        return {k: _to_plain_dict(v) for k, v in value.items()}
    return value


def _normalize_database_url(value):
    if not isinstance(value, str):
        return None
    candidate = value.strip().strip('"').strip("'")
    if not candidate:
        return None
    if candidate.startswith("https://https://"):
        candidate = "https://" + candidate[len("https://https://"):]
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.netloc.lower() == "https":
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_app_password() -> str:
    secrets = _to_plain_dict(st.secrets)
    if not isinstance(secrets, dict):
        return ""
    return str(secrets.get("APP_PASSWORD", "")).strip()


def require_app_password() -> None:
    expected_password = _get_app_password()
    if not expected_password:
        return

    if st.session_state.get("authenticated", False):
        return

    st.markdown("""
    <div class="alert alert-warn" style="max-width:520px;">
        🔒 Esta aplicación está protegida. Introduce la contraseña para continuar.
    </div>
    """, unsafe_allow_html=True)

    entered_password = st.text_input("Contraseña", type="password", key="app_password")
    if st.button("Entrar", type="primary"):
        if entered_password == expected_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# FIREBASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _extract_firebase_config():
    secrets = _to_plain_dict(st.secrets)
    firebase_section = secrets.get("firebase", {}) if isinstance(secrets, dict) else {}
    merged = {}
    if isinstance(secrets, dict):
        merged.update(secrets)
    if isinstance(firebase_section, dict):
        merged.update(firebase_section)

    db_url = _normalize_database_url(
        merged.get("databaseURL") or merged.get("database_url") or merged.get("FIREBASE_DATABASE_URL")
    )
    sa = merged.get("service_account")
    if not isinstance(sa, dict):
        sa = {k: merged.get(k) for k in [
            "type", "project_id", "private_key_id", "private_key", "client_email",
            "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url",
        ] if merged.get(k) is not None}
    if isinstance(sa, dict) and isinstance(sa.get("private_key"), str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    config_source = "firebase.service_account" if merged.get("service_account") else "top-level keys"
    return sa if isinstance(sa, dict) else {}, db_url, config_source


@st.cache_resource(show_spinner="Conectando a Firebase…")
def init_firebase():
    try:
        cred_info, database_url, config_source = _extract_firebase_config()
        if firebase_admin._apps:
            return True, "Firebase conectado", config_source
        if not database_url or not all(cred_info.get(k) for k in ["project_id", "private_key", "client_email"]):
            return False, "Faltan credenciales de Firebase en st.secrets", config_source
        firebase_admin.initialize_app(credentials.Certificate(cred_info), {"databaseURL": database_url})
        return True, "Firebase conectado", config_source
    except Exception as e:
        return False, f"Error Firebase: {e}", "unknown"


def save_df_to_firebase(path: str, df: pd.DataFrame):
    import sys, json
    payload = {
        "columns": [str(c) for c in df.columns],
        "rows": df.replace({np.nan: None}).values.tolist(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    size_bytes = sys.getsizeof(json.dumps(payload))
    if size_bytes > 8_000_000:
        raise ValueError(f"Dataset demasiado grande ({size_bytes / 1e6:.1f} MB > 8 MB).")
    db.reference(path).set(payload)


@st.cache_data(ttl=300, show_spinner=False)
def load_df_from_firebase(path: str) -> pd.DataFrame:
    raw = db.reference(path).get()
    if not raw:
        return pd.DataFrame()

    def _coerce(rows, columns):
        if isinstance(rows, dict):
            try:
                rows = [rows[k] for k in sorted(rows, key=lambda x: int(x) if str(x).isdigit() else str(x))]
            except Exception:
                rows = list(rows.values())
        rows = [] if rows is None else (rows if isinstance(rows, list) else [rows])
        columns = ([] if columns is None else
                   (list(columns) if hasattr(columns, "__iter__") and not isinstance(columns, str) else [columns]))
        return rows, [str(c) for c in columns]

    if isinstance(raw, dict) and "columns" in raw and "rows" in raw:
        rows, columns = _coerce(raw.get("rows"), raw.get("columns"))
        if rows and all(isinstance(item, dict) or hasattr(item, "items") for item in rows):
            return pd.DataFrame.from_records([dict(item) for item in rows], columns=columns or None)
        return pd.DataFrame(rows, columns=columns or None)
    if isinstance(raw, list):
        if all(isinstance(item, dict) or hasattr(item, "items") for item in raw):
            return pd.DataFrame.from_records([dict(item) for item in raw])
        return pd.DataFrame({"value": raw})
    if isinstance(raw, dict):
        rows = []
        for key, value in raw.items():
            if isinstance(value, dict) or hasattr(value, "items"):
                row = dict(value)
                if "_key" not in row:
                    row["_key"] = key
                rows.append(row)
            else:
                rows.append({"_key": key, "value": value})
        return pd.DataFrame.from_records(rows)
    return pd.DataFrame()


def invalidate_firebase_cache():
    load_df_from_firebase.clear()


# ══════════════════════════════════════════════════════════════════════════════
# FILE READING
# ══════════════════════════════════════════════════════════════════════════════

def read_sheet(uploaded_file, sheet_name):
    bio = BytesIO(uploaded_file.read())
    uploaded_file.seek(0)
    xls = pd.ExcelFile(bio)
    return pd.read_excel(bio, sheet_name=sheet_name if sheet_name in xls.sheet_names else 0)


def read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    uploaded_file.seek(0)
    data = uploaded_file.read()
    uploaded_file.seek(0)
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else str(data)
    try:
        return pd.read_csv(BytesIO(text.encode("utf-8")), sep=None, engine="python")
    except Exception as first_error:
        for sep in (";", ",", "\t", "|"):
            try:
                return pd.read_csv(BytesIO(text.encode("utf-8")), sep=sep)
            except Exception:
                continue
        raise ValueError(f"No se pudo leer el CSV. Detalle: {first_error}") from first_error


# ══════════════════════════════════════════════════════════════════════════════
# DATASET VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_dataset(df: pd.DataFrame, dataset_key: str, dataset_name: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError(f"{dataset_name} está vacío.")
    dfx = df.copy()
    dfx.columns = [str(c).strip() for c in dfx.columns]

    if dataset_key == "sales":
        rename = {}
        brand_col = _first_existing(dfx, ["Clave 1", "Nombre Cliente", "Marca", "Nombre"])
        if brand_col: rename[brand_col] = "Nombre"
        net_col = _first_existing(dfx, ["Importe Neto", "Importe"])
        if net_col: rename[net_col] = "Importe Neto"
        margin_col = _first_existing(dfx, ["CR3: % Margen s/Venta", "Margen %", "Margin %"])
        if margin_col: rename[margin_col] = "CR3: % Margen s/Venta"
        dfx = dfx.rename(columns=rename)

        required = ["Nombre", "Importe Neto"]
        missing = [c for c in required if c not in dfx.columns]
        if missing:
            raise ValueError(f"{dataset_name}: faltan columnas {missing}.")

        month_col = _first_existing(dfx, ["Mes Factura", "Mes", "Month"])
        if month_col is None:
            date_col = _first_existing(dfx, ["Fecha", "Fecha Factura", "Date"])
            if date_col is None:
                raise ValueError(f"{dataset_name}: falta columna de mes o fecha.")
            parsed = pd.to_datetime(dfx[date_col], errors="coerce", dayfirst=True)
            invalid_dates = dfx[date_col].notna() & parsed.isna()
            if invalid_dates.any():
                raise ValueError(f"{dataset_name}: hay fechas inválidas en '{date_col}'.")
            dfx["Mes Factura"] = parsed.dt.month
        else:
            dfx["Mes Factura"] = pd.to_numeric(dfx[month_col], errors="coerce")
            if (dfx[month_col].notna() & dfx["Mes Factura"].isna()).any():
                raise ValueError(f"{dataset_name}: valores inválidos en '{month_col}'.")

        dfx = dfx[dfx["Mes Factura"].between(1, 12, inclusive="both")]
        importe_num = pd.to_numeric(dfx["Importe Neto"], errors="coerce")
        if (dfx["Importe Neto"].notna() & importe_num.isna()).any():
            raise ValueError(f"{dataset_name}: hay importes netos inválidos.")
        dfx["Importe Neto"] = importe_num.fillna(0)

        if "Margen_Euros" not in dfx.columns:
            mg_pct_col = _first_existing(dfx, ["CR3: % Margen s/Venta", "Margen %", "Margin %"])
            if mg_pct_col:
                dfx["Margen_Euros"] = (dfx["Importe Neto"]
                    * pd.to_numeric(dfx[mg_pct_col], errors="coerce").fillna(0) / 100)
            else:
                dfx["Margen_Euros"] = 0
        dfx["Margen_Euros"] = pd.to_numeric(dfx["Margen_Euros"], errors="coerce").fillna(0)

    elif dataset_key == "stock":
        rename = {}
        brand_col = _first_existing(dfx, ["Clave 1", "Marca"])
        if brand_col: rename[brand_col] = "Marca"
        code_col = _first_existing(dfx, ["Código Artículo", "Codigo Articulo", "Código", "Codigo"])
        if code_col: rename[code_col] = "Codigo Articulo"
        amount_col = _first_existing(dfx, ["Importe", "Stock"])
        if amount_col: rename[amount_col] = "Importe"
        dfx = dfx.rename(columns=rename)

        required = ["Marca", "Codigo Articulo", "Importe"]
        missing = [c for c in required if c not in dfx.columns]
        if missing:
            raise ValueError(f"{dataset_name}: faltan columnas {missing}.")

        dfx["Codigo Articulo"] = dfx["Codigo Articulo"].astype(str).str.strip()
        has_code = dfx["Codigo Articulo"].replace({"": np.nan, "nan": np.nan, "None": np.nan}).notna()
        dfx = dfx[has_code].copy()
        dfx["Stock"] = pd.to_numeric(dfx["Importe"], errors="coerce").fillna(0)

    elif dataset_key == "margin_ly":
        rename = {}
        month_name_to_number = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        }
        brand_col = _first_existing(dfx, ["Clave 1 Stock", "Clave 1", "Marca"])
        if brand_col: rename[brand_col] = "Marca"
        for c in dfx.columns:
            n = _normalize_col(c)
            n_plain = _normalize_text(c)
            if n in ("acumulado_-_revenue", "acumulado_revenue", "ly_rev", "revenue_ly", "ly_revenue"):
                rename[c] = "LY_Rev"
            if n in ("acumulado_-_margen_€", "acumulado_margen_€", "acumulado_margen_eur", "ly_mgeur", "ly_mg_eur"):
                rename[c] = "LY_MgEur"
            if n in ("acumulado_-_margen%", "acumulado_margen%", "ly_mg%", "ly_mg_pct"):
                rename[c] = "LY_Mg%"

            month_match = re.match(
                r"^(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*-\s*(.+)$",
                n_plain,
            )
            if month_match:
                month_name, metric = month_match.groups()
                month_num = month_name_to_number[month_name]
                metric = metric.strip()
                if metric == "revenue":
                    rename[c] = f"LY_M{month_num:02d}_Rev"
                elif metric in ("margen%", "margen %"):
                    rename[c] = f"LY_M{month_num:02d}_MgPct"
                elif metric in ("margen", "margen eur", "margen e", "margen euro"):
                    rename[c] = f"LY_M{month_num:02d}_MgEur"

        dfx = dfx.rename(columns=rename)
        if "Marca" not in dfx.columns:
            raise ValueError(f"{dataset_name}: falta columna de marca.")

        monthly_rev_cols     = [f"LY_M{i:02d}_Rev"   for i in range(1, 13) if f"LY_M{i:02d}_Rev"   in dfx.columns]
        monthly_mg_eur_cols  = [f"LY_M{i:02d}_MgEur" for i in range(1, 13) if f"LY_M{i:02d}_MgEur" in dfx.columns]
        monthly_mg_pct_cols  = [f"LY_M{i:02d}_MgPct" for i in range(1, 13) if f"LY_M{i:02d}_MgPct" in dfx.columns]

        for c in [*monthly_rev_cols, *monthly_mg_eur_cols, *monthly_mg_pct_cols]:
            dfx[c] = pd.to_numeric(dfx[c], errors="coerce").fillna(0)
        for c in ["LY_Rev", "LY_MgEur", "LY_Mg%"]:
            if c in dfx.columns:
                dfx[c] = pd.to_numeric(dfx[c], errors="coerce").fillna(0)

        if "LY_Rev" not in dfx.columns:
            dfx["LY_Rev"] = dfx[monthly_rev_cols].sum(axis=1) if monthly_rev_cols else 0
        if "LY_MgEur" not in dfx.columns:
            dfx["LY_MgEur"] = dfx[monthly_mg_eur_cols].sum(axis=1) if monthly_mg_eur_cols else 0
        if "LY_Mg%" not in dfx.columns:
            if monthly_mg_pct_cols and not monthly_mg_eur_cols:
                dfx["LY_Mg%"] = dfx[monthly_mg_pct_cols].mean(axis=1)
            else:
                dfx["LY_Mg%"] = np.where(dfx["LY_Rev"] != 0, dfx["LY_MgEur"] / dfx["LY_Rev"] * 100, 0)

        for c in ["LY_Rev", "LY_MgEur", "LY_Mg%"]:
            dfx[c] = pd.to_numeric(dfx.get(c, 0), errors="coerce").fillna(0)

    return dfx


# ══════════════════════════════════════════════════════════════════════════════
# BRAND CONFIG HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_brand_master(df_sales, df_stock, df_margin_ly):
    brand_map = {}
    def _register(series: pd.Series):
        for value in series.dropna().astype(str).str.strip():
            if not value:
                continue
            key = _normalize_brand(value)
            if key and key not in brand_map:
                brand_map[key] = value
    _register(_get_series(df_sales, "Nombre"))
    _register(_get_series(df_stock, "Marca"))
    _register(_get_series(df_margin_ly, "Marca"))

    master = pd.DataFrame(sorted(
        ({"Brand": brand, "BrandKey": key} for key, brand in brand_map.items()),
        key=lambda x: x["BrandKey"]
    ))
    if master.empty:
        return pd.DataFrame(columns=["Brand", "BrandKey"])
    master["BrandKey"] = master["Brand"].apply(_normalize_brand)
    return master


def validate_brand_config_csv(df_csv: pd.DataFrame, expected_brand_keys: set[str]):
    required = {"Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %"}
    missing = required - set(df_csv.columns)
    if missing:
        raise ValueError(f"CSV inválido: faltan columnas {sorted(missing)}")

    cfg = df_csv.copy()
    cfg["BrandKey"] = cfg["Brand"].apply(_normalize_brand)
    for col in MONTH_BUDGET_COLS:
        if col not in cfg.columns:
            cfg[col] = np.nan

    bad_status = sorted(set(cfg[~cfg["Status"].isin(STATUS_OPTIONS)]["Status"].dropna().astype(str)))
    bad_family = sorted(set(cfg[~cfg["Family"].isin(FAMILY_OPTIONS)]["Family"].dropna().astype(str)))
    if bad_status: raise ValueError(f"CSV inválido: Status no permitido {bad_status}")
    if bad_family: raise ValueError(f"CSV inválido: Family no permitida {bad_family}")

    numeric_cols = ["Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
    for col in numeric_cols:
        cfg[col] = pd.to_numeric(cfg[col], errors="coerce")

    if cfg["BrandKey"].duplicated().any():
        dup = cfg.loc[cfg["BrandKey"].duplicated(), "Brand"].tolist()
        raise ValueError(f"CSV inválido: marcas duplicadas {dup}")

    missing_brands = sorted(expected_brand_keys - set(cfg["BrandKey"]))
    if missing_brands:
        raise ValueError(f"CSV incompleto: faltan {len(missing_brands)} marcas del master list")
    extra_brands = sorted(set(cfg["BrandKey"]) - expected_brand_keys)
    if extra_brands:
        raise ValueError(f"CSV inválido: marcas no reconocidas ({len(extra_brands)})")
    return cfg


def validate_brand_config_df(df_cfg: pd.DataFrame, expected_brand_keys: set[str], immutable_brand_map=None):
    cfg = validate_brand_config_csv(df_cfg, expected_brand_keys)
    if immutable_brand_map is not None:
        cfg_brand_map = cfg.set_index("BrandKey")["Brand"].astype(str).to_dict()
        changed = [k for k, v in immutable_brand_map.items() if k in cfg_brand_map and cfg_brand_map[k] != v]
        if changed:
            raise ValueError("'Brand' es inmutable y no puede editarse manualmente.")
    return cfg


def build_brand_config(master_df: pd.DataFrame, saved_cfg: pd.DataFrame) -> pd.DataFrame:
    cfg = master_df.copy()
    cfg["Short Name"] = cfg["Brand"].apply(_auto_short_name)
    cfg["Status"] = "STANDARD"
    cfg["Family"] = "UNCLASSIFIED"
    cfg["Annual Budget"] = 0.0
    cfg["Expected Margin %"] = 0.0
    cfg["Budget_Source"] = "Auto-spread"
    for c in MONTH_BUDGET_COLS:
        cfg[c] = np.nan

    if not saved_cfg.empty:
        temp = saved_cfg.copy()
        if "BrandKey" not in temp.columns and "Brand" in temp.columns:
            temp["BrandKey"] = temp["Brand"].apply(_normalize_brand)
        cfg = cfg.merge(temp.drop_duplicates("BrandKey"), on="BrandKey", how="left", suffixes=("", "_saved"))
        for col in ["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]:
            saved_col = f"{col}_saved"
            if saved_col in cfg.columns:
                cfg[col] = cfg[saved_col].combine_first(cfg[col])
        keep = ["Brand", "BrandKey", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
        cfg = cfg[[c for c in keep if c in cfg.columns]]

    for c in ["Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]:
        cfg[c] = pd.to_numeric(cfg[c], errors="coerce")

    monthly_sum = cfg[MONTH_BUDGET_COLS].fillna(0).sum(axis=1)
    cfg["Annual Budget"] = np.where(cfg["Annual Budget"].fillna(0) > 0, cfg["Annual Budget"], monthly_sum)
    needs_spread = monthly_sum == 0
    if "Budget_Source" not in cfg.columns:
        cfg["Budget_Source"] = "Manual"
    cfg["Budget_Source"] = np.where(needs_spread, "Auto-spread (uniform)", "Manual")
    for col in MONTH_BUDGET_COLS:
        cfg[col] = np.where(needs_spread, cfg["Annual Budget"].fillna(0) / 12, cfg[col].fillna(0))

    em = cfg["Expected Margin %"].fillna(0)
    cfg["Expected Margin %"] = np.where(em > 1, em / 100, em)
    cfg["Status"] = cfg["Status"].where(cfg["Status"].isin(STATUS_OPTIONS), "STANDARD")
    cfg["Family"] = cfg["Family"].where(cfg["Family"].isin(FAMILY_OPTIONS), "UNCLASSIFIED")
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
# CORE MODEL PREPARATION
# ══════════════════════════════════════════════════════════════════════════════

def prepare_model(df_sales, df_stock, df_margin_ly, brand_cfg, current_month):
    sales = df_sales.copy()
    sales["BrandKey"] = _get_series(sales, "Nombre").apply(_normalize_brand)
    sales["Mes Factura"] = pd.to_numeric(sales["Mes Factura"], errors="coerce").fillna(0).astype(int)

    sales_ytd = sales[sales["Mes Factura"] <= current_month].copy()
    grouped = sales_ytd.groupby("BrandKey", as_index=False).agg(
        Revenue_YTD=("Importe Neto", "sum"),
        Margin_EUR_YTD=("Margen_Euros", "sum"),
    )
    grouped["Margin_PCT_YTD"] = np.where(
        grouped["Revenue_YTD"] != 0, grouped["Margin_EUR_YTD"] / grouped["Revenue_YTD"], 0
    )
    grouped["Revenue_YTD_raw"] = grouped["Revenue_YTD"]

    monthly_sales = sales.groupby(["BrandKey", "Mes Factura"], as_index=False).agg(
        Revenue_Month=("Importe Neto", "sum"),
        Margin_EUR_Month=("Margen_Euros", "sum"),
    )

    prev_month = 12 if current_month == 1 else current_month - 1
    prev_month_sales = (
        monthly_sales[monthly_sales["Mes Factura"] == prev_month]
        .groupby("BrandKey", as_index=False)
        .agg(Revenue_Prev_Month=("Revenue_Month", "sum"), Margin_EUR_Prev_Month=("Margin_EUR_Month", "sum"))
    )
    current_month_sales = (
        monthly_sales[monthly_sales["Mes Factura"] == current_month]
        .groupby("BrandKey", as_index=False)
        .agg(Revenue_Current_Month=("Revenue_Month", "sum"), Margin_EUR_Current_Month=("Margin_EUR_Month", "sum"))
    )

    stock = df_stock.copy()
    stock["BrandKey"] = _get_series(stock, "Marca").apply(_normalize_brand)
    if "Mes" in stock.columns:
        stock_current = stock[stock["Mes"] == current_month]
        if stock_current.empty:
            latest_mes = stock["Mes"].max()
            stock_current = stock[stock["Mes"] == latest_mes]
        stock = stock_current.groupby("BrandKey", as_index=False)["Stock"].sum()
    else:
        stock = stock.groupby("BrandKey", as_index=False)["Stock"].sum()

    ly = df_margin_ly.copy()
    ly["BrandKey"] = _get_series(ly, "Marca").apply(_normalize_brand)
    monthly_ly_rev_cols    = [f"LY_M{i:02d}_Rev"   for i in range(1, 13) if f"LY_M{i:02d}_Rev"   in ly.columns]
    monthly_ly_mg_eur_cols = [f"LY_M{i:02d}_MgEur" for i in range(1, 13) if f"LY_M{i:02d}_MgEur" in ly.columns]

    ly_agg = {}
    if "LY_Rev"   in ly.columns: ly_agg["LY_Rev"]   = "sum"
    if "LY_MgEur" in ly.columns: ly_agg["LY_MgEur"] = "sum"
    ly_agg.update({c: "sum" for c in monthly_ly_rev_cols})
    ly_agg.update({c: "sum" for c in monthly_ly_mg_eur_cols})
    ly = ly.groupby("BrandKey", as_index=False).agg(ly_agg)
    if "LY_Rev" in ly.columns and "LY_MgEur" in ly.columns:
        ly["LY_Mg_pct"] = np.where(ly["LY_Rev"] != 0, ly["LY_MgEur"] / ly["LY_Rev"], 0)
    else:
        ly["LY_Mg_pct"] = 0

    if current_month == 1 and {"LY_M12_Rev", "LY_M12_MgEur"}.issubset(ly.columns):
        prev_month_sales = ly[["BrandKey", "LY_M12_Rev", "LY_M12_MgEur"]].rename(
            columns={"LY_M12_Rev": "Revenue_Prev_Month", "LY_M12_MgEur": "Margin_EUR_Prev_Month"}
        )
    elif current_month == 1:
        st.sidebar.warning("⚠ Enero: faltan LY_M12_Rev / LY_M12_MgEur para tendencia de mes anterior.")

    if monthly_ly_rev_cols:
        ly["LY_Rev"]          = ly[monthly_ly_rev_cols].sum(axis=1)
        ly["LY_Rev_YTD"]      = ly[monthly_ly_rev_cols[:current_month]].sum(axis=1)
        ly["LY_Rev_Remaining"]= ly[monthly_ly_rev_cols[current_month:]].sum(axis=1)
    else:
        ly["LY_Rev_YTD"]       = ly.get("LY_Rev", 0) * current_month / 12
        ly["LY_Rev_Remaining"] = ly.get("LY_Rev", 0) * (12 - current_month) / 12

    if monthly_ly_mg_eur_cols:
        ly["LY_MgEur"]     = ly[monthly_ly_mg_eur_cols].sum(axis=1)
        ly["LY_MgEur_YTD"] = ly[monthly_ly_mg_eur_cols[:current_month]].sum(axis=1)
    else:
        ly["LY_MgEur_YTD"] = ly.get("LY_MgEur", 0) * current_month / 12

    ly["LY_YTD_is_estimated"] = len(monthly_ly_rev_cols) == 0

    model = (
        brand_cfg
        .merge(grouped,              on="BrandKey", how="left")
        .merge(current_month_sales,  on="BrandKey", how="left")
        .merge(prev_month_sales,     on="BrandKey", how="left")
        .merge(stock,                on="BrandKey", how="left")
        .merge(ly,                   on="BrandKey", how="left")
    )

    for c in [
        "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Stock",
        "LY_Rev", "LY_MgEur", "LY_Mg_pct", "LY_Rev_YTD", "LY_MgEur_YTD",
        "LY_Rev_Remaining", "Revenue_Current_Month", "Margin_EUR_Current_Month",
        "Revenue_Prev_Month", "Margin_EUR_Prev_Month",
    ]:
        if c in model.columns:
            model[c] = pd.to_numeric(model[c], errors="coerce").fillna(0)

    model["Budget_YTD"]    = model[MONTH_BUDGET_COLS[:current_month]].sum(axis=1)
    model["Budget_Month"]  = model[MONTH_BUDGET_COLS[current_month - 1]]
    model["Annual Budget"] = pd.to_numeric(model["Annual Budget"], errors="coerce").fillna(0)
    model["Budget_vs_Actual"] = model["Revenue_YTD"] - model["Budget_YTD"]
    model["Stock_vs_Year_Budget"] = np.where(
        model["Annual Budget"] != 0, model["Stock"] / model["Annual Budget"], np.nan
    )

    revenue_ly_base  = model["LY_Rev_YTD"].replace(0, np.nan)
    margin_ly_base   = model["LY_MgEur_YTD"].replace(0, np.nan)
    budget_base      = model["Budget_YTD"].replace(0, np.nan)
    prev_rev_base    = model["Revenue_Prev_Month"].replace(0, np.nan)
    prev_margin_base = model["Margin_EUR_Prev_Month"].replace(0, np.nan)

    model["Growth_vs_LY_Revenue_PCT"]  = (model["Revenue_YTD"]       / revenue_ly_base)  - 1
    model["Growth_vs_LY_Margin_PCT"]   = (model["Margin_EUR_YTD"]    / margin_ly_base)   - 1
    ly_margin_rate = model["LY_MgEur_YTD"].replace(0, np.nan) / model["LY_Rev_YTD"].replace(0, np.nan)
    model["Margin_Rate_vs_LY"]         = model["Margin_PCT_YTD"] - ly_margin_rate
    model["Vs_Budget_PCT"]             = (model["Revenue_YTD"]        / budget_base)      - 1
    model["Last_Month_Trend_Revenue_PCT"] = (model["Revenue_Current_Month"] / prev_rev_base)   - 1
    model["Last_Month_Trend_Margin_PCT"]  = (model["Margin_EUR_Current_Month"] / prev_margin_base) - 1

    ly_full = model["LY_Rev"].replace(0, np.nan)
    ly_ytd_share = model["LY_Rev_YTD"] / ly_full
    model["Revenue_Projected"] = np.where(
        (ly_ytd_share > 0) & ly_ytd_share.notna(),
        model["Revenue_YTD"] / ly_ytd_share,
        model["Revenue_YTD"] / max(current_month, 1) * 12,
    )

    monthly_by_brand = monthly_sales[monthly_sales["Mes Factura"] <= current_month].copy()
    return model, monthly_by_brand


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

def fmt_eur(v):
    if pd.isna(v): return "–"
    if abs(v) >= 1_000_000: return f"€{v / 1_000_000:,.2f}M"
    return f"€{v:,.0f}"

def fmt_eur_delta(v):
    if pd.isna(v): return "–"
    sign = "+" if v > 0 else "-" if v < 0 else ""
    abs_v = abs(v)
    if abs(v) >= 1_000_000: return f"{sign}€{abs_v / 1_000_000:,.2f}M"
    return f"{sign}€{abs_v:,.0f}"

def fmt_pct(v):
    if pd.isna(v): return "–"
    return f"{v * 100:.1f}%"

def fmt_pct_pts(v):
    if pd.isna(v): return "–"
    sign = "+" if v > 0 else ""
    return f"{sign}{v * 100:.1f} pp"


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def detect_outliers(series: pd.Series, threshold: float = 2.5) -> tuple[pd.Series, float, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return pd.Series([False] * len(series), index=series.index), np.nan, np.nan
    if len(clean) < 30:
        q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            return pd.Series([False] * len(series), index=series.index), float(clean.mean()), 0.0
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (pd.to_numeric(series, errors="coerce") < lower) | (pd.to_numeric(series, errors="coerce") > upper)
        return mask, float(clean.mean()), float(iqr)
    mean, std = clean.mean(), clean.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series([False] * len(series), index=series.index), float(mean), float(std)
    z = (pd.to_numeric(series, errors="coerce") - mean).abs() / std
    return z > threshold, float(mean), float(std)


def build_monthly_overview(fam_series: pd.DataFrame, current_month: int) -> pd.DataFrame:
    monthly = fam_series.groupby(["Family", "Mes Factura"], as_index=False).agg(
        Revenue_Month=("Revenue_Month", "sum"),
        Margin_EUR_Month=("Margin_EUR_Month", "sum"),
    )
    monthly = monthly[monthly["Mes Factura"].between(1, current_month, inclusive="both")].copy()
    monthly = monthly.sort_values(["Family", "Mes Factura"])
    monthly["MoM_Revenue_PCT"] = monthly.groupby("Family")["Revenue_Month"].pct_change()
    monthly["MoM_Margin_PCT"]  = monthly.groupby("Family")["Margin_EUR_Month"].pct_change()
    monthly["Quarter"] = ((monthly["Mes Factura"] - 1) // 3) + 1
    monthly["Margin_Rate"] = np.where(
        monthly["Revenue_Month"] != 0, monthly["Margin_EUR_Month"] / monthly["Revenue_Month"], np.nan
    )
    monthly["COGS_Rate"] = 1 - monthly["Margin_Rate"].fillna(0)
    return monthly


def weighted_expected_margin_display(df: pd.DataFrame):
    expected = pd.to_numeric(df.get("Expected Margin %"), errors="coerce")
    weights  = pd.to_numeric(df.get("Annual Budget"), errors="coerce").fillna(0).clip(lower=0)
    valid    = expected.notna()
    expected_valid, weights_valid = expected[valid], weights[valid]
    total_weight = weights_valid.sum()
    if expected_valid.empty or total_weight <= 0:
        return "N/A"
    return fmt_pct(np.average(expected_valid, weights=weights_valid))


# ══════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════

def page_header(title: str, subtitle: str = ""):
    """Render the consistent page header."""
    sub_html = f'<span class="page-subtitle">{subtitle}</span>' if subtitle else ""
    st.markdown(f"""
    <div class="page-header">
        <h1 class="page-title">{title}</h1>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)


def section_label(text: str):
    st.markdown(f'<div class="section-label">{text}</div>', unsafe_allow_html=True)


def kpi_card(label: str, value: str, delta: str = "", delta_dir: str = "neu", help_text: str = ""):
    """Render a custom KPI card (used for hero metrics)."""
    delta_class = f"kpi-delta {delta_dir}"
    delta_icon = "▲" if delta_dir == "pos" else ("▼" if delta_dir == "neg" else "")
    delta_html = f'<div class="{delta_class}">{delta_icon} {delta}</div>' if delta else ""
    help_html  = f'<div class="kpi-help">{help_text}</div>' if help_text else ""
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
        {help_html}
    </div>
    """, unsafe_allow_html=True)


def filter_banner(selected_families: list, selected_brands: list):
    if selected_families or selected_brands:
        pills = "".join(
            [f'<span class="filter-pill">📂 {f}</span>' for f in selected_families] +
            [f'<span class="filter-pill">🏷 {b}</span>' for b in selected_brands]
        )
        st.markdown(f'<div class="filter-strip">{pills}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="filter-strip"><span class="filter-all">◎ Todos los verticales · todas las marcas</span></div>', unsafe_allow_html=True)


def apply_dashboard_filters(df: pd.DataFrame, section_name: str, default_family=None):
    st.sidebar.markdown('<div class="sidebar-section">Filtros</div>', unsafe_allow_html=True)

    families = sorted(df["Family"].dropna().astype(str).unique().tolist())
    selected_families = st.sidebar.multiselect(
        "Verticales", options=families, default=[],
        placeholder="Sin selección = todos",
        key=f"families_{section_name}",
    )

    if selected_families:
        filtered = df[df["Family"].isin(selected_families)].copy()
    elif default_family and default_family in families:
        filtered = df[df["Family"] == default_family].copy()
    else:
        filtered = df.copy()

    brand_options = sorted(filtered["Brand"].dropna().astype(str).unique().tolist())
    selected_brands = st.sidebar.multiselect(
        "Marcas", options=brand_options, default=[],
        placeholder="Sin selección = todas",
        key=f"brands_{section_name}",
    )
    if selected_brands:
        filtered = filtered[filtered["Brand"].isin(selected_brands)].copy()

    return filtered, selected_families, selected_brands


def apply_chart_style(fig, yformat: str = "€,.0f", percent_y: bool = False):
    """Apply consistent dark-mode chart styling."""
    fig.update_layout(**CHART_TEMPLATE)
    yaxis_cfg = dict(gridcolor="#1C2333", zeroline=False)
    if percent_y:
        yaxis_cfg["tickformat"] = ".1%"
    else:
        yaxis_cfg["tickprefix"] = "€"
        yaxis_cfg["tickformat"] = ",.0s"
    fig.update_layout(yaxis=yaxis_cfg)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# APP BOOT — Firebase + Sidebar
# ══════════════════════════════════════════════════════════════════════════════

require_app_password()

firebase_ok, firebase_msg, config_source = init_firebase()

with st.sidebar:
    # Wordmark
    st.markdown("""
    <div style="padding: 1rem 0 0.5rem; display:flex; align-items:center; gap:10px;">
        <span style="font-size:1.5rem;">🏍️</span>
        <div>
            <div style="font-size:1rem; font-weight:700; color:#F1F5F9; letter-spacing:-0.02em;">Sportech IB</div>
            <div style="font-size:0.7rem; color:#64748B; font-weight:500; letter-spacing:0.04em;">BRAND ANALYTICS</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Firebase status indicator
    if firebase_ok:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:6px;padding:8px 10px;background:#14532D22;border:1px solid #22c55e33;border-radius:8px;margin-bottom:0.5rem;">
            <span style="width:6px;height:6px;border-radius:50%;background:#22C55E;display:inline-block;box-shadow:0 0 6px #22C55E;"></span>
            <span style="font-size:0.75rem;color:#22C55E;font-weight:600;">Firebase conectado</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:6px;padding:8px 10px;background:#45151522;border:1px solid #ef444433;border-radius:8px;margin-bottom:0.5rem;">
            <span style="width:6px;height:6px;border-radius:50%;background:#EF4444;display:inline-block;"></span>
            <span style="font-size:0.75rem;color:#EF4444;font-weight:600;">Firebase error</span>
        </div>
        """, unsafe_allow_html=True)
        with st.expander("Ver detalles"):
            st.code(firebase_msg, language=None)
            st.markdown("""
            **Checklist:**
            - `project_id` ✓?
            - `private_key` ✓?
            - `client_email` ✓?
            - `databaseURL` ✓?
            """)

    st.markdown('<div class="sidebar-section">Sección</div>', unsafe_allow_html=True)
    MAIN_SECTIONS = [
        "📊  Resumen",
        "📈  Margen",
        "🚲  2 Wheels",
        "🎮  Free Time",
        "🏕️  Outdoor Tech",
    ]
    selected_main_section = st.radio("Ir a", MAIN_SECTIONS, key="section_selector", label_visibility="collapsed")

    st.markdown("---")
    with st.expander("⚙️", expanded=False):
        open_config = st.toggle("Pantalla de configuración", key="open_config_section")

        st.markdown('<div class="sidebar-section">Período</div>', unsafe_allow_html=True)
        selected_month = st.selectbox(
            "Mes actual",
            options=list(range(1, 13)),
            index=datetime.now().month - 1,
            format_func=lambda m: f"{MONTHS_ES[m]} ({m:02d})",
            key="month_selector",
        )

        st.markdown('<div class="sidebar-section">Datos de entrada</div>', unsafe_allow_html=True)
        with st.expander("📥 Subir archivos", expanded=False):
            up_sales  = st.file_uploader("Ventas mensuales", type=["xlsx"], key="sales",
                                         help="INPUT (Monthly) Sales")
            st.markdown('<div style="font-size:0.8rem;color:#64748B;margin-top:8px;">Stock por mes</div>',
                        unsafe_allow_html=True)
            stock_uploads = {}
            for month_idx in range(1, 13):
                stock_uploads[month_idx] = st.file_uploader(
                    MONTHS_ES[month_idx], type=["xlsx"], key=f"stock_{month_idx}"
                )
            up_margin = st.file_uploader("Margen año anterior", type=["xlsx"], key="margin",
                                         help="INPUT (Annual) MARGIN LY")

            if st.button("💾 Guardar en Firebase", disabled=not firebase_ok, use_container_width=True):
                with st.spinner("Guardando…"):
                    try:
                        if up_sales:
                            save_df_to_firebase(
                                "datasets/monthly_sales",
                                validate_dataset(read_sheet(up_sales, "INPUT (Monthly) Sales"), "sales", "Ventas"),
                            )
                        stock_frames = []
                        for month_idx, up_stock in stock_uploads.items():
                            if not up_stock:
                                continue
                            sm = validate_dataset(
                                read_sheet(up_stock, "INPUT (Monthly) Stock"), "stock", f"Stock · {MONTHS_ES[month_idx]}"
                            )
                            sm["Mes"] = month_idx
                            stock_frames.append(sm)
                        if stock_frames:
                            save_df_to_firebase("datasets/monthly_stock", pd.concat(stock_frames, ignore_index=True))
                        if up_margin:
                            save_df_to_firebase(
                                "datasets/annual_margin_ly",
                                validate_dataset(read_sheet(up_margin, "INPUT (Annual) MARGIN LY"), "margin_ly", "Margen LY"),
                            )
                        invalidate_firebase_cache()
                        st.success("✓ Datos guardados correctamente.")
                    except Exception as e:
                        st.error(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════

sales_df      = load_df_from_firebase("datasets/monthly_sales")     if firebase_ok else pd.DataFrame()
stock_df      = load_df_from_firebase("datasets/monthly_stock")     if firebase_ok else pd.DataFrame()
margin_ly_df  = load_df_from_firebase("datasets/annual_margin_ly")  if firebase_ok else pd.DataFrame()
saved_brand_cfg = load_df_from_firebase("datasets/brand_configuration") if firebase_ok else pd.DataFrame()

if sales_df.empty or stock_df.empty or margin_ly_df.empty:
    # Empty state
    page_header("Sportech IB", "Panel de análisis de marcas")
    st.markdown("""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-top:2rem;">
        <div style="background:#111827;border:1px dashed #2A3548;border-radius:12px;padding:1.5rem;text-align:center;">
            <div style="font-size:1.5rem;margin-bottom:8px;">📊</div>
            <div style="font-size:0.875rem;font-weight:600;color:#94A3B8;">Ventas mensuales</div>
            <div style="font-size:0.75rem;color:#64748B;margin-top:4px;">INPUT (Monthly) Sales</div>
        </div>
        <div style="background:#111827;border:1px dashed #2A3548;border-radius:12px;padding:1.5rem;text-align:center;">
            <div style="font-size:1.5rem;margin-bottom:8px;">📦</div>
            <div style="font-size:0.875rem;font-weight:600;color:#94A3B8;">Stock por mes</div>
            <div style="font-size:0.75rem;color:#64748B;margin-top:4px;">INPUT (Monthly) Stock</div>
        </div>
        <div style="background:#111827;border:1px dashed #2A3548;border-radius:12px;padding:1.5rem;text-align:center;">
            <div style="font-size:1.5rem;margin-bottom:8px;">📈</div>
            <div style="font-size:0.875rem;font-weight:600;color:#94A3B8;">Margen año anterior</div>
            <div style="font-size:0.75rem;color:#64748B;margin-top:4px;">INPUT (Annual) MARGIN LY</div>
        </div>
    </div>
    <div style="text-align:center;margin-top:2rem;color:#64748B;font-size:0.875rem;">
        Sube los 3 archivos en el panel lateral para comenzar.
    </div>
    """, unsafe_allow_html=True)
    st.stop()

try:
    sales_df     = validate_dataset(sales_df,    "sales",     "Ventas mensuales")
    stock_df     = validate_dataset(stock_df,    "stock",     "Stock mensual")
    margin_ly_df = validate_dataset(margin_ly_df,"margin_ly", "Margen LY")
except ValueError as e:
    st.error(str(e))
    st.stop()

# LY monthly warning
monthly_ly_cols_check = [f"LY_M{i:02d}_Rev" for i in range(1, 13)]
if not any(c in margin_ly_df.columns for c in monthly_ly_cols_check):
    st.sidebar.markdown("""
    <div class="alert alert-warn">
        ⚠ MARGIN LY sin columnas mensuales — YTD estimado linealmente.
    </div>
    """, unsafe_allow_html=True)

brand_master    = extract_brand_master(sales_df, stock_df, margin_ly_df)
brand_cfg       = build_brand_config(brand_master, saved_brand_cfg)

auto_spread_budget = brand_cfg.loc[
    brand_cfg.get("Budget_Source", pd.Series(dtype=str)).str.startswith("Auto", na=False), "Annual Budget"
].sum()
total_budget_check = brand_cfg["Annual Budget"].sum()
if total_budget_check > 0 and (auto_spread_budget / total_budget_check) > 0.2:
    pct_str = f"{auto_spread_budget / total_budget_check:.0%}"
    st.sidebar.markdown(f"""
    <div style="font-size:0.75rem;color:#F59E0B;padding:6px 10px;background:#431C0022;border:1px solid #f59e0b33;border-radius:6px;margin:4px 0;">
        ⚠ {pct_str} del presupuesto usa distribución uniforme automática.
    </div>
    """, unsafe_allow_html=True)

available_months = sorted(sales_df["Mes Factura"].dropna().astype(int).unique().tolist())
if not available_months:
    st.error("Dataset sin meses válidos (1–12). Revisa el archivo de ventas.")
    st.stop()

current_month = selected_month if selected_month in available_months else available_months[-1]
section = "⚙️  Configuración" if open_config else selected_main_section


# ══════════════════════════════════════════════════════════════════════════════
# BRAND CONFIG
# ══════════════════════════════════════════════════════════════════════════════

if "Configuración" in section:
    page_header("Configuración de marcas", "Master de marcas y presupuestos")

    # Auto-spread warning
    n_auto = int(brand_cfg.get("Budget_Source", pd.Series(dtype=str)).str.startswith("Auto", na=False).sum())
    if n_auto > 0:
        st.markdown(f"""
        <div class="alert alert-warn">
            ⚠ <strong>{n_auto} marcas</strong> usan distribución de presupuesto uniforme automática.
            Introduce presupuestos mensuales reales en la tabla para mejorar los KPIs vs. Budget.
        </div>
        """, unsafe_allow_html=True)

    # CSV upload
    section_label("Importar configuración")
    col_up, col_sample = st.columns([2, 1])
    with col_up:
        csv_up = st.file_uploader("Subir CSV de configuración de marcas", type=["csv"], key="cfg_csv")
        if csv_up is not None:
            try:
                incoming   = read_uploaded_csv(csv_up)
                valid_cfg  = validate_brand_config_df(incoming, set(brand_cfg["BrandKey"]))
                save_df_to_firebase("datasets/brand_configuration", valid_cfg)
                invalidate_firebase_cache()
                st.markdown('<div class="alert alert-success">✓ CSV validado y guardado correctamente.</div>',
                            unsafe_allow_html=True)
                st.rerun()
            except Exception as e:
                st.markdown(f'<div class="alert alert-error">✗ {e}</div>', unsafe_allow_html=True)

    with col_sample:
        with st.expander("📋 Formato requerido"):
            st.markdown("""
            **Obligatorias:** `Brand` · `Short Name` · `Status` · `Family` · `Annual Budget` · `Expected Margin %`

            **Opcionales:** `Budget Enero` … `Budget Diciembre`

            **Status:** NEW · STANDARD · PHASE OUT

            **Family:** 2 WHEELS · FREE TIME · OUTDOOR TECH · UNCLASSIFIED

            `Expected Margin %` → introduce como número (ej: 15 para 15%).
            Stock debe estar en **euros (€)**, no en unidades.
            """)
            sample_cols = ["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
            available_sample_cols = [c for c in sample_cols if c in brand_cfg.columns]
            st.dataframe(brand_cfg[available_sample_cols].head(3), use_container_width=True)

    # Inline editor
    section_label("Editar configuración")

    immutable_brand_map = brand_cfg.set_index("BrandKey")["Brand"].astype(str).to_dict()
    edit_cols = ["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
    available_edit_cols = [c for c in edit_cols if c in brand_cfg.columns]

    edited = st.data_editor(
        brand_cfg[available_edit_cols],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Brand":             st.column_config.TextColumn(disabled=True),
            "Status":            st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
            "Family":            st.column_config.SelectboxColumn(options=FAMILY_OPTIONS),
            "Expected Margin %": st.column_config.NumberColumn(
                help="Introduce como porcentaje (ej: 15 para 15%). El sistema convierte automáticamente."
            ),
        },
    )

    # Change preview
    diff_rows = []
    for col in ["Status", "Family", "Annual Budget", "Expected Margin %"]:
        if col not in brand_cfg.columns or col not in edited.columns:
            continue
        orig = brand_cfg[col].reset_index(drop=True)
        new  = edited[col].reset_index(drop=True)
        changed_mask = orig.astype(str) != new.astype(str)
        if changed_mask.any():
            for b in brand_cfg.loc[changed_mask, "Brand"].tolist():
                idx = brand_cfg[brand_cfg["Brand"] == b].index[0]
                diff_rows.append({"Marca": b, "Campo": col, "Antes": orig[idx], "Después": new.iloc[idx]})

    if diff_rows:
        with st.expander(f"👁 Vista previa · {len(diff_rows)} cambios pendientes", expanded=True):
            st.dataframe(pd.DataFrame(diff_rows), use_container_width=True)

    col_save, col_ts = st.columns([1, 2])
    with col_save:
        if st.button("💾 Guardar configuración", use_container_width=True):
            try:
                out = edited.copy()
                out["BrandKey"] = out["Brand"].apply(_normalize_brand)
                valid_cfg = validate_brand_config_df(out, set(brand_cfg["BrandKey"]), immutable_brand_map=immutable_brand_map)
                save_df_to_firebase("datasets/brand_configuration", valid_cfg)
                invalidate_firebase_cache()
                st.markdown('<div class="alert alert-success">✓ Configuración guardada.</div>', unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f'<div class="alert alert-error">✗ {e}</div>', unsafe_allow_html=True)

    with col_ts:
        if firebase_ok:
            raw_cfg = db.reference("datasets/brand_configuration").get()
            if isinstance(raw_cfg, dict) and "updated_at" in raw_cfg:
                st.markdown(f'<div style="padding-top:0.6rem;color:#64748B;font-size:0.75rem;">Última actualización: {raw_cfg["updated_at"]}</div>',
                            unsafe_allow_html=True)
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# BUILD MODEL (for all analytics sections)
# ══════════════════════════════════════════════════════════════════════════════

model, monthly_brand_series = prepare_model(sales_df, stock_df, margin_ly_df, brand_cfg, current_month)


# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════════════════════

if "Resumen" in section:
    filtered_model, sel_fam, sel_brands = apply_dashboard_filters(model, "resumen")
    page_header(f"Resumen · {MONTHS_ES[current_month]}", f"Portfolio consolidado · YTD")
    filter_banner(sel_fam, sel_brands)

    if filtered_model.empty:
        st.markdown('<div class="alert alert-warn">⚠ Sin datos para los filtros seleccionados.</div>',
                    unsafe_allow_html=True)
        st.stop()

    total_rev          = filtered_model["Revenue_YTD"].sum()
    total_mg           = filtered_model["Margin_EUR_YTD"].sum()
    total_budget       = filtered_model["Budget_YTD"].sum()
    total_stock        = filtered_model["Stock"].sum()
    total_rev_ly       = filtered_model["LY_Rev_YTD"].sum()
    total_mg_ly        = filtered_model["LY_MgEur_YTD"].sum()
    total_annual_budget= filtered_model["Annual Budget"].sum()

    # ── Tier 1: Hero KPIs ─────────────────────────────────────────────────────
    section_label("Indicadores clave")
    c1, c2, c3 = st.columns(3)
    with c1:
        delta = pct_delta(total_rev, total_rev_ly)
        dir_ = "pos" if not pd.isna(delta) and delta >= 0 else "neg"
        kpi_card("Revenue YTD", fmt_eur(total_rev),
                 delta=f"{fmt_pct(delta)} vs. año anterior", delta_dir=dir_)
    with c2:
        att   = safe_ratio(total_rev, total_budget)
        dir_ = "pos" if not pd.isna(att) and att >= 1 else "neg"
        kpi_card("Attainment vs. Budget", fmt_pct(att),
                 delta=fmt_eur_delta(total_rev - total_budget), delta_dir=dir_)
    with c3:
        mg_rate = safe_ratio(total_mg, total_rev)
        delta   = pct_delta(total_mg, total_mg_ly)
        dir_ = "pos" if not pd.isna(delta) and delta >= 0 else "neg"
        kpi_card("Tasa Margen Bruto %", fmt_pct(mg_rate),
                 delta=f"{fmt_pct(delta)} Margen € vs. LY", delta_dir=dir_)

    # ── Tier 2: Context ───────────────────────────────────────────────────────
    section_label("Contexto y proyección")
    e1, e2, e3, e4 = st.columns(4)
    with e1:
        st.metric("Margen € YTD", fmt_eur(total_mg))
    with e2:
        st.metric("Crecimiento YoY Revenue", fmt_pct(pct_delta(total_rev, total_rev_ly)))
    with e3:
        st.metric(
            "Proyección Revenue FY",
            fmt_eur(filtered_model["Revenue_Projected"].sum()),
            help="Ajustada por estacionalidad LY. Distribución lineal si no hay datos mensuales LY.",
        )
    with e4:
        st.metric(
            "Stock vs. Presupuesto Anual",
            fmt_pct(safe_ratio(total_stock, total_annual_budget)),
            help="Stock (€) / Presupuesto anual (€)",
        )

    # ── Charts ────────────────────────────────────────────────────────────────
    fam_agg = filtered_model.groupby("Family", as_index=False).agg(
        Revenue_YTD  =("Revenue_YTD", "sum"),
        Budget_YTD   =("Budget_YTD", "sum"),
        Margin_EUR_YTD=("Margin_EUR_YTD", "sum"),
        LY_Rev_YTD   =("LY_Rev_YTD", "sum"),
    )
    fam_agg["Attainment"] = fam_agg.apply(lambda r: safe_ratio(r["Revenue_YTD"], r["Budget_YTD"]), axis=1)
    fam_agg["Margen_Rate"] = fam_agg.apply(lambda r: safe_ratio(r["Margin_EUR_YTD"], r["Revenue_YTD"]), axis=1)

    section_label("Desglose por vertical")
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        bar_data = pd.melt(
            fam_agg, id_vars="Family", value_vars=["Revenue_YTD", "Budget_YTD"],
            var_name="Tipo", value_name="Importe"
        )
        bar_data["Tipo"] = bar_data["Tipo"].map({"Revenue_YTD": "Revenue YTD", "Budget_YTD": "Presupuesto YTD"})
        fig_bar = px.bar(
            bar_data, x="Family", y="Importe", color="Tipo", barmode="group",
            color_discrete_map={"Revenue YTD": "#3B82F6", "Presupuesto YTD": "#2A3548"},
            title="Revenue vs. Presupuesto por Vertical",
        )
        apply_chart_style(fig_bar)
        fig_bar.update_layout(xaxis_title="", yaxis_title="Revenue (€)")
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart2:
        fam_att = fam_agg.copy()
        fam_att["Color"] = fam_att["Attainment"].apply(lambda v: "#22C55E" if v >= 1 else "#EF4444")
        fig_att = go.Figure()
        fig_att.add_trace(go.Bar(
            x=fam_att["Family"], y=fam_att["Attainment"],
            marker_color=fam_att["Color"],
            text=[f"{v*100:.1f}%" for v in fam_att["Attainment"]],
            textposition="outside",
            textfont=dict(color="#94A3B8", size=11),
        ))
        fig_att.add_hline(y=1, line_dash="dash", line_color="#64748B", annotation_text="100%",
                          annotation_font_color="#64748B")
        apply_chart_style(fig_att, percent_y=True)
        fig_att.update_layout(title="Attainment vs. Budget", xaxis_title="", showlegend=False)
        st.plotly_chart(fig_att, use_container_width=True)

    # ── KPI table ─────────────────────────────────────────────────────────────
    section_label("KPIs por vertical")
    overview_fam = filtered_model.groupby("Family", as_index=False).agg(
        Revenue_YTD           =("Revenue_YTD", "sum"),
        Margin_EUR_YTD        =("Margin_EUR_YTD", "sum"),
        Budget_YTD            =("Budget_YTD", "sum"),
        LY_Rev_YTD            =("LY_Rev_YTD", "sum"),
        LY_MgEur_YTD          =("LY_MgEur_YTD", "sum"),
        Revenue_Current_Month =("Revenue_Current_Month", "sum"),
        Revenue_Prev_Month    =("Revenue_Prev_Month", "sum"),
        Margin_EUR_Current_Month=("Margin_EUR_Current_Month", "sum"),
        Margin_EUR_Prev_Month =("Margin_EUR_Prev_Month", "sum"),
        Stock                 =("Stock", "sum"),
        Annual_Budget         =("Annual Budget", "sum"),
    )
    overview_fam["Crecimiento Rev %"]    = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["LY_Rev_YTD"]), axis=1)
    overview_fam["Crecimiento Rev €"]    = overview_fam["Revenue_YTD"] - overview_fam["LY_Rev_YTD"]
    overview_fam["Crecimiento Margen %"] = overview_fam.apply(lambda r: pct_delta(r["Margin_EUR_YTD"], r["LY_MgEur_YTD"]), axis=1)
    overview_fam["Crecimiento Margen €"] = overview_fam["Margin_EUR_YTD"] - overview_fam["LY_MgEur_YTD"]
    ly_rate = overview_fam["LY_MgEur_YTD"] / overview_fam["LY_Rev_YTD"].replace(0, np.nan)
    cy_rate = overview_fam["Margin_EUR_YTD"] / overview_fam["Revenue_YTD"].replace(0, np.nan)
    overview_fam["Δ Tasa Margen (pp)"]   = cy_rate - ly_rate
    overview_fam["Vs Budget %"]          = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["Budget_YTD"]), axis=1)
    overview_fam["Vs Budget €"]          = overview_fam["Revenue_YTD"] - overview_fam["Budget_YTD"]
    overview_fam["Tendencia Rev %"]      = overview_fam.apply(lambda r: pct_delta(r["Revenue_Current_Month"], r["Revenue_Prev_Month"]), axis=1)
    overview_fam["Tendencia Margen %"]   = overview_fam.apply(lambda r: pct_delta(r["Margin_EUR_Current_Month"], r["Margin_EUR_Prev_Month"]), axis=1)
    overview_fam["Stock vs. Ppto Anual"] = overview_fam.apply(lambda r: safe_ratio(r["Stock"], r["Annual_Budget"]), axis=1)

    display_fam = overview_fam[[
        "Family", "Crecimiento Rev %", "Crecimiento Rev €", "Crecimiento Margen %", "Crecimiento Margen €",
        "Δ Tasa Margen (pp)", "Vs Budget %", "Vs Budget €",
        "Tendencia Rev %", "Tendencia Margen %", "Stock vs. Ppto Anual",
    ]].copy()

    st.dataframe(
        display_fam.style.format({
            "Crecimiento Rev %":    fmt_pct,
            "Crecimiento Rev €":    fmt_eur,
            "Crecimiento Margen %": fmt_pct,
            "Crecimiento Margen €": fmt_eur,
            "Δ Tasa Margen (pp)":   fmt_pct_pts,
            "Vs Budget %":          fmt_pct,
            "Vs Budget €":          fmt_eur,
            "Tendencia Rev %":      fmt_pct,
            "Tendencia Margen %":   fmt_pct,
            "Stock vs. Ppto Anual": fmt_pct,
        })
        .map(color_negative, subset=[
            "Crecimiento Rev %", "Crecimiento Margen %", "Vs Budget %",
            "Tendencia Rev %", "Tendencia Margen %", "Δ Tasa Margen (pp)",
        ])
        .map(color_negative, subset=["Crecimiento Rev €", "Crecimiento Margen €", "Vs Budget €"]),
        use_container_width=True,
    )

    # ── Brand lifecycle ────────────────────────────────────────────────────────
    section_label("Portfolio por estado de marca")
    status_agg = filtered_model.groupby("Status", as_index=False).agg(
        Revenue_YTD   =("Revenue_YTD", "sum"),
        Margin_EUR_YTD=("Margin_EUR_YTD", "sum"),
        Num_Marcas    =("Brand", "count"),
    )
    status_agg["Revenue %"] = status_agg["Revenue_YTD"] / status_agg["Revenue_YTD"].sum()
    status_agg["Margen %"]  = status_agg.apply(lambda r: safe_ratio(r["Margin_EUR_YTD"], r["Revenue_YTD"]), axis=1)

    scol1, scol2 = st.columns([3, 2])
    with scol1:
        status_colors = {"NEW": "#22C55E", "STANDARD": "#3B82F6", "PHASE OUT": "#64748B"}
        fig_status = px.bar(
            status_agg, x="Status", y="Revenue_YTD", color="Status",
            color_discrete_map=status_colors, text="Revenue %",
            title="Revenue YTD por Estado de Marca",
        )
        fig_status.update_traces(texttemplate="%{text:.1%}", textposition="outside",
                                  textfont=dict(color="#94A3B8"))
        apply_chart_style(fig_status)
        fig_status.update_layout(showlegend=False, xaxis_title="", yaxis_title="Revenue YTD (€)")
        st.plotly_chart(fig_status, use_container_width=True)
    with scol2:
        st.dataframe(
            status_agg.style.format({
                "Revenue_YTD":    fmt_eur,
                "Margin_EUR_YTD": fmt_eur,
                "Revenue %":      fmt_pct,
                "Margen %":       fmt_pct,
            }),
            use_container_width=True,
        )

    # ── Monthly trend ──────────────────────────────────────────────────────────
    section_label("Tendencias y alertas")
    fam_series  = monthly_brand_series.merge(filtered_model[["BrandKey", "Family"]], on="BrandKey", how="inner")
    fam_monthly = build_monthly_overview(fam_series, current_month)

    family_budgets = filtered_model.groupby("Family")[MONTH_BUDGET_COLS].sum()

    last_mom_rev = fam_monthly.sort_values("Mes Factura").groupby("Family")["MoM_Revenue_PCT"].last().dropna()
    last_mom_mg  = fam_monthly.sort_values("Mes Factura").groupby("Family")["MoM_Margin_PCT"].last().dropna()
    portfolio_mom_rev = last_mom_rev.mean() if not last_mom_rev.empty else 0
    portfolio_mom_mg  = last_mom_mg.mean()  if not last_mom_mg.empty  else 0

    outlier_mask, mean_revenue, std_revenue = detect_outliers(fam_monthly["Revenue_Month"])
    fam_monthly["Revenue_Outlier"] = outlier_mask

    tcol1, tcol2, tcol3 = st.columns(3)
    tcol1.metric(f"MoM Revenue · {MONTHS_ES[current_month]}", fmt_pct(portfolio_mom_rev),
                 help="Variación del último mes disponible vs. anterior.")
    tcol2.metric(f"MoM Margen · {MONTHS_ES[current_month]}", fmt_pct(portfolio_mom_mg),
                 help="Variación del último mes disponible vs. anterior.")
    tcol3.metric("Outliers detectados", int(fam_monthly["Revenue_Outlier"].sum()),
                 help="IQR (n<30) o z-score (n≥30, 2.5σ).")

    flow = px.line(
        fam_monthly, x="Mes Factura", y="Revenue_Month", color="Family", markers=True,
        color_discrete_map=FAMILY_COLORS,
        title="Tendencia mensual de ventas por vertical",
        line_shape="spline",
    )
    for fam in family_budgets.index:
        fam_budget_monthly = [
            family_budgets.loc[fam, MONTH_BUDGET_COLS[m - 1]] for m in range(1, current_month + 1)
        ]
        flow.add_trace(go.Scatter(
            x=list(range(1, current_month + 1)), y=fam_budget_monthly,
            mode="lines", name=f"Target · {fam}",
            line={"dash": "dot", "color": FAMILY_COLORS.get(fam, "#64748B"), "width": 1},
            opacity=0.4, showlegend=True,
        ))
    apply_chart_style(flow)
    flow.update_layout(
        xaxis=dict(tickvals=list(range(1, 13)), ticktext=list(MONTHS_ES.values()), gridcolor="#1C2333"),
        yaxis_title="Revenue (€)",
    )
    flow.update_traces(selector=dict(mode="lines+markers"), line=dict(width=2.5))
    st.plotly_chart(flow, use_container_width=True)

    anomaly_view = fam_monthly[fam_monthly["Revenue_Outlier"]][
        ["Family", "Mes Factura", "Revenue_Month", "MoM_Revenue_PCT"]
    ]
    if not anomaly_view.empty:
        st.markdown(f"""
        <div class="alert alert-warn">
            ⚠ {len(anomaly_view)} outlier(s) detectados
            (media={fmt_eur(mean_revenue)}, dispersión={fmt_eur(std_revenue)}).
        </div>
        """, unsafe_allow_html=True)
        st.dataframe(
            anomaly_view.style.format({"Revenue_Month": fmt_eur, "MoM_Revenue_PCT": fmt_pct}),
            use_container_width=True,
        )

    # ── Quarterly segmentation ─────────────────────────────────────────────────
    section_label("Segmentación trimestral")
    segment = fam_monthly.groupby(["Family", "Quarter"], as_index=False).agg(
        Revenue=("Revenue_Month", "sum"), Margin=("Margin_EUR_Month", "sum"),
    )
    segment["Tasa Margen %"] = np.where(segment["Revenue"] != 0, segment["Margin"] / segment["Revenue"], np.nan)
    segment["COGS Rate %"]   = 1 - segment["Tasa Margen %"].fillna(0)
    segment["Quarter"]       = segment["Quarter"].apply(lambda q: f"Q{int(q)}")

    st.dataframe(
        segment.style.format({
            "Revenue": fmt_eur, "Margin": fmt_eur, "Tasa Margen %": fmt_pct, "COGS Rate %": fmt_pct,
        })
        .apply(style_gradient_fallback, subset=["Tasa Margen %"], low_color="#7F1D1D", high_color="#14532D")
        .apply(style_gradient_fallback, subset=["Revenue"], low_color="#1E3A5F", high_color="#1D4ED8"),
        use_container_width=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MARGEN
# ══════════════════════════════════════════════════════════════════════════════

elif "Margen" in section:
    filtered_model, sel_fam, sel_brands = apply_dashboard_filters(model, "margen")
    page_header(f"Análisis de Margen · {MONTHS_ES[current_month]}", "Rentabilidad por marca y vertical")
    filter_banner(sel_fam, sel_brands)

    if filtered_model.empty:
        st.markdown('<div class="alert alert-warn">⚠ Sin datos para los filtros seleccionados.</div>',
                    unsafe_allow_html=True)
        st.stop()

    total_rev_mg     = filtered_model["Revenue_YTD"].sum()
    total_mg_val     = filtered_model["Margin_EUR_YTD"].sum()
    total_mg_ly_val  = filtered_model["LY_MgEur_YTD"].sum()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    section_label("Indicadores de rentabilidad")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Margen € YTD", fmt_eur(total_mg_val))
    m2.metric("Tasa Margen % YTD", fmt_pct(safe_ratio(total_mg_val, total_rev_mg)))
    m3.metric("Margen Esperado % (ponderado)", weighted_expected_margin_display(filtered_model),
              help="Media ponderada por presupuesto anual de cada marca.")
    m4.metric("Desviación vs. LY (€)", fmt_eur(total_mg_val - total_mg_ly_val),
              delta=fmt_pct(pct_delta(total_mg_val, total_mg_ly_val)) + " vs. LY")

    # Margin rate variance (pp)
    mcol1, mcol2 = st.columns(2)
    ly_rate_mg = safe_ratio(total_mg_ly_val, filtered_model["LY_Rev_YTD"].sum())
    cy_rate_mg = safe_ratio(total_mg_val, total_rev_mg)
    with mcol1:
        st.metric("Δ Tasa Margen vs. LY", fmt_pct_pts(cy_rate_mg - ly_rate_mg),
                  help="pp de diferencia en tasa de margen. Positivo = mejora de mix/precio, no solo volumen.")

    # ── Brand detail table ─────────────────────────────────────────────────────
    section_label("Detalle por marca")
    table = filtered_model[[
        "Brand", "Short Name", "Status", "Family",
        "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD",
        "Expected Margin %", "Margin_Rate_vs_LY",
        "Stock", "LY_Rev_YTD", "LY_MgEur_YTD",
    ]].copy()
    table["Expected Margin %"] = table["Expected Margin %"].apply(fmt_pct)
    st.dataframe(
        table.style.format({
            "Revenue_YTD":    fmt_eur,
            "Margin_EUR_YTD": fmt_eur,
            "Margin_PCT_YTD": fmt_pct,
            "Margin_Rate_vs_LY": fmt_pct_pts,
            "Stock":          fmt_eur,
            "LY_Rev_YTD":     fmt_eur,
            "LY_MgEur_YTD":   fmt_eur,
        })
        .map(color_negative, subset=["Margin_Rate_vs_LY"]),
        use_container_width=True,
    )

    # ── Strategic quadrant scatter ─────────────────────────────────────────────
    section_label("Cuadrante estratégico")
    avg_rev    = filtered_model["Revenue_YTD"].mean()
    avg_mg_pct = filtered_model["Margin_PCT_YTD"].mean()

    mg_scatter = px.scatter(
        filtered_model,
        x="Revenue_YTD", y="Margin_PCT_YTD",
        size="Annual Budget", color="Family",
        color_discrete_map=FAMILY_COLORS,
        hover_name="Short Name",
        hover_data={"Status": True, "Budget_YTD": ":,.0f", "Growth_vs_LY_Revenue_PCT": ":.1%"},
        title="Revenue vs. Tasa de Margen % · tamaño = Presupuesto Anual",
        size_max=60,
    )
    mg_scatter.add_vline(x=avg_rev, line_dash="dash", line_color="#64748B",
                          annotation_text="Avg Rev", annotation_font_color="#64748B")
    mg_scatter.add_hline(y=avg_mg_pct, line_dash="dash", line_color="#64748B",
                          annotation_text="Avg Margen %", annotation_font_color="#64748B")
    apply_chart_style(mg_scatter, percent_y=True)
    mg_scatter.update_layout(
        xaxis_title="Revenue YTD (€)",
        yaxis=dict(tickformat=".1%", title="Tasa Margen %", gridcolor="#1C2333"),
    )
    st.plotly_chart(mg_scatter, use_container_width=True)
    st.markdown("""
    <div style="font-size:0.78rem;color:#64748B;padding:8px 0;">
        <strong style="color:#94A3B8;">Cuadrantes:</strong>
        Arriba-derecha = Estrellas (alto rev + alto margen) ·
        Arriba-izquierda = Nicho (bajo rev + alto margen) ·
        Abajo-derecha = Volumen (alto rev + bajo margen) ·
        Abajo-izquierda = Revisión (bajo rev + bajo margen)
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# VERTICALS (2 Wheels / Free Time / Outdoor Tech)
# ══════════════════════════════════════════════════════════════════════════════

else:
    # Map nav label → Family value
    vertical_map = {
        "2 Wheels":    "2 WHEELS",
        "Free Time":   "FREE TIME",
        "Outdoor Tech":"OUTDOOR TECH",
    }
    vertical = next((v for k, v in vertical_map.items() if k.upper() in section.upper()), None)
    if vertical is None:
        st.stop()

    sub, sel_fam, sel_brands = apply_dashboard_filters(model, f"vertical_{vertical}", default_family=vertical)
    page_header(f"{vertical} · {MONTHS_ES[current_month]}", "Análisis de vertical")
    filter_banner(sel_fam, sel_brands)

    if sub.empty:
        n_configured = model[model["Family"] == vertical].shape[0]
        if n_configured == 0:
            st.markdown(f"""
            <div class="alert alert-warn">
                ⚠ No hay marcas configuradas para <strong>{vertical}</strong>.
                Ve a <strong>Configuración</strong> y asigna marcas a esta familia.
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="alert alert-warn">⚠ Sin datos de ventas para los filtros seleccionados.</div>',
                        unsafe_allow_html=True)
        st.stop()

    agg = {
        "revenue":          sub["Revenue_YTD"].sum(),
        "margin":           sub["Margin_EUR_YTD"].sum(),
        "ly_rev":           sub["LY_Rev_YTD"].sum(),
        "ly_margin":        sub["LY_MgEur_YTD"].sum(),
        "budget":           sub["Budget_YTD"].sum(),
        "cur_month_rev":    sub["Revenue_Current_Month"].sum(),
        "prev_month_rev":   sub["Revenue_Prev_Month"].sum(),
        "cur_month_margin": sub["Margin_EUR_Current_Month"].sum(),
        "prev_month_margin":sub["Margin_EUR_Prev_Month"].sum(),
        "stock":            sub["Stock"].sum(),
        "annual_budget":    sub["Annual Budget"].sum(),
    }

    # ── Tier 1: Hero KPIs ─────────────────────────────────────────────────────
    section_label("Indicadores clave")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        delta = pct_delta(agg["revenue"], agg["ly_rev"])
        dir_  = "pos" if not pd.isna(delta) and delta >= 0 else "neg"
        kpi_card("Crecimiento Revenue", fmt_pct(delta),
                 delta=fmt_eur_delta(agg["revenue"] - agg["ly_rev"]), delta_dir=dir_)
    with k2:
        delta = pct_delta(agg["margin"], agg["ly_margin"])
        dir_  = "pos" if not pd.isna(delta) and delta >= 0 else "neg"
        kpi_card("Crecimiento Margen", fmt_pct(delta),
                 delta=fmt_eur_delta(agg["margin"] - agg["ly_margin"]), delta_dir=dir_)
    with k3:
        att  = pct_delta(agg["revenue"], agg["budget"])
        dir_ = "pos" if not pd.isna(att) and att >= 0 else "neg"
        kpi_card("Attainment vs. Budget", fmt_pct(att),
                 delta=fmt_eur_delta(agg["revenue"] - agg["budget"]), delta_dir=dir_)
    with k4:
        stock_ratio = safe_ratio(agg["stock"], agg["annual_budget"])
        kpi_card("Stock vs. Ppto Anual", fmt_pct(stock_ratio),
                 help_text="Stock (€) / Presupuesto anual (€)")

    # ── Tier 2: Trend ─────────────────────────────────────────────────────────
    section_label("Tendencia del mes")
    t1, t2, t3 = st.columns(3)
    t1.metric(f"Revenue MoM · {MONTHS_ES[current_month]}",
              fmt_pct(pct_delta(agg["cur_month_rev"], agg["prev_month_rev"])))
    t2.metric(f"Margen MoM · {MONTHS_ES[current_month]}",
              fmt_pct(pct_delta(agg["cur_month_margin"], agg["prev_month_margin"])))
    t3.metric("Tasa de Margen Bruto % YTD",
              fmt_pct(safe_ratio(agg["margin"], agg["revenue"])),
              help="Margen € / Revenue €. Rentabilidad bruta del vertical.")

    # ── Brand detail table ─────────────────────────────────────────────────────
    section_label("Detalle por marca")
    brand_view = sub[[
        "Short Name", "Status", "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD",
        "LY_Rev_YTD", "LY_MgEur_YTD", "Budget_YTD",
        "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Margin_Rate_vs_LY",
        "Vs_Budget_PCT", "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT",
        "Stock_vs_Year_Budget",
    ]].copy().sort_values("Revenue_YTD", ascending=False)

    st.dataframe(
        brand_view.style.format({
            "Revenue_YTD":                  fmt_eur,
            "Margin_EUR_YTD":               fmt_eur,
            "Margin_PCT_YTD":               fmt_pct,
            "LY_Rev_YTD":                   fmt_eur,
            "LY_MgEur_YTD":                 fmt_eur,
            "Budget_YTD":                   fmt_eur,
            "Growth_vs_LY_Revenue_PCT":     fmt_pct,
            "Growth_vs_LY_Margin_PCT":      fmt_pct,
            "Margin_Rate_vs_LY":            fmt_pct_pts,
            "Vs_Budget_PCT":                fmt_pct,
            "Last_Month_Trend_Revenue_PCT": fmt_pct,
            "Last_Month_Trend_Margin_PCT":  fmt_pct,
            "Stock_vs_Year_Budget":         fmt_pct,
        })
        .map(color_negative, subset=[
            "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Margin_Rate_vs_LY",
            "Vs_Budget_PCT", "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT",
        ]),
        use_container_width=True,
    )

    # ── Monthly trend ──────────────────────────────────────────────────────────
    section_label("Tendencia mensual por marca")
    monthly_vertical = monthly_brand_series.merge(
        sub[["BrandKey", "Short Name"]], on="BrandKey", how="inner"
    )
    n_brands    = monthly_vertical["Short Name"].nunique()
    chart_title = f"Tendencia mensual · {vertical}"

    if n_brands > 6:
        st.markdown(f"""
        <div class="alert alert-info">
            ℹ {n_brands} marcas activas. Modo foco: top 5 por Revenue YTD + resto agrupado como "Otras".
        </div>
        """, unsafe_allow_html=True)
        top5 = sub.nlargest(5, "Revenue_YTD")["Short Name"].tolist()
        monthly_vertical["Marca Display"] = monthly_vertical["Short Name"].apply(
            lambda x: x if x in top5 else "Otras"
        )
        monthly_agg = monthly_vertical.groupby(
            ["Marca Display", "Mes Factura"], as_index=False
        ).agg(Revenue_Month=("Revenue_Month", "sum"))
        fig = px.line(
            monthly_agg, x="Mes Factura", y="Revenue_Month",
            color="Marca Display", markers=True, title=chart_title, line_shape="spline",
        )
    else:
        fig = px.line(
            monthly_vertical, x="Mes Factura", y="Revenue_Month",
            color="Short Name", markers=True, title=chart_title, line_shape="spline",
        )

    apply_chart_style(fig)
    fig.update_layout(
        xaxis=dict(tickvals=list(range(1, 13)), ticktext=list(MONTHS_ES.values()), gridcolor="#1C2333"),
        yaxis_title="Revenue (€)",
    )
    fig.update_traces(line=dict(width=2.5))
    st.plotly_chart(fig, use_container_width=True)
