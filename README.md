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
