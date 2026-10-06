import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Centro de Comando | Rentabilidad", layout="wide", page_icon="🚌")

# --- SISTEMA DE LOGIN BÁSICO ---
# Credenciales de prueba (En producción se pueden cambiar o encriptar)
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
    st.stop() # Detiene la ejecución de la app si no hay login exitoso

# --- CONEXIÓN A BASE DE DATOS (HISTORIAL) ---
# Crea un archivo local SQLite para guardar el historial
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

# --- FUNCIONES DE ANÁLISIS ---
def procesar_ocupacion(df):
    """Extrae datos exactos de la columna 'Ocupación Relativa' Ej: '1/42 (2.38%)' -> 1, 42 y '2.38%'"""
    # 1. Separar los asientos vendidos
    temp = df['Ocupación Relativa'].astype(str).str.split('/', n=1, expand=True)
    df['Cantidad de asientos vendidos'] = pd.to_numeric(temp[0], errors='coerce').fillna(0).astype(int)
    
    # 2. Separar la capacidad del bus
    temp2 = temp[1].str.split(' ', n=1, expand=True)
    df['Capacidad del bus'] = pd.to_numeric(temp2[0], errors='coerce').fillna(1).astype(int)
    
    # 3. Extraer el porcentaje exacto (lo que está dentro de los paréntesis)
    df['Ocupación relativa %'] = df['Ocupación Relativa'].str.extract(r'\((.*?)\)')
    
    # 4. Crear columnas matemáticas internas (invisibles) para el algoritmo del Semáforo
    df['Pct Numérico'] = pd.to_numeric(df['Ocupación relativa %'].str.replace('%', ''), errors='coerce').fillna(0)
    df['Asientos Libres'] = df['Capacidad del bus'] - df['Cantidad de asientos vendidos']
    
    # 5. Formatear Valor de planilla y Folio
    df['Valor de planilla CLP'] = pd.to_numeric(df['Valor de planilla CLP'], errors='coerce').fillna(0).astype(int)
    df['Folio de viaje'] = df['Folio de viaje'].astype(str) # Se pasa a texto para evitar que se vea con comas ej: 8,399
    
    return df

def categorizar_accion(pct, libres, horas_faltantes):
    if pct >= 85 and libres <= 5:
        return '🟢 INYECTAR BUS (Alta Demanda)'
    elif pct <= 25 and horas_faltantes < 48:
        return '🔴 RIESGO (Evaluar Fusión)'
    else:
        return '🟡 NORMAL'

# --- INTERFAZ DEL DASHBOARD ---
st.title(f"📊 Centro de Comando de Flota - Hola, {st.session_state['usuario'].capitalize()}")
st.markdown("Sube el reporte diario para compararlo con el historial y detectar oportunidades de negocio.")

archivo_subido = st.file_uploader("📥 Subir Reporte de Ocupación de Terra", type=["xlsx"])

if archivo_subido is not None:
    try:
        # 1. Leer y Procesar
        df_hoy = pd.read_excel(archivo_subido, skiprows=1)
        df_hoy = procesar_ocupacion(df_hoy)
        
        # Filtramos solo los viajes activos
        df_hoy = df_hoy[df_hoy['Estado de viaje'] == 'Activo'].copy()
        
        # Calcular horas faltantes aproximadas para el semáforo
        hoy_dt = datetime.now()
        df_hoy['Fecha_Hora_dt'] = pd.to_datetime(df_hoy['Fecha salida'] + ' ' + df_hoy['Hora salida'], format='%d/%m/%Y %H:%M', errors='coerce')
        df_hoy['Horas_Faltantes'] = (df_hoy['Fecha_Hora_dt'] - hoy_dt).dt.total_seconds() / 3600
        df_hoy['Horas_Faltantes'] = df_hoy['Horas_Faltantes'].fillna(999)
        
        # Aplicar el semáforo basado en el % Numérico extraído
        df_hoy['Acción Sugerida'] = df_hoy.apply(lambda row: categorizar_accion(row['Pct Numérico'], row['Asientos Libres'], row['Horas_Faltantes']), axis=1)

        # 2. Guardar en Base de Datos
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')
        if st.button("💾 Guardar este reporte en el Historial"):
            for index, row in df_hoy.iterrows():
                c.execute('''
                    INSERT INTO historial (fecha_carga, usuario, folio_viaje, fecha_salida, hora_salida, ruta, asientos_vendidos, capacidad, monto)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (fecha_carga, st.session_state['usuario'], str(row['Folio de viaje']), str(row['Fecha salida']), 
                      str(row['Hora salida']), str(row['Ruta']), row['Cantidad de asientos vendidos'], row['Capacidad del bus'], row['Valor de planilla CLP']))
            conn.commit()
            st.success("✅ Historial guardado correctamente en la base de datos.")

        # 3. Comparativa con Ayer (Cruzar Folios)
        st.subheader("⚡ Velocidad de Venta (Comparativa con el último registro)")
        
        # Leer el historial de la DB
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            
            # Cruzar datos
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_24h'] = df_cruce['Cantidad de asientos vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Cantidad de asientos vendidos'])
            
            # Mostrar métricas destacadas
            viajes_top = df_cruce.sort_values(by='Crecimiento_24h', ascending=False).head(3)
            
            col1, col2, col3 = st.columns(3)
            for i, (idx, row) in enumerate(viajes_top.iterrows()):
                cols = [col1, col2, col3]
                with cols[i]:
                    st.metric(label=f"🔥 {row['Ruta'][:20]}... ({row['Fecha salida']})", 
                              value=f"{int(row['Cantidad de asientos vendidos'])} vendidos", 
                              delta=f"+{int(row['Crecimiento_24h'])} vs último reporte")
        else:
            st.info("ℹ️ Guarda este primer reporte para que mañana el sistema pueda calcular la velocidad de venta.")

        # 4. Vista de Tabla Táctica con las Columnas Solicitadas
        st.subheader("📋 Panel de Acción Táctica")
        
        # Estas son las columnas exactas que pediste ver
        columnas_ver = [
            'Folio de viaje', 
            'Fecha salida', 
            'Hora salida', 
            'Origen (ciudad)', 
            'Destino (ciudad)', 
            'Cantidad de asientos vendidos', 
            'Capacidad del bus', 
            'Ocupación relativa %', 
            'Valor de planilla CLP', 
            'Acción Sugerida'
        ]
        
        # Ordenamos los viajes para ver primero los más urgentes y con mayor ocupación
        df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
        
        # Mostrar tabla coloreada
        st.dataframe(df_mostrar.style.map(
            lambda x: 'background-color: #d4edda; color: black;' if 'INYECTAR' in str(x) else ('background-color: #f8d7da; color: black;' if 'RIESGO' in str(x) else ''),
            subset=['Acción Sugerida']
        ), use_container_width=True)

        # 5. Generar Excel Táctico Descargable
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_mostrar.to_excel(writer, sheet_name='Acciones Requeridas', index=False)
            
            # Segunda pestaña: Resumen Financiero basado en Planillas
            df_finanzas = df_hoy.groupby(['Fecha salida', 'Ruta']).agg({
                'Valor de planilla CLP': 'sum', 
                'Cantidad de asientos vendidos': 'sum'
            }).reset_index()
            df_finanzas.to_excel(writer, sheet_name='Proyección Financiera', index=False)
            
        st.download_button(
            label="📥 Descargar Excel Táctico",
            data=output.getvalue(),
            file_name=f"Reporte_Tactico_Ocupacion_{hoy_dt.strftime('%d%m%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
            
    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")

# Cerrar conexión al terminar
conn.close()
