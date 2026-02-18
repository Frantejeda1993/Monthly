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
    </style>
    """,
    unsafe_allow_html=True,
)

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
STATUS_OPTIONS = ["NEW", "STANDARD", "PHASE OUT"]
FAMILY_OPTIONS = ["2 WHEELS", "FREE TIME", "OUTDOOR TECH", "UNCLASSIFIED"]
MONTH_BUDGET_COLS = [f"Budget {MONTHS_ES[i]}" for i in range(1, 13)]


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
    return sa if isinstance(sa, dict) else {}, db_url


@st.cache_resource
def init_firebase():
    try:
        cred_info, database_url = _extract_firebase_config()
        if firebase_admin._apps:
            return True, "Firebase conectado"
        if not database_url or not all(cred_info.get(k) for k in ["project_id", "private_key", "client_email"]):
            return False, "Faltan credenciales de Firebase en st.secrets"
        firebase_admin.initialize_app(credentials.Certificate(cred_info), {"databaseURL": database_url})
        return True, "Firebase conectado"
    except Exception as e:
        return False, f"Error Firebase: {e}"


def save_df_to_firebase(path: str, df: pd.DataFrame):
    ref = db.reference(path)
    ref.set({"columns": [str(c) for c in df.columns], "rows": df.replace({np.nan: None}).values.tolist(),
             "updated_at": datetime.now(timezone.utc).isoformat()})


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


def read_sheet(uploaded_file, sheet_name):
    bio = BytesIO(uploaded_file.read())
    uploaded_file.seek(0)
    xls = pd.ExcelFile(bio)
    return pd.read_excel(bio, sheet_name=sheet_name if sheet_name in xls.sheet_names else 0)


def read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    """Read CSV files uploaded from Streamlit with automatic delimiter detection."""
    uploaded_file.seek(0)
    data = uploaded_file.read()
    uploaded_file.seek(0)

    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = str(data)

    # Handle common exports that use semicolons and/or commas as decimal separators.
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

            month_match = re.match(r"^(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s*-\s*(.+)$", n_plain)
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
        if "LY_Mg%" not in dfx.columns:
            if monthly_mg_pct_cols:
                dfx["LY_Mg%"] = dfx[monthly_mg_pct_cols].mean(axis=1)
            else:
                dfx["LY_Mg%"] = np.where(dfx["LY_Rev"] != 0, dfx["LY_MgEur"] / dfx["LY_Rev"] * 100, 0)

        dfx["LY_Rev"] = pd.to_numeric(dfx["LY_Rev"], errors="coerce").fillna(0)
        dfx["LY_MgEur"] = pd.to_numeric(dfx["LY_MgEur"], errors="coerce").fillna(0)
        dfx["LY_Mg%"] = pd.to_numeric(dfx["LY_Mg%"], errors="coerce").fillna(0)

    return dfx


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


def validate_brand_config_df(df_cfg: pd.DataFrame, expected_brand_keys: set[str], immutable_brand_map: dict[str, str] | None = None):
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
        cfg = cfg[["Brand", "BrandKey", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]]

    for c in ["Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]:
        cfg[c] = pd.to_numeric(cfg[c], errors="coerce")

    monthly_sum = cfg[MONTH_BUDGET_COLS].fillna(0).sum(axis=1)
    cfg["Annual Budget"] = np.where(cfg["Annual Budget"].fillna(0) > 0, cfg["Annual Budget"], monthly_sum)
    needs_spread = monthly_sum == 0
    for col in MONTH_BUDGET_COLS:
        cfg[col] = np.where(needs_spread, cfg["Annual Budget"].fillna(0) / 12, cfg[col].fillna(0))

    cfg["Expected Margin %"] = cfg["Expected Margin %"].fillna(0) / np.where(cfg["Expected Margin %"] > 1, 100, 1)
    cfg["Status"] = cfg["Status"].where(cfg["Status"].isin(STATUS_OPTIONS), "STANDARD")
    cfg["Family"] = cfg["Family"].where(cfg["Family"].isin(FAMILY_OPTIONS), "UNCLASSIFIED")
    return cfg


def prepare_model(df_sales, df_stock, df_margin_ly, brand_cfg, current_month):
    sales = df_sales.copy()
    sales["BrandKey"] = _get_series(sales, "Nombre").apply(_normalize_brand)
    sales["Mes Factura"] = pd.to_numeric(sales["Mes Factura"], errors="coerce").fillna(0).astype(int)

    sales_ytd = sales[sales["Mes Factura"] <= current_month].copy()
    grouped = sales_ytd.groupby("BrandKey", as_index=False).agg(
        Revenue_YTD=("Importe Neto", "sum"), Margin_EUR_YTD=("Margen_Euros", "sum")
    )
    grouped["Margin_PCT_YTD"] = np.where(grouped["Revenue_YTD"] != 0, grouped["Margin_EUR_YTD"] / grouped["Revenue_YTD"], 0)
    grouped["Revenue_Projected"] = grouped["Revenue_YTD"] / max(current_month, 1) * 12

    monthly_sales = sales.groupby(["BrandKey", "Mes Factura"], as_index=False).agg(
        Revenue_Month=("Importe Neto", "sum"), Margin_EUR_Month=("Margen_Euros", "sum")
    )

    prev_month = 12 if current_month == 1 else current_month - 1
    prev_month_sales = monthly_sales[monthly_sales["Mes Factura"] == prev_month].groupby("BrandKey", as_index=False).agg(
        Revenue_Prev_Month=("Revenue_Month", "sum"), Margin_EUR_Prev_Month=("Margin_EUR_Month", "sum")
    )

    current_month_sales = monthly_sales[monthly_sales["Mes Factura"] == current_month].groupby("BrandKey", as_index=False).agg(
        Revenue_Current_Month=("Revenue_Month", "sum"), Margin_EUR_Current_Month=("Margin_EUR_Month", "sum")
    )

    stock = df_stock.copy()
    stock["BrandKey"] = _get_series(stock, "Marca").apply(_normalize_brand)
    stock = stock.groupby("BrandKey", as_index=False)["Stock"].sum()

    ly = df_margin_ly.copy()
    ly["BrandKey"] = _get_series(ly, "Marca").apply(_normalize_brand)
    monthly_ly_rev_cols = [f"LY_M{i:02d}_Rev" for i in range(1, 13) if f"LY_M{i:02d}_Rev" in ly.columns]
    monthly_ly_mg_eur_cols = [f"LY_M{i:02d}_MgEur" for i in range(1, 13) if f"LY_M{i:02d}_MgEur" in ly.columns]

    ly_agg = {"LY_Rev": "sum", "LY_MgEur": "sum", "LY_Mg%": "mean"}
    ly_agg.update({c: "sum" for c in monthly_ly_rev_cols})
    ly_agg.update({c: "sum" for c in monthly_ly_mg_eur_cols})
    ly = ly.groupby("BrandKey", as_index=False).agg(ly_agg).rename(columns={"LY_Mg%": "LY_Mg_pct"})

    if monthly_ly_rev_cols:
        ly["LY_Rev"] = ly[monthly_ly_rev_cols].sum(axis=1)
        ly["LY_Rev_YTD"] = ly[monthly_ly_rev_cols[:current_month]].sum(axis=1)
    else:
        ly["LY_Rev_YTD"] = ly["LY_Rev"] * current_month / 12

    if monthly_ly_mg_eur_cols:
        ly["LY_MgEur"] = ly[monthly_ly_mg_eur_cols].sum(axis=1)
        ly["LY_MgEur_YTD"] = ly[monthly_ly_mg_eur_cols[:current_month]].sum(axis=1)
    else:
        ly["LY_MgEur_YTD"] = ly["LY_MgEur"] * current_month / 12

    model = (
        brand_cfg
        .merge(grouped, on="BrandKey", how="left")
        .merge(current_month_sales, on="BrandKey", how="left")
        .merge(prev_month_sales, on="BrandKey", how="left")
        .merge(stock, on="BrandKey", how="left")
        .merge(ly, on="BrandKey", how="left")
    )
    for c in [
        "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Revenue_Projected", "Stock", "LY_Rev", "LY_MgEur", "LY_Mg_pct",
        "LY_Rev_YTD", "LY_MgEur_YTD", "Revenue_Current_Month", "Margin_EUR_Current_Month", "Revenue_Prev_Month", "Margin_EUR_Prev_Month",
    ]:
        model[c] = pd.to_numeric(model[c], errors="coerce").fillna(0)

    model["Budget_YTD"] = model[MONTH_BUDGET_COLS[:current_month]].sum(axis=1)
    model["Budget_Month"] = model[MONTH_BUDGET_COLS[current_month - 1]]
    model["Annual Budget"] = pd.to_numeric(model["Annual Budget"], errors="coerce").fillna(0)
    model["Budget_vs_Actual"] = model["Revenue_YTD"] - model["Budget_YTD"]
    model["Stock_vs_Year_Budget"] = np.where(model["Annual Budget"] != 0, model["Stock"] / model["Annual Budget"], np.nan)

    revenue_ly_base = model["LY_Rev_YTD"].replace(0, np.nan)
    margin_ly_base = model["LY_MgEur_YTD"].replace(0, np.nan)
    budget_base = model["Budget_YTD"].replace(0, np.nan)
    prev_rev_base = model["Revenue_Prev_Month"].replace(0, np.nan)
    prev_margin_base = model["Margin_EUR_Prev_Month"].replace(0, np.nan)

    model["Growth_vs_LY_Revenue_PCT"] = (model["Revenue_YTD"] / revenue_ly_base) - 1
    model["Growth_vs_LY_Margin_PCT"] = (model["Margin_EUR_YTD"] / margin_ly_base) - 1
    model["Vs_Budget_PCT"] = (model["Revenue_YTD"] / budget_base) - 1
    model["Last_Month_Trend_Revenue_PCT"] = (model["Revenue_Current_Month"] / prev_rev_base) - 1
    model["Last_Month_Trend_Margin_PCT"] = (model["Margin_EUR_Current_Month"] / prev_margin_base) - 1

    monthly_by_brand = monthly_sales[monthly_sales["Mes Factura"] <= current_month].copy()
    return model, monthly_by_brand


def fmt_eur(v):
    return f"€{v:,.0f}"


def fmt_pct(v):
    return f"{v * 100:.1f}%"


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


def apply_dashboard_filters(df: pd.DataFrame, section_name: str, default_family: str | None = None) -> pd.DataFrame:
    """Apply family and brand filters in sidebar for dashboard sections."""
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

    return filtered


firebase_ok, firebase_msg = init_firebase()

with st.sidebar:
    st.markdown("### 🏍️ Sportech IB")
    st.caption("Nueva arquitectura: 3 inputs + configuración dinámica de marcas")
    if firebase_ok:
        st.success(firebase_msg)
    else:
        st.error(firebase_msg)

    with st.expander("📥 INPUTS", expanded=False):
        up_sales = st.file_uploader("INPUT (Monthly) Sales", type=["xlsx"], key="sales")
        st.markdown("#### INPUT (Monthly) Stock por mes")
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
                save_df_to_firebase("datasets/monthly_sales", validate_dataset(read_sheet(up_sales, "INPUT (Monthly) Sales"), "sales", "INPUT (Monthly) Sales"))
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
                save_df_to_firebase("datasets/annual_margin_ly", validate_dataset(read_sheet(up_margin, "INPUT (Annual) MARGIN LY"), "margin_ly", "INPUT (Annual) MARGIN LY"))
            st.success("INPUTS guardados")
        except Exception as e:
            st.error(str(e))

sales_df = load_df_from_firebase("datasets/monthly_sales") if firebase_ok else pd.DataFrame()
stock_df = load_df_from_firebase("datasets/monthly_stock") if firebase_ok else pd.DataFrame()
margin_ly_df = load_df_from_firebase("datasets/annual_margin_ly") if firebase_ok else pd.DataFrame()
saved_brand_cfg = load_df_from_firebase("datasets/brand_configuration") if firebase_ok else pd.DataFrame()

if sales_df.empty or stock_df.empty or margin_ly_df.empty:
    st.title("Sportech IB Dashboard")
    st.info("Carga los 3 INPUTS requeridos para comenzar: Sales, Stock y MARGIN LY.")
    st.stop()

try:
    sales_df = validate_dataset(sales_df, "sales", "INPUT (Monthly) Sales")
    stock_df = validate_dataset(stock_df, "stock", "INPUT (Monthly) Stock")
    margin_ly_df = validate_dataset(margin_ly_df, "margin_ly", "INPUT (Annual) MARGIN LY")
except ValueError as e:
    st.error(str(e))
    st.stop()

brand_master = extract_brand_master(sales_df, stock_df, margin_ly_df)
brand_cfg = build_brand_config(brand_master, saved_brand_cfg)

st.sidebar.markdown("---")
available_months = sorted(sales_df["Mes Factura"].dropna().astype(int).unique().tolist())
if not available_months:
    st.warning(
        "El dataset de ventas no tiene meses válidos (1-12) después de la validación. "
        "Revisa y vuelve a subir el archivo con valores correctos en `Mes Factura` o `Fecha`."
    )
    st.stop()
current_month = st.sidebar.selectbox("Current Month", options=available_months, index=len(available_months) - 1)
section = st.sidebar.radio("Sección", ["Brand Config", "Overview", "Margin", "Vertical · 2 WHEELS", "Vertical · FREE TIME", "Vertical · OUTDOOR TECH"], key="section_selector")

if section == "Brand Config":
    st.title("⚙️ Brand Master & Financial Configuration")
    st.write("Lista única de marcas generada automáticamente a partir de los 3 INPUTS.")

    with st.expander("CSV upload: estructura requerida", expanded=True):
        st.markdown(
            "- **Columnas obligatorias**: `Brand`, `Short Name`, `Status`, `Family`, `Annual Budget`, `Expected Margin %`.\n"
            "- **Columnas opcionales**: `Budget Enero` ... `Budget Diciembre`.\n"
            "- **Status válidos**: NEW, STANDARD, PHASE OUT.\n"
            "- **Family válidas**: 2 WHEELS, FREE TIME, OUTDOOR TECH, UNCLASSIFIED.\n"
            "- **Validaciones**: marcas duplicadas, marcas faltantes, marcas extra no existentes, tipos numéricos inválidos.\n"
            "- **Errores**: se muestran con detalle y no se persiste el CSV hasta corregir."
        )
        sample = brand_cfg[["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]].head(3)
        st.dataframe(sample, use_container_width=True)

    csv_up = st.file_uploader("Upload brand configuration CSV", type=["csv"], key="cfg_csv")
    if csv_up is not None:
        try:
            incoming = read_uploaded_csv(csv_up)
            valid_cfg = validate_brand_config_df(incoming, set(brand_cfg["BrandKey"]))
            save_df_to_firebase("datasets/brand_configuration", valid_cfg)
            st.success("CSV validado y guardado.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    immutable_brand_map = brand_cfg.set_index("BrandKey")["Brand"].astype(str).to_dict()

    edited = st.data_editor(
        brand_cfg[["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Brand": st.column_config.TextColumn(disabled=True),
            "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
            "Family": st.column_config.SelectboxColumn(options=FAMILY_OPTIONS),
        },
    )
    if st.button("Guardar configuración", use_container_width=True):
        try:
            out = edited.copy()
            out["BrandKey"] = out["Brand"].apply(_normalize_brand)
            valid_cfg = validate_brand_config_df(
                out,
                set(brand_cfg["BrandKey"]),
                immutable_brand_map=immutable_brand_map,
            )
            save_df_to_firebase("datasets/brand_configuration", valid_cfg)
            st.success("Configuración guardada")
        except Exception as e:
            st.error(str(e))

    st.stop()

model, monthly_brand_series = prepare_model(sales_df, stock_df, margin_ly_df, brand_cfg, current_month)

if section == "Overview":
    filtered_model = apply_dashboard_filters(model, "overview")
    st.title(f"📊 Overview · {MONTHS_ES[current_month]}")
    if filtered_model.empty:
        st.warning("No hay datos para los filtros seleccionados.")
        st.stop()

    total_rev = filtered_model["Revenue_YTD"].sum()
    total_mg = filtered_model["Margin_EUR_YTD"].sum()
    total_budget = filtered_model["Budget_YTD"].sum()
    total_stock = filtered_model["Stock"].sum()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Revenue YTD", fmt_eur(total_rev))
    c2.metric("Margin € YTD", fmt_eur(total_mg))
    c3.metric("Margin % YTD", fmt_pct(total_mg / total_rev if total_rev else 0))
    c4.metric("Budget Attainment", fmt_pct(total_rev / total_budget if total_budget else 0))
    c5.metric("Gap vs Budget", fmt_eur(total_rev - total_budget))
    c6.metric("Stock", fmt_eur(total_stock))

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
    overview_fam["Growth Rev %"] = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["LY_Rev_YTD"]), axis=1)
    overview_fam["Growth Rev €"] = overview_fam["Revenue_YTD"] - overview_fam["LY_Rev_YTD"]
    overview_fam["Growth Margin %"] = overview_fam.apply(lambda r: pct_delta(r["Margin_EUR_YTD"], r["LY_MgEur_YTD"]), axis=1)
    overview_fam["Growth Margin €"] = overview_fam["Margin_EUR_YTD"] - overview_fam["LY_MgEur_YTD"]
    overview_fam["Vs Budget %"] = overview_fam.apply(lambda r: pct_delta(r["Revenue_YTD"], r["Budget_YTD"]), axis=1)
    overview_fam["Vs Budget €"] = overview_fam["Revenue_YTD"] - overview_fam["Budget_YTD"]
    overview_fam["Last Month Rev %"] = overview_fam.apply(lambda r: pct_delta(r["Revenue_Current_Month"], r["Revenue_Prev_Month"]), axis=1)
    overview_fam["Last Month Margin %"] = overview_fam.apply(lambda r: pct_delta(r["Margin_EUR_Current_Month"], r["Margin_EUR_Prev_Month"]), axis=1)
    overview_fam["% Stock vs Year Budget"] = overview_fam.apply(lambda r: safe_ratio(r["Stock"], r["Annual_Budget"]), axis=1)

    display_fam = overview_fam[[
        "Family", "Growth Rev %", "Growth Rev €", "Growth Margin %", "Growth Margin €",
        "Vs Budget %", "Vs Budget €", "Last Month Rev %", "Last Month Margin %", "% Stock vs Year Budget"
    ]].copy()
    st.subheader("KPIs por Familia")
    st.dataframe(
        display_fam.style.format({
            "Growth Rev %": fmt_pct,
            "Growth Rev €": fmt_eur,
            "Growth Margin %": fmt_pct,
            "Growth Margin €": fmt_eur,
            "Vs Budget %": fmt_pct,
            "Vs Budget €": fmt_eur,
            "Last Month Rev %": fmt_pct,
            "Last Month Margin %": fmt_pct,
            "% Stock vs Year Budget": fmt_pct,
        }).map(color_negative, subset=["Growth Rev %", "Growth Margin %", "Vs Budget %", "Last Month Rev %", "Last Month Margin %"]).map(color_negative, subset=["Growth Rev €", "Growth Margin €", "Vs Budget €"]),
        use_container_width=True,
    )

    fam_series = monthly_brand_series.merge(filtered_model[["BrandKey", "Family"]], on="BrandKey", how="inner")
    fam_monthly = fam_series.groupby(["Family", "Mes Factura"], as_index=False).agg(Revenue_Month=("Revenue_Month", "sum"), Margin_EUR_Month=("Margin_EUR_Month", "sum"))
    flow = px.line(
        fam_monthly,
        x="Mes Factura",
        y="Revenue_Month",
        color="Family",
        markers=True,
        title="Last Month Trend · Flujo mensual de ventas por Familia",
    )
    flow.update_layout(xaxis_title="Mes", yaxis_title="Revenue (€)")
    st.plotly_chart(flow, use_container_width=True)

elif section == "Margin":
    filtered_model = apply_dashboard_filters(model, "margin")
    st.title(f"📈 Margin · {MONTHS_ES[current_month]}")
    if filtered_model.empty:
        st.warning("No hay datos para los filtros seleccionados.")
        st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Margin € YTD", fmt_eur(filtered_model["Margin_EUR_YTD"].sum()))
    m2.metric("Margin % YTD", fmt_pct(filtered_model["Margin_EUR_YTD"].sum() / filtered_model["Revenue_YTD"].sum() if filtered_model["Revenue_YTD"].sum() else 0))
    m3.metric("Expected Margin %", weighted_expected_margin_display(filtered_model))
    m4.metric("Desviación vs LY", fmt_eur(filtered_model["Margin_EUR_YTD"].sum() - filtered_model["LY_MgEur_YTD"].sum()))

    table = filtered_model[["Brand", "Short Name", "Status", "Family", "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Expected Margin %", "Stock", "LY_Rev_YTD", "LY_MgEur_YTD"]].copy()
    st.dataframe(table, use_container_width=True)

    mg_scatter = px.scatter(
        filtered_model,
        x="Revenue_YTD",
        y="Margin_PCT_YTD",
        size="Stock",
        color="Family",
        hover_name="Short Name",
        title="Mix de margen: Revenue vs Margin %",
    )
    mg_scatter.update_layout(xaxis_title="Revenue YTD (€)", yaxis_title="Margin %")
    st.plotly_chart(mg_scatter, use_container_width=True)

else:
    vertical = section.split("·", 1)[1].strip()
    st.title(f"{vertical} · {MONTHS_ES[current_month]}")
    sub = apply_dashboard_filters(model, f"vertical_{vertical}", default_family=vertical)
    if sub.empty:
        st.warning("No hay marcas configuradas para este vertical.")
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

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("ARE WE GROWING? Rev", fmt_pct(pct_delta(agg["revenue"], agg["ly_rev"])))
        k2.metric("ARE WE GROWING? Margin", fmt_pct(pct_delta(agg["margin"], agg["ly_margin"])))
        k3.metric("HOW ARE WE DOING VS BUDGET?", fmt_pct(pct_delta(agg["revenue"], agg["budget"])))
        k4.metric("% STOCK VS YEAR BUDGET", fmt_pct(safe_ratio(agg["stock"], agg["annual_budget"])))

        t1, t2 = st.columns(2)
        t1.metric("LAST MONTH TREND Rev", fmt_pct(pct_delta(agg["cur_month_rev"], agg["prev_month_rev"])))
        t2.metric("LAST MONTH TREND Margin", fmt_pct(pct_delta(agg["cur_month_margin"], agg["prev_month_margin"])))

        brand_view = sub[[
            "Short Name", "Revenue_YTD", "Margin_EUR_YTD", "LY_Rev_YTD", "LY_MgEur_YTD", "Budget_YTD",
            "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Vs_Budget_PCT",
            "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT", "Stock_vs_Year_Budget"
        ]].copy().sort_values("Revenue_YTD", ascending=False)
        st.dataframe(
            brand_view.style.format({
                "Revenue_YTD": fmt_eur,
                "Margin_EUR_YTD": fmt_eur,
                "LY_Rev_YTD": fmt_eur,
                "LY_MgEur_YTD": fmt_eur,
                "Budget_YTD": fmt_eur,
                "Growth_vs_LY_Revenue_PCT": fmt_pct,
                "Growth_vs_LY_Margin_PCT": fmt_pct,
                "Vs_Budget_PCT": fmt_pct,
                "Last_Month_Trend_Revenue_PCT": fmt_pct,
                "Last_Month_Trend_Margin_PCT": fmt_pct,
                "Stock_vs_Year_Budget": fmt_pct,
            }).map(color_negative, subset=[
                "Growth_vs_LY_Revenue_PCT", "Growth_vs_LY_Margin_PCT", "Vs_Budget_PCT",
                "Last_Month_Trend_Revenue_PCT", "Last_Month_Trend_Margin_PCT"
            ]),
            use_container_width=True,
        )

        monthly_vertical = monthly_brand_series.merge(sub[["BrandKey", "Short Name"]], on="BrandKey", how="inner")
        fig = px.line(
            monthly_vertical,
            x="Mes Factura",
            y="Revenue_Month",
            color="Short Name",
            markers=True,
            title="LAST MONTH TREND · Flujo mensual por marca",
        )
        fig.update_layout(xaxis_title="Mes", yaxis_title="Revenue (€)")
        st.plotly_chart(fig, use_container_width=True)
