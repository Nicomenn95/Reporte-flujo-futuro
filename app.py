import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

st.set_page_config(page_title="Centro de Comando | Rentabilidad", layout="wide", page_icon="🚌")

# --- SISTEMA DE LOGIN Y ROLES (Punto 14) ---
# Diccionario: Usuario -> [Contraseña, Rol]
USUARIOS = {
    "admin": ["admin123", "administrador"], 
    "operador": ["ahumada2026", "planificacion"]
}

if 'logeado' not in st.session_state:
    st.session_state['logeado'] = False
    st.session_state['usuario'] = ""
    st.session_state['rol'] = ""

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
                if usuario in USUARIOS and USUARIOS[usuario][0] == password:
                    st.session_state['logeado'] = True
                    st.session_state['usuario'] = usuario
                    st.session_state['rol'] = USUARIOS[usuario][1]
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos")
    st.stop() 

# --- BASE DE DATOS (Puntos 2 y 12) ---
conn = sqlite3.connect('historial_ocupacion.db', check_same_thread=False)
c = conn.cursor()

# Tabla 1: Historial de Archivos
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

# Tabla 2: Seguimiento de Decisiones (Nuevo Etapa 4)
c.execute('''
    CREATE TABLE IF NOT EXISTS decisiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folio_viaje TEXT,
        fecha_registro TEXT,
        usuario TEXT,
        accion_tomada TEXT,
        responsable TEXT,
        estado TEXT
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
    
    df['Ingreso por Pasaje'] = np.where(df['Vendidos'] > 0, df['Valor de planilla CLP'] / df['Vendidos'], 0)
    df['Ingreso por Asiento Total'] = np.where(df['Capacidad'] > 0, df['Valor de planilla CLP'] / df['Capacidad'], 0)
    
    hoy_dt = datetime.now()
    df['Fecha_Hora_dt'] = pd.to_datetime(df['Fecha salida'] + ' ' + df['Hora salida'], format='%d/%m/%Y %H:%M', errors='coerce')
    df['Horas Restantes'] = ((df['Fecha_Hora_dt'] - hoy_dt).dt.total_seconds() / 3600).round(1)
    df['Horas Restantes'] = df['Horas Restantes'].fillna(999)
    return df

def categorizar_accion_inteligente(row):
    pct = row['Pct Numérico']
    horas = row['Horas Restantes']
    libres = row['Asientos Disponibles']
    
    if pct >= 85 and horas > 24: return '🟢 ALTA DEMANDA (Evaluar Refuerzo temprano)'
    elif pct >= 80 and libres <= 5: return '🟢 ALTA DEMANDA (Lleno inminente)'
    elif pct <= 20 and horas <= 24: return '🔴 CRÍTICO (Venta frenada - Evaluar Suspensión)'
    elif pct <= 40 and horas <= 48: return '🔴 CRÍTICO (Baja ocupación próxima a salida)'
    else: return '🟡 MEDIO (Rendimiento Normal)'

def calcular_proyeccion(row, df_historial):
    if df_historial.empty or row['Folio de viaje'] not in df_historial['folio_viaje'].values:
        return row['Vendidos']
    hist_folio = df_historial[df_historial['folio_viaje'] == row['Folio de viaje']].sort_values('fecha_carga')
    if len(hist_folio) >= 2:
        primer_registro = hist_folio.iloc[0]
        ultimo_registro = hist_folio.iloc[-1]
        tiempo_pasado_horas = (pd.to_datetime(ultimo_registro['fecha_carga']) - pd.to_datetime(primer_registro['fecha_carga'])).total_seconds() / 3600
        ventas_logradas = ultimo_registro['asientos_vendidos'] - primer_registro['asientos_vendidos']
        if tiempo_pasado_horas > 0 and ventas_logradas > 0:
            ritmo_por_hora = ventas_logradas / tiempo_pasado_horas
            horas_proyectadas = min(row['Horas Restantes'], 48)
            ventas_estimadas_futuras = ritmo_por_hora * horas_proyectadas
            estimacion_final = int(row['Vendidos'] + ventas_estimadas_futuras)
            return min(estimacion_final, row['Capacidad'])
    return row['Vendidos']

def aplicar_color_fila(val):
    if 'ALTA DEMANDA' in str(val): return 'background-color: #d4edda; color: black;' 
    elif 'MEDIO' in str(val): return 'background-color: #fff3cd; color: black;' 
    elif 'CRÍTICO' in str(val): return 'background-color: #f8d7da; color: black;' 
    return ''

# --- INTERFAZ PRINCIPAL ---
st.title(f"📊 Centro de Comando - {st.session_state['usuario'].capitalize()} (Rol: {st.session_state['rol'].capitalize()})")

archivo_subido = st.file_uploader("📥 Subir Reporte de Ocupación de Terra", type=["xlsx"])

if archivo_subido is not None:
    try:
        df_base = pd.read_excel(archivo_subido, skiprows=1)
        df_proc = procesar_ocupacion(df_base)
        df_proc['Acción Sugerida'] = df_proc.apply(categorizar_accion_inteligente, axis=1)
        
        st.sidebar.header("🔍 Filtros Operativos")
        rutas_unicas = df_proc['Ruta'].dropna().unique().tolist()
        ruta_filtro = st.sidebar.multiselect("Rutas", rutas_unicas, default=[])
        
        estados_unicos = df_proc['Estado de viaje'].dropna().unique().tolist()
        estado_filtro = st.sidebar.multiselect("Estado", estados_unicos, default=['Activo'])
        
        fechas_unicas = sorted(df_proc['Fecha salida'].dropna().unique().tolist())
        fecha_filtro = st.sidebar.multiselect("Fechas", fechas_unicas, default=[])
        
        if st.session_state['rol'] == 'administrador':
            st.sidebar.header("💰 Parámetros Económicos")
            costo_salida = st.sidebar.number_input("Costo Estimado por Salida (CLP)", min_value=0, value=250000, step=10000)
        else:
            costo_salida = 250000 # Default oculto para operadores

        df_hoy = df_proc.copy()
        if ruta_filtro: df_hoy = df_hoy[df_hoy['Ruta'].isin(ruta_filtro)]
        if estado_filtro: df_hoy = df_hoy[df_hoy['Estado de viaje'].isin(estado_filtro)]
        if fecha_filtro: df_hoy = df_hoy[df_hoy['Fecha salida'].isin(fecha_filtro)]

        df_hoy['Margen Estimado'] = df_hoy['Valor de planilla CLP'] - costo_salida
        df_hoy['Estado Financiero'] = np.where(df_hoy['Margen Estimado'] >= 0, '✅ Rentable', '❌ Pérdida')

        hoy_dt = datetime.now()
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute("SELECT COUNT(*) FROM historial WHERE usuario = ? AND fecha_carga > datetime('now', '-5 minutes')", (st.session_state['usuario'],))
        recent_uploads = c.fetchone()[0]

        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("💾 Guardar Carga Oficial"):
                if recent_uploads > 0:
                    st.warning("⚠️ Ya has guardado un reporte en los últimos 5 minutos.")
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

        # --- HISTÓRICOS Y PROYECCIONES ---
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        df_cruce = pd.DataFrame()
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos', 'capacidad']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_Neto'] = df_cruce['Vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Vendidos'])
            hist_pct = (df_cruce['asientos_vendidos'] / df_cruce['capacidad']) * 100
            df_cruce['Var. Pct. Ocupación'] = (df_cruce['Pct Numérico'] - hist_pct.fillna(df_cruce['Pct Numérico'])).round(1)
            df_cruce['Proyección Cierre (Vendidos)'] = df_cruce.apply(lambda row: calcular_proyeccion(row, df_historial), axis=1)
            df_cruce['Proyección Cierre (%)'] = ((df_cruce['Proyección Cierre (Vendidos)'] / df_cruce['Capacidad']) * 100).round(1)

        # --- PESTAÑAS DE NAVEGACIÓN ---
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Acción Táctica & Tareas", "💰 Análisis Financiero", "📈 Proyecciones", "⚙️ Simulador Rotativa", "🕒 Agenda por Terminal", "📊 Mapas y Curvas"])

        # PESTAÑA 1: TABLA TÁCTICA Y SEGUIMIENTO DE DECISIONES (Puntos 12 y 13)
        with tab1:
            st.markdown("### Tabla Táctica de Flota")
            todas_las_columnas = ['Folio de viaje', 'Estado de viaje', 'Fecha salida', 'Hora salida', 'Día de semana', 'Origen (ciudad)', 'Destino (ciudad)', 'Ruta', 'Vendidos', 'Capacidad', 'Asientos Disponibles', 'Horas Restantes', 'Ocupación %', 'Valor de planilla CLP', 'Acción Sugerida']
            if not df_cruce.empty:
                df_hoy = df_cruce.copy()
                todas_las_columnas.extend(['Crecimiento_Neto', 'Var. Pct. Ocupación'])
            
            columnas_default = ['Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 'Capacidad', 'Asientos Disponibles', 'Ocupación %', 'Acción Sugerida']
            columnas_ver = st.multiselect("Columnas Visibles", todas_las_columnas, default=columnas_default)
            
            df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
            st.dataframe(df_mostrar.style.map(aplicar_color_fila, subset=['Acción Sugerida'] if 'Acción Sugerida' in columnas_ver else []), use_container_width=True, height=400)

            # Botón de Descarga Mejorado (Resumen Ejecutivo)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Pestaña 1: Resumen Ejecutivo
                df_ejecutivo = pd.DataFrame({
                    'Métrica': ['Fecha de Reporte', 'Total Servicios', 'Ocupación Ponderada', 'Recaudación Total'],
                    'Valor': [hoy_dt.strftime('%d/%m/%Y %H:%M'), total_servicios, f"{ocupacion_ponderada:.1f}%", f"${total_recaudacion:,.0f}"]
                })
                df_ejecutivo.to_excel(writer, sheet_name='Resumen Ejecutivo', index=False)
                # Pestaña 2: Los datos
                df_mostrar.to_excel(writer, sheet_name='Filtro Actual', index=False)
                
            st.download_button("📥 Exportar Vista Actual (Excel)", data=output.getvalue(), file_name=f"Reporte_Ocupacion_{hoy_dt.strftime('%d%m%Y_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            # Módulo de Decisiones
            st.markdown("---")
            st.markdown("### 📝 Registro de Decisiones y Tareas")
            col_d1, col_d2 = st.columns([1, 2])
            
            with col_d1:
                with st.form("form_decisiones"):
                    folio_tarea = st.selectbox("Folio:", df_hoy['Folio de viaje'].unique())
                    accion = st.text_input("Acción a tomar (Ej. Fusionar, Inyectar Bus):")
                    responsable = st.text_input("Asignar a:")
                    estado_tarea = st.selectbox("Estado:", ["Pendiente", "En revisión", "Resuelto"])
                    btn_guardar_tarea = st.form_submit_button("Guardar Decisión")
                    
                    if btn_guardar_tarea and accion:
                        c.execute("INSERT INTO decisiones (folio_viaje, fecha_registro, usuario, accion_tomada, responsable, estado) VALUES (?, ?, ?, ?, ?, ?)",
                                  (folio_tarea, hoy_dt.strftime('%Y-%m-%d %H:%M'), st.session_state['usuario'], accion, responsable, estado_tarea))
                        conn.commit()
                        st.success("Decisión registrada.")
                        
            with col_d2:
                df_decisiones = pd.read_sql_query('SELECT folio_viaje, fecha_registro, accion_tomada, responsable, estado FROM decisiones ORDER BY id DESC LIMIT 10', conn)
                if not df_decisiones.empty:
                    st.write("Últimas acciones registradas:")
                    def color_estado(val):
                        if val == 'Pendiente': return 'color: red;'
                        elif val == 'Resuelto': return 'color: green;'
                        return 'color: orange;'
                    st.dataframe(df_decisiones.style.map(color_estado, subset=['estado']), use_container_width=True)

        # PESTAÑA 2: ANÁLISIS FINANCIERO
        with tab2:
            st.markdown("### 💰 Análisis Comercial y Punto de Equilibrio")
            st.write(f"*Cálculos basados en un costo estimado por salida de **${costo_salida:,.0f}***")
            
            col_f1, col_f2, col_f3 = st.columns(3)
            promedio_yield = df_hoy[df_hoy['Vendidos'] > 0]['Ingreso por Pasaje'].mean()
            promedio_revpar = df_hoy[df_hoy['Capacidad'] > 0]['Ingreso por Asiento Total'].mean()
            buses_rentables = len(df_hoy[df_hoy['Estado Financiero'] == '✅ Rentable'])
            
            col_f1.metric("Ingreso Promedio por Pasaje (Yield)", f"${promedio_yield:,.0f}".replace(',', '.') if pd.notna(promedio_yield) else "$0")
            col_f2.metric("Ingreso por Asiento Ofrecido (RevPAR)", f"${promedio_revpar:,.0f}".replace(',', '.') if pd.notna(promedio_revpar) else "$0")
            col_f3.metric("Viajes sobre Punto de Equilibrio", f"{buses_rentables} de {total_servicios}", f"{(buses_rentables/total_servicios*100):.1f}% de la flota" if total_servicios > 0 else "0%")

            st.markdown("#### 🏆 Participación de Recaudación por Ruta")
            df_finanzas_ruta = df_hoy.groupby('Ruta').agg(
                Salidas=('Folio de viaje', 'count'),
                Recaudación_Total=('Valor de planilla CLP', 'sum'),
                Margen_Neto=('Margen Estimado', 'sum')
            ).reset_index().sort_values('Recaudación_Total', ascending=False)
            
            st.dataframe(df_finanzas_ruta.style.format({'Recaudación_Total': '${:,.0f}', 'Margen_Neto': '${:,.0f}'}), use_container_width=True)
            
            st.markdown("#### 🚨 Viajes Operando a Pérdida (Bajo el Costo de Salida)")
            df_perdida = df_hoy[df_hoy['Estado Financiero'] == '❌ Pérdida'][['Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 'Valor de planilla CLP', 'Margen Estimado']]
            
            def highlight_loss(val):
                return 'color: red; font-weight: bold;' if isinstance(val, (int, float)) and val < 0 else ''
                
            st.dataframe(df_perdida.style.format({'Valor de planilla CLP': '${:,.0f}', 'Margen Estimado': '${:,.0f}'}).map(highlight_loss, subset=['Margen Estimado']), use_container_width=True)

        # PESTAÑA 3: PROYECCIONES
        with tab3:
            st.markdown("### 🎯 Estimación de Ocupación Final")
            if not df_cruce.empty and 'Proyección Cierre (Vendidos)' in df_cruce.columns:
                col_proy = ['Folio de viaje', 'Fecha salida', 'Hora salida', 'Ruta', 'Vendidos', 'Proyección Cierre (Vendidos)', 'Capacidad', 'Ocupación %', 'Proyección Cierre (%)']
                df_proyeccion = df_cruce[col_proy].sort_values('Proyección Cierre (%)', ascending=False)
                
                def highlight_full(val):
                    if isinstance(val, (int, float)) and val >= 95: return 'background-color: #d4edda; color: black; font-weight: bold;'
                    return ''
                st.dataframe(df_proyeccion.style.map(highlight_full, subset=['Proyección Cierre (%)']), use_container_width=True)
            else:
                st.info("Necesitas guardar al menos 2 reportes para proyectar el cierre.")

        # PESTAÑA 4: SIMULADOR DE ROTATIVA
        with tab4:
            st.markdown("### ⚙️ Simulador de Cambio de Capacidad")
            st.write("Selecciona un folio para evaluar el impacto de cambiar el tamaño del bus asignado.")
            folio_simular = st.selectbox("Seleccionar Folio a Simular:", df_hoy['Folio de viaje'].unique(), key='sim_folio')
            if folio_simular:
                datos_sim = df_hoy[df_hoy['Folio de viaje'] == folio_simular].iloc[0]
                col_s1, col_s2, col_s3 = st.columns(3)
                with col_s1: st.metric("Asientos Vendidos Actuales", datos_sim['Vendidos'])
                with col_s2: st.metric("Capacidad Actual Programada", datos_sim['Capacidad'])
                with col_s3: st.metric("Ocupación Actual", f"{datos_sim['Pct Numérico']}%")
                
                st.markdown("---")
                nueva_capacidad = st.slider("Simular Nueva Capacidad del Bus:", min_value=30, max_value=80, value=int(datos_sim['Capacidad']), step=1)
                
                if nueva_capacidad != datos_sim['Capacidad']:
                    nueva_ocupacion = (datos_sim['Vendidos'] / nueva_capacidad) * 100
                    nuevos_libres = nueva_capacidad - datos_sim['Vendidos']
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Nueva Ocupación Proyectada", f"{nueva_ocupacion:.1f}%", f"{nueva_ocupacion - datos_sim['Pct Numérico']:.1f}%")
                    c2.metric("Nuevos Asientos Disponibles", nuevos_libres, f"{nuevos_libres - datos_sim['Asientos Disponibles']} asientos")
                    
                    if nueva_ocupacion < 30: st.error("⚠️ Alerta: Conducir este bus con esta capacidad generará rentabilidad crítica.")
                    elif nueva_ocupacion > 90: st.success("✅ Excelente: Maximización de rentabilidad sin riesgo de sobreventa inminente.")

        # PESTAÑA 5: AGENDA POR TERMINAL
        with tab5:
            st.markdown("### 🕒 Agenda Diaria de Salidas por Terminal")
            terminal = st.selectbox("Seleccionar Terminal de Origen:", df_hoy['Origen (ciudad)'].unique())
            if terminal:
                df_terminal = df_hoy[df_hoy['Origen (ciudad)'] == terminal].copy()
                df_agenda = df_terminal.groupby(['Fecha salida', 'Hora salida']).agg(
                    Salidas=('Folio de viaje', 'count'), Capacidad_Total=('Capacidad', 'sum'), Vendidos_Total=('Vendidos', 'sum')
                ).reset_index()
                df_agenda['Ocupación Horaria %'] = ((df_agenda['Vendidos_Total'] / df_agenda['Capacidad_Total']) * 100).round(1)
                df_agenda['Exceso de Plazas Libres'] = df_agenda['Capacidad_Total'] - df_agenda['Vendidos_Total']
                
                def highlight_exceso(val):
                    if isinstance(val, (int, float)) and val > 50: return 'background-color: #f8d7da; color: black;'
                    return ''
                    
                st.write(f"Vista operativa para las salidas desde **{terminal}**:")
                st.dataframe(df_agenda.style.map(highlight_exceso, subset=['Exceso de Plazas Libres']), use_container_width=True)

        # PESTAÑA 6: GRÁFICOS Y CURVAS
        with tab6:
            st.markdown("### 🔍 Análisis Visual")
            col_g1, col_g2 = st.columns([1, 2])
            with col_g1:
                resumen_estado = df_hoy['Acción Sugerida'].value_counts().reset_index()
                resumen_estado.columns = ['Estado', 'Cantidad']
                def map_color(estado):
                    if 'ALTA DEMANDA' in estado: return '#28a745'
                    if 'MEDIO' in estado: return '#ffc107'
                    return '#dc3545'
                colores_pie = [map_color(e) for e in resumen_estado['Estado']]
                fig_pie = px.pie(resumen_estado, values='Cantidad', names='Estado', hole=0.4, color_discrete_sequence=colores_pie, title="Distribución de Flota")
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_g2:
                if not df_historial.empty:
                    folio_buscar = st.selectbox("Evolución Histórica de Ventas por Folio:", df_hoy['Folio de viaje'].unique())
                    if folio_buscar:
                        hist_data = df_historial[df_historial['folio_viaje'] == folio_buscar].sort_values('fecha_carga')
                        if len(hist_data) > 1:
                            fig_line = px.line(hist_data, x='fecha_carga', y='asientos_vendidos', markers=True, title=f"Folio {folio_buscar}")
                            cap_max = hist_data['capacidad'].iloc[0]
                            fig_line.add_hline(y=cap_max, line_dash="dash", line_color="red", annotation_text=f"Capacidad ({cap_max})")
                            st.plotly_chart(fig_line, use_container_width=True)
            
    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")

conn.close()
