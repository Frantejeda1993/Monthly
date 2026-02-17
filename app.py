import re
import warnings
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

warnings.filterwarnings("ignore")

st.set_page_config(page_title="Sportech IB · Dashboard", page_icon="🏍️", layout="wide")

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
STATUS_OPTIONS = ["NEW", "STANDARD", "PHASE OUT"]
FAMILY_OPTIONS = ["2 WHEELS", "FREE TIME", "OUTDOOR TECH", "UNCLASSIFIED"]
MONTH_BUDGET_COLS = [f"Budget {MONTHS_ES[i]}" for i in range(1, 13)]


def _normalize_col(col):
    return str(col).strip().lower().replace(" ", "_")


def _normalize_brand(value):
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _first_existing(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _auto_short_name(brand: str) -> str:
    cleaned = re.sub(r"[^A-Za-z\s]", "", str(brand))
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
    if isinstance(raw, dict) and "columns" in raw and "rows" in raw:
        return pd.DataFrame(raw["rows"], columns=raw["columns"])
    if isinstance(raw, list):
        return pd.DataFrame(raw)
    if isinstance(raw, dict):
        return pd.DataFrame(list(raw.values()))
    return pd.DataFrame()


def read_sheet(uploaded_file, sheet_name):
    bio = BytesIO(uploaded_file.read())
    uploaded_file.seek(0)
    xls = pd.ExcelFile(bio)
    return pd.read_excel(bio, sheet_name=sheet_name if sheet_name in xls.sheet_names else 0)


def validate_dataset(df: pd.DataFrame, dataset_key: str, dataset_name: str) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError(f"{dataset_name} está vacío.")
    dfx = df.copy()
    dfx.columns = [str(c).strip() for c in dfx.columns]

    if dataset_key == "sales":
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
            dfx["Mes Factura"] = parsed.dt.month
        else:
            dfx["Mes Factura"] = pd.to_numeric(dfx[month_col], errors="coerce")
        dfx = dfx[dfx["Mes Factura"].between(1, 12, inclusive="both")]
        dfx["Importe Neto"] = pd.to_numeric(dfx["Importe Neto"], errors="coerce").fillna(0)
        if "Margen_Euros" not in dfx.columns:
            mg_pct_col = _first_existing(dfx, ["CR3: % Margen s/Venta", "Margen %", "Margin %"])
            if mg_pct_col:
                dfx["Margen_Euros"] = dfx["Importe Neto"] * pd.to_numeric(dfx[mg_pct_col], errors="coerce").fillna(0) / 100
            else:
                dfx["Margen_Euros"] = 0
        dfx["Margen_Euros"] = pd.to_numeric(dfx["Margen_Euros"], errors="coerce").fillna(0)

    elif dataset_key == "stock":
        if "Marca" not in dfx.columns:
            dfx = dfx.rename(columns={dfx.columns[0]: "Marca"})
        if "Stock" not in dfx.columns and len(dfx.columns) > 1:
            dfx = dfx.rename(columns={dfx.columns[1]: "Stock"})
        if "Marca" not in dfx.columns or "Stock" not in dfx.columns:
            raise ValueError(f"{dataset_name}: se requieren columnas Marca y Stock.")
        dfx["Stock"] = pd.to_numeric(dfx["Stock"], errors="coerce").fillna(0)

    elif dataset_key == "margin_ly":
        if "Marca" not in dfx.columns:
            dfx = dfx.rename(columns={dfx.columns[0]: "Marca"})
        rename = {}
        for c in dfx.columns:
            n = _normalize_col(c)
            if "ly_rev" in n or n in ("revenue_ly", "ly_revenue"):
                rename[c] = "LY_Rev"
            if "ly_mgeur" in n or "ly_mg_eur" in n:
                rename[c] = "LY_MgEur"
            if "ly_mg" in n and "%" in c:
                rename[c] = "LY_Mg%"
        dfx = dfx.rename(columns=rename)
        for c in ["LY_Rev", "LY_MgEur", "LY_Mg%"]:
            if c not in dfx.columns:
                dfx[c] = 0
            dfx[c] = pd.to_numeric(dfx[c], errors="coerce").fillna(0)

    return dfx


def extract_brand_master(df_sales, df_stock, df_margin_ly):
    brands = set(df_sales["Nombre"].dropna().astype(str).str.strip().tolist())
    brands.update(df_stock["Marca"].dropna().astype(str).str.strip().tolist())
    brands.update(df_margin_ly["Marca"].dropna().astype(str).str.strip().tolist())
    clean = sorted({b for b in brands if b})
    master = pd.DataFrame({"Brand": clean})
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
    sales["BrandKey"] = sales["Nombre"].apply(_normalize_brand)

    sales_ytd = sales[sales["Mes Factura"] <= current_month].copy()
    grouped = sales_ytd.groupby("BrandKey", as_index=False).agg(
        Revenue_YTD=("Importe Neto", "sum"), Margin_EUR_YTD=("Margen_Euros", "sum")
    )
    grouped["Margin_PCT_YTD"] = np.where(grouped["Revenue_YTD"] != 0, grouped["Margin_EUR_YTD"] / grouped["Revenue_YTD"], 0)
    grouped["Revenue_Projected"] = grouped["Revenue_YTD"] / max(current_month, 1) * 12

    stock = df_stock.copy()
    stock["BrandKey"] = stock["Marca"].apply(_normalize_brand)
    stock = stock.groupby("BrandKey", as_index=False)["Stock"].sum()

    ly = df_margin_ly.copy()
    ly["BrandKey"] = ly["Marca"].apply(_normalize_brand)
    ly = ly.groupby("BrandKey", as_index=False).agg(LY_Rev=("LY_Rev", "sum"), LY_MgEur=("LY_MgEur", "sum"), LY_Mg_pct=("LY_Mg%", "mean"))

    model = brand_cfg.merge(grouped, on="BrandKey", how="left").merge(stock, on="BrandKey", how="left").merge(ly, on="BrandKey", how="left")
    for c in ["Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Revenue_Projected", "Stock", "LY_Rev", "LY_MgEur", "LY_Mg_pct"]:
        model[c] = pd.to_numeric(model[c], errors="coerce").fillna(0)

    model["Budget_YTD"] = model[MONTH_BUDGET_COLS[:current_month]].sum(axis=1)
    model["Budget_Month"] = model[MONTH_BUDGET_COLS[current_month - 1]]
    model["Budget_vs_Actual"] = model["Revenue_YTD"] - model["Budget_YTD"]
    return model


def fmt_eur(v):
    return f"€{v:,.0f}"


def fmt_pct(v):
    return f"{v * 100:.1f}%"


firebase_ok, firebase_msg = init_firebase()

with st.sidebar:
    st.markdown("### 🏍️ Sportech IB")
    st.caption("Nueva arquitectura: 3 inputs + configuración dinámica de marcas")
    if firebase_ok:
        st.success(firebase_msg)
    else:
        st.error(firebase_msg)

    up_sales = st.file_uploader("INPUT (Monthly) Sales", type=["xlsx"], key="sales")
    up_stock = st.file_uploader("INPUT (Monthly) Stock", type=["xlsx"], key="stock")
    up_margin = st.file_uploader("INPUT (Annual) MARGIN LY", type=["xlsx"], key="margin")

    if st.button("Guardar INPUTS en Firebase", disabled=not firebase_ok, use_container_width=True):
        try:
            if up_sales:
                save_df_to_firebase("datasets/monthly_sales", validate_dataset(read_sheet(up_sales, "INPUT (Monthly) Sales"), "sales", "INPUT (Monthly) Sales"))
            if up_stock:
                save_df_to_firebase("datasets/monthly_stock", validate_dataset(read_sheet(up_stock, "INPUT (Monthly) Stock"), "stock", "INPUT (Monthly) Stock"))
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
section = st.sidebar.radio("Section", ["Brand Config", "Overview", "Margin", "Vertical · 2 WHEELS", "Vertical · FREE TIME", "Vertical · OUTDOOR TECH"])

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
            incoming = pd.read_csv(csv_up)
            valid_cfg = validate_brand_config_csv(incoming, set(brand_cfg["BrandKey"]))
            save_df_to_firebase("datasets/brand_configuration", valid_cfg)
            st.success("CSV validado y guardado.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    edited = st.data_editor(
        brand_cfg[["Brand", "Short Name", "Status", "Family", "Annual Budget", "Expected Margin %", *MONTH_BUDGET_COLS]],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS),
            "Family": st.column_config.SelectboxColumn(options=FAMILY_OPTIONS),
        },
    )
    if st.button("Guardar configuración", use_container_width=True):
        out = edited.copy()
        out["BrandKey"] = out["Brand"].apply(_normalize_brand)
        save_df_to_firebase("datasets/brand_configuration", out)
        st.success("Configuración guardada")

    st.stop()

model = prepare_model(sales_df, stock_df, margin_ly_df, brand_cfg, current_month)

if section == "Overview":
    st.title(f"📊 Overview · {MONTHS_ES[current_month]}")
    total_rev = model["Revenue_YTD"].sum()
    total_mg = model["Margin_EUR_YTD"].sum()
    total_budget = model["Budget_YTD"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue YTD", fmt_eur(total_rev))
    c2.metric("Margin € YTD", fmt_eur(total_mg))
    c3.metric("Margin % YTD", fmt_pct(total_mg / total_rev if total_rev else 0))
    c4.metric("Budget Attainment", fmt_pct(total_rev / total_budget if total_budget else 0))

    vert = model.groupby("Family", as_index=False).agg(Revenue=("Revenue_YTD", "sum"), Margin=("Margin_EUR_YTD", "sum"))
    fig = px.bar(vert, x="Family", y="Revenue", color="Family", title="Revenue YTD por Vertical")
    st.plotly_chart(fig, use_container_width=True)

elif section == "Margin":
    st.title(f"📈 Margin · {MONTHS_ES[current_month]}")
    table = model[["Brand", "Short Name", "Status", "Family", "Revenue_YTD", "Margin_EUR_YTD", "Margin_PCT_YTD", "Expected Margin %", "Stock", "LY_Rev", "LY_MgEur"]].copy()
    st.dataframe(table, use_container_width=True)

else:
    vertical = section.split("·", 1)[1].strip()
    st.title(f"{vertical} · {MONTHS_ES[current_month]}")
    sub = model[model["Family"].str.upper() == vertical].copy()
    if sub.empty:
        st.warning("No hay marcas configuradas para este vertical.")
    else:
        k1, k2, k3 = st.columns(3)
        k1.metric("Revenue YTD", fmt_eur(sub["Revenue_YTD"].sum()))
        k2.metric("Budget YTD", fmt_eur(sub["Budget_YTD"].sum()))
        k3.metric("Expected Margin %", fmt_pct(np.average(sub["Expected Margin %"], weights=np.maximum(sub["Annual Budget"], 1))))

        by_brand = sub.sort_values("Revenue_YTD", ascending=False)
        fig = go.Figure()
        fig.add_bar(x=by_brand["Short Name"], y=by_brand["Revenue_YTD"], name="Revenue YTD")
        fig.add_bar(x=by_brand["Short Name"], y=by_brand["Budget_YTD"], name="Budget YTD")
        fig.update_layout(barmode="group")
        st.plotly_chart(fig, use_container_width=True)
