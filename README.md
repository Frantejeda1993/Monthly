# Sportech IB · Monthly Performance Dashboard

Dashboard interactivo construido con **Streamlit** para visualizar los datos del `TemplateMonthly.xlsx`.

## 📦 Estructura

```
sportech_dashboard/
├── app.py              # Aplicación principal
├── requirements.txt    # Dependencias Python
└── README.md           # Este archivo
```

## 🚀 Deploy en Streamlit Cloud

1. Sube esta carpeta a un repositorio de **GitHub** (público o privado)
2. Ve a [share.streamlit.io](https://share.streamlit.io) e inicia sesión con GitHub
3. Pulsa **"New app"** → selecciona tu repo y el archivo `app.py`
4. Haz clic en **"Deploy"**

Una vez desplegada, la app pedirá subir el archivo Excel desde la barra lateral.

## 🖥️ Ejecutar en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 📊 Secciones del dashboard

| Sección | Descripción |
|---------|-------------|
| **Overview · RECAP** | KPIs globales, revenue por vertical, evolución budget mensual, top marcas |
| **MARGINS · Marcas** | Tabla completa de márgenes, scatter Budget vs LY, stock por marca |
| **Vertical 2 Wheels** | Dashboard específico: indicadores are we growing?, revenue vs budget por marca |
| **Vertical Free Time** | Ídem para la vertical de Free Time |
| **Vertical Outdoor Tech** | Ídem para la vertical de Outdoor Tech |

## 📋 Datos utilizados del Excel

- `INPUT (Mensual) Ventas` → transacciones reales de ventas
- `MARGINS` → stock, budget, datos año anterior por marca
- `INPUT (Anual) Budget` → desglose mensual del budget
- `INPUT (Anual) Familias` → relación Marca ↔ Código Familia ↔ Vertical


## 🔐 Configuración de Firebase en Streamlit Cloud

En **App settings → Secrets**, puedes usar cualquiera de estos formatos:

```toml
[firebase]
databaseURL = "https://TU-PROYECTO-default-rtdb.europe-west1.firebasedatabase.app"

[firebase.service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

También se aceptan claves planas (`database_url`, `firebase_database_url`, `FIREBASE_DATABASE_URL`) y `service_account` como JSON string.
