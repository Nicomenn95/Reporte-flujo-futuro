import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

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

        # --- GUARDADO EN HISTORIAL (CON PREVENCIÓN DE DUPLICADOS) ---
        hoy_dt = datetime.now()
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Check for recent identical uploads by this user to prevent spam
        c.execute("SELECT COUNT(*) FROM historial WHERE usuario = ? AND fecha_carga > datetime('now', '-5 minutes')", (st.session_state['usuario'],))
        recent_uploads = c.fetchone()[0]

        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("💾 Guardar Carga Oficial"):
                if recent_uploads > 0:
                    st.warning("⚠️ Ya has guardado un reporte en los últimos 5 minutos. Evitando duplicidad.")
                else:
                    for index, row in df_proc.iterrows():
                        c.execute('''
                            INSERT INTO historial (fecha_carga, usuario, folio_viaje, fecha_salida, hora_salida, ruta, asientos_vendidos, capacidad, monto)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (fecha_carga, st.session_state['usuario'], str(row['Folio de viaje']), str(row['Fecha salida']), 
                              str(row['Hora salida']), str(row['Ruta']), row['Vendidos'], row['Capacidad'], row['Valor de planilla CLP']))
                    conn.commit()
                    st.success("✅ Carga guardada con éxito.")

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

        # --- PREPARACIÓN COMPARATIVA HISTÓRICA ---
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        df_cruce = pd.DataFrame()
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos', 'capacidad']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_Neto'] = df_cruce['Vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Vendidos'])
            
            # Calculate change in occupancy percentage
            hist_pct = (df_cruce['asientos_vendidos'] / df_cruce['capacidad']) * 100
            df_cruce['Var. Pct. Ocupación'] = (df_cruce['Pct Numérico'] - hist_pct.fillna(df_cruce['Pct Numérico'])).round(1)

        # --- PESTAÑAS DE NAVEGACIÓN ---
        tab1, tab2, tab3 = st.tabs(["📋 Panel de Acción Táctica", "📊 Gráficos y Mapas de Calor", "⚡ Evolución de Ventas"])

        # PESTAÑA 1: TABLA DE ACCIÓN
        with tab1:
            st.markdown("Selecciona las columnas que deseas visualizar:")
            
            todas_las_columnas = [
                'Folio de viaje', 'Estado de viaje', 'Fecha salida', 'Hora salida', 'Día de semana',
                'Origen (ciudad)', 'Destino (ciudad)', 'Ruta', 'Vendidos', 'Capacidad', 
                'Asientos Disponibles', 'Horas Restantes', 'Ocupación %', 'Valor de planilla CLP', 
                'Acción Sugerida'
            ]
            
            # Add comparitive columns if available
            if not df_cruce.empty:
                df_hoy = df_cruce.copy()
                todas_las_columnas.extend(['Crecimiento_Neto', 'Var. Pct. Ocupación'])
            
            # Default columns to show
            columnas_default = [
                'Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 
                'Capacidad', 'Asientos Disponibles', 'Ocupación %', 'Acción Sugerida'
            ]

            columnas_ver = st.multiselect("Columnas Visibles", todas_las_columnas, default=columnas_default)
            
            df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
            
            st.dataframe(df_mostrar.style.map(
                aplicar_color_fila, subset=['Acción Sugerida'] if 'Acción Sugerida' in columnas_ver else []
            ), use_container_width=True, height=400)

            # Exportación
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_mostrar.to_excel(writer, sheet_name='Filtro Actual', index=False)
                df_finanzas = df_hoy.groupby(['Fecha salida', 'Ruta']).agg({
                    'Valor de planilla CLP': 'sum', 'Vendidos': 'sum', 'Capacidad': 'sum'
                }).reset_index()
                df_finanzas.to_excel(writer, sheet_name='Agrupado Financiero', index=False)
                
            st.download_button(
                label="📥 Exportar Vista Actual (Excel)",
                data=output.getvalue(),
                file_name=f"Reporte_Ocupacion_{hoy_dt.strftime('%d%m%Y_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # PESTAÑA 2: GRÁFICOS INTERACTIVOS
        with tab2:
            col_g1, col_g2 = st.columns([1, 2])
            
            with col_g1:
                st.markdown("**Distribución de Rentabilidad**")
                resumen_estado = df_hoy['Acción Sugerida'].value_counts().reset_index()
                resumen_estado.columns = ['Estado', 'Cantidad']
                
                color_map = {
                    '🟢 ALTA DEMANDA (Posible Inyección)': '#28a745',
                    '🟡 MEDIO (Rendimiento Normal)': '#ffc107',
                    '🔴 CRÍTICO (Baja Ocupación)': '#dc3545'
                }
                
                fig_pie = px.pie(resumen_estado, values='Cantidad', names='Estado', hole=0.4,
                                 color='Estado', color_discrete_map=color_map)
                fig_pie.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_g2:
                st.markdown("**Mapa de Calor: Ocupación Ponderada por Ruta y Día**")
                mapa_data = df_hoy.groupby(['Ruta', 'Día de semana']).agg(
                    Total_Vendidos=('Vendidos', 'sum'),
                    Total_Capacidad=('Capacidad', 'sum')
                ).reset_index()
                mapa_data['Ocupación Promedio %'] = (mapa_data['Total_Vendidos'] / mapa_data['Total_Capacidad']) * 100
                
                orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                mapa_pivot = mapa_data.pivot(index='Ruta', columns='Día de semana', values='Ocupación Promedio %')
                mapa_pivot = mapa_pivot.reindex(columns=[d for d in orden_dias if d in mapa_pivot.columns])
                
                fig_heat = px.imshow(mapa_pivot, 
                                     labels=dict(x="Día", y="Ruta", color="% Ocupación"),
                                     x=mapa_pivot.columns, y=mapa_pivot.index,
                                     color_continuous_scale="RdYlGn", aspect="auto")
                fig_heat.update_layout(margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_heat, use_container_width=True)

        # PESTAÑA 3: EVOLUCIÓN E HISTÓRICOS
        with tab3:
            if not df_historial.empty and not df_cruce.empty:
                st.markdown("**Top 10 Servicios con Mayor Crecimiento (vs Última Carga)**")
                viajes_top = df_cruce[df_cruce['Crecimiento_Neto'] > 0].sort_values(by='Crecimiento_Neto', ascending=False).head(10)
                
                if not viajes_top.empty:
                    viajes_top['Etiqueta_Viaje'] = "F: " + viajes_top['Folio de viaje'].astype(str) + " - " + viajes_top['Hora salida']
                    
                    fig_bar = px.bar(viajes_top, x='Etiqueta_Viaje', y='Crecimiento_Neto', 
                                     text='Crecimiento_Neto', color='Crecimiento_Neto',
                                     color_continuous_scale='Blues',
                                     labels={'Etiqueta_Viaje': 'Folio y Hora', 'Crecimiento_Neto': 'Nuevos Asientos Vendidos'})
                    fig_bar.update_traces(textposition='outside')
                    fig_bar.update_layout(showlegend=False, xaxis_tickangle=-45)
                    st.plotly_chart(fig_bar, use_container_width=True)
                else:
                    st.info("No se registraron ventas nuevas significativas comparado con el reporte anterior en los filtros seleccionados.")
            else:
                st.info("ℹ️ El análisis de evolución se activará automáticamente después de guardar tu primer reporte.")
            
    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")

conn.close()
