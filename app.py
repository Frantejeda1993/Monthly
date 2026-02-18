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

st.set_page_config(page_title="Sportech IB · Dashboard", page_icon="🏍️", layout="wide")

st.markdown(
    """
    <style>
    .stSidebar .stRadio > div {gap: 0.35rem;}
    .stSidebar .stRadio label p {font-weight: 700; font-size: 0.95rem;}
    .kpi-card {background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 0.65rem;}
    .filter-tag {
        display: inline-block; background: #dbeafe; color: #1e40af;
        border-radius: 4px; padding: 2px 8px; font-size: 0.78rem; margin: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Constants ──────────────────────────────────────────────────────────────────
MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
STATUS_OPTIONS = ["NEW", "STANDARD", "PHASE OUT"]
FAMILY_OPTIONS = ["2 WHEELS", "FREE TIME", "OUTDOOR TECH", "UNCLASSIFIED"]
MONTH_BUDGET_COLS = [f"Budget {MONTHS_ES[i]}" for i in range(1, 13)]

# Consistent colour palette per family — used in all charts
FAMILY_COLORS = {
    "2 WHEELS":    "#2563EB",
    "FREE TIME":   "#16A34A",
    "OUTDOOR TECH":"#D97706",
    "UNCLASSIFIED":"#9CA3AF",
}


# ── Pure helper functions ──────────────────────────────────────────────────────
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
        return "color: #6b7280"
    return "color: #dc2626; font-weight: 700" if value < 0 else "color: #15803d; font-weight: 700"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return 255, 255, 255
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)


def _interpolate_hex(start: str, end: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    start_rgb = _hex_to_rgb(start)
    end_rgb = _hex_to_rgb(end)
    mixed = tuple(int(round(s + (e - s) * ratio)) for s, e in zip(start_rgb, end_rgb))
    return _rgb_to_hex(mixed)


def _contrast_text_color(bg_hex: str) -> str:
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#111827" if luminance > 0.6 else "#f9fafb"


def style_gradient_fallback(series: pd.Series, low_color: str, high_color: str) -> pd.Series:
    valid = series.dropna()
    if valid.empty:
        return pd.Series([""] * len(series), index=series.index)

    min_val = valid.min()
    max_val = valid.max()
    span = max_val - min_val

    styles = []
    for value in series:
        if pd.isna(value):
            styles.append("")
            continue
        ratio = 0.5 if span == 0 else (value - min_val) / span
        bg_color = _interpolate_hex(low_color, high_color, ratio)
        fg_color = _contrast_text_color(bg_color)
        styles.append(f"background-color: {bg_color}; color: {fg_color};")
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
    """Return a single Series even when duplicate column names are present."""
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
    if len(tokens) == 1:
        return tokens[0][:12]
    return " ".join(tokens[:2])[:18]


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


# ── Firebase helpers ───────────────────────────────────────────────────────────
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
        sa = {
            k: merged.get(k)
            for k in [
                "type", "project_id", "private_key_id", "private_key", "client_email",
                "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url",
            ]
            if merged.get(k) is not None
        }
    if isinstance(sa, dict) and isinstance(sa.get("private_key"), str):
        sa["private_key"] = sa["private_key"].replace("\\n", "\n")

    # Log resolved config path for debuggability
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
    """Atomic write to Firebase with size guard."""
    import sys, json
    payload = {
        "columns": [str(c) for c in df.columns],
        "rows": df.replace({np.nan: None}).values.tolist(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    size_bytes = sys.getsizeof(json.dumps(payload))
    if size_bytes > 8_000_000:
        raise ValueError(
            f"El dataset es demasiado grande para Firebase RTDB ({size_bytes / 1e6:.1f} MB > 8 MB). "
            "Reduce el número de filas o contacta al administrador."
        )
    db.reference(path).set(payload)


# FIX P1: cache Firebase reads to avoid 4 reads per user interaction
@st.cache_data(ttl=300, show_spinner=False)
def load_df_from_firebase(path: str) -> pd.DataFrame:
    raw = db.reference(path).get()
    if not raw:
        return pd.DataFrame()

    def _coerce_rows_and_columns(rows, columns):
        if isinstance(rows, dict):
            try:
                rows = [rows[k] for k in sorted(rows, key=lambda x: int(x) if str(x).isdigit() else str(x))]
            except Exception:
                rows = list(rows.values())
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            rows = [rows]
        if columns is None:
            columns = []
        if not isinstance(columns, list):
            columns = list(columns) if hasattr(columns, "__iter__") and not isinstance(columns, str) else [columns]
        return rows, [str(c) for c in columns]

    if isinstance(raw, dict) and "columns" in raw and "rows" in raw:
        rows, columns = _coerce_rows_and_columns(raw.get("rows"), raw.get("columns"))
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
    """Clear the data cache so next load fetches fresh data from Firebase."""
    load_df_from_firebase.clear()


# ── File reading ───────────────────────────────────────────────────────────────
def read_sheet(uploaded_file, sheet_name):
    bio = BytesIO(uploaded_file.read())
    uploaded_file.seek(0)
    xls = pd.ExcelFile(bio)
    return pd.read_excel(bio, sheet_name=sheet_name if sheet_name in xls.sheet_names else 0)


def read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    """Read CSV files with automatic delimiter detection."""
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
        raise ValueError(
            "No se pudo leer el CSV. Verifica delimitador y formato del archivo. "
            f"Detalle original: {first_error}"
        ) from first_error


# ── Dataset validation ─────────────────────────────────────────────────────────
def validate_dataset(df: pd.DataFrame, dataset_key: str, dataset_name: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError(f"{dataset_name} está vacío.")
    dfx = df.copy()
    dfx.columns = [str(c).strip() for c in dfx.columns]

    if dataset_key == "sales":
        rename = {}
        brand_col = _first_existing(dfx, ["Clave 1", "Nombre Cliente", "Marca", "Nombre"])
        if brand_col:
            rename[brand_col] = "Nombre"
        net_col = _first_existing(dfx, ["Importe Neto", "Importe"])
        if net_col:
            rename[net_col] = "Importe Neto"
        margin_col = _first_existing(dfx, ["CR3: % Margen s/Venta", "Margen %", "Margin %"])
        if margin_col:
            rename[margin_col] = "CR3: % Margen s/Venta"
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
                raise ValueError(
                    f"{dataset_name}: hay fechas inválidas en '{date_col}' que no se pueden interpretar."
                )
            dfx["Mes Factura"] = parsed.dt.month
        else:
            dfx["Mes Factura"] = pd.to_numeric(dfx[month_col], errors="coerce")
            invalid_months = dfx[month_col].notna() & dfx["Mes Factura"].isna()
            if invalid_months.any():
                raise ValueError(
                    f"{dataset_name}: hay valores inválidos en '{month_col}' que no se pueden convertir a mes."
                )
        dfx = dfx[dfx["Mes Factura"].between(1, 12, inclusive="both")]
        importe_num = pd.to_numeric(dfx["Importe Neto"], errors="coerce")
        invalid_importe = dfx["Importe Neto"].notna() & importe_num.isna()
        if invalid_importe.any():
            raise ValueError(f"{dataset_name}: hay importes netos inválidos que no se pueden convertir a número.")
        dfx["Importe Neto"] = importe_num.fillna(0)
        if "Margen_Euros" not in dfx.columns:
            mg_pct_col = _first_existing(dfx, ["CR3: % Margen s/Venta", "Margen %", "Margin %"])
            if mg_pct_col:
                dfx["Margen_Euros"] = dfx["Importe Neto"] * pd.to_numeric(dfx[mg_pct_col], errors="coerce").fillna(0) / 100
            else:
                dfx["Margen_Euros"] = 0
        dfx["Margen_Euros"] = pd.to_numeric(dfx["Margen_Euros"], errors="coerce").fillna(0)

    elif dataset_key == "stock":
        rename = {}
        brand_col = _first_existing(dfx, ["Clave 1", "Marca"])
        if brand_col:
            rename[brand_col] = "Marca"
        code_col = _first_existing(dfx, ["Código Artículo", "Codigo Articulo", "Código", "Codigo"])
        if code_col:
            rename[code_col] = "Codigo Articulo"
        amount_col = _first_existing(dfx, ["Importe", "Stock"])
        if amount_col:
            rename[amount_col] = "Importe"
        dfx = dfx.rename(columns=rename)

        required = ["Marca", "Codigo Articulo", "Importe"]
        missing = [c for c in required if c not in dfx.columns]
        if missing:
            raise ValueError(f"{dataset_name}: faltan columnas {missing}.")

        dfx["Codigo Articulo"] = dfx["Codigo Articulo"].astype(str).str.strip()
        has_code = dfx["Codigo Articulo"].replace({"": np.nan, "nan": np.nan, "None": np.nan}).notna()
        dfx = dfx[has_code].copy()
        # Stock 'Importe' is expected in euros (€). Units would produce meaningless KPIs.
        dfx["Stock"] = pd.to_numeric(dfx["Importe"], errors="coerce").fillna(0)

    elif dataset_key == "margin_ly":
        rename = {}
        month_name_to_number = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        }
        brand_col = _first_existing(dfx, ["Clave 1 Stock", "Clave 1", "Marca"])
        if brand_col:
            rename[brand_col] = "Marca"
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
            raise ValueError(f"{dataset_name}: falta columna de marca (Clave 1 Stock).")

        monthly_rev_cols = [f"LY_M{i:02d}_Rev" for i in range(1, 13) if f"LY_M{i:02d}_Rev" in dfx.columns]
        monthly_mg_eur_cols = [f"LY_M{i:02d}_MgEur" for i in range(1, 13) if f"LY_M{i:02d}_MgEur" in dfx.columns]
        monthly_mg_pct_cols = [f"LY_M{i:02d}_MgPct" for i in range(1, 13) if f"LY_M{i:02d}_MgPct" in dfx.columns]

        for c in [*monthly_rev_cols, *monthly_mg_eur_cols, *monthly_mg_pct_cols]:
            dfx[c] = pd.to_numeric(dfx[c], errors="coerce").fillna(0)

        for c in ["LY_Rev", "LY_MgEur", "LY_Mg%"]:
            if c in dfx.columns:
                dfx[c] = pd.to_numeric(dfx[c], errors="coerce").fillna(0)

        if "LY_Rev" not in dfx.columns:
            dfx["LY_Rev"] = dfx[monthly_rev_cols].sum(axis=1) if monthly_rev_cols else 0
        if "LY_MgEur" not in dfx.columns:
            dfx["LY_MgEur"] = dfx[monthly_mg_eur_cols].sum(axis=1) if monthly_mg_eur_cols else 0
        # FIX: LY_Mg% derived from summed numerator/denominator — never average percentages
        if "LY_Mg%" not in dfx.columns:
            if monthly_mg_pct_cols and not monthly_mg_eur_cols:
                # Only percentage columns available — simple average is the best we can do
                dfx["LY_Mg%"] = dfx[monthly_mg_pct_cols].mean(axis=1)
            else:
                dfx["LY_Mg%"] = np.where(dfx["LY_Rev"] != 0, dfx["LY_MgEur"] / dfx["LY_Rev"] * 100, 0)

        dfx["LY_Rev"] = pd.to_numeric(dfx["LY_Rev"], errors="coerce").fillna(0)
        dfx["LY_MgEur"] = pd.to_numeric(dfx["LY_MgEur"], errors="coerce").fillna(0)
        dfx["LY_Mg%"] = pd.to_numeric(dfx["LY_Mg%"], errors="coerce").fillna(0)

    return dfx


# ── Brand config helpers ───────────────────────────────────────────────────────
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

    master = pd.DataFrame(
        sorted(({"Brand": brand, "BrandKey": key} for key, brand in brand_map.items()), key=lambda x: x["BrandKey"])
    )
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
    if bad_status:
        raise ValueError(f"CSV inválido: Status no permitido {bad_status}")
    if bad_family:
        raise ValueError(f"CSV inválido: Family no permitida {bad_family}")

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
        raise ValueError(f"CSV inválido: hay marcas no reconocidas ({len(extra_brands)})")

    return cfg


def validate_brand_config_df(
    df_cfg: pd.DataFrame,
    expected_brand_keys: set[str],
    immutable_brand_map: dict[str, str] | None = None,
):
    cfg = validate_brand_config_csv(df_cfg, expected_brand_keys)

    if immutable_brand_map is not None:
        cfg_brand_map = cfg.set_index("BrandKey")["Brand"].astype(str).to_dict()
        changed = [
            key for key, original_brand in immutable_brand_map.items()
            if key in cfg_brand_map and cfg_brand_map[key] != original_brand
        ]
        if changed:
            raise ValueError(
                "Campos de identidad inmutables modificados: 'Brand' no se puede editar manualmente."
            )

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
        keep_cols = ["Brand", "BrandKey", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
        cfg = cfg[[c for c in keep_cols if c in cfg.columns]]

    for c in ["Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]:
        cfg[c] = pd.to_numeric(cfg[c], errors="coerce")

    monthly_sum = cfg[MONTH_BUDGET_COLS].fillna(0).sum(axis=1)
    cfg["Annual Budget"] = np.where(cfg["Annual Budget"].fillna(0) > 0, cfg["Annual Budget"], monthly_sum)
    needs_spread = monthly_sum == 0
    # Track whether budgets were auto-spread so we can warn the user
    if "Budget_Source" not in cfg.columns:
        cfg["Budget_Source"] = "Manual"
    cfg["Budget_Source"] = np.where(needs_spread, "Auto-spread (uniform)", "Manual")
    for col in MONTH_BUDGET_COLS:
        cfg[col] = np.where(needs_spread, cfg["Annual Budget"].fillna(0) / 12, cfg[col].fillna(0))

    # FIX: enforce a single convention — always store Expected Margin % as a decimal (0.15 = 15%)
    # Users enter as percentage (e.g. 15), so always divide by 100.
    em = cfg["Expected Margin %"].fillna(0)
    cfg["Expected Margin %"] = np.where(em > 1, em / 100, em)

    cfg["Status"] = cfg["Status"].where(cfg["Status"].isin(STATUS_OPTIONS), "STANDARD")
    cfg["Family"] = cfg["Family"].where(cfg["Family"].isin(FAMILY_OPTIONS), "UNCLASSIFIED")
    return cfg


# ── Core model preparation ─────────────────────────────────────────────────────
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

    # FIX (seasonality-aware projection): use LY monthly distribution when available.
    # Applied later after LY merge; store raw YTD for now.
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

    # ── Stock: FIX P0 — use only current_month snapshot, not sum of all months ──
    stock = df_stock.copy()
    stock["BrandKey"] = _get_series(stock, "Marca").apply(_normalize_brand)
    if "Mes" in stock.columns:
        stock_current = stock[stock["Mes"] == current_month]
        if stock_current.empty:
            # Fallback to latest available month if current month not uploaded yet
            latest_mes = stock["Mes"].max()
            stock_current = stock[stock["Mes"] == latest_mes]
        stock = stock_current.groupby("BrandKey", as_index=False)["Stock"].sum()
    else:
        # No month column — treat as a single point-in-time snapshot
        stock = stock.groupby("BrandKey", as_index=False)["Stock"].sum()

    # ── Last Year data ──────────────────────────────────────────────────────────
    ly = df_margin_ly.copy()
    ly["BrandKey"] = _get_series(ly, "Marca").apply(_normalize_brand)
    monthly_ly_rev_cols = [f"LY_M{i:02d}_Rev" for i in range(1, 13) if f"LY_M{i:02d}_Rev" in ly.columns]
    monthly_ly_mg_eur_cols = [f"LY_M{i:02d}_MgEur" for i in range(1, 13) if f"LY_M{i:02d}_MgEur" in ly.columns]

    # FIX P0: revenue-weighted aggregation — never simple-mean percentages across brands
    ly_agg = {}
    if "LY_Rev" in ly.columns:
        ly_agg["LY_Rev"] = "sum"
    if "LY_MgEur" in ly.columns:
        ly_agg["LY_MgEur"] = "sum"
    ly_agg.update({c: "sum" for c in monthly_ly_rev_cols})
    ly_agg.update({c: "sum" for c in monthly_ly_mg_eur_cols})
    ly = ly.groupby("BrandKey", as_index=False).agg(ly_agg)
    # Derive LY_Mg_pct from summed numerator/denominator — not averaged percentages
    if "LY_Rev" in ly.columns and "LY_MgEur" in ly.columns:
        ly["LY_Mg_pct"] = np.where(ly["LY_Rev"] != 0, ly["LY_MgEur"] / ly["LY_Rev"], 0)
    else:
        ly["LY_Mg_pct"] = 0

    # January edge case: use LY December for previous month comparison
    if current_month == 1 and {"LY_M12_Rev", "LY_M12_MgEur"}.issubset(ly.columns):
        prev_month_sales = ly[["BrandKey", "LY_M12_Rev", "LY_M12_MgEur"]].rename(
            columns={"LY_M12_Rev": "Revenue_Prev_Month", "LY_M12_MgEur": "Margin_EUR_Prev_Month"}
        )
    elif current_month == 1 and not {"LY_M12_Rev", "LY_M12_MgEur"}.issubset(ly.columns):
        # Warn: January edge-case data missing
        st.sidebar.warning(
            "⚠ Mes = Enero: no se encontraron columnas LY_M12_Rev / LY_M12_MgEur para calcular "
            "la tendencia del mes anterior. 'Tendencia Último Mes' puede aparecer como 0."
        )

    if monthly_ly_rev_cols:
        ly["LY_Rev"] = ly[monthly_ly_rev_cols].sum(axis=1)
        ly["LY_Rev_YTD"] = ly[monthly_ly_rev_cols[:current_month]].sum(axis=1)
        ly["LY_Rev_Remaining"] = ly[monthly_ly_rev_cols[current_month:]].sum(axis=1)
    else:
        ly["LY_Rev_YTD"] = ly.get("LY_Rev", 0) * current_month / 12
        ly["LY_Rev_Remaining"] = ly.get("LY_Rev", 0) * (12 - current_month) / 12

    if monthly_ly_mg_eur_cols:
        ly["LY_MgEur"] = ly[monthly_ly_mg_eur_cols].sum(axis=1)
        ly["LY_MgEur_YTD"] = ly[monthly_ly_mg_eur_cols[:current_month]].sum(axis=1)
    else:
        ly["LY_MgEur_YTD"] = ly.get("LY_MgEur", 0) * current_month / 12

    # Warn if LY YTD fallback (linear) is being used
    ly["LY_YTD_is_estimated"] = len(monthly_ly_rev_cols) == 0

    model = (
        brand_cfg
        .merge(grouped, on="BrandKey", how="left")
        .merge(current_month_sales, on="BrandKey", how="left")
        .merge(prev_month_sales, on="BrandKey", how="left")
        .merge(stock, on="BrandKey", how="left")
        .merge(ly, on="BrandKey", how="left")
    )
    for c in [
        "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Stock",
        "LY_Rev", "LY_MgEur", "LY_Mg_pct", "LY_Rev_YTD", "LY_MgEur_YTD",
        "LY_Rev_Remaining", "Revenue_Current_Month", "Margin_EUR_Current_Month",
        "Revenue_Prev_Month", "Margin_EUR_Prev_Month",
    ]:
        if c in model.columns:
            model[c] = pd.to_numeric(model[c], errors="coerce").fillna(0)

    model["Budget_YTD"] = model[MONTH_BUDGET_COLS[:current_month]].sum(axis=1)
    model["Budget_Month"] = model[MONTH_BUDGET_COLS[current_month - 1]]
    model["Annual Budget"] = pd.to_numeric(model["Annual Budget"], errors="coerce").fillna(0)
    model["Budget_vs_Actual"] = model["Revenue_YTD"] - model["Budget_YTD"]
    # Stock coverage — both numerator and denominator in euros
    model["Stock_vs_Year_Budget"] = np.where(
        model["Annual Budget"] != 0, model["Stock"] / model["Annual Budget"], np.nan
    )

    revenue_ly_base = model["LY_Rev_YTD"].replace(0, np.nan)
    margin_ly_base = model["LY_MgEur_YTD"].replace(0, np.nan)
    budget_base = model["Budget_YTD"].replace(0, np.nan)
    prev_rev_base = model["Revenue_Prev_Month"].replace(0, np.nan)
    prev_margin_base = model["Margin_EUR_Prev_Month"].replace(0, np.nan)

    model["Growth_vs_LY_Revenue_PCT"] = (model["Revenue_YTD"] / revenue_ly_base) - 1
    model["Growth_vs_LY_Margin_PCT"] = (model["Margin_EUR_YTD"] / margin_ly_base) - 1
    # Margin Rate variance vs LY (rate change, not € change)
    ly_margin_rate = model["LY_MgEur_YTD"].replace(0, np.nan) / model["LY_Rev_YTD"].replace(0, np.nan)
    model["Margin_Rate_vs_LY"] = model["Margin_PCT_YTD"] - ly_margin_rate
    model["Vs_Budget_PCT"] = (model["Revenue_YTD"] / budget_base) - 1
    model["Last_Month_Trend_Revenue_PCT"] = (model["Revenue_Current_Month"] / prev_rev_base) - 1
    model["Last_Month_Trend_Margin_PCT"] = (model["Margin_EUR_Current_Month"] / prev_margin_base) - 1

    # FIX: seasonality-aware FY projection using LY distribution
    ly_full = model["LY_Rev"].replace(0, np.nan)
    ly_ytd_share = model["LY_Rev_YTD"] / ly_full  # fraction of LY revenue that fell in YTD period
    # Where we have LY monthly data: project = YTD / LY_YTD_share
    # Where we don't: fall back to linear
    model["Revenue_Projected"] = np.where(
        (ly_ytd_share > 0) & ly_ytd_share.notna(),
        model["Revenue_YTD"] / ly_ytd_share,
        model["Revenue_YTD"] / max(current_month, 1) * 12,
    )

    monthly_by_brand = monthly_sales[monthly_sales["Mes Factura"] <= current_month].copy()
    return model, monthly_by_brand


# ── Formatting helpers ─────────────────────────────────────────────────────────
def fmt_eur(v):
    if pd.isna(v):
        return "–"
    if abs(v) >= 1_000_000:
        return f"€{v / 1_000_000:,.2f}M"
    return f"€{v:,.0f}"


def fmt_eur_delta(v):
    """Format KPI delta in € with sign first so Streamlit detects direction/colour."""
    if pd.isna(v):
        return "–"
    sign = "+" if v > 0 else "-" if v < 0 else ""
    abs_v = abs(v)
    if abs(v) >= 1_000_000:
        return f"{sign}€{abs_v / 1_000_000:,.2f}M"
    return f"{sign}€{abs_v:,.0f}"


def fmt_pct(v):
    if pd.isna(v):
        return "–"
    return f"{v * 100:.1f}%"


def fmt_pct_pts(v):
    """Format a percentage-point difference (e.g. margin rate change)."""
    if pd.isna(v):
        return "–"
    sign = "+" if v > 0 else ""
    return f"{sign}{v * 100:.1f} pp"


# ── Analytics helpers ──────────────────────────────────────────────────────────
def detect_outliers(series: pd.Series, threshold: float = 2.5) -> tuple[pd.Series, float, float]:
    """IQR-based for n < 30, z-score otherwise."""
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

    mean = clean.mean()
    std = clean.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series([False] * len(series), index=series.index), float(mean), float(std)
    z_score = (pd.to_numeric(series, errors="coerce") - mean).abs() / std
    return z_score > threshold, float(mean), float(std)


def build_monthly_overview(fam_series: pd.DataFrame, current_month: int) -> pd.DataFrame:
    monthly = fam_series.groupby(["Family", "Mes Factura"], as_index=False).agg(
        Revenue_Month=("Revenue_Month", "sum"),
        Margin_EUR_Month=("Margin_EUR_Month", "sum"),
    )
    monthly = monthly[monthly["Mes Factura"].between(1, current_month, inclusive="both")].copy()
    monthly = monthly.sort_values(["Family", "Mes Factura"])
    monthly["MoM_Revenue_PCT"] = monthly.groupby("Family")["Revenue_Month"].pct_change()
    monthly["MoM_Margin_PCT"] = monthly.groupby("Family")["Margin_EUR_Month"].pct_change()
    monthly["Quarter"] = ((monthly["Mes Factura"] - 1) // 3) + 1
    # FIX: Margin Rate computed correctly from summed €, not averaged percentages
    monthly["Margin_Rate"] = np.where(
        monthly["Revenue_Month"] != 0,
        monthly["Margin_EUR_Month"] / monthly["Revenue_Month"],
        np.nan,
    )
    # COGS Rate = 1 − Margin Rate (replaces the mislabeled Cost_per_Unit)
    monthly["COGS_Rate"] = 1 - monthly["Margin_Rate"].fillna(0)
    return monthly


def weighted_expected_margin_display(df: pd.DataFrame):
    expected = pd.to_numeric(df.get("Expected Margin %"), errors="coerce")
    weights = pd.to_numeric(df.get("Annual Budget"), errors="coerce").fillna(0).clip(lower=0)
    valid = expected.notna()
    expected_valid = expected[valid]
    weights_valid = weights[valid]
    total_weight = weights_valid.sum()
    if expected_valid.empty or total_weight <= 0:
        return "N/A"
    return fmt_pct(np.average(expected_valid, weights=weights_valid))


def apply_dashboard_filters(
    df: pd.DataFrame, section_name: str, default_family: str | None = None
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Apply family + brand filters; return (filtered_df, selected_families, selected_brands)."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"#### Filtros · {section_name}")

    families = sorted(df["Family"].dropna().astype(str).unique().tolist())
    selected_families = st.sidebar.multiselect(
        "Familias",
        options=families,
        default=[],
        placeholder="Sin selección = todas",
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
        "Marcas",
        options=brand_options,
        default=[],
        placeholder="Sin selección = todas",
        key=f"brands_{section_name}",
    )
    if selected_brands:
        filtered = filtered[filtered["Brand"].isin(selected_brands)].copy()

    return filtered, selected_families, selected_brands


def _active_filter_banner(selected_families: list, selected_brands: list):
    """Render a compact inline filter status strip below the page title."""
    tags = []
    for f in selected_families:
        tags.append(f'<span class="filter-tag">📂 {f}</span>')
    for b in selected_brands:
        tags.append(f'<span class="filter-tag">🏷 {b}</span>')
    if tags:
        st.markdown("**Filtros activos:** " + " ".join(tags), unsafe_allow_html=True)
    else:
        st.caption("Mostrando todas las familias y marcas.")


def _apply_chart_style(fig, yformat: str = "€,.0f"):
    """Apply consistent styling to all Plotly figures."""
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        font_family="Inter, Arial, sans-serif",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=60, b=40, l=40, r=20),
        yaxis=dict(tickprefix="€", tickformat=",.0s", gridcolor="#F3F4F6"),
        xaxis=dict(gridcolor="#F3F4F6"),
    )
    return fig


# ── App boot ───────────────────────────────────────────────────────────────────
firebase_ok, firebase_msg, config_source = init_firebase()

with st.sidebar:
    st.markdown("### 🏍️ Sportech IB")
    st.caption("Nueva arquitectura: 3 inputs + configuración dinámica de marcas")
    if firebase_ok:
        st.success(firebase_msg)
        st.caption(f"Config source: `{config_source}`")
    else:
        st.error(firebase_msg)
        st.info(
            "**Checklist de configuración:**\n"
            "- `project_id` ✓?\n- `private_key` ✓?\n- `client_email` ✓?\n- `databaseURL` ✓?"
        )

    with st.expander("📥 INPUTS", expanded=False):
        up_sales = st.file_uploader("INPUT (Monthly) Sales", type=["xlsx"], key="sales")
        st.markdown("#### INPUT (Monthly) Stock por mes")
        st.caption(
            "Sube solo el mes actual o los meses necesarios. "
            "El dashboard usa únicamente el snapshot del mes seleccionado. "
            "Stock debe estar en **euros (€)**, no en unidades."
        )
        stock_uploads = {}
        for month_idx in range(1, 13):
            stock_uploads[month_idx] = st.file_uploader(
                f"Stock · {MONTHS_ES[month_idx]}",
                type=["xlsx"],
                key=f"stock_{month_idx}",
            )
        up_margin = st.file_uploader("INPUT (Annual) MARGIN LY", type=["xlsx"], key="margin")

    if st.button("Guardar INPUTS en Firebase", disabled=not firebase_ok, use_container_width=True):
        try:
            if up_sales:
                save_df_to_firebase(
                    "datasets/monthly_sales",
                    validate_dataset(read_sheet(up_sales, "INPUT (Monthly) Sales"), "sales", "INPUT (Monthly) Sales"),
                )
            stock_frames = []
            for month_idx, up_stock in stock_uploads.items():
                if not up_stock:
                    continue
                stock_month = validate_dataset(
                    read_sheet(up_stock, "INPUT (Monthly) Stock"),
                    "stock",
                    f"INPUT (Monthly) Stock · {MONTHS_ES[month_idx]}",
                )
                stock_month["Mes"] = month_idx
                stock_frames.append(stock_month)
            if stock_frames:
                save_df_to_firebase("datasets/monthly_stock", pd.concat(stock_frames, ignore_index=True))
            if up_margin:
                save_df_to_firebase(
                    "datasets/annual_margin_ly",
                    validate_dataset(read_sheet(up_margin, "INPUT (Annual) MARGIN LY"), "margin_ly", "INPUT (Annual) MARGIN LY"),
                )
            invalidate_firebase_cache()
            st.success("INPUTS guardados — caché refrescada.")
        except Exception as e:
            st.error(str(e))

# ── Load data ──────────────────────────────────────────────────────────────────
sales_df = load_df_from_firebase("datasets/monthly_sales") if firebase_ok else pd.DataFrame()
stock_df = load_df_from_firebase("datasets/monthly_stock") if firebase_ok else pd.DataFrame()
margin_ly_df = load_df_from_firebase("datasets/annual_margin_ly") if firebase_ok else pd.DataFrame()
saved_brand_cfg = load_df_from_firebase("datasets/brand_configuration") if firebase_ok else pd.DataFrame()

if sales_df.empty or stock_df.empty or margin_ly_df.empty:
    st.title("Sportech IB Dashboard")
    st.info("Carga los 3 INPUTS requeridos para comenzar: Sales, Stock y MARGIN LY.")
    st.stop()

# Validate loaded data (schema check only — no double-validate on already-clean data)
try:
    sales_df = validate_dataset(sales_df, "sales", "INPUT (Monthly) Sales")
    stock_df = validate_dataset(stock_df, "stock", "INPUT (Monthly) Stock")
    margin_ly_df = validate_dataset(margin_ly_df, "margin_ly", "INPUT (Annual) MARGIN LY")
except ValueError as e:
    st.error(str(e))
    st.stop()

# ── Warn if LY YTD fallback is active ─────────────────────────────────────────
monthly_ly_rev_cols_check = [f"LY_M{i:02d}_Rev" for i in range(1, 13)]
ly_has_monthly = any(c in margin_ly_df.columns for c in monthly_ly_rev_cols_check)
if not ly_has_monthly:
    st.sidebar.warning(
        "⚠ MARGIN LY no contiene columnas mensuales (e.g. Enero - Revenue). "
        "El YTD del año anterior se estima con distribución lineal, lo que puede sesgar las comparativas en negocios estacionales."
    )

# ── Warn if auto-spread budgets exceed threshold ───────────────────────────────
brand_master = extract_brand_master(sales_df, stock_df, margin_ly_df)
brand_cfg = build_brand_config(brand_master, saved_brand_cfg)
auto_spread_budget = brand_cfg.loc[brand_cfg.get("Budget_Source", pd.Series(dtype=str)).str.startswith("Auto", na=False), "Annual Budget"].sum()
total_budget_check = brand_cfg["Annual Budget"].sum()
if total_budget_check > 0 and (auto_spread_budget / total_budget_check) > 0.2:
    st.sidebar.warning(
        f"⚠ {auto_spread_budget / total_budget_check:.0%} del presupuesto usa distribución uniforme automática. "
        "Considera introducir presupuestos mensuales reales en Brand Config."
    )

st.sidebar.markdown("---")
available_months = sorted(sales_df["Mes Factura"].dropna().astype(int).unique().tolist())
if not available_months:
    st.warning(
        "El dataset de ventas no tiene meses válidos (1-12) después de la validación. "
        "Revisa y vuelve a subir el archivo con valores correctos en `Mes Factura` o `Fecha`."
    )
    st.stop()
current_month = st.sidebar.selectbox(
    "Mes actual", options=available_months, index=len(available_months) - 1
)
section = st.sidebar.radio(
    "Sección",
    ["Brand Config", "Resumen", "Margen", "Vertical · 2 WHEELS", "Vertical · FREE TIME", "Vertical · OUTDOOR TECH"],
    key="section_selector",
)

# ── Brand Config section ───────────────────────────────────────────────────────
if section == "Brand Config":
    st.title("⚙️ Brand Master & Financial Configuration")
    st.write("Lista única de marcas generada automáticamente a partir de los 3 INPUTS.")

    # Budget auto-spread warning
    n_auto = int(brand_cfg.get("Budget_Source", pd.Series(dtype=str)).str.startswith("Auto", na=False).sum())
    if n_auto > 0:
        st.warning(
            f"**{n_auto} marcas** usan presupuesto distribuido uniformemente (sin presupuesto mensual manual). "
            "Introduce presupuestos mensuales reales para mejorar la fiabilidad de los KPIs vs. Budget."
        )

    with st.expander("CSV upload: estructura requerida", expanded=True):
        st.markdown(
            "- **Columnas obligatorias**: `Brand`, `Short Name`, `Status`, `Family`, `Annual Budget`, `Expected Margin %`.\n"
            "- **Columnas opcionales**: `Budget Enero` ... `Budget Diciembre`.\n"
            "- **Status válidos**: NEW, STANDARD, PHASE OUT.\n"
            "- **Family válidas**: 2 WHEELS, FREE TIME, OUTDOOR TECH, UNCLASSIFIED.\n"
            "- **`Expected Margin %`**: introducir como porcentaje (ej: `15` para 15%). El sistema siempre almacena en decimal.\n"
            "- **`Stock`** en el dataset de stock debe estar en **euros (€)**, no en unidades.\n"
            "- **Validaciones**: marcas duplicadas, marcas faltantes, marcas extra no existentes, tipos numéricos inválidos.\n"
            "- **Errores**: se muestran con detalle y no se persiste el CSV hasta corregir."
        )
        sample_cols = ["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
        available_sample_cols = [c for c in sample_cols if c in brand_cfg.columns]
        st.dataframe(brand_cfg[available_sample_cols].head(3), use_container_width=True)

    csv_up = st.file_uploader("Upload brand configuration CSV", type=["csv"], key="cfg_csv")
    if csv_up is not None:
        try:
            incoming = read_uploaded_csv(csv_up)
            valid_cfg = validate_brand_config_df(incoming, set(brand_cfg["BrandKey"]))
            save_df_to_firebase("datasets/brand_configuration", valid_cfg)
            invalidate_firebase_cache()
            st.success("CSV validado y guardado.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    immutable_brand_map = brand_cfg.set_index("BrandKey")["Brand"].astype(str).to_dict()

    edit_cols = ["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]
    available_edit_cols = [c for c in edit_cols if c in brand_cfg.columns]
    edited = st.data_editor(
        brand_cfg[available_edit_cols],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Brand": st.column_config.TextColumn(disabled=True),
            "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
            "Family": st.column_config.SelectboxColumn(options=FAMILY_OPTIONS),
            "Expected Margin %": st.column_config.NumberColumn(
                help="Introduce como porcentaje (ej: 15 para 15%). El sistema convierte automáticamente."
            ),
        },
    )

    # Preview changes before saving
    diff_rows = []
    for col in ["Status", "Family", "Annual Budget", "Expected Margin %"]:
        if col not in brand_cfg.columns or col not in edited.columns:
            continue
        orig = brand_cfg[col].reset_index(drop=True)
        new = edited[col].reset_index(drop=True)
        changed_mask = orig.astype(str) != new.astype(str)
        if changed_mask.any():
            brands_changed = brand_cfg.loc[changed_mask, "Brand"].tolist()
            for b in brands_changed:
                idx = brand_cfg[brand_cfg["Brand"] == b].index[0]
                diff_rows.append({"Marca": b, "Campo": col, "Antes": orig[idx], "Después": new.iloc[idx]})

    if diff_rows:
        with st.expander(f"👁 Vista previa de cambios ({len(diff_rows)} modificaciones)", expanded=True):
            st.dataframe(pd.DataFrame(diff_rows), use_container_width=True)

    if st.button("Guardar configuración", use_container_width=True):
        try:
            out = edited.copy()
            out["BrandKey"] = out["Brand"].apply(_normalize_brand)
            valid_cfg = validate_brand_config_df(
                out, set(brand_cfg["BrandKey"]), immutable_brand_map=immutable_brand_map
            )
            save_df_to_firebase("datasets/brand_configuration", valid_cfg)
            invalidate_firebase_cache()
            st.success("Configuración guardada")
        except Exception as e:
            st.error(str(e))

    # Show last update timestamp
    raw_cfg = db.reference("datasets/brand_configuration").get() if firebase_ok else {}
    if isinstance(raw_cfg, dict) and "updated_at" in raw_cfg:
        st.caption(f"Última actualización: {raw_cfg['updated_at']}")

    st.stop()

# ── Build model ────────────────────────────────────────────────────────────────
model, monthly_brand_series = prepare_model(sales_df, stock_df, margin_ly_df, brand_cfg, current_month)

# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN (formerly "Overview")
# ══════════════════════════════════════════════════════════════════════════════
if section == "Resumen":
    filtered_model, sel_fam, sel_brands = apply_dashboard_filters(model, "resumen")
    st.title(f"📊 Resumen · {MONTHS_ES[current_month]}")
    _active_filter_banner(sel_fam, sel_brands)

    if filtered_model.empty:
        n_brands_in_fam = model[model["Family"].isin(sel_fam)].shape[0] if sel_fam else 0
        if sel_fam and n_brands_in_fam == 0:
            st.warning("No hay marcas configuradas en las familias seleccionadas. Ve a **Brand Config** para asignar marcas.")
        else:
            st.warning("No hay datos de ventas para los filtros seleccionados en este período.")
        st.stop()

    total_rev = filtered_model["Revenue_YTD"].sum()
    total_mg = filtered_model["Margin_EUR_YTD"].sum()
    total_budget = filtered_model["Budget_YTD"].sum()
    total_stock = filtered_model["Stock"].sum()
    total_rev_ly = filtered_model["LY_Rev_YTD"].sum()
    total_mg_ly = filtered_model["LY_MgEur_YTD"].sum()
    total_annual_budget = filtered_model["Annual Budget"].sum()

    # ── Tier 1: Decision-critical KPIs ────────────────────────────────────────
    st.markdown("#### Indicadores clave")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Revenue YTD",
        fmt_eur(total_rev),
        delta=fmt_pct(pct_delta(total_rev, total_rev_ly)) + " vs. LY",
    )
    c2.metric(
        "Attainment vs. Budget",
        fmt_pct(total_rev / total_budget if total_budget else 0),
        delta=fmt_eur_delta(total_rev - total_budget),
    )
    c3.metric(
        "Margen Bruto % YTD",
        fmt_pct(total_mg / total_rev if total_rev else 0),
        delta=fmt_pct(pct_delta(total_mg, total_mg_ly)) + " vs. LY €",
    )

    # ── Tier 2: Supporting context ─────────────────────────────────────────────
    st.markdown("#### Contexto")
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Margen € YTD", fmt_eur(total_mg))
    e2.metric("Crecimiento YoY Revenue", fmt_pct(pct_delta(total_rev, total_rev_ly)))
    e3.metric(
        "Proyección Revenue FY",
        fmt_eur(filtered_model["Revenue_Projected"].sum()),
        help="Proyección ajustada por estacionalidad LY. Si no hay datos mensuales LY, usa distribución lineal.",
    )
    e4.metric(
        "Stock (€) vs. Presupuesto Anual",
        fmt_pct(safe_ratio(total_stock, total_annual_budget)),
        help="Stock en euros / Presupuesto anual en euros. Ambas magnitudes deben estar en €.",
    )

    # ── Portfolio chart: Revenue vs Budget per family ─────────────────────────
    st.markdown("---")
    fam_agg = filtered_model.groupby("Family", as_index=False).agg(
        Revenue_YTD=("Revenue_YTD", "sum"),
        Budget_YTD=("Budget_YTD", "sum"),
        Margin_EUR_YTD=("Margin_EUR_YTD", "sum"),
        LY_Rev_YTD=("LY_Rev_YTD", "sum"),
    )
    fam_agg["Attainment"] = fam_agg.apply(lambda r: safe_ratio(r["Revenue_YTD"], r["Budget_YTD"]), axis=1)
    fam_agg["Margen_Rate"] = fam_agg.apply(lambda r: safe_ratio(r["Margin_EUR_YTD"], r["Revenue_YTD"]), axis=1)

    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.subheader("Revenue vs. Presupuesto por Familia")
        bar_data = pd.melt(
            fam_agg, id_vars="Family", value_vars=["Revenue_YTD", "Budget_YTD"],
            var_name="Tipo", value_name="Importe"
        )
        bar_data["Tipo"] = bar_data["Tipo"].map({"Revenue_YTD": "Revenue YTD", "Budget_YTD": "Presupuesto YTD"})
        fig_bar = px.bar(
            bar_data, x="Family", y="Importe", color="Tipo", barmode="group",
            color_discrete_map={"Revenue YTD": "#2563EB", "Presupuesto YTD": "#D1D5DB"},
            text_auto=False,
        )
        _apply_chart_style(fig_bar)
        fig_bar.update_layout(xaxis_title="", yaxis_title="Revenue (€)")
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart2:
        st.subheader("Attainment vs. Budget por Familia")
        fam_att = fam_agg.copy()
        fam_att["Color"] = fam_att["Attainment"].apply(lambda v: "#15803D" if v >= 1 else "#DC2626")
        fig_att = go.Figure()
        fig_att.add_trace(go.Bar(
            x=fam_att["Family"], y=fam_att["Attainment"],
            marker_color=fam_att["Color"],
            text=[f"{v*100:.1f}%" for v in fam_att["Attainment"]],
            textposition="outside",
        ))
        fig_att.add_hline(y=1, line_dash="dash", line_color="#6B7280", annotation_text="100%")
        _apply_chart_style(fig_att)
        fig_att.update_layout(
            xaxis_title="", yaxis_title="Attainment",
            yaxis=dict(tickformat=".0%", gridcolor="#F3F4F6"),
        )
        st.plotly_chart(fig_att, use_container_width=True)

    # ── KPI table by family ────────────────────────────────────────────────────
    overview_fam = filtered_model.groupby("Family", as_index=False).agg(
        Revenue_YTD=("Revenue_YTD", "sum"),
        Margin_EUR_YTD=("Margin_EUR_YTD", "sum"),
        Budget_YTD=("Budget_YTD", "sum"),
        LY_Rev_YTD=("LY_Rev_YTD", "sum"),
        LY_MgEur_YTD=("LY_MgEur_YTD", "sum"),
        Revenue_Current_Month=("Revenue_Current_Month", "sum"),
        Revenue_Prev_Month=("Revenue_Prev_Month", "sum"),
        Margin_EUR_Current_Month=("Margin_EUR_Current_Month", "sum"),
        Margin_EUR_Prev_Month=("Margin_EUR_Prev_Month", "sum"),
        Stock=("Stock", "sum"),
        Annual_Budget=("Annual Budget", "sum"),
    )
    overview_fam["Crecimiento Rev %"] = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["LY_Rev_YTD"]), axis=1)
    overview_fam["Crecimiento Rev €"] = overview_fam["Revenue_YTD"] - overview_fam["LY_Rev_YTD"]
    overview_fam["Crecimiento Margen %"] = overview_fam.apply(lambda r: pct_delta(r["Margin_EUR_YTD"], r["LY_MgEur_YTD"]), axis=1)
    overview_fam["Crecimiento Margen €"] = overview_fam["Margin_EUR_YTD"] - overview_fam["LY_MgEur_YTD"]
    # Margin rate variance (percentage points, not %)
    ly_rate = overview_fam["LY_MgEur_YTD"] / overview_fam["LY_Rev_YTD"].replace(0, np.nan)
    cy_rate = overview_fam["Margin_EUR_YTD"] / overview_fam["Revenue_YTD"].replace(0, np.nan)
    overview_fam["Δ Tasa Margen (pp)"] = cy_rate - ly_rate
    overview_fam["Vs Budget %"] = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["Budget_YTD"]), axis=1)
    overview_fam["Vs Budget €"] = overview_fam["Revenue_YTD"] - overview_fam["Budget_YTD"]
    overview_fam["Tendencia Mes Rev %"] = overview_fam.apply(
        lambda r: pct_delta(r["Revenue_Current_Month"], r["Revenue_Prev_Month"]), axis=1
    )
    overview_fam["Tendencia Mes Margen %"] = overview_fam.apply(
        lambda r: pct_delta(r["Margin_EUR_Current_Month"], r["Margin_EUR_Prev_Month"]), axis=1
    )
    overview_fam["Stock (€) vs. Presupuesto Anual"] = overview_fam.apply(
        lambda r: safe_ratio(r["Stock"], r["Annual_Budget"]), axis=1
    )

    display_fam = overview_fam[[
        "Family", "Crecimiento Rev %", "Crecimiento Rev €", "Crecimiento Margen %", "Crecimiento Margen €",
        "Δ Tasa Margen (pp)", "Vs Budget %", "Vs Budget €", "Tendencia Mes Rev %",
        "Tendencia Mes Margen %", "Stock (€) vs. Presupuesto Anual",
    ]].copy()

    st.subheader("KPIs por Familia")
    st.dataframe(
        display_fam.style.format({
            "Crecimiento Rev %": fmt_pct,
            "Crecimiento Rev €": fmt_eur,
            "Crecimiento Margen %": fmt_pct,
            "Crecimiento Margen €": fmt_eur,
            "Δ Tasa Margen (pp)": fmt_pct_pts,
            "Vs Budget %": fmt_pct,
            "Vs Budget €": fmt_eur,
            "Tendencia Mes Rev %": fmt_pct,
            "Tendencia Mes Margen %": fmt_pct,
            "Stock (€) vs. Presupuesto Anual": fmt_pct,
        })
        .map(color_negative, subset=["Crecimiento Rev %", "Crecimiento Margen %", "Vs Budget %", "Tendencia Mes Rev %", "Tendencia Mes Margen %", "Δ Tasa Margen (pp)"])
        .map(color_negative, subset=["Crecimiento Rev €", "Crecimiento Margen €", "Vs Budget €"]),
        use_container_width=True,
    )

    # ── Brand lifecycle KPIs (NEW / PHASE OUT) ─────────────────────────────────
    st.markdown("---")
    st.subheader("Portfolio por Estado de Marca")
    status_agg = filtered_model.groupby("Status", as_index=False).agg(
        Revenue_YTD=("Revenue_YTD", "sum"),
        Margin_EUR_YTD=("Margin_EUR_YTD", "sum"),
        Num_Marcas=("Brand", "count"),
    )
    status_agg["Revenue %"] = status_agg["Revenue_YTD"] / status_agg["Revenue_YTD"].sum()
    status_agg["Margen %"] = status_agg.apply(
        lambda r: safe_ratio(r["Margin_EUR_YTD"], r["Revenue_YTD"]), axis=1
    )
    scol1, scol2 = st.columns(2)
    with scol1:
        status_colors = {"NEW": "#16A34A", "STANDARD": "#2563EB", "PHASE OUT": "#9CA3AF"}
        fig_status = px.bar(
            status_agg, x="Status", y="Revenue_YTD", color="Status",
            color_discrete_map=status_colors, text="Revenue %",
            title="Revenue YTD por Estado de Marca",
        )
        fig_status.update_traces(texttemplate="%{text:.1%}", textposition="outside")
        _apply_chart_style(fig_status)
        fig_status.update_layout(showlegend=False, xaxis_title="", yaxis_title="Revenue YTD (€)")
        st.plotly_chart(fig_status, use_container_width=True)
    with scol2:
        st.dataframe(
            status_agg.style.format({
                "Revenue_YTD": fmt_eur,
                "Margin_EUR_YTD": fmt_eur,
                "Revenue %": fmt_pct,
                "Margen %": fmt_pct,
            }),
            use_container_width=True,
        )

    # ── Monthly trend chart with per-family budget targets ─────────────────────
    st.markdown("---")
    fam_series = monthly_brand_series.merge(filtered_model[["BrandKey", "Family"]], on="BrandKey", how="inner")
    fam_monthly = build_monthly_overview(fam_series, current_month)

    # FIX: per-family monthly budget targets (not a single portfolio average line)
    family_budgets = filtered_model.groupby("Family")[MONTH_BUDGET_COLS].sum()

    st.subheader("Tendencias, eficiencia y alertas")

    # FIX: MoM metric shows actual last-month value, not the period average
    last_mom_rev = (
        fam_monthly.sort_values("Mes Factura")
        .groupby("Family")["MoM_Revenue_PCT"]
        .last()
        .dropna()
    )
    last_mom_mg = (
        fam_monthly.sort_values("Mes Factura")
        .groupby("Family")["MoM_Margin_PCT"]
        .last()
        .dropna()
    )
    portfolio_mom_rev = last_mom_rev.mean() if not last_mom_rev.empty else 0
    portfolio_mom_mg = last_mom_mg.mean() if not last_mom_mg.empty else 0

    outlier_mask, mean_revenue, std_revenue = detect_outliers(fam_monthly["Revenue_Month"])
    fam_monthly["Revenue_Outlier"] = outlier_mask

    tcol1, tcol2, tcol3 = st.columns(3)
    tcol1.metric(
        f"MoM Revenue · {MONTHS_ES[current_month]}",
        fmt_pct(portfolio_mom_rev),
        help="Variación del último mes disponible respecto al anterior (no promedio del período).",
    )
    tcol2.metric(
        f"MoM Margen · {MONTHS_ES[current_month]}",
        fmt_pct(portfolio_mom_mg),
        help="Variación del último mes disponible respecto al anterior.",
    )
    tcol3.metric(
        "Outliers detectados",
        f"{int(fam_monthly['Revenue_Outlier'].sum())}",
        help="Detección IQR (n<30) o z-score (n≥30, umbral 2.5σ).",
    )

    # Monthly trend with per-family budget lines
    flow = px.line(
        fam_monthly, x="Mes Factura", y="Revenue_Month", color="Family", markers=True,
        color_discrete_map=FAMILY_COLORS,
        title="Tendencia mensual de ventas por familia",
    )
    for fam in family_budgets.index:
        fam_budget_monthly = [
            family_budgets.loc[fam, MONTH_BUDGET_COLS[m - 1]]
            for m in range(1, current_month + 1)
        ]
        flow.add_trace(go.Scatter(
            x=list(range(1, current_month + 1)),
            y=fam_budget_monthly,
            mode="lines",
            name=f"Target · {fam}",
            line={"dash": "dot", "color": FAMILY_COLORS.get(fam, "#9CA3AF"), "width": 1},
            opacity=0.5,
            showlegend=True,
        ))
    _apply_chart_style(flow)
    flow.update_layout(
        xaxis_title="Mes",
        yaxis_title="Revenue (€)",
        xaxis=dict(tickvals=list(range(1, 13)), ticktext=list(MONTHS_ES.values())),
    )
    st.plotly_chart(flow, use_container_width=True)

    anomaly_view = fam_monthly[fam_monthly["Revenue_Outlier"]][
        ["Family", "Mes Factura", "Revenue_Month", "MoM_Revenue_PCT"]
    ]
    if anomaly_view.empty:
        st.info("No se detectaron outliers de revenue.")
    else:
        st.warning(
            f"Se detectaron {len(anomaly_view)} outliers (media={fmt_eur(mean_revenue)}, "
            f"dispersión={fmt_eur(std_revenue)})."
        )
        st.dataframe(
            anomaly_view.style.format({"Revenue_Month": fmt_eur, "MoM_Revenue_PCT": fmt_pct}),
            use_container_width=True,
        )

    # ── Quarterly segmentation (correct margin rate from sums, not averaged %) ─
    segment = fam_monthly.groupby(["Family", "Quarter"], as_index=False).agg(
        Revenue=("Revenue_Month", "sum"),
        Margin=("Margin_EUR_Month", "sum"),
    )
    # Margin rate from summed numerator/denominator — never average of monthly rates
    segment["Tasa Margen %"] = np.where(
        segment["Revenue"] != 0, segment["Margin"] / segment["Revenue"], np.nan
    )
    segment["COGS Rate %"] = 1 - segment["Tasa Margen %"].fillna(0)
    segment["Quarter"] = segment["Quarter"].apply(lambda q: f"Q{int(q)}")

    st.subheader("Segmentación por familia y trimestre")
    segment_styler = segment.style.format({
        "Revenue": fmt_eur,
        "Margin": fmt_eur,
        "Tasa Margen %": fmt_pct,
        "COGS Rate %": fmt_pct,
    })

    st.dataframe(
        segment_styler
        .apply(style_gradient_fallback, subset=["Tasa Margen %"], low_color="#b91c1c", high_color="#15803d")
        .apply(style_gradient_fallback, subset=["Revenue"], low_color="#dbeafe", high_color="#1d4ed8"),
        use_container_width=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# MARGEN (formerly "Margin")
# ══════════════════════════════════════════════════════════════════════════════
elif section == "Margen":
    filtered_model, sel_fam, sel_brands = apply_dashboard_filters(model, "margen")
    st.title(f"📈 Margen · {MONTHS_ES[current_month]}")
    _active_filter_banner(sel_fam, sel_brands)

    if filtered_model.empty:
        st.warning("No hay datos para los filtros seleccionados.")
        st.stop()

    total_rev_mg = filtered_model["Revenue_YTD"].sum()
    total_mg_val = filtered_model["Margin_EUR_YTD"].sum()
    total_mg_ly_val = filtered_model["LY_MgEur_YTD"].sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Margen € YTD", fmt_eur(total_mg_val))
    m2.metric(
        "Tasa Margen % YTD",
        fmt_pct(total_mg_val / total_rev_mg if total_rev_mg else 0),
    )
    m3.metric(
        "Margen Esperado % (ponderado)",
        weighted_expected_margin_display(filtered_model),
        help="Media ponderada por presupuesto anual de cada marca.",
    )
    m4.metric(
        "Desviación vs. LY (€)",
        fmt_eur(total_mg_val - total_mg_ly_val),
        delta=fmt_pct(pct_delta(total_mg_val, total_mg_ly_val)) + " vs. LY",
    )

    # Margin rate variance (pp) vs LY
    ly_rate_mg = total_mg_ly_val / filtered_model["LY_Rev_YTD"].sum() if filtered_model["LY_Rev_YTD"].sum() else 0
    cy_rate_mg = total_mg_val / total_rev_mg if total_rev_mg else 0
    st.metric(
        "Δ Tasa Margen vs. LY",
        fmt_pct_pts(cy_rate_mg - ly_rate_mg),
        help="Diferencia en puntos porcentuales de tasa de margen respecto al año anterior. "
             "Valor positivo = mejora de mix/precio, no solo volumen.",
    )

    table = filtered_model[[
        "Brand", "Short Name", "Status", "Family",
        "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD",
        "Expected Margin %", "Margin_Rate_vs_LY",
        "Stock", "LY_Rev_YTD", "LY_MgEur_YTD",
    ]].copy()
    table["Expected Margin %"] = table["Expected Margin %"].apply(fmt_pct)
    st.dataframe(
        table.style.format({
            "Revenue_YTD": fmt_eur,
            "Margin_EUR_YTD": fmt_eur,
            "Margin_PCT_YTD": fmt_pct,
            "Margin_Rate_vs_LY": fmt_pct_pts,
            "Stock": fmt_eur,
            "LY_Rev_YTD": fmt_eur,
            "LY_MgEur_YTD": fmt_eur,
        })
        .map(color_negative, subset=["Margin_Rate_vs_LY"]),
        use_container_width=True,
    )

    # ── Scatter: strategic quadrant view ──────────────────────────────────────
    # FIX: bubble size = Annual Budget (intentional strategic weight), NOT stock
    # FIX: add quadrant reference lines at portfolio averages
    avg_rev = filtered_model["Revenue_YTD"].mean()
    avg_mg_pct = filtered_model["Margin_PCT_YTD"].mean()

    mg_scatter = px.scatter(
        filtered_model,
        x="Revenue_YTD",
        y="Margin_PCT_YTD",
        size="Annual Budget",
        color="Family",
        color_discrete_map=FAMILY_COLORS,
        hover_name="Short Name",
        hover_data={"Status": True, "Budget_YTD": ":,.0f", "Growth_vs_LY_Revenue_PCT": ":.1%"},
        title="Mix estratégico: Revenue vs. Tasa de Margen % (tamaño = Presupuesto Anual)",
        size_max=60,
    )
    mg_scatter.add_vline(x=avg_rev, line_dash="dash", line_color="#9CA3AF", annotation_text="Avg Rev")
    mg_scatter.add_hline(y=avg_mg_pct, line_dash="dash", line_color="#9CA3AF", annotation_text="Avg Margen %")
    _apply_chart_style(mg_scatter)
    mg_scatter.update_layout(
        xaxis_title="Revenue YTD (€)",
        yaxis=dict(tickformat=".1%", title="Tasa Margen %", gridcolor="#F3F4F6"),
    )
    st.plotly_chart(mg_scatter, use_container_width=True)
    st.caption(
        "**Cuadrantes:** Arriba-derecha = Estrellas (alto rev + alto margen) · "
        "Arriba-izquierda = Nicho (bajo rev + alto margen) · "
        "Abajo-derecha = Volumen (alto rev + bajo margen) · "
        "Abajo-izquierda = Revisión (bajo rev + bajo margen)."
    )

# ══════════════════════════════════════════════════════════════════════════════
# VERTICALS
# ══════════════════════════════════════════════════════════════════════════════
else:
    vertical = section.split("·", 1)[1].strip()
    st.title(f"{vertical} · {MONTHS_ES[current_month]}")
    sub, sel_fam, sel_brands = apply_dashboard_filters(model, f"vertical_{vertical}", default_family=vertical)
    _active_filter_banner(sel_fam, sel_brands)

    if sub.empty:
        n_configured = model[model["Family"] == vertical].shape[0]
        if n_configured == 0:
            st.warning(
                f"No hay marcas configuradas para **{vertical}**. "
                "Ve a **Brand Config** y asigna marcas a esta familia."
            )
        else:
            st.warning("No hay datos de ventas para los filtros seleccionados en este período.")
    else:
        agg = {
            "revenue": sub["Revenue_YTD"].sum(),
            "margin": sub["Margin_EUR_YTD"].sum(),
            "ly_rev": sub["LY_Rev_YTD"].sum(),
            "ly_margin": sub["LY_MgEur_YTD"].sum(),
            "budget": sub["Budget_YTD"].sum(),
            "cur_month_rev": sub["Revenue_Current_Month"].sum(),
            "prev_month_rev": sub["Revenue_Prev_Month"].sum(),
            "cur_month_margin": sub["Margin_EUR_Current_Month"].sum(),
            "prev_month_margin": sub["Margin_EUR_Prev_Month"].sum(),
            "stock": sub["Stock"].sum(),
            "annual_budget": sub["Annual Budget"].sum(),
        }

        # ── Tier 1 KPIs ───────────────────────────────────────────────────────
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Crecimiento Revenue",
            fmt_pct(pct_delta(agg["revenue"], agg["ly_rev"])),
            delta=fmt_eur_delta(agg["revenue"] - agg["ly_rev"]),
        )
        k2.metric(
            "Crecimiento Margen",
            fmt_pct(pct_delta(agg["margin"], agg["ly_margin"])),
            delta=fmt_eur_delta(agg["margin"] - agg["ly_margin"]),
        )
        k3.metric(
            "Attainment vs. Budget",
            fmt_pct(pct_delta(agg["revenue"], agg["budget"])),
            delta=fmt_eur_delta(agg["revenue"] - agg["budget"]),
        )
        k4.metric(
            "Stock (€) vs. Presupuesto Anual",
            fmt_pct(safe_ratio(agg["stock"], agg["annual_budget"])),
            help="Stock en euros / Presupuesto anual en euros.",
        )

        # ── Tier 2 KPIs ───────────────────────────────────────────────────────
        t1, t2, t3 = st.columns(3)
        t1.metric(
            f"Tendencia Mes Revenue ({MONTHS_ES[current_month]})",
            fmt_pct(pct_delta(agg["cur_month_rev"], agg["prev_month_rev"])),
        )
        t2.metric(
            f"Tendencia Mes Margen ({MONTHS_ES[current_month]})",
            fmt_pct(pct_delta(agg["cur_month_margin"], agg["prev_month_margin"])),
        )
        # Gross Margin Rate (correctly labeled — NOT ROI)
        t3.metric(
            "Tasa de Margen Bruto % YTD",
            fmt_pct(safe_ratio(agg["margin"], agg["revenue"])),
            help="Margen € / Revenue €. Indica la rentabilidad bruta del vertical.",
        )

        # ── Brand detail table ─────────────────────────────────────────────────
        brand_view = sub[[
            "Short Name", "Status", "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD",
            "LY_Rev_YTD", "LY_MgEur_YTD", "Budget_YTD",
            "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Margin_Rate_vs_LY",
            "Vs_Budget_PCT", "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT",
            "Stock_vs_Year_Budget",
        ]].copy().sort_values("Revenue_YTD", ascending=False)

        st.dataframe(
            brand_view.style.format({
                "Revenue_YTD": fmt_eur,
                "Margin_EUR_YTD": fmt_eur,
                "Margin_PCT_YTD": fmt_pct,
                "LY_Rev_YTD": fmt_eur,
                "LY_MgEur_YTD": fmt_eur,
                "Budget_YTD": fmt_eur,
                "Growth_vs_LY_Revenue_PCT": fmt_pct,
                "Growth_vs_LY_Margin_PCT": fmt_pct,
                "Margin_Rate_vs_LY": fmt_pct_pts,
                "Vs_Budget_PCT": fmt_pct,
                "Last_Month_Trend_Revenue_PCT": fmt_pct,
                "Last_Month_Trend_Margin_PCT": fmt_pct,
                "Stock_vs_Year_Budget": fmt_pct,
            })
            .map(color_negative, subset=[
                "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Margin_Rate_vs_LY",
                "Vs_Budget_PCT", "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT",
            ]),
            use_container_width=True,
        )

        # ── Monthly trend (focus mode for many brands) ─────────────────────────
        monthly_vertical = monthly_brand_series.merge(
            sub[["BrandKey", "Short Name"]], on="BrandKey", how="inner"
        )
        n_brands = monthly_vertical["Short Name"].nunique()

        chart_title = f"Tendencia mensual por marca · {vertical}"
        if n_brands > 6:
            st.info(
                f"Hay {n_brands} marcas. Modo foco activo: se muestran las top 5 por Revenue YTD + 'Otras'."
            )
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

        _apply_chart_style(fig)
        fig.update_layout(
            xaxis_title="Mes",
            xaxis=dict(tickvals=list(range(1, 13)), ticktext=list(MONTHS_ES.values())),
            yaxis_title="Revenue (€)",
        )
        fig.update_traces(line=dict(width=2.5))
        st.plotly_chart(fig, use_container_width=True)
