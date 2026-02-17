import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
from io import BytesIO
from urllib.parse import urlparse
import warnings
warnings.filterwarnings('ignore')

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sportech IB · Dashboard",
    page_icon="🏍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap');

:root {
    --bg:       #0a0c10;
    --surface:  #12151c;
    --card:     #1a1f2b;
    --border:   #252d3d;
    --accent:   #e8ff00;
    --accent2:  #00e5ff;
    --danger:   #ff4757;
    --success:  #2ed573;
    --muted:    #5a6378;
    --text:     #d4dbe8;
    --text-dim: #8896ab;
}

html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
    color: var(--text);
    font-family: 'Syne', sans-serif;
}

[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .block-container { padding-top: 2rem; }

h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }

/* Metric cards */
.metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 12px;
    transition: border-color 0.2s;
}
.metric-card:hover { border-color: var(--accent); }
.metric-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-dim);
    margin-bottom: 6px;
}
.metric-value {
    font-family: 'DM Mono', monospace;
    font-size: 28px;
    font-weight: 500;
    color: var(--text);
    line-height: 1;
}
.metric-delta {
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    margin-top: 6px;
}
.delta-up   { color: var(--success); }
.delta-down { color: var(--danger); }
.delta-neu  { color: var(--text-dim); }

/* Section headers */
.section-header {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent);
    padding: 12px 0 8px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 16px;
}

/* Tag pill */
.tag {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.tag-2w  { background: #1a2a4a; color: #7eb8ff; border: 1px solid #2a4a7a; }
.tag-ft  { background: #1a3a1a; color: #5de85d; border: 1px solid #2a5a2a; }
.tag-ot  { background: #3a1a3a; color: #e87de8; border: 1px solid #5a2a5a; }
.tag-tot { background: #2a2a1a; color: var(--accent);  border: 1px solid #4a4a2a; }

/* Sidebar nav */
.nav-item {
    padding: 10px 14px;
    border-radius: 8px;
    margin: 3px 0;
    cursor: pointer;
    font-weight: 600;
    font-size: 13px;
    transition: all 0.15s;
}

/* Plotly chart bg */
.js-plotly-plot .plotly { background: transparent !important; }

/* Streamlit overrides */
div[data-testid="stMetric"] {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
}
div[data-testid="stMetricValue"] {
    font-family: 'DM Mono', monospace !important;
    font-size: 22px !important;
}
[data-testid="stSelectbox"] label,
[data-testid="stRadio"] label { color: var(--text-dim) !important; font-size: 12px !important; }

.stDataFrame { border-radius: 10px; overflow: hidden; }
thead tr th { background: var(--card) !important; }

hr { border-color: var(--border); }
</style>
""", unsafe_allow_html=True)

# ── Data loading + Firebase ───────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, db


def _normalize_col(col):
    return str(col).strip().lower().replace(' ', '_')


def _normalize_vertical(value):
    key = _normalize_col(value)
    aliases = {
        '2_wheels': '2 WHEELS',
        '2wheel': '2 WHEELS',
        '2_wheel': '2 WHEELS',
        'free_time': 'FREE TIME',
        'freetime': 'FREE TIME',
        'outdoor_tech': 'OUTDOOR TECH',
        'outdoor': 'OUTDOOR TECH',
        'varios': 'VARIOS',
    }
    return aliases.get(key, str(value).strip().upper() if pd.notna(value) else '—')


def _normalize_brand(value):
    if pd.isna(value):
        return ''
    return str(value).strip().upper()


def _to_records(df: pd.DataFrame):
    clean = df.copy()
    clean = clean.replace({np.nan: None})
    return clean.to_dict(orient='records')


def _to_firebase_payload(df: pd.DataFrame):
    """Serializa DataFrames evitando usar nombres de columna como claves JSON.

    Firebase Realtime Database no permite ciertos caracteres en claves
    (., #, $, [, ], /). Varias columnas del Excel los incluyen.
    """
    clean = df.copy().replace({np.nan: None})
    return {
        '__format__': 'table_v1',
        'columns': [str(c) for c in clean.columns],
        'rows': clean.values.tolist(),
    }


def _to_plain_dict(value):
    if isinstance(value, dict):
        return {k: _to_plain_dict(v) for k, v in value.items()}
    if hasattr(value, 'items'):
        return {k: _to_plain_dict(v) for k, v in value.items()}
    return value


def _normalize_database_url(value):
    if not isinstance(value, str):
        return None

    candidate = value.strip().strip('"').strip("'")
    if not candidate:
        return None

    # Error común: URL duplicada (https://https://...)
    duplicate_prefix = 'https://https://'
    if candidate.startswith(duplicate_prefix):
        candidate = 'https://' + candidate[len(duplicate_prefix):]

    if not candidate.startswith(('http://', 'https://')):
        candidate = f'https://{candidate}'

    parsed = urlparse(candidate)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None

    # Evita URLs inválidas como "https" o "https://https" (host='https').
    if parsed.netloc.lower() == 'https':
        return None

    return f'{parsed.scheme}://{parsed.netloc}'


def _extract_firebase_config():
    secrets = _to_plain_dict(st.secrets)
    firebase_section = secrets.get('firebase', {}) if isinstance(secrets, dict) else {}

    merged = {}
    if isinstance(secrets, dict):
        merged.update(secrets)
    if isinstance(firebase_section, dict):
        merged.update(firebase_section)

    db_url = (
        merged.get('databaseURL')
        or merged.get('database_url')
        or merged.get('firebase_database_url')
        or merged.get('FIREBASE_DATABASE_URL')
    )
    db_url = _normalize_database_url(db_url)

    sa = merged.get('service_account') or merged.get('firebase_service_account')
    if isinstance(sa, str):
        try:
            import json
            sa = json.loads(sa)
        except Exception:
            sa = None

    if not isinstance(sa, dict):
        sa = {
            k: merged.get(k) for k in [
                'type', 'project_id', 'private_key_id', 'private_key', 'client_email',
                'client_id', 'auth_uri', 'token_uri', 'auth_provider_x509_cert_url', 'client_x509_cert_url'
            ] if merged.get(k) is not None
        }

    if isinstance(sa, dict) and isinstance(sa.get('private_key'), str):
        sa['private_key'] = sa['private_key'].replace('\\n', '\n')

    return sa if isinstance(sa, dict) else {}, db_url, merged


@st.cache_resource
def init_firebase():
    try:
        cred_info, database_url, merged = _extract_firebase_config()
        raw_database_url = (
            merged.get('databaseURL')
            or merged.get('database_url')
            or merged.get('firebase_database_url')
            or merged.get('FIREBASE_DATABASE_URL')
        )

        if firebase_admin._apps:
            app = firebase_admin.get_app()
            existing_url = _normalize_database_url(
                app.options.get('databaseURL') or app.options.get('database_url')
            )

            # Si el app cargado está corrupto (ej. host='https') o desincronizado,
            # lo recreamos usando la config actual de st.secrets.
            if (not existing_url) or (database_url and existing_url != database_url):
                firebase_admin.delete_app(app)
            else:
                return True, 'Firebase conectado.'

        missing = []
        if not database_url:
            missing.append('databaseURL')
        required_sa_keys = ['project_id', 'private_key', 'client_email']
        if not all(cred_info.get(k) for k in required_sa_keys):
            missing.append('service_account')

        if missing:
            available = ', '.join(sorted([str(k) for k in merged.keys()])) if isinstance(merged, dict) else 'sin claves'
            db_hint = ''
            if raw_database_url:
                db_hint = (
                    f' Valor recibido para databaseURL: {raw_database_url!r}. '
                    'Debe ser una URL válida, por ejemplo: '
                    'https://TU-PROYECTO-default-rtdb.europe-west1.firebasedatabase.app'
                )
            return False, (
                'Faltan credenciales de Firebase en st.secrets. '
                f'Campos faltantes: {", ".join(missing)}. '
                f'Claves detectadas: {available}.{db_hint}'
            )

        cred = credentials.Certificate(cred_info)
        firebase_admin.initialize_app(cred, {'databaseURL': database_url})
        return True, 'Firebase conectado.'
    except Exception as e:
        return False, f'Error Firebase: {e}'


def save_df_to_firebase(path: str, df: pd.DataFrame):
    ref = db.reference(path)
    ref.set(_to_firebase_payload(df))


def load_df_from_firebase(path: str) -> pd.DataFrame:
    def _coerce_rows(rows):
        """Normaliza filas para evitar errores con estructuras mixtas en Firebase."""
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, (list, tuple)):
            return []

        normalized = []
        for row in rows:
            if isinstance(row, dict):
                normalized.append(row)
                continue
            if isinstance(row, (list, tuple)):
                normalized.append(list(row))
                continue
            if hasattr(row, 'items'):
                normalized.append(dict(row.items()))
                continue

            # Último recurso para filas sueltas (str/int/float/etc.)
            normalized.append([row])
        return normalized

    ref = db.reference(path)
    raw = ref.get()
    if not raw:
        return pd.DataFrame()

    # Nuevo formato robusto frente a claves inválidas en Firebase.
    if isinstance(raw, dict) and raw.get('__format__') == 'table_v1':
        cols = raw.get('columns') or []
        rows = _coerce_rows(raw.get('rows') or [])

        if cols:
            normalized_dict_rows = []
            for row in rows:
                if isinstance(row, dict):
                    normalized_dict_rows.append({c: row.get(c) for c in cols})
                    continue
                row_list = list(row) if isinstance(row, (list, tuple)) else [row]
                normalized_dict_rows.append({c: (row_list[i] if i < len(row_list) else None) for i, c in enumerate(cols)})
            return pd.DataFrame(normalized_dict_rows, columns=cols)

        if rows and isinstance(rows[0], dict):
            return pd.DataFrame(rows)

        if cols:
            normalized_rows = []
            for row in rows:
                row_list = row if isinstance(row, list) else [row]
                if len(row_list) < len(cols):
                    row_list = row_list + [None] * (len(cols) - len(row_list))
                elif len(row_list) > len(cols):
                    row_list = row_list[:len(cols)]
                normalized_rows.append(row_list)
            return pd.DataFrame(normalized_rows, columns=cols)

        return pd.DataFrame(rows)

    # Compatibilidad con datasets existentes guardados como lista de registros.
    if isinstance(raw, dict):
        raw = list(raw.values())

    return pd.DataFrame(_coerce_rows(raw))


def read_sheet(uploaded_file, sheet_name):
    bio = BytesIO(uploaded_file.read())
    uploaded_file.seek(0)
    xls = pd.ExcelFile(bio)
    if sheet_name in xls.sheet_names:
        return pd.read_excel(bio, sheet_name=sheet_name)
    return pd.read_excel(bio, sheet_name=0)


def build_margins_table(df_estado, df_stock, df_margin_ly, df_budget):
    base = df_estado.copy() if not df_estado.empty else pd.DataFrame(columns=['Marca', 'Vertical'])
    if 'Marca' not in base.columns:
        base['Marca'] = ''
    if 'Vertical' not in base.columns:
        base['Vertical'] = '—'

    base['Marca'] = base['Marca'].astype(str).str.strip()
    base['BrandKey'] = base['Marca'].apply(_normalize_brand)
    base['Vertical'] = base['Vertical'].apply(_normalize_vertical)

    for c in ['Budget_Rev', 'Budget_Mg%', 'Budget_MgEur', 'LY_Rev', 'LY_MgEur', 'LY_Mg%']:
        if c not in base.columns:
            base[c] = 0

    if not df_stock.empty:
        stock = df_stock.copy()
        stock.columns = [str(c).strip() for c in stock.columns]
        if 'Marca' not in stock.columns:
            stock.rename(columns={stock.columns[0]: 'Marca'}, inplace=True)
        if 'Stock' not in stock.columns:
            stock.rename(columns={stock.columns[1]: 'Stock'}, inplace=True)
        stock['BrandKey'] = stock['Marca'].apply(_normalize_brand)
        stock = stock.groupby('BrandKey', as_index=False)['Stock'].sum()
        base = base.merge(stock, on='BrandKey', how='left')
    if 'Stock' not in base.columns:
        base['Stock'] = 0

    if not df_margin_ly.empty:
        ly = df_margin_ly.copy()
        ly.columns = [str(c).strip() for c in ly.columns]
        if 'Marca' not in ly.columns:
            ly.rename(columns={ly.columns[0]: 'Marca'}, inplace=True)
        rename_map = {}
        for col in ly.columns:
            n = _normalize_col(col)
            if 'ly_rev' in n or n in ('revenue_ly', 'ly_revenue'):
                rename_map[col] = 'LY_Rev'
            if 'ly_mgeur' in n or 'ly_mg_eur' in n:
                rename_map[col] = 'LY_MgEur'
            if 'ly_mg' in n and '%' in col:
                rename_map[col] = 'LY_Mg%'
        ly = ly.rename(columns=rename_map)
        ly['BrandKey'] = ly['Marca'].apply(_normalize_brand)
        for c in ['LY_Rev', 'LY_MgEur', 'LY_Mg%']:
            if c not in ly.columns:
                ly[c] = 0
        ly = ly[['BrandKey', 'LY_Rev', 'LY_MgEur', 'LY_Mg%']]
        base = base.drop(columns=['LY_Rev', 'LY_MgEur', 'LY_Mg%'], errors='ignore').merge(ly, on='BrandKey', how='left')

    if not df_budget.empty:
        budget = df_budget.copy()
        budget.columns = [str(c).strip() for c in budget.columns]
        if 'Marca' not in budget.columns:
            budget.rename(columns={budget.columns[0]: 'Marca'}, inplace=True)

        month_cols = [
            c for c in [
                'Venta Enero', 'Venta Febrero', 'Venta Marzo', 'Venta Abril',
                'Venta Mayo', 'Venta Junio', 'Venta Julio', 'Venta Agosto',
                'Venta Septiembre', 'Venta Octubre', 'Venta Noviembre', 'Venta Diciembre'
            ] if c in budget.columns
        ]
        if month_cols:
            budget['Budget_Rev'] = budget[month_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1)

        if 'Budget_Rev' not in budget.columns:
            budget['Budget_Rev'] = 0

        mg_pct_col = next(
            (c for c in budget.columns if 'budget' in _normalize_col(c) and ('mg%' in _normalize_col(c) or 'margen' in _normalize_col(c))),
            None
        )
        mg_eur_col = next(
            (c for c in budget.columns if 'budget' in _normalize_col(c) and ('mgeur' in _normalize_col(c) or 'mg_eur' in _normalize_col(c))),
            None
        )

        budget['Budget_Rev'] = pd.to_numeric(budget['Budget_Rev'], errors='coerce').fillna(0)
        if mg_pct_col:
            budget['Budget_Mg%'] = pd.to_numeric(budget[mg_pct_col], errors='coerce').fillna(0)
        if mg_eur_col:
            budget['Budget_MgEur'] = pd.to_numeric(budget[mg_eur_col], errors='coerce').fillna(0)

        if 'Budget_MgEur' not in budget.columns:
            budget_mg_pct = budget['Budget_Mg%'] if 'Budget_Mg%' in budget.columns else pd.Series(0, index=budget.index)
            budget['Budget_MgEur'] = budget['Budget_Rev'] * pd.to_numeric(budget_mg_pct, errors='coerce').fillna(0)
        if 'Budget_Mg%' not in budget.columns:
            budget['Budget_Mg%'] = np.where(
                budget['Budget_Rev'] != 0,
                budget['Budget_MgEur'] / budget['Budget_Rev'],
                0,
            )

        budget['BrandKey'] = budget['Marca'].apply(_normalize_brand)
        budget = budget.groupby('BrandKey', as_index=False)[['Budget_Rev', 'Budget_Mg%', 'Budget_MgEur']].sum()
        budget['Budget_Mg%'] = np.where(
            budget['Budget_Rev'] != 0,
            budget['Budget_MgEur'] / budget['Budget_Rev'],
            0,
        )

        base = base.drop(columns=['Budget_Rev', 'Budget_Mg%', 'Budget_MgEur'], errors='ignore').merge(
            budget, on='BrandKey', how='left'
        )

    for c in ['Stock', 'Budget_Rev', 'Budget_Mg%', 'Budget_MgEur', 'LY_Rev', 'LY_MgEur', 'LY_Mg%']:
        base[c] = pd.to_numeric(base[c], errors='coerce').fillna(0)

    base = base.drop(columns=['BrandKey'], errors='ignore')

    aggs = []
    for v in ['2 WHEELS', 'FREE TIME', 'OUTDOOR TECH', 'VARIOS']:
        sub = base[base['Vertical'].astype(str).str.upper() == v]
        if len(sub) == 0:
            continue
        aggs.append({
            'Marca': v,
            'Vertical': v,
            'Stock': sub['Stock'].sum(),
            'Budget_Rev': sub['Budget_Rev'].sum(),
            'Budget_Mg%': (sub['Budget_MgEur'].sum() / sub['Budget_Rev'].sum()) if sub['Budget_Rev'].sum() else 0,
            'Budget_MgEur': sub['Budget_MgEur'].sum(),
            'LY_Rev': sub['LY_Rev'].sum(),
            'LY_MgEur': sub['LY_MgEur'].sum(),
            'LY_Mg%': (sub['LY_MgEur'].sum() / sub['LY_Rev'].sum()) if sub['LY_Rev'].sum() else 0,
        })

    total = {
        'Marca': 'TOTAL',
        'Vertical': 'TOTAL',
        'Stock': base['Stock'].sum(),
        'Budget_Rev': base['Budget_Rev'].sum(),
        'Budget_Mg%': (base['Budget_MgEur'].sum() / base['Budget_Rev'].sum()) if base['Budget_Rev'].sum() else 0,
        'Budget_MgEur': base['Budget_MgEur'].sum(),
        'LY_Rev': base['LY_Rev'].sum(),
        'LY_MgEur': base['LY_MgEur'].sum(),
        'LY_Mg%': (base['LY_MgEur'].sum() / base['LY_Rev'].sum()) if base['LY_Rev'].sum() else 0,
    }

    return pd.concat([base, pd.DataFrame(aggs + [total])], ignore_index=True)


def load_data_from_firebase():
    df_ventas = load_df_from_firebase('datasets/mensual_ventas')
    df_stock = load_df_from_firebase('datasets/mensual_stock')
    df_margin_ly = load_df_from_firebase('datasets/anual_margin_ly')
    df_budget_raw = load_df_from_firebase('datasets/anual_budget')
    df_estado = load_df_from_firebase('datasets/anual_estado_marcas')
    df_familias = load_df_from_firebase('datasets/anual_familias')

    if df_ventas.empty or df_familias.empty:
        return None

    if 'Margen_Euros' not in df_ventas.columns and {'Importe Neto', 'CR3: % Margen s/Venta'}.issubset(df_ventas.columns):
        df_ventas['Margen_Euros'] = df_ventas['Importe Neto'] * df_ventas['CR3: % Margen s/Venta'] / 100

    df_ventas_full = df_ventas.merge(
        df_familias[['Nombre', 'Familia', 'Columna1']],
        left_on='Clave 1', right_on='Familia', how='left'
    )

    brand_monthly = df_ventas_full.groupby(['Nombre', 'Mes Factura']).agg(
        Revenue=('Importe Neto', 'sum'), Margen_Euros=('Margen_Euros', 'sum')
    ).reset_index()
    brand_monthly['Margen_Pct'] = np.where(
        brand_monthly['Revenue'] != 0,
        brand_monthly['Margen_Euros'] / brand_monthly['Revenue'],
        0
    )

    vertical_monthly = df_ventas_full.groupby(['Columna1', 'Mes Factura']).agg(
        Revenue=('Importe Neto', 'sum'), Margen_Euros=('Margen_Euros', 'sum')
    ).reset_index()
    vertical_monthly['Margen_Pct'] = np.where(
        vertical_monthly['Revenue'] != 0,
        vertical_monthly['Margen_Euros'] / vertical_monthly['Revenue'],
        0
    )

    month_budget_cols = {
        1:'Venta Enero',2:'Venta Febrero',3:'Venta Marzo',4:'Venta Abril',
        5:'Venta Mayo',6:'Venta Junio',7:'Venta Julio',8:'Venta Agosto',
        9:'Venta Septiembre',10:'Venta Octubre',11:'Venta Noviembre',12:'Venta Diciembre'
    }
    budget_monthly = {}
    for m, col in month_budget_cols.items():
        budget_monthly[m] = pd.to_numeric(df_budget_raw[col], errors='coerce').fillna(0).sum() if col in df_budget_raw.columns else 0

    df_margins = build_margins_table(df_estado, df_stock, df_margin_ly, df_budget_raw)

    return {
        'ventas': df_ventas,
        'ventas_full': df_ventas_full,
        'familias': df_familias,
        'budget_raw': df_budget_raw,
        'margins': df_margins,
        'brand_monthly': brand_monthly,
        'vertical_monthly': vertical_monthly,
        'budget_monthly': budget_monthly,
    }

# ── Chart helpers ───────────────────────────────────────────────────────────────
CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font_family='Syne',
    font_color='#d4dbe8',
    margin=dict(l=0, r=0, t=32, b=0),
)

DEFAULT_LEGEND = dict(
    bgcolor='rgba(26,31,43,0.8)',
    bordercolor='#252d3d',
    borderwidth=1,
    font_size=11,
)

VERTICAL_COLORS = {
    '2 WHEELS':    '#7eb8ff',
    'FREE TIME':   '#5de85d',
    'OUTDOOR TECH':'#e87de8',
    'VARIOS':      '#f5a623',
    'TOTAL':       '#e8ff00',
    '—':           '#8896ab',
}

def fmt_eur(v, decimals=0):
    if abs(v) >= 1_000_000:
        return f"€{v/1_000_000:.1f}M"
    elif abs(v) >= 1_000:
        return f"€{v/1_000:.0f}K"
    return f"€{v:,.{decimals}f}"

def fmt_pct(v):
    return f"{v*100:.1f}%"

def metric_card(label, value, delta=None, delta_label="vs LY"):
    delta_html = ""
    if delta is not None:
        if isinstance(delta, float) and abs(delta) < 10:
            dval = f"{delta*100:+.1f}pp" if "%" in delta_label else f"{delta:+.1f}%"
        else:
            dval = fmt_eur(delta) if delta > 100 else f"{delta:+.0f}"
        cls = "delta-up" if (delta if isinstance(delta, (int,float)) else 0) >= 0 else "delta-down"
        delta_html = f'<div class="metric-delta {cls}">{dval} {delta_label}</div>'
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {delta_html}
    </div>"""


# ── Sidebar ─────────────────────────────────────────────────────────────────────
firebase_ok, firebase_msg = init_firebase()

with st.sidebar:
    st.markdown("### 🏍️ **Sportech IB**")
    st.markdown('<div style="color:#5a6378;font-size:11px;margin-bottom:20px;">Monthly Performance Dashboard</div>', unsafe_allow_html=True)

    if firebase_ok:
        st.success("Firebase conectado")
    else:
        st.error(firebase_msg)

    st.markdown("#### 📤 Carga mensual/anual (Excel)")
    up_ventas = st.file_uploader("INPUT (Mensual) Ventas", type=["xlsx"], key='u_ventas')
    up_stock = st.file_uploader("INPUT (Mensual) Stock", type=["xlsx"], key='u_stock')
    up_margin_ly = st.file_uploader("INPUT (Anual) MARGIN LY", type=["xlsx"], key='u_margin')

    if st.button("Guardar Excel en Firebase", width='stretch', disabled=not firebase_ok):
        try:
            if up_ventas is not None:
                save_df_to_firebase('datasets/mensual_ventas', read_sheet(up_ventas, 'INPUT (Mensual) Ventas'))
            if up_stock is not None:
                save_df_to_firebase('datasets/mensual_stock', read_sheet(up_stock, 'INPUT (Mensual) Stock'))
            if up_margin_ly is not None:
                save_df_to_firebase('datasets/anual_margin_ly', read_sheet(up_margin_ly, 'INPUT (Anual) MARGIN LY'))
            st.success('Datos de Excel guardados correctamente.')
        except Exception as e:
            st.error(f'No se pudo guardar: {e}')

    st.markdown('---')
    page = st.radio(
        "Sección",
        ["⚙️ Configuración de Datos", "📊 Overview · RECAP", "📈 MARGINS · Marcas", "🏍️ Vertical 2 Wheels",
         "🌲 Vertical Free Time", "📡 Vertical Outdoor Tech"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.markdown('<div style="color:#5a6378;font-size:10px;">Datos en Firebase Realtime Database</div>', unsafe_allow_html=True)

# ── Configuración editable (Firebase) ─────────────────────────────────────────
if page == "⚙️ Configuración de Datos":
    st.title("⚙️ Configuración de datos anuales")
    if not firebase_ok:
        st.stop()

    st.caption("Edita y guarda en Firebase: Budget, Estado Marcas y Familias.")

    tabs = st.tabs(["INPUT (Anual) Budget", "INPUT (Anual) Estado Marcas", "INPUT (Anual) Familias"])
    table_map = [
        ('datasets/anual_budget', 'budget_editor'),
        ('datasets/anual_estado_marcas', 'estado_editor'),
        ('datasets/anual_familias', 'familias_editor'),
    ]

    for tab, (path, key) in zip(tabs, table_map):
        with tab:
            df = load_df_from_firebase(path)
            edited = st.data_editor(df, num_rows='dynamic', width='stretch', key=key)
            c1, c2 = st.columns([1, 3])
            with c1:
                if st.button("Guardar", key=f"save_{key}", width='stretch'):
                    save_df_to_firebase(path, edited)
                    st.success("Guardado en Firebase")
            with c2:
                up = st.file_uploader("Cargar desde Excel (opcional)", type=['xlsx'], key=f"u_{key}")
                if up is not None and st.button("Importar Excel", key=f"import_{key}"):
                    name = {
                        'datasets/anual_budget': 'INPUT (Anual) Budget',
                        'datasets/anual_estado_marcas': 'INPUT (Anual) Estado Marcas',
                        'datasets/anual_familias': 'INPUT (Anual) Familias',
                    }[path]
                    new_df = read_sheet(up, name)
                    save_df_to_firebase(path, new_df)
                    st.success("Importado y guardado")
    st.stop()

# ── Load data ───────────────────────────────────────────────────────────────────
if not firebase_ok:
    st.error(firebase_msg)
    st.stop()

data = load_data_from_firebase()
if data is None:
    st.markdown("""
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                height:60vh;gap:16px;">
        <div style="font-size:64px;">🏍️</div>
        <div style="font-size:28px;font-weight:800;color:#e8ff00;">Sportech IB Dashboard</div>
        <div style="color:#5a6378;font-size:14px;">Sube <strong>INPUT (Mensual) Ventas</strong> y configura <strong>INPUT (Anual) Familias</strong> para comenzar.</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

df_margins      = data['margins']
brand_monthly   = data['brand_monthly']
vert_monthly    = data['vertical_monthly']
budget_monthly  = data['budget_monthly']
df_ventas       = data['ventas']
df_ventas_full  = data['ventas_full']
df_budget_raw   = data['budget_raw']

# Computed totals for current month
MONTHS_ES = {1:'Enero',2:'Febrero',3:'Marzo',4:'Abril',5:'Mayo',6:'Junio',
             7:'Julio',8:'Agosto',9:'Septiembre',10:'Octubre',11:'Noviembre',12:'Diciembre'}

avail_months = sorted(brand_monthly['Mes Factura'].unique())
current_month = avail_months[-1] if avail_months else 1
current_month_name = MONTHS_ES.get(current_month, str(current_month))

total_rev   = df_ventas_full['Importe Neto'].sum()
total_mg_eur= df_ventas_full['Margen_Euros'].sum()
total_mg_pct= total_mg_eur / total_rev if total_rev else 0
total_stock = df_margins['Stock'].sum()
budget_enero= budget_monthly.get(1, 0)


# ════════════════════════════════════════════════════════════════════════════════
# PAGE 1: OVERVIEW · RECAP
# ════════════════════════════════════════════════════════════════════════════════
if page == "📊 Overview · RECAP":

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px;">
        <h1 style="margin:0;font-size:32px;">RECAP</h1>
        <span style="color:#5a6378;font-size:14px;">Resumen Global · {current_month_name} 2026</span>
    </div>""", unsafe_allow_html=True)

    # ── KPI row ──
    c1, c2, c3, c4, c5 = st.columns(5)
    ly_total = df_margins.loc[df_margins['Marca']=='TOTAL','LY_Rev'].values
    ly_rev   = ly_total[0] if len(ly_total) > 0 else 0
    ly_mg    = df_margins.loc[df_margins['Marca']=='TOTAL','LY_MgEur'].values
    ly_mg_eur= ly_mg[0] if len(ly_mg) > 0 else 0
    ly_mg_pct= ly_mg_eur / ly_rev if ly_rev else 0
    budget_tot= df_margins.loc[df_margins['Marca']=='TOTAL','Budget_Rev'].values
    budget_rev= float(budget_tot[0]) if len(budget_tot) > 0 else 0

    with c1:
        st.metric("Revenue Enero", fmt_eur(total_rev),
                  f"{(total_rev/ly_rev*12 - 1)*100:+.1f}% vs LY (anualiz.)" if ly_rev else "—")
    with c2:
        st.metric("Margen €", fmt_eur(total_mg_eur),
                  f"{(total_mg_pct - ly_mg_pct)*100:+.1f}pp vs LY" if ly_rev else "—")
    with c3:
        st.metric("Margen %", fmt_pct(total_mg_pct),
                  f"Budget: {fmt_pct(df_margins.loc[df_margins['Marca']=='TOTAL','Budget_Mg%'].values[0] if len(df_margins.loc[df_margins['Marca']=='TOTAL']) else 0)}")
    with c4:
        st.metric("Stock", fmt_eur(total_stock))
    with c5:
        bud_ene = budget_monthly.get(1, 0)
        cumpl = total_rev / bud_ene if bud_ene else 0
        st.metric("Cumpl. Budget", fmt_pct(cumpl),
                  f"Budget: {fmt_eur(bud_ene)}")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Revenue by vertical (bar) + Margin % (scatter) ──
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown('<div class="section-header">Revenue por Vertical</div>', unsafe_allow_html=True)

        verticals_summary = vert_monthly.groupby('Columna1').agg(
            Revenue=('Revenue','sum'), Margen_Euros=('Margen_Euros','sum')
        ).reset_index().dropna()
        verticals_summary['Margen_Pct'] = verticals_summary['Margen_Euros'] / verticals_summary['Revenue']

        # Add budget per vertical using margins data
        v_budget = df_margins[df_margins['Marca'].isin(['2 WHEELS','FREE TIME','OUTDOOR TECH'])][['Marca','Budget_Rev']].copy()
        v_budget.columns = ['Columna1','Budget']
        v_budget['Columna1'] = v_budget['Columna1'].str.upper().str.strip()
        verticals_summary['Columna1_upper'] = verticals_summary['Columna1'].str.upper().str.strip()

        fig = go.Figure()
        for _, row in verticals_summary.iterrows():
            vname = str(row['Columna1'])
            color = VERTICAL_COLORS.get(vname.upper(), '#7eb8ff')
            bud_match = v_budget[v_budget['Columna1']==vname.upper()]
            bud_val = float(bud_match['Budget'].iloc[0]) if len(bud_match) else 0
            monthly_budget = bud_val / 12

            fig.add_trace(go.Bar(
                name=vname,
                x=[vname],
                y=[row['Revenue']],
                marker_color=color,
                marker_line_width=0,
                text=[fmt_eur(row['Revenue'])],
                textposition='outside',
                textfont=dict(size=11, color=color),
                hovertemplate=f"<b>{vname}</b><br>Revenue: €%{{y:,.0f}}<br>Margen: {fmt_pct(row['Margen_Pct'])}<extra></extra>",
            ))
            if monthly_budget > 0:
                fig.add_shape(type='line',
                    x0=-0.4+list(verticals_summary['Columna1']).index(vname),
                    x1=0.4+list(verticals_summary['Columna1']).index(vname),
                    y0=monthly_budget, y1=monthly_budget,
                    line=dict(color='#e8ff00', width=2, dash='dot'),
                )

        fig.update_layout(**CHART_LAYOUT, height=320, showlegend=False,
                          yaxis_title=None, xaxis_title=None,
                          bargap=0.3)
        fig.add_annotation(x=0.98, y=0.96, xref='paper', yref='paper',
                           text="— Budget mensual", font=dict(size=10, color='#e8ff00'),
                           showarrow=False, align='right')
        st.plotly_chart(fig, width='stretch')

    with col_right:
        st.markdown('<div class="section-header">Margen % por Vertical</div>', unsafe_allow_html=True)

        fig2 = go.Figure()
        for _, row in verticals_summary.iterrows():
            vname = str(row['Columna1'])
            color = VERTICAL_COLORS.get(vname.upper(), '#7eb8ff')
            fig2.add_trace(go.Bar(
                name=vname,
                x=[fmt_pct(row['Margen_Pct'])],
                y=[vname],
                orientation='h',
                marker_color=color,
                marker_line_width=0,
                text=[fmt_pct(row['Margen_Pct'])],
                textposition='outside',
                textfont=dict(size=11, color=color),
                hovertemplate=f"<b>{vname}</b><br>Margen: {fmt_pct(row['Margen_Pct'])}<extra></extra>",
            ))

        fig2.update_layout(**CHART_LAYOUT, height=320, showlegend=False, bargap=0.35)
        fig2.update_xaxes(tickformat='.0%', gridcolor='#252d3d', linecolor='#252d3d')
        fig2.update_yaxes(gridcolor='#252d3d', linecolor='#252d3d')
        st.plotly_chart(fig2, width='stretch')

    # ── Budget evolution ──
    st.markdown('<div class="section-header">Budget Mensual 2026 — Distribución</div>', unsafe_allow_html=True)
    months_list = list(MONTHS_ES.values())
    budget_vals = [budget_monthly.get(m, 0) for m in range(1, 13)]
    cum_budget  = np.cumsum(budget_vals)

    fig3 = make_subplots(specs=[[{"secondary_y": True}]])
    fig3.add_trace(go.Bar(
        x=months_list, y=budget_vals,
        marker_color='#252d3d',
        marker_line_color='#3d4b63', marker_line_width=1,
        name='Budget Mensual',
        hovertemplate='%{x}: €%{y:,.0f}<extra></extra>',
    ), secondary_y=False)
    # Mark enero actual
    fig3.add_trace(go.Bar(
        x=[months_list[current_month-1]],
        y=[total_rev],
        marker_color='#e8ff00',
        name='Ventas Real',
        hovertemplate='Real: €%{y:,.0f}<extra></extra>',
    ), secondary_y=False)
    fig3.add_trace(go.Scatter(
        x=months_list, y=cum_budget,
        mode='lines+markers',
        line=dict(color='#00e5ff', width=2),
        marker=dict(size=5, color='#00e5ff'),
        name='Acum. Budget',
        hovertemplate='%{x} Acum: €%{y:,.0f}<extra></extra>',
    ), secondary_y=True)

    fig3.update_layout(**CHART_LAYOUT, height=280, bargap=0.15,
                       legend={**DEFAULT_LEGEND, 'orientation':'h', 'y':1.1, 'x':0})
    fig3.update_yaxes(gridcolor='#252d3d', linecolor='#252d3d', secondary_y=False)
    fig3.update_yaxes(gridcolor='rgba(0,0,0,0)', linecolor='#252d3d', secondary_y=True)
    st.plotly_chart(fig3, width='stretch')

    # ── Top brands table ──
    st.markdown('<div class="section-header">Top Marcas · Enero 2026</div>', unsafe_allow_html=True)
    top_brands = brand_monthly[brand_monthly['Mes Factura']==current_month].copy()
    top_brands = top_brands[top_brands['Nombre'].notna() & (top_brands['Nombre'] != '0 - SIN CLASIFICAR')]
    top_brands = top_brands.sort_values('Revenue', ascending=False).head(15)

    # Merge vertical info
    top_brands = top_brands.merge(
        data['familias'][['Nombre','Columna1']].drop_duplicates(),
        on='Nombre', how='left'
    )

    def render_table(df):
        rows = ""
        for _, r in df.iterrows():
            v = str(r.get('Columna1','—') or '—').upper().strip()
            tag_cls = {'2 WHEELS':'tag-2w','FREE TIME':'tag-ft','OUTDOOR TECH':'tag-ot'}.get(v,'')
            tag_label = {'2 WHEELS':'2W','FREE TIME':'FT','OUTDOOR TECH':'OT'}.get(v,'—')
            mg_color = '#2ed573' if r['Margen_Pct'] > 0.2 else ('#ff4757' if r['Margen_Pct'] < 0 else '#d4dbe8')
            rev_pct = r['Revenue'] / total_rev * 100
            rows += f"""
            <tr style="border-bottom:1px solid #1a1f2b;">
                <td style="padding:8px 12px;font-weight:600;">{r['Nombre']}</td>
                <td style="padding:8px 12px;"><span class="tag {tag_cls}">{tag_label}</span></td>
                <td style="padding:8px 12px;font-family:'DM Mono',monospace;text-align:right;">€{r['Revenue']:>10,.0f}</td>
                <td style="padding:8px 12px;font-family:'DM Mono',monospace;text-align:right;">€{r['Margen_Euros']:>8,.0f}</td>
                <td style="padding:8px 12px;font-family:'DM Mono',monospace;text-align:right;color:{mg_color};">{r['Margen_Pct']*100:.1f}%</td>
                <td style="padding:8px 12px;">
                    <div style="background:#252d3d;border-radius:4px;height:6px;">
                        <div style="background:#e8ff00;border-radius:4px;height:6px;width:{min(rev_pct*3,100):.0f}%;"></div>
                    </div>
                </td>
            </tr>"""
        return f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
                <tr style="background:#12151c;border-bottom:1px solid #252d3d;">
                    <th style="padding:8px 12px;text-align:left;color:#5a6378;font-size:11px;letter-spacing:.1em;text-transform:uppercase;">Marca</th>
                    <th style="padding:8px 12px;text-align:left;color:#5a6378;font-size:11px;">Vert.</th>
                    <th style="padding:8px 12px;text-align:right;color:#5a6378;font-size:11px;">Revenue</th>
                    <th style="padding:8px 12px;text-align:right;color:#5a6378;font-size:11px;">Margen €</th>
                    <th style="padding:8px 12px;text-align:right;color:#5a6378;font-size:11px;">Mg%</th>
                    <th style="padding:8px 12px;text-align:left;color:#5a6378;font-size:11px;">Share</th>
                </tr>
            </thead>
            <tbody style="background:#1a1f2b;">{rows}</tbody>
        </table>"""

    st.markdown(render_table(top_brands), unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# PAGE 2: MARGINS
# ════════════════════════════════════════════════════════════════════════════════
elif page == "📈 MARGINS · Marcas":

    st.markdown("""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px;">
        <h1 style="margin:0;font-size:32px;">MARGINS</h1>
        <span style="color:#5a6378;font-size:14px;">Detalle por Marca · Datos 2026</span>
    </div>""", unsafe_allow_html=True)

    # Filter controls
    fc1, fc2 = st.columns([2, 1])
    with fc1:
        vertical_filter = st.multiselect(
            "Filtrar por Vertical",
            options=['2 WHEELS', 'FREE TIME', 'OUTDOOR TECH', 'VARIOS'],
            default=['2 WHEELS', 'FREE TIME', 'OUTDOOR TECH'],
        )
    with fc2:
        sort_by = st.selectbox("Ordenar por", ["Budget Revenue", "Stock", "LY Revenue", "Margen% Budget"])

    df_fil = df_margins[
        df_margins['Vertical'].isin(vertical_filter) &
        ~df_margins['Marca'].isin(['TOTAL','2 WHEELS','FREE TIME','OUTDOOR TECH','VARIOS',
                                    'SIN CLASIFICAR','NUEVAS MARCAS','0 - SIN CLASIFICAR','—'])
    ].copy()

    sort_map = {"Budget Revenue":"Budget_Rev","Stock":"Stock","LY Revenue":"LY_Rev","Margen% Budget":"Budget_Mg%"}
    df_fil = df_fil.sort_values(sort_map[sort_by], ascending=False)

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("Marcas activas", len(df_fil[df_fil['Budget_Rev'] > 0]))
    with k2: st.metric("Budget total", fmt_eur(df_fil['Budget_Rev'].sum()))
    with k3: st.metric("Stock total", fmt_eur(df_fil['Stock'].sum()))
    with k4: st.metric("Revenue LY total", fmt_eur(df_fil['LY_Rev'].sum()))

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Scatter: Budget vs LY ──
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('<div class="section-header">Budget vs Revenue LY por Marca</div>', unsafe_allow_html=True)
        scatter_df = df_fil[df_fil['Budget_Rev'] > 0].copy()
        scatter_df['color'] = scatter_df['Vertical'].map(VERTICAL_COLORS)

        fig_sc = px.scatter(
            scatter_df,
            x='LY_Rev', y='Budget_Rev',
            size='Stock',
            color='Vertical',
            color_discrete_map=VERTICAL_COLORS,
            hover_name='Marca',
            hover_data={'LY_Rev':':.0f','Budget_Rev':':.0f','Stock':':.0f','Vertical':False},
            size_max=40,
            labels={'LY_Rev':'Revenue LY (€)','Budget_Rev':'Budget 2026 (€)'},
        )
        # Diagonal reference line
        max_val = max(scatter_df['LY_Rev'].max(), scatter_df['Budget_Rev'].max())
        fig_sc.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode='lines', line=dict(color='#252d3d', dash='dot', width=1),
            showlegend=False, hoverinfo='skip'
        ))
        fig_sc.update_layout(**CHART_LAYOUT, height=340)
        st.plotly_chart(fig_sc, width='stretch')

    with col_b:
        st.markdown('<div class="section-header">Margen % Budget vs LY</div>', unsafe_allow_html=True)
        mg_df = df_fil[(df_fil['Budget_Mg%'] != 0) | (df_fil['LY_Mg%'] != 0)].copy()
        mg_df = mg_df[mg_df['Budget_Rev'] > 5000].head(20)

        fig_mg = go.Figure()
        colors = mg_df['Vertical'].map(VERTICAL_COLORS).tolist()
        fig_mg.add_trace(go.Bar(
            name='Margen% LY',
            x=mg_df['Marca'],
            y=mg_df['LY_Mg%'],
            marker_color='#252d3d',
            marker_line_color='#3d4b63',
            marker_line_width=1,
        ))
        fig_mg.add_trace(go.Bar(
            name='Margen% Budget',
            x=mg_df['Marca'],
            y=mg_df['Budget_Mg%'],
            marker_color=[VERTICAL_COLORS.get(v,'#7eb8ff') for v in mg_df['Vertical']],
            marker_opacity=0.8,
        ))
        fig_mg.update_layout(**CHART_LAYOUT, height=340, barmode='group', bargap=0.15,
                             yaxis=dict(tickformat='.0%', gridcolor='#252d3d', linecolor='#252d3d'),
                             xaxis=dict(tickangle=-35, gridcolor='#252d3d', linecolor='#252d3d'))
        st.plotly_chart(fig_mg, width='stretch')

    # ── Main margins table ──
    st.markdown('<div class="section-header">Tabla de Márgenes</div>', unsafe_allow_html=True)

    display_cols = {
        'Marca':'Marca','Vertical':'Vertical','Stock':'Stock',
        'Budget_Rev':'Budget Rev.','Budget_Mg%':'Budget Mg%',
        'LY_Rev':'LY Revenue','LY_Mg%':'LY Mg%','LY_MgEur':'LY Mg€'
    }
    tbl = df_fil[list(display_cols.keys())].copy()
    tbl.columns = list(display_cols.values())

    def style_margins(df):
        def color_mg(val):
            if isinstance(val, float):
                if val > 0.25: return 'color: #2ed573'
                if val < 0:    return 'color: #ff4757'
                if val > 0.15: return 'color: #d4dbe8'
            return 'color: #8896ab'

        styled = df.style\
            .format({
                'Stock':       '€{:,.0f}',
                'Budget Rev.': '€{:,.0f}',
                'Budget Mg%':  '{:.1%}',
                'LY Revenue':  '€{:,.0f}',
                'LY Mg%':      '{:.1%}',
                'LY Mg€':      '€{:,.0f}',
            })\
            .applymap(color_mg, subset=['Budget Mg%', 'LY Mg%'])\
            .set_properties(**{'background-color': '#1a1f2b', 'color': '#d4dbe8',
                               'border-color': '#252d3d', 'font-size': '12px'})
        return styled

    st.dataframe(style_margins(tbl), width='stretch', height=420)

    # ── Stock waterfall ──
    st.markdown('<div class="section-header">Stock por Marca (Top 20)</div>', unsafe_allow_html=True)
    stock_df = df_fil[df_fil['Stock'] > 0].nlargest(20, 'Stock')
    fig_stock = go.Figure(go.Bar(
        x=stock_df['Marca'],
        y=stock_df['Stock'],
        marker_color=[VERTICAL_COLORS.get(v, '#7eb8ff') for v in stock_df['Vertical']],
        text=[fmt_eur(v) for v in stock_df['Stock']],
        textposition='outside',
        textfont=dict(size=10),
    ))
    fig_stock.update_layout(**CHART_LAYOUT, height=280, bargap=0.25,
                            xaxis=dict(tickangle=-35, gridcolor='#252d3d', linecolor='#252d3d'))
    st.plotly_chart(fig_stock, width='stretch')


# ════════════════════════════════════════════════════════════════════════════════
# VERTICAL PAGES (shared renderer)
# ════════════════════════════════════════════════════════════════════════════════
else:
    # Determine which vertical
    vertical_config = {
        "🏍️ Vertical 2 Wheels":      {'key':'2 WHEELS',    'label':'2 Wheels',    'color':'#7eb8ff', 'icon':'🏍️'},
        "🌲 Vertical Free Time":      {'key':'FREE TIME',   'label':'Free Time',   'color':'#5de85d', 'icon':'🌲'},
        "📡 Vertical Outdoor Tech":   {'key':'OUTDOOR TECH','label':'Outdoor Tech','color':'#e87de8', 'icon':'📡'},
    }
    cfg = vertical_config[page]
    V_KEY   = cfg['key']
    V_LABEL = cfg['label']
    V_COLOR = cfg['color']
    V_ICON  = cfg['icon']

    st.markdown(f"""
    <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px;">
        <h1 style="margin:0;font-size:32px;color:{V_COLOR};">{V_ICON} {V_LABEL}</h1>
        <span style="color:#5a6378;font-size:14px;">Vertical Dashboard · {current_month_name} 2026</span>
    </div>""", unsafe_allow_html=True)

    # Filter data for this vertical
    brands_v = df_margins[df_margins['Vertical']==V_KEY].copy()
    brands_v = brands_v[~brands_v['Marca'].isin([V_KEY,'NUEVAS MARCAS','Marca',''])]

    # Actual sales from ventas
    ventas_v = vert_monthly[vert_monthly['Columna1'].str.upper()==V_KEY].copy()
    brand_v_actual = df_ventas_full[
        df_ventas_full['Columna1'].str.upper()==V_KEY
    ].groupby('Nombre').agg(
        Revenue=('Importe Neto','sum'),
        Margen_Euros=('Margen_Euros','sum')
    ).reset_index()
    brand_v_actual['Margen_Pct'] = np.where(
        brand_v_actual['Revenue'] != 0,
        brand_v_actual['Margen_Euros'] / brand_v_actual['Revenue'], 0
    )

    rev_v  = brand_v_actual['Revenue'].sum()
    mg_v   = brand_v_actual['Margen_Euros'].sum()
    mgpct_v= mg_v / rev_v if rev_v else 0

    # Budget for this vertical
    v_row = df_margins[df_margins['Marca'].str.upper()==V_KEY]
    budget_v     = float(v_row['Budget_Rev'].iloc[0]) if len(v_row) else 0
    budget_mg_v  = float(v_row['Budget_Mg%'].iloc[0]) if len(v_row) else 0
    stock_v      = float(v_row['Stock'].iloc[0]) if len(v_row) else 0
    ly_rev_v     = float(v_row['LY_Rev'].iloc[0]) if len(v_row) else 0
    ly_mgeur_v   = float(v_row['LY_MgEur'].iloc[0]) if len(v_row) else 0
    ly_mgpct_v   = float(v_row['LY_Mg%'].iloc[0]) if len(v_row) else 0

    bud_monthly_v= budget_v / 12

    # ── KPI row ──
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.metric("Revenue Enero", fmt_eur(rev_v),
                  f"Budget: {fmt_eur(bud_monthly_v)}")
    with k2:
        cumpl_v = rev_v / bud_monthly_v if bud_monthly_v else 0
        st.metric("Cumpl. Budget", fmt_pct(cumpl_v),
                  f"{rev_v - bud_monthly_v:+,.0f}€ vs budget")
    with k3:
        st.metric("Margen €", fmt_eur(mg_v),
                  f"LY: {fmt_eur(ly_mgeur_v/12)}/mes")
    with k4:
        st.metric("Margen %", fmt_pct(mgpct_v),
                  f"{(mgpct_v - ly_mgpct_v)*100:+.1f}pp vs LY")
    with k5:
        st.metric("Stock", fmt_eur(stock_v))

    # Are we growing? HOW DOING vs BUDGET? LAST MONTH TREND
    st.markdown("<br>", unsafe_allow_html=True)
    ia1, ia2, ia3 = st.columns(3)
    ly_monthly = ly_rev_v / 12
    with ia1:
        growing = rev_v > ly_monthly
        indicator = "▲ GROWING" if growing else "▼ DECLINING"
        ind_color = "#2ed573" if growing else "#ff4757"
        pct_vs_ly = (rev_v / ly_monthly - 1)*100 if ly_monthly else 0
        st.markdown(f"""
        <div class="metric-card" style="border-color:{ind_color}40;">
            <div class="metric-label">Are we growing?</div>
            <div class="metric-value" style="font-size:20px;color:{ind_color};">{indicator}</div>
            <div class="metric-delta" style="color:{ind_color};">{pct_vs_ly:+.1f}% vs LY (mensualiz.)</div>
        </div>""", unsafe_allow_html=True)
    with ia2:
        doing_ok = rev_v >= bud_monthly_v * 0.9
        doing_label = "✓ ON TRACK" if doing_ok else "✗ BEHIND BUDGET"
        doing_color = "#2ed573" if doing_ok else "#ff4757"
        diff_eur = rev_v - bud_monthly_v
        st.markdown(f"""
        <div class="metric-card" style="border-color:{doing_color}40;">
            <div class="metric-label">How are we doing vs Budget?</div>
            <div class="metric-value" style="font-size:20px;color:{doing_color};">{doing_label}</div>
            <div class="metric-delta" style="color:{doing_color};">{diff_eur:+,.0f}€ vs budget mensual</div>
        </div>""", unsafe_allow_html=True)
    with ia3:
        stock_pct = stock_v / budget_v if budget_v else 0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">% Stock vs Year Budget</div>
            <div class="metric-value" style="font-family:'DM Mono',monospace;">{fmt_pct(stock_pct)}</div>
            <div class="metric-delta delta-neu">Stock: {fmt_eur(stock_v)} | Budget anual: {fmt_eur(budget_v)}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts ──
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.markdown('<div class="section-header">Revenue Real vs Budget por Marca</div>', unsafe_allow_html=True)
        merged_v = brand_v_actual.merge(
            brands_v[['Marca','Budget_Rev','LY_Rev']].rename(columns={'Marca':'Nombre'}),
            on='Nombre', how='outer'
        ).fillna(0)
        merged_v = merged_v.sort_values('Revenue', ascending=False).head(15)

        fig_bv = go.Figure()
        fig_bv.add_trace(go.Bar(
            name='LY (anualiz./12)',
            x=merged_v['Nombre'],
            y=merged_v['LY_Rev'] / 12,
            marker_color='#252d3d',
            marker_line_color='#3d4b63', marker_line_width=1,
        ))
        fig_bv.add_trace(go.Bar(
            name='Revenue Enero',
            x=merged_v['Nombre'],
            y=merged_v['Revenue'],
            marker_color=V_COLOR,
            marker_opacity=0.85,
        ))
        fig_bv.add_trace(go.Scatter(
            name='Budget /mes',
            x=merged_v['Nombre'],
            y=merged_v['Budget_Rev'] / 12,
            mode='markers',
            marker=dict(symbol='diamond', size=9, color='#e8ff00',
                        line=dict(color='#0a0c10', width=1)),
        ))
        fig_bv.update_layout(**CHART_LAYOUT, height=340, barmode='group', bargap=0.2,
                             xaxis=dict(tickangle=-35, gridcolor='#252d3d', linecolor='#252d3d'),
                             legend={**DEFAULT_LEGEND, 'orientation':'h', 'y':1.1})
        st.plotly_chart(fig_bv, width='stretch')

    with col_r:
        st.markdown('<div class="section-header">Margen % Real por Marca</div>', unsafe_allow_html=True)
        mg_brand = brand_v_actual[brand_v_actual['Revenue'] > 0].sort_values('Revenue', ascending=False).head(12)
        colors_mg = ['#2ed573' if m > 0.2 else ('#ff4757' if m < 0 else V_COLOR) for m in mg_brand['Margen_Pct']]

        fig_mgb = go.Figure(go.Bar(
            x=mg_brand['Margen_Pct'],
            y=mg_brand['Nombre'],
            orientation='h',
            marker_color=colors_mg,
            text=[fmt_pct(m) for m in mg_brand['Margen_Pct']],
            textposition='outside',
            textfont=dict(size=10),
        ))
        # Budget margin line
        if budget_mg_v:
            fig_mgb.add_vline(x=budget_mg_v, line_color='#e8ff00', line_dash='dot', line_width=2,
                              annotation_text=f"Budget {fmt_pct(budget_mg_v)}", annotation_font_size=10)
        fig_mgb.update_layout(**CHART_LAYOUT, height=340, showlegend=False,
                              xaxis=dict(tickformat='.0%', gridcolor='#252d3d', linecolor='#252d3d'),
                              yaxis=dict(gridcolor='#252d3d', linecolor='#252d3d'))
        st.plotly_chart(fig_mgb, width='stretch')

    # ── Budget monthly distribution ──
    st.markdown('<div class="section-header">Distribución Budget Mensual 2026</div>', unsafe_allow_html=True)

    # Get budget by month for this vertical from budget table
    vert_brand_list = brands_v['Marca'].tolist()
    vert_budget_rows = df_budget_raw[df_budget_raw['Marca'].isin(vert_brand_list)]
    month_cols_budget = {
        'Enero':'Venta Enero','Febrero':'Venta Febrero','Marzo':'Venta Marzo',
        'Abril':'Venta Abril','Mayo':'Venta Mayo','Junio':'Venta Junio',
        'Julio':'Venta Julio','Agosto':'Venta Agosto','Septiembre':'Venta Septiembre',
        'Octubre':'Venta Octubre','Noviembre':'Venta Noviembre','Diciembre':'Venta Diciembre'
    }
    bud_by_month = []
    for mes, col in month_cols_budget.items():
        val = vert_budget_rows[col].sum() if col in vert_budget_rows.columns else 0
        bud_by_month.append({'Mes': mes, 'Budget': val})
    df_bm = pd.DataFrame(bud_by_month)

    fig_bm = go.Figure()
    fig_bm.add_trace(go.Bar(
        x=df_bm['Mes'],
        y=df_bm['Budget'],
        marker_color=V_COLOR,
        marker_opacity=0.3,
        name='Budget',
        hovertemplate='%{x}: €%{y:,.0f}<extra></extra>',
    ))
    # Actual for current month
    fig_bm.add_trace(go.Bar(
        x=[current_month_name],
        y=[rev_v],
        marker_color=V_COLOR,
        name='Real',
        hovertemplate=f'Real {current_month_name}: €%{{y:,.0f}}<extra></extra>',
    ))
    fig_bm.add_hline(y=bud_monthly_v, line_color='#e8ff00', line_dash='dot', line_width=1.5,
                     annotation_text=f"Media mensual {fmt_eur(bud_monthly_v)}", annotation_font_size=10)
    fig_bm.update_layout(**CHART_LAYOUT, height=260, bargap=0.2,
                         legend={**DEFAULT_LEGEND, 'orientation':'h', 'y':1.1})
    st.plotly_chart(fig_bm, width='stretch')

    # ── Detailed brands table ──
    st.markdown('<div class="section-header">Detalle de Marcas</div>', unsafe_allow_html=True)
    detail = brand_v_actual.merge(
        brands_v[['Marca','Budget_Rev','Budget_Mg%','Stock','LY_Rev','LY_Mg%','LY_MgEur']]\
            .rename(columns={'Marca':'Nombre'}),
        on='Nombre', how='outer'
    ).fillna(0)
    detail['Rev vs Budget'] = np.where(
        detail['Budget_Rev'] / 12 > 0,
        detail['Revenue'] / (detail['Budget_Rev'] / 12),
        0
    )
    detail = detail.sort_values('Revenue', ascending=False)
    detail_show = detail[['Nombre','Revenue','Margen_Euros','Margen_Pct',
                           'Budget_Rev','Budget_Mg%','Stock','LY_Rev','LY_Mg%','Rev vs Budget']].copy()
    detail_show.columns = ['Marca','Revenue','Margen€','Mg%','Budget Rev','Budget Mg%',
                           'Stock','LY Rev','LY Mg%','Rev/Budget']

    styled_detail = detail_show.style.format({
        'Revenue':'€{:,.0f}','Margen€':'€{:,.0f}','Mg%':'{:.1%}',
        'Budget Rev':'€{:,.0f}','Budget Mg%':'{:.1%}','Stock':'€{:,.0f}',
        'LY Rev':'€{:,.0f}','LY Mg%':'{:.1%}','Rev/Budget':'{:.1%}'
    }).applymap(
        lambda v: 'color: #2ed573' if isinstance(v,float) and v > 0.2 else
                  ('color: #ff4757' if isinstance(v,float) and v < 0 else ''),
        subset=['Mg%','Budget Mg%','LY Mg%']
    ).applymap(
        lambda v: 'color: #2ed573' if isinstance(v,float) and v >= 1 else
                  ('color: #ff4757' if isinstance(v,float) and 0 < v < 0.8 else ''),
        subset=['Rev/Budget']
    ).set_properties(**{'background-color':'#1a1f2b','color':'#d4dbe8',
                        'border-color':'#252d3d','font-size':'12px'})

    st.dataframe(styled_detail, width='stretch', height=380)
