import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Centro de Comando | Rentabilidad", layout="wide", page_icon="🚌")

# --- SISTEMA DE LOGIN BÁSICO ---
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

# --- CONEXIÓN A BASE DE DATOS ---
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
    """Extrae datos exactos de la columna 'Ocupación Relativa'"""
    # 1. Separar asientos
    temp = df['Ocupación Relativa'].astype(str).str.split('/', n=1, expand=True)
    df['Cantidad de asientos vendidos'] = pd.to_numeric(temp[0], errors='coerce').fillna(0).astype(int)
    
    temp2 = temp[1].str.split(' ', n=1, expand=True)
    df['Capacidad del bus'] = pd.to_numeric(temp2[0], errors='coerce').fillna(1).astype(int)
    
    # 2. Porcentaje Exacto
    df['Ocupación relativa %'] = df['Ocupación Relativa'].str.extract(r'\((.*?)\)')
    df['Pct Numérico'] = pd.to_numeric(df['Ocupación relativa %'].str.replace('%', ''), errors='coerce').fillna(0)
    
    # 3. Datos Extra
    df['Valor de planilla CLP'] = pd.to_numeric(df['Valor de planilla CLP'], errors='coerce').fillna(0).astype(int)
    df['Folio de viaje'] = df['Folio de viaje'].astype(str)
    
    return df

def categorizar_accion(pct):
    """Clasificación estricta de rentabilidad basada en % de ocupación"""
    if pct >= 71:
        return '🟢 ALTA DEMANDA (Posible Inyección)'
    elif 30 <= pct <= 70:
        return '🟡 MEDIO (Rendimiento Normal)'
    else:
        return '🔴 CRÍTICO (Baja Ocupación)'

def aplicar_color_fila(val):
    """Devuelve el estilo CSS para la celda según la alerta"""
    if 'ALTA DEMANDA' in str(val):
        return 'background-color: #d4edda; color: black;' # Verde claro
    elif 'MEDIO' in str(val):
        return 'background-color: #fff3cd; color: black;' # Amarillo claro
    elif 'CRÍTICO' in str(val):
        return 'background-color: #f8d7da; color: black;' # Rojo claro
    return ''

# --- INTERFAZ DEL DASHBOARD ---
st.title(f"📊 Centro de Comando de Flota - Hola, {st.session_state['usuario'].capitalize()}")
st.markdown("Sube el reporte diario para compararlo con el historial y detectar oportunidades de negocio.")

archivo_subido = st.file_uploader("📥 Subir Reporte de Ocupación de Terra", type=["xlsx"])

if archivo_subido is not None:
    try:
        # 1. Procesamiento Inicial
        df_hoy = pd.read_excel(archivo_subido, skiprows=1)
        df_hoy = procesar_ocupacion(df_hoy)
        df_hoy = df_hoy[df_hoy['Estado de viaje'] == 'Activo'].copy()
        
        # Aplicamos la nueva lógica semáforo
        df_hoy['Acción Sugerida'] = df_hoy['Pct Numérico'].apply(categorizar_accion)

        hoy_dt = datetime.now()
        fecha_carga = hoy_dt.strftime('%Y-%m-%d %H:%M:%S')

        # 2. Botón de Guardado
        if st.button("💾 Guardar este reporte en el Historial"):
            for index, row in df_hoy.iterrows():
                c.execute('''
                    INSERT INTO historial (fecha_carga, usuario, folio_viaje, fecha_salida, hora_salida, ruta, asientos_vendidos, capacidad, monto)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (fecha_carga, st.session_state['usuario'], str(row['Folio de viaje']), str(row['Fecha salida']), 
                      str(row['Hora salida']), str(row['Ruta']), row['Cantidad de asientos vendidos'], row['Capacidad del bus'], row['Valor de planilla CLP']))
            conn.commit()
            st.success("✅ Historial guardado correctamente en la base de datos.")

        # 3. Velocidad de Venta
        st.subheader("⚡ Velocidad de Venta (Comparativa con el último registro)")
        df_historial = pd.read_sql_query('SELECT * FROM historial ORDER BY id DESC', conn)
        
        if not df_historial.empty:
            df_historial_unico = df_historial.drop_duplicates(subset=['folio_viaje'], keep='first')
            df_cruce = pd.merge(df_hoy, df_historial_unico[['folio_viaje', 'asientos_vendidos']], left_on='Folio de viaje', right_on='folio_viaje', how='left')
            df_cruce['Crecimiento_24h'] = df_cruce['Cantidad de asientos vendidos'] - df_cruce['asientos_vendidos'].fillna(df_cruce['Cantidad de asientos vendidos'])
            
            viajes_top = df_cruce.sort_values(by='Crecimiento_24h', ascending=False).head(3)
            
            col1, col2, col3 = st.columns(3)
            for i, (idx, row) in enumerate(viajes_top.iterrows()):
                cols = [col1, col2, col3]
                with cols[i]:
                    st.metric(label=f"🔥 {row['Ruta'][:20]}... ({row['Fecha salida']} {row['Hora salida']})", 
                              value=f"{int(row['Cantidad de asientos vendidos'])} vendidos", 
                              delta=f"+{int(row['Crecimiento_24h'])} vs último reporte")
        else:
            st.info("ℹ️ Guarda este primer reporte para que mañana el sistema pueda calcular la velocidad de venta.")

        # 4. Tabla Táctica
        st.subheader("📋 Panel de Acción Táctica")
        
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
        
        # Ordenar primero por los críticos
        df_mostrar = df_hoy[columnas_ver].sort_values(by=['Acción Sugerida', 'Fecha salida'], ascending=[True, True])
        
        # Aplicamos los tres colores a la columna de acción
        st.dataframe(df_mostrar.style.map(
            aplicar_color_fila,
            subset=['Acción Sugerida']
        ), use_container_width=True)

        # 5. Exportar a Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_mostrar.to_excel(writer, sheet_name='Acciones Requeridas', index=False)
            
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

conn.close()
