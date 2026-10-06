import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

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
    if pct >= 71: return '🟢 ALTA DEMANDA'
    elif 30 <= pct <= 70: return '🟡 MEDIO (Normal)'
    else: return '🔴 CRÍTICO (Baja)'

def calcular_proyeccion(row, df_historial):
    """Motor predictivo simplificado: Estima la ocupación final en base a la velocidad de venta histórica."""
    if df_historial.empty or row['Folio de viaje'] not in df_historial['folio_viaje'].values:
        return row['Vendidos'] # Sin datos, asume que se queda igual
        
    hist_folio = df_historial[df_historial['folio_viaje'] == row['Folio de viaje']].sort_values('fecha_carga')
    
    # Si hay al menos 2 reportes previos, calculamos el ritmo de venta
    if len(hist_folio) >= 2:
        primer_registro = hist_folio.iloc[0]
        ultimo_registro = hist_folio.iloc[-1]
        
        tiempo_pasado_horas = (pd.to_datetime(ultimo_registro['fecha_carga']) - pd.to_datetime(primer_registro['fecha_carga'])).total_seconds() / 3600
        ventas_logradas = ultimo_registro['asientos_vendidos'] - primer_registro['asientos_vendidos']
        
        if tiempo_pasado_horas > 0 and ventas_logradas > 0:
            ritmo_por_hora = ventas_logradas / tiempo_pasado_horas
            # Aplicamos un freno matemático (factor de desaceleración) para que no proyecte ventas infinitas
            horas_proyectadas = min(row['Horas Restantes'], 48) # Solo proyectamos máximo a 48 hrs para no exagerar
            ventas_estimadas_futuras = ritmo_por_hora * horas_proyectadas
            
            estimacion_final = int(row['Vendidos'] + ventas_estimadas_futuras)
            return min(estimacion_final, row['Capacidad']) # Nunca puede superar la capacidad del bus
            
    return row['Vendidos']

def aplicar_color_fila(val):
    if 'ALTA DEMANDA' in str(val): return 'background-color: #d4edda; color: black;' 
    elif 'MEDIO' in str(val): return 'background-color: #fff3cd; color: black;' 
    elif 'CRÍTICO' in str(val): return 'background-color: #f8d7da; color: black;' 
    return ''

# --- INTERFAZ PRINCIPAL ---
st.title(f"📊 Centro de Comando - {st.session_state['usuario'].capitalize()}")

archivo_subido = st.file_uploader("📥 Subir Reporte de Ocupación de Terra", type=["xlsx"])

if archivo_subido is not None:
    try:
        df_base = pd.read_excel(archivo_subido, skiprows=1)
        df_proc = procesar_ocupacion(df_base)
        df_proc['Acción Sugerida'] = df_proc['Pct Numérico'].apply(categorizar_accion)
        
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

        hoy_dt = datetime.now()
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')
        
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

        st.markdown("### 📈 Indicadores Globales")
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

        # --- PREPARACIÓN HISTÓRICA Y PROYECCIONES ---
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        df_cruce = pd.DataFrame()
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos', 'capacidad']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_Neto'] = df_cruce['Vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Vendidos'])
            hist_pct = (df_cruce['asientos_vendidos'] / df_cruce['capacidad']) * 100
            df_cruce['Var. Pct. Ocupación'] = (df_cruce['Pct Numérico'] - hist_pct.fillna(df_cruce['Pct Numérico'])).round(1)
            
            # Ejecutar proyecciones (Fase 1)
            df_cruce['Proyección Cierre (Vendidos)'] = df_cruce.apply(lambda row: calcular_proyeccion(row, df_historial), axis=1)
            df_cruce['Proyección Cierre (%)'] = ((df_cruce['Proyección Cierre (Vendidos)'] / df_cruce['Capacidad']) * 100).round(1)

        # --- PESTAÑAS DE NAVEGACIÓN ---
        tab1, tab2, tab3, tab4 = st.tabs(["📋 Acción Táctica", "📈 Proyecciones de Cierre", "📊 Mapas de Calor", "🔍 Análisis por Folio (Curvas)"])

        # PESTAÑA 1: TABLA DE ACCIÓN
        with tab1:
            st.markdown("Selecciona las columnas que deseas visualizar:")
            todas_las_columnas = ['Folio de viaje', 'Estado de viaje', 'Fecha salida', 'Hora salida', 'Día de semana', 'Origen (ciudad)', 'Destino (ciudad)', 'Ruta', 'Vendidos', 'Capacidad', 'Asientos Disponibles', 'Horas Restantes', 'Ocupación %', 'Valor de planilla CLP', 'Acción Sugerida']
            if not df_cruce.empty:
                df_hoy = df_cruce.copy()
                todas_las_columnas.extend(['Crecimiento_Neto', 'Var. Pct. Ocupación'])
            
            columnas_default = ['Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 'Capacidad', 'Asientos Disponibles', 'Ocupación %', 'Acción Sugerida']
            columnas_ver = st.multiselect("Columnas Visibles", todas_las_columnas, default=columnas_default)
            
            df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
            st.dataframe(df_mostrar.style.map(aplicar_color_fila, subset=['Acción Sugerida'] if 'Acción Sugerida' in columnas_ver else []), use_container_width=True, height=400)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_mostrar.to_excel(writer, sheet_name='Filtro Actual', index=False)
            st.download_button("📥 Exportar Vista Actual (Excel)", data=output.getvalue(), file_name=f"Reporte_Ocupacion_{hoy_dt.strftime('%d%m%Y_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # PESTAÑA 2: PROYECCIONES DE CIERRE (NUEVO FASE 1)
        with tab2:
            st.markdown("### 🎯 Estimación de Ocupación Final")
            st.write("Calculado en base a la velocidad de venta histórica de los reportes anteriores.")
            if not df_cruce.empty and 'Proyección Cierre (Vendidos)' in df_cruce.columns:
                col_proy = ['Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 'Proyección Cierre (Vendidos)', 'Capacidad', 'Ocupación %', 'Proyección Cierre (%)']
                df_proyeccion = df_cruce[col_proy].sort_values('Proyección Cierre (%)', ascending=False)
                
                # Resaltar servicios que proyectan llenarse
                def highlight_full(val):
                    if isinstance(val, (int, float)) and val >= 95: return 'background-color: #d4edda; color: black; font-weight: bold;'
                    return ''
                
                st.dataframe(df_proyeccion.style.map(highlight_full, subset=['Proyección Cierre (%)']), use_container_width=True)
            else:
                st.info("Necesitas guardar al menos 2 reportes de días distintos para que el motor predictivo pueda calcular la velocidad de venta.")

        # PESTAÑA 3: GRÁFICOS INTERACTIVOS
        with tab3:
            col_g1, col_g2 = st.columns([1, 2])
            with col_g1:
                resumen_estado = df_hoy['Acción Sugerida'].value_counts().reset_index()
                resumen_estado.columns = ['Estado', 'Cantidad']
                color_map = {'🟢 ALTA DEMANDA': '#28a745', '🟡 MEDIO (Normal)': '#ffc107', '🔴 CRÍTICO (Baja)': '#dc3545'}
                fig_pie = px.pie(resumen_estado, values='Cantidad', names='Estado', hole=0.4, color='Estado', color_discrete_map=color_map, title="Distribución de Rentabilidad")
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_g2:
                mapa_data = df_hoy.groupby(['Ruta', 'Día de semana']).agg(Total_Vendidos=('Vendidos', 'sum'), Total_Capacidad=('Capacidad', 'sum')).reset_index()
                mapa_data['Ocupación Promedio %'] = (mapa_data['Total_Vendidos'] / mapa_data['Total_Capacidad']) * 100
                orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                mapa_pivot = mapa_data.pivot(index='Ruta', columns='Día de semana', values='Ocupación Promedio %')
                mapa_pivot = mapa_pivot.reindex(columns=[d for d in orden_dias if d in mapa_pivot.columns])
                fig_heat = px.imshow(mapa_pivot, labels=dict(x="Día", y="Ruta", color="% Ocupación"), x=mapa_pivot.columns, y=mapa_pivot.index, color_continuous_scale="RdYlGn", aspect="auto", title="Mapa de Calor: Ocupación Promedio")
                st.plotly_chart(fig_heat, use_container_width=True)

        # PESTAÑA 4: ANÁLISIS HISTÓRICO POR FOLIO (NUEVO FASE 1)
        with tab4:
            st.markdown("### 🔍 Curva Histórica de Vendidos por Folio")
            if not df_historial.empty:
                folio_buscar = st.selectbox("Selecciona un Folio de Viaje para analizar:", df_hoy['Folio de viaje'].unique())
                
                if folio_buscar:
                    hist_data = df_historial[df_historial['folio_viaje'] == folio_buscar].sort_values('fecha_carga')
                    if len(hist_data) > 1:
                        fig_line = px.line(hist_data, x='fecha_carga', y='asientos_vendidos', markers=True, 
                                           title=f"Evolución de Ventas - Folio {folio_buscar}",
                                           labels={'fecha_carga': 'Fecha del Reporte', 'asientos_vendidos': 'Asientos Vendidos'})
                        
                        # Línea roja de capacidad máxima
                        cap_max = hist_data['capacidad'].iloc[0]
                        fig_line.add_hline(y=cap_max, line_dash="dash", line_color="red", annotation_text=f"Capacidad Máxima ({cap_max})")
                        
                        st.plotly_chart(fig_line, use_container_width=True)
                    else:
                        st.warning(f"Aún no hay suficientes reportes guardados en el historial para trazar la curva del folio {folio_buscar}.")
            else:
                st.info("Guarda reportes diariamente para desbloquear las curvas históricas.")
            
    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")

conn.close()
