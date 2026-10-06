import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

st.set_page_config(page_title="Centro de Comando | Rentabilidad", layout="wide", page_icon="🚌")

# --- SISTEMA DE LOGIN ---
USUARIOS = {"admin": "admin123", "operador": "ahumada2026"}

if 'logeado' not in st.session_state:
    st.session_state['logeado'] = False
    st.session_state['usuario'] = ""

if not st.session_state['logeado']:
    st.markdown("<h1 style='text-align: center;'>🚌 Acceso al Sistema</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            st.write("Ingrese sus credenciales para continuar")
            usuario = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar")
            
            if submit:
                if usuario in USUARIOS and USUARIOS[usuario] == password:
                    st.session_state['logeado'] = True
                    st.session_state['usuario'] = usuario
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos")
    st.stop() 

# --- BASE DE DATOS ---
conn = sqlite3.connect('historial_ocupacion.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS historial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_carga TEXT,
        usuario TEXT,
        folio_viaje TEXT,
        fecha_salida TEXT,
        hora_salida TEXT,
        ruta TEXT,
        asientos_vendidos INTEGER,
        capacidad INTEGER,
        monto REAL
    )
''')
conn.commit()

# --- PROCESAMIENTO ---
def procesar_ocupacion(df):
    temp = df['Ocupación Relativa'].astype(str).str.split('/', n=1, expand=True)
    df['Vendidos'] = pd.to_numeric(temp[0], errors='coerce').fillna(0).astype(int)
    
    temp2 = temp[1].str.split(' ', n=1, expand=True)
    df['Capacidad'] = pd.to_numeric(temp2[0], errors='coerce').fillna(1).astype(int)
    
    df['Ocupación %'] = df['Ocupación Relativa'].str.extract(r'\((.*?)\)')
    df['Pct Numérico'] = pd.to_numeric(df['Ocupación %'].str.replace('%', ''), errors='coerce').fillna(0)
    df['Asientos Disponibles'] = df['Capacidad'] - df['Vendidos']
    
    df['Valor de planilla CLP'] = pd.to_numeric(df['Valor de planilla CLP'], errors='coerce').fillna(0).astype(int)
    df['Folio de viaje'] = df['Folio de viaje'].astype(str)
    
    hoy_dt = datetime.now()
    df['Fecha_Hora_dt'] = pd.to_datetime(df['Fecha salida'] + ' ' + df['Hora salida'], format='%d/%m/%Y %H:%M', errors='coerce')
    df['Horas Restantes'] = ((df['Fecha_Hora_dt'] - hoy_dt).dt.total_seconds() / 3600).round(1)
    df['Horas Restantes'] = df['Horas Restantes'].fillna(999)
    
    return df

def categorizar_accion(pct):
    if pct >= 71:
        return '🟢 ALTA DEMANDA (Posible Inyección)'
    elif 30 <= pct <= 70:
        return '🟡 MEDIO (Rendimiento Normal)'
    else:
        return '🔴 CRÍTICO (Baja Ocupación)'

def aplicar_color_fila(val):
    if 'ALTA DEMANDA' in str(val):
        return 'background-color: #d4edda; color: black;' 
    elif 'MEDIO' in str(val):
        return 'background-color: #fff3cd; color: black;' 
    elif 'CRÍTICO' in str(val):
        return 'background-color: #f8d7da; color: black;' 
    return ''

# --- INTERFAZ PRINCIPAL ---
st.title(f"📊 Centro de Comando - {st.session_state['usuario'].capitalize()}")

archivo_subido = st.file_uploader("📥 Subir Reporte de Ocupación de Terra", type=["xlsx"])

if archivo_subido is not None:
    try:
        df_base = pd.read_excel(archivo_subido, skiprows=1)
        df_proc = procesar_ocupacion(df_base)
        df_proc['Acción Sugerida'] = df_proc['Pct Numérico'].apply(categorizar_accion)
        
        # --- BARRA LATERAL: FILTROS ---
        st.sidebar.header("🔍 Filtros de Búsqueda")
        rutas_unicas = df_proc['Ruta'].dropna().unique().tolist()
        ruta_filtro = st.sidebar.multiselect("Rutas", rutas_unicas, default=[])
        
        estados_unicos = df_proc['Estado de viaje'].dropna().unique().tolist()
        estado_filtro = st.sidebar.multiselect("Estado", estados_unicos, default=['Activo'])
        
        fechas_unicas = sorted(df_proc['Fecha salida'].dropna().unique().tolist())
        fecha_filtro = st.sidebar.multiselect("Fechas", fechas_unicas, default=[])
        
        df_hoy = df_proc.copy()
        if ruta_filtro: df_hoy = df_hoy[df_hoy['Ruta'].isin(ruta_filtro)]
        if estado_filtro: df_hoy = df_hoy[df_hoy['Estado de viaje'].isin(estado_filtro)]
        if fecha_filtro: df_hoy = df_hoy[df_hoy['Fecha salida'].isin(fecha_filtro)]

        # --- GUARDADO EN HISTORIAL ---
        hoy_dt = datetime.now()
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("💾 Guardar Carga Oficial"):
                for index, row in df_proc.iterrows():
                    c.execute('''
                        INSERT INTO historial (fecha_carga, usuario, folio_viaje, fecha_salida, hora_salida, ruta, asientos_vendidos, capacidad, monto)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (fecha_carga, st.session_state['usuario'], str(row['Folio de viaje']), str(row['Fecha salida']), 
                          str(row['Hora salida']), str(row['Ruta']), row['Vendidos'], row['Capacidad'], row['Valor de planilla CLP']))
                conn.commit()
                st.success("Carga guardada con éxito.")

        # --- INDICADORES GENERALES (KPIs) ---
        st.markdown("### 📈 Indicadores Globales (Filtro Actual)")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        total_servicios = len(df_hoy)
        total_capacidad = df_hoy['Capacidad'].sum()
        total_vendidos = df_hoy['Vendidos'].sum()
        ocupacion_ponderada = (total_vendidos / total_capacidad * 100) if total_capacidad > 0 else 0
        total_recaudacion = df_hoy['Valor de planilla CLP'].sum()
        
        kpi1.metric("Servicios Programados", f"{total_servicios}")
        kpi2.metric("Ocupación Ponderada", f"{ocupacion_ponderada:.1f}%", f"{total_vendidos} / {total_capacidad} asientos")
        kpi3.metric("Asientos Disponibles", f"{df_hoy['Asientos Disponibles'].sum()}")
        kpi4.metric("Valor Planilla Total", f"${total_recaudacion:,.0f}".replace(',', '.'))

        st.divider()

        # --- VELOCIDAD DE VENTA ---
        st.markdown("### ⚡ Crecimiento vs Última Carga")
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_Neto'] = df_cruce['Vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Vendidos'])
            
            viajes_top = df_cruce.sort_values(by='Crecimiento_Neto', ascending=False).head(3)
            col_v1, col_v2, col_v3 = st.columns(3)
            for i, (idx, row) in enumerate(viajes_top.iterrows()):
                cols = [col_v1, col_v2, col_v3]
                with cols[i]:
                    st.metric(label=f"Folio {row['Folio de viaje']} ({row['Fecha salida']})", 
                              value=f"{int(row['Vendidos'])} vendidos", 
                              delta=f"+{int(row['Crecimiento_Neto'])} netos")
        else:
            st.info("ℹ️ Guarda el reporte para activar la comparativa histórica.")

        # --- TABLA TÁCTICA EXPANDIDA ---
        st.markdown("### 📋 Panel de Acción")
        columnas_ver = [
            'Folio de viaje', 'Estado de viaje', 'Fecha salida', 'Hora salida', 'Día de semana',
            'Ruta', 'Vendidos', 'Capacidad', 'Asientos Disponibles', 'Horas Restantes', 
            'Ocupación %', 'Valor de planilla CLP', 'Acción Sugerida'
        ]
        
        df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
        
        st.dataframe(df_mostrar.style.map(
            aplicar_color_fila, subset=['Acción Sugerida']
        ), use_container_width=True, height=400)

        # --- EXPORTACIÓN ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_mostrar.to_excel(writer, sheet_name='Filtro Actual', index=False)
            
            df_finanzas = df_hoy.groupby(['Fecha salida', 'Ruta']).agg({
                'Valor de planilla CLP': 'sum', 
                'Vendidos': 'sum',
                'Capacidad': 'sum'
            }).reset_index()
            df_finanzas.to_excel(writer, sheet_name='Agrupado Financiero', index=False)
            
        st.download_button(
            label="📥 Exportar Vista Actual (Excel)",
            data=output.getvalue(),
            file_name=f"Reporte_Ocupacion_{hoy_dt.strftime('%d%m%Y_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
            
    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")

conn.close()
