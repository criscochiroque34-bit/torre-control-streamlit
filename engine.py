"""
Motor de cruce — Torre de Control de Despacho
Misma lógica validada en la versión HTML, portada a pandas para manejar
archivos pesados (TMS con millones de filas) en segundos.
"""
import pandas as pd
import numpy as np
import unicodedata
import re
import zipfile
import io

FLOTAS_VALIDAS = ['OF MOTORIZADOS', 'VANS RUTEO DINAMICO', 'VANS RUTEO ESTATICO']
FLOTA_LABELS = {
    'OF MOTORIZADOS': 'OF MOTORIZADOS',
    'VANS RUTEO DINAMICO': 'VANS RUTEO DINÁMICO',
    'VANS RUTEO ESTATICO': 'VANS RUTEO ESTÁTICO',
}

TMS_MAP = {
    'EN REPARTO':           {'cat': 'dispatched', 'label': 'En reparto'},
    'ENTREGADO':            {'cat': 'dispatched', 'label': 'Entregado'},
    'EXCEPCION DE ENTREGA': {'cat': 'dispatched', 'label': 'Excepción de entrega'},
    'EN BODEGA CROSSDOCK':  {'cat': 'pending',    'label': 'En bodega'},
    'REENVIO CLIENTE':      {'cat': 'pending',    'label': 'Reenvío'},
    'REGISTRADO':           {'cat': 'review',     'label': 'Registrado'},
    'CUARENTENA':           {'cat': 'quarantine', 'label': 'Cuarentena'},
}

# Estados de TMS que se IGNORAN (se tratan como "sin registro") para las
# 3 flotas actuales. Ej: "Tránsito local" no aplica para estas flotas hoy,
# pero al escalar a otras flotas podría sí ser relevante para ellas.
TMS_IGNORAR_PARA_FLOTAS_ACTUALES = {'TRANSITO LOCAL'}

# Posiciones de columna por índice (A=0, B=1, ... E=4, G=6, K=10, M=12, T=19)
COL_ZEUS_CODIGO, COL_ZEUS_FLOTA, COL_ZEUS_FECHA, COL_ZEUS_TIPOREC, COL_ZEUS_BULTOS = 0, 4, 6, 12, 19
COL_ETI_CODIGO, COL_ETI_FECHA = 0, 4
COL_ANC_CODIGO, COL_ANC_CONO, COL_ANC_FECHA = 0, 4, 10


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def norm(s):
    """Normaliza texto: sin BOM, sin tildes, mayúsculas, espacios colapsados."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ''
    s = str(s).replace('\ufeff', '').strip().upper()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s)


def norm_code(v):
    """Normaliza un código para cruce tipo BUSCARV: texto exacto, sin BOM,
    sin '.0' residual de floats, mayúsculas (case-insensitive)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, (int, np.integer)):
        return str(v)
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return str(v)
    s = str(v).replace('\ufeff', '').strip()
    if re.match(r'^\d+\.0+$', s):
        s = re.sub(r'\.0+$', '', s)
    return s.upper()


# ---------------------------------------------------------------------------
# Lectores de archivo
# ---------------------------------------------------------------------------
def read_excel_positional(file) -> pd.DataFrame:
    """Lee un Excel sin asumir nombres de columna — todo por posición.
    header=None para no perder la fila 1 si no es encabezado real,
    luego se descarta la primera fila (encabezados)."""
    df = pd.read_excel(file, header=None, dtype=object)
    # primera fila = encabezados -> se descarta para el motor
    return df.iloc[1:].reset_index(drop=True)


def _detect_encoding(head: bytes) -> str:
    """Detecta el encoding por los primeros bytes (BOM)."""
    if head.startswith(b'\xff\xfe') or head.startswith(b'\xfe\xff'):
        return 'utf-16'          # UTF-16 LE/BE (común en exports "Unicode" de Windows)
    if head.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'       # UTF-8 con BOM
    return 'utf-8-sig'           # default, con fallback más abajo


def _read_csv_bytes(raw_bytes: bytes) -> pd.DataFrame:
    """Lee bytes de CSV probando encodings, priorizando el motor C (rápido).
    Solo cae a engine='python' con detección de separador como último recurso."""
    primary = _detect_encoding(raw_bytes[:4])
    encodings = list(dict.fromkeys([primary, 'utf-8-sig', 'utf-16', 'latin-1']))

    # 1) Intento rápido: motor C, separador coma (caso normal, millones de filas en segundos)
    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, dtype=str, low_memory=False)
            # si quedó todo en una sola columna, el separador no era coma -> fallback
            if df.shape[1] > 1:
                return df
        except UnicodeDecodeError:
            continue
        except Exception:
            continue

    # 2) Fallback lento: detectar separador automáticamente
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, dtype=str,
                                sep=None, engine='python')
        except UnicodeDecodeError:
            continue

    raise ValueError('No se pudo leer el CSV con ningún encoding/separador conocido')


def read_tms(file, filename: str) -> tuple[pd.DataFrame, int]:
    """Lee el TMS (zip->csv o csv directo), deduplicando por código
    quedándose con el registro MÁS RECIENTE. Devuelve (df_dedup, total_filas_raw).
    Usa pandas/C para que archivos de millones de filas tarden segundos.
    Detecta automáticamente el encoding (UTF-8 con BOM, UTF-16, latin-1)."""
    if filename.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(file.read())) as z:
            csv_name = next((n for n in z.namelist() if re.search(r'\.(csv|txt)$', n, re.I)), None)
            if not csv_name:
                raise ValueError('No se encontró CSV dentro del ZIP')
            raw_bytes = z.read(csv_name)
    else:
        raw_bytes = file.read()

    raw = _read_csv_bytes(raw_bytes)

    # normalizar nombres de columna (sin BOM/tildes/mayúsculas)
    raw.columns = [norm(c) for c in raw.columns]

    cod_col, est_col, fecha_col = 'NUMERO', 'NOMBREESTADOENVIO', 'ENREPARTO'
    for required in (cod_col, est_col):
        if required not in raw.columns:
            raise ValueError(f"No se encontró la columna '{required}' en el TMS. "
                              f"Columnas disponibles: {', '.join(raw.columns[:15])}...")

    total_raw = len(raw)
    raw['_cod'] = raw[cod_col].apply(norm_code)
    raw = raw[raw['_cod'] != '']
    if fecha_col in raw.columns:
        raw['_fecha'] = pd.to_datetime(raw[fecha_col], errors='coerce', dayfirst=False)
    else:
        raw['_fecha'] = pd.NaT

    # quedarse con el más reciente por código
    raw = raw.sort_values('_fecha', na_position='first')
    dedup = raw.groupby('_cod', as_index=False).last()
    return dedup, total_raw


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------
def run_engine(zeus_df, etiq_df, anc_df, tms_df, desde, hasta):
    """Ejecuta el cruce completo. Devuelve dict con:
       pedidos (DataFrame), sin_recepcion (DataFrame), stats por flota."""

    # ---- Zeus: normalizar, filtrar ventana, quedarse con el más reciente, filtrar flota
    z = zeus_df.copy()
    z['_cod'] = z[COL_ZEUS_CODIGO].apply(norm_code)
    z['_fecha'] = pd.to_datetime(z[COL_ZEUS_FECHA], errors='coerce')
    z['_flota'] = z[COL_ZEUS_FLOTA].apply(norm)
    z['_bultos'] = pd.to_numeric(z[COL_ZEUS_BULTOS], errors='coerce').fillna(1).astype(int).clip(lower=1)
    z['_tiporecep'] = z[COL_ZEUS_TIPOREC]
    z = z[z['_cod'] != '']
    z = z[(z['_fecha'] >= desde) & (z['_fecha'] <= hasta)]
    z = z.sort_values('_fecha').groupby('_cod', as_index=False).last()
    z_validas = z[z['_flota'].isin(FLOTAS_VALIDAS)].copy()

    # ---- Etiquetado: normalizar, filtrar ventana, set de códigos presentes
    e = etiq_df.copy()
    e['_cod'] = e[COL_ETI_CODIGO].apply(norm_code)
    e['_fecha'] = pd.to_datetime(e[COL_ETI_FECHA], errors='coerce')
    e = e[e['_cod'] != '']
    e = e[(e['_fecha'] >= desde) & (e['_fecha'] <= hasta)]
    etiq_codes = set(e['_cod'].unique())

    # ---- Anclaje: normalizar, filtrar ventana, contar filas por código + cono más reciente
    a = anc_df.copy()
    a['_cod'] = a[COL_ANC_CODIGO].apply(norm_code)
    a['_fecha'] = pd.to_datetime(a[COL_ANC_FECHA], errors='coerce')
    a['_cono'] = a[COL_ANC_CONO]
    a = a[a['_cod'] != '']
    a = a[(a['_fecha'] >= desde) & (a['_fecha'] <= hasta)]
    anc_counts = a.groupby('_cod').size().to_dict()
    anc_cono = a.sort_values('_fecha').groupby('_cod')['_cono'].last().to_dict()

    # ---- TMS: ya viene deduplicado (más reciente por código), sin filtro de ventana
    tms_estado = {}
    if tms_df is not None and len(tms_df):
        for _, row in tms_df.iterrows():
            tms_estado[row['_cod']] = row['NOMBREESTADOENVIO']

    # ---- Construir pedidos (universo = Zeus filtrado por flota)
    pedidos = []
    zeus_codes = set(z['_cod'])
    for _, row in z_validas.iterrows():
        cod = row['_cod']
        flota = row['_flota']
        bultos = int(row['_bultos'])
        etiq = cod in etiq_codes
        anc_count = anc_counts.get(cod, 0)
        cono = anc_cono.get(cod)
        tms_raw = tms_estado.get(cod)
        tms_norm = norm(tms_raw) if tms_raw else None
        # "Tránsito local" no aplica para las flotas actuales -> tratar como sin registro TMS
        if tms_norm in TMS_IGNORAR_PARA_FLOTAS_ACTUALES and flota in FLOTAS_VALIDAS:
            tms_raw, tms_norm = None, None
        tms_info = TMS_MAP.get(tms_norm) if tms_norm else None
        p = {
            'codigo': cod, 'flota': flota, 'bultos': bultos,
            'recep': True, 'etiq': etiq, 'anc_count': anc_count, 'cono': cono,
            'tms_cat': tms_info['cat'] if tms_info else None,
            'tms_label': tms_info['label'] if tms_info else (tms_raw if tms_raw else None),
        }
        p['estado_label'], p['estado_cat'] = _compute_estado(p)
        pedidos.append(p)

    pedidos_df = pd.DataFrame(pedidos)

    # ---- Sin recepción: códigos en etiquetado/anclaje/TMS pero no en Zeus
    sin_recep = []
    seen = set()
    tms_codes = set(tms_estado.keys())
    for cod in (etiq_codes | set(anc_counts.keys()) | tms_codes):
        if cod in zeus_codes or cod in seen:
            continue
        seen.add(cod)
        tms_raw = tms_estado.get(cod)
        tms_info = TMS_MAP.get(norm(tms_raw)) if tms_raw else None
        sin_recep.append({
            'codigo': cod, 'flota': '—',
            'etiq': cod in etiq_codes, 'anc_count': anc_counts.get(cod, 0),
            'cono': anc_cono.get(cod),
            'tms_cat': tms_info['cat'] if tms_info else None,
            'tms_label': tms_info['label'] if tms_info else (tms_raw if tms_raw else None),
            'estado_label': 'Sin recepción', 'estado_cat': 'alert', 'bultos': 0,
        })
    sin_recep_df = pd.DataFrame(sin_recep)

    return {'pedidos': pedidos_df, 'sin_recepcion': sin_recep_df,
            'tms_total_raw': None}


def _compute_estado(p):
    is_van = p['flota'] != 'OF MOTORIZADOS'
    if p['tms_cat'] == 'quarantine':
        return 'No debe salir', 'priority'
    # Si TMS confirma que salió, cuenta como Despachado sin problemas,
    # sin importar si falta etiquetado/anclaje (solo Cuarentena lo bloquea).
    if p['tms_cat'] == 'dispatched':
        return ('Entregado' if p['tms_label'] == 'Entregado' else 'Despachado'), 'ok'
    if not p['etiq']:
        return 'Sin etiquetar', 'alert'
    if is_van:
        if p['anc_count'] == 0:
            return 'Sin anclar', 'alert'
        if p['anc_count'] < p['bultos']:
            return 'Anclaje parcial', 'alert'
    if p['tms_cat'] == 'pending':
        return f"No salió ({p['tms_label']})", 'warn'
    if p['tms_cat'] == 'review':
        return 'Revisar', 'orange'
    return 'Pendiente TMS', 'warn'


# ---------------------------------------------------------------------------
# Agrupación por cono (vista de migración TMS)
# ---------------------------------------------------------------------------
def build_conos(pedidos_df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve un DataFrame con una fila por cono: total, migrados, pendientes."""
    vans = pedidos_df[pedidos_df['flota'] != 'OF MOTORIZADOS']
    vans = vans[vans['cono'].notna() & (vans['cono'].astype(str) != '')]
    if vans.empty:
        return pd.DataFrame(columns=['cono', 'flota', 'total', 'migrados', 'sin_migrar', 'pct'])

    rows = []
    for cono, grp in vans.groupby('cono'):
        total = len(grp)
        migrados = (grp['tms_cat'] == 'dispatched').sum()
        rows.append({
            'cono': cono,
            'flota': grp['flota'].iloc[0],
            'total': total,
            'migrados': migrados,
            'sin_migrar': total - migrados,
            'pct': round(migrados / total * 100) if total else 0,
        })
    df = pd.DataFrame(rows).sort_values('sin_migrar', ascending=False).reset_index(drop=True)
    return df
