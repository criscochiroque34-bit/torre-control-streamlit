"""
Motor de cruce — Torre de Control de Despacho
Procesa archivos pesados con pandas (TMS de millones de filas en segundos).
"""
import pandas as pd
import numpy as np
import unicodedata
import re
import zipfile
import io

FLOTAS_VALIDAS = ['OF MOTORIZADOS', 'VANS RUTEO DINAMICO', 'VANS RUTEO ESTATICO']
FLOTA_LABELS = {
    'OF MOTORIZADOS':     'OF MOTORIZADOS',
    'VANS RUTEO DINAMICO':'VANS RUTEO DINÁMICO',
    'VANS RUTEO ESTATICO':'VANS RUTEO ESTÁTICO',
}

TMS_MAP = {
    'EN REPARTO':           {'cat': 'dispatched', 'label': 'En reparto'},
    'ENTREGADO':            {'cat': 'dispatched', 'label': 'Entregado'},
    'EXCEPCION DE ENTREGA': {'cat': 'dispatched', 'label': 'Excepción de entrega'},
    'EN BODEGA CROSSDOCK':  {'cat': 'pending',    'label': 'En bodega'},
    'REENVIO CLIENTE':      {'cat': 'pending',    'label': 'Reenvío'},
    'REGISTRADO':           {'cat': 'review',     'label': 'Registrado'},
    'CUARENTENA':           {'cat': 'quarantine', 'label': 'Cuarentena'},
    # Resueltos: no son pendientes ni salieron físicamente.
    'RECHAZADO':            {'cat': 'no_action',  'label': 'Rechazado'},
    'EN CUSTODIA':          {'cat': 'no_action',  'label': 'En custodia'},
    'FALLO DE ENTREGA':     {'cat': 'no_action',  'label': 'Fallo de entrega'},
    'ANULADO':              {'cat': 'no_action',  'label': 'Anulado'},
    'TRANSITO LOCAL':       {'cat': 'no_action',  'label': 'Tránsito local'},
    'EN DEVOLUCION':        {'cat': 'no_action',  'label': 'En devolución'},
}

# Posiciones de columna por índice (A=0)
COL_ZEUS_CODIGO  = 0
COL_ZEUS_FLOTA   = 4
COL_ZEUS_FECHA   = 6
COL_ZEUS_TIPOREC = 12
COL_ZEUS_BULTOS  = 19
COL_ETI_CODIGO   = 0
COL_ETI_FECHA    = 4
COL_ANC_CODIGO   = 0
COL_ANC_CONO     = 4
COL_ANC_RUTA     = 6
COL_ANC_FECHA    = 10


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def norm(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ''
    s = str(s).replace('\ufeff', '').strip().upper()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s)


def norm_code(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, (int, np.integer)):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    s = str(v).replace('\ufeff', '').strip()
    if re.match(r'^\d+\.0+$', s):
        s = re.sub(r'\.0+$', '', s)
    return s.upper()


def _clean_str(v):
    """Convierte a string limpio, devuelve '' para None/NaN."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return str(v).strip()


# ---------------------------------------------------------------------------
# Lectores de archivo
# ---------------------------------------------------------------------------
def read_excel_positional(file) -> pd.DataFrame:
    df = pd.read_excel(file, header=None, dtype=object)
    return df.iloc[1:].reset_index(drop=True)


def _detect_encoding(head: bytes) -> str:
    if head.startswith(b'\xff\xfe') or head.startswith(b'\xfe\xff'):
        return 'utf-16'
    if head.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    return 'utf-8-sig'


def _read_csv_bytes(raw_bytes: bytes) -> pd.DataFrame:
    primary = _detect_encoding(raw_bytes[:4])
    encodings = list(dict.fromkeys([primary, 'utf-8-sig', 'utf-16', 'latin-1']))
    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, dtype=str, low_memory=False)
            if df.shape[1] > 1:
                return df
        except (UnicodeDecodeError, Exception):
            continue
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, dtype=str,
                               sep=None, engine='python')
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError('No se pudo leer el CSV con ningún encoding/separador conocido')


def read_tms(file, filename: str) -> tuple[pd.DataFrame, int]:
    """Lee TMS (zip->csv o csv), deduplica por código (más reciente).
    Devuelve (df_dedup, total_filas_raw)."""
    if filename.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(file.read())) as z:
            csv_name = next((n for n in z.namelist() if re.search(r'\.(csv|txt)$', n, re.I)), None)
            if not csv_name:
                raise ValueError('No se encontró CSV dentro del ZIP')
            raw_bytes = z.read(csv_name)
    else:
        raw_bytes = file.read()

    raw = _read_csv_bytes(raw_bytes)
    raw.columns = [norm(c) for c in raw.columns]

    cod_col, est_col, fecha_col = 'NUMERO', 'NOMBREESTADOENVIO', 'ENREPARTO'
    for required in (cod_col, est_col):
        if required not in raw.columns:
            raise ValueError(f"No se encontró '{required}' en el TMS. "
                             f"Columnas: {', '.join(raw.columns[:15])}...")

    total_raw = len(raw)
    raw['_cod'] = raw[cod_col].apply(norm_code)
    raw = raw[raw['_cod'] != '']
    raw['_fecha'] = pd.to_datetime(raw[fecha_col], errors='coerce') if fecha_col in raw.columns else pd.NaT
    raw = raw.sort_values('_fecha', na_position='first')
    dedup = raw.groupby('_cod', as_index=False).last()
    return dedup, total_raw


# ---------------------------------------------------------------------------
# Helpers de lógica
# ---------------------------------------------------------------------------
def _resolve_tms(tms_raw, _flota=None):
    """Resuelve estado TMS. Desconocido -> (None, None).
    no_action se resuelve (tiene registro pero no es pendiente)."""
    if not tms_raw:
        return None, None
    tms_info = TMS_MAP.get(norm(tms_raw))
    if not tms_info:
        return None, None
    return tms_info['cat'], tms_info['label']


def _salio(tms_cat):
    return tms_cat == 'dispatched'


def _ruta_digitos(ruta) -> int:
    if ruta is None or (isinstance(ruta, float) and pd.isna(ruta)):
        return 0
    return len(re.sub(r'\D', '', str(ruta)))


def _flota_por_ruta(ruta_digs: int, anc_count: int):
    """
    Determina la flota que sugiere la ruta, desempatando con el anclaje:
      3 díg → Dinámico (exclusivo)
      2 díg → Estático si anclado, Moto si no
      1 díg → Moto si no anclado, no concluyente si anclado
      0/4+ → None
    """
    if ruta_digs == 3:
        return 'VANS RUTEO DINAMICO'
    if ruta_digs == 2:
        return 'VANS RUTEO ESTATICO' if anc_count > 0 else 'OF MOTORIZADOS'
    if ruta_digs == 1:
        return 'OF MOTORIZADOS' if anc_count == 0 else None
    return None


def _analizar_ruta_y_flota(flota: str, anc_count: int, ruta_digs: int):
    """
    Devuelve (reclasificar_a, ruta_alerta, descartar).

    Reglas:
    - 4+ dígitos → descartar (no pertenece a estas flotas)
    - Moto sin anclaje → sin ruta es normal, no se alerta
    - Van sin ruta → alerta 'Sin ruta'
    - Si la flota sugerida por ruta+anclaje ≠ flota Zeus → reclasificar
    """
    if ruta_digs >= 4:
        return None, None, True

    reclasificar_a, ruta_alerta = None, None

    if ruta_digs == 0:
        # Sin ruta: normal para moto sin anclaje; para vans o moto anclada → alerta
        if not (flota == 'OF MOTORIZADOS' and anc_count == 0):
            ruta_alerta = 'Sin ruta'
        return reclasificar_a, ruta_alerta, False

    flota_sugerida = _flota_por_ruta(ruta_digs, anc_count)
    if flota_sugerida and flota_sugerida != flota:
        reclasificar_a = flota_sugerida
    # Si flota_sugerida is None (1 dígito + anclado), no se reclasifica.
    return reclasificar_a, ruta_alerta, False


def _estado_anclaje(anc_count: int, bultos: int, is_van: bool) -> str:
    """Estado del anclaje a nivel de bultos para el reporte de discrepancias."""
    if not is_van:
        return 'N/A'
    if anc_count == 0:
        return 'Sin anclar'
    if anc_count == bultos:
        return 'Completo'
    if anc_count < bultos:
        return 'Parcial'
    return 'Exceso'  # anc_count > bultos


def _compute_estado(p: dict) -> tuple[str, str]:
    is_van = p['flota'] != 'OF MOTORIZADOS'
    tms_cat = p['tms_cat']
    if tms_cat == 'quarantine':
        return 'No debe salir', 'priority'
    if tms_cat == 'dispatched':
        return ('Entregado' if p['tms_label'] == 'Entregado' else 'Despachado'), 'ok'
    if tms_cat == 'no_action':
        return p['tms_label'], 'no_action'
    if not p['etiq']:
        return 'Sin etiquetar', 'alert'
    if is_van:
        if p['anc_count'] == 0:
            return 'Sin anclar', 'alert'
        if p['anc_count'] < p['bultos']:
            return 'Anclaje parcial', 'alert'
    if tms_cat == 'pending':
        return f"No salió ({p['tms_label']})", 'warn'
    if tms_cat == 'review':
        return 'Revisar', 'orange'
    return 'Sin registro TMS', 'warn'


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------
def run_engine(zeus_df, etiq_df, anc_df, tms_df, desde, hasta) -> dict:

    # Zeus
    z = zeus_df.copy()
    z['_cod']   = z[COL_ZEUS_CODIGO].apply(norm_code)
    z['_fecha'] = pd.to_datetime(z[COL_ZEUS_FECHA], errors='coerce')
    z['_flota'] = z[COL_ZEUS_FLOTA].apply(norm)
    z['_bultos'] = pd.to_numeric(z[COL_ZEUS_BULTOS], errors='coerce').fillna(1).astype(int).clip(lower=1)
    z = z[z['_cod'] != '']
    z = z[(z['_fecha'] >= desde) & (z['_fecha'] <= hasta)]
    z = z.sort_values('_fecha').groupby('_cod', as_index=False).last()
    z_validas = z[z['_flota'].isin(FLOTAS_VALIDAS)].copy()

    # Etiquetado
    e = etiq_df.copy()
    e['_cod']   = e[COL_ETI_CODIGO].apply(norm_code)
    e['_fecha'] = pd.to_datetime(e[COL_ETI_FECHA], errors='coerce')
    e = e[e['_cod'] != '']
    e = e[(e['_fecha'] >= desde) & (e['_fecha'] <= hasta)]
    etiq_codes = set(e['_cod'].unique())

    # Anclaje
    a = anc_df.copy()
    a['_cod']   = a[COL_ANC_CODIGO].apply(norm_code)
    a['_fecha'] = pd.to_datetime(a[COL_ANC_FECHA], errors='coerce')
    a['_cono']  = a[COL_ANC_CONO]
    a['_ruta']  = a[COL_ANC_RUTA] if COL_ANC_RUTA < a.shape[1] else None
    a = a[a['_cod'] != '']
    a = a[(a['_fecha'] >= desde) & (a['_fecha'] <= hasta)]
    anc_counts = a.groupby('_cod').size().to_dict()
    a_last     = a.sort_values('_fecha').groupby('_cod', as_index=False).last()
    anc_cono   = a_last.set_index('_cod')['_cono'].to_dict()
    anc_ruta   = a_last.set_index('_cod')['_ruta'].to_dict()

    # TMS
    tms_estado: dict[str, str] = {}
    if tms_df is not None and len(tms_df):
        for _, row in tms_df.iterrows():
            tms_estado[row['_cod']] = row['NOMBREESTADOENVIO']

    # Construir pedido
    def _build_pedido(cod: str, flota: str, bultos: int, inferido: bool):
        etiq      = cod in etiq_codes
        anc_count = anc_counts.get(cod, 0)
        cono      = anc_cono.get(cod)
        ruta_raw  = anc_ruta.get(cod)
        ruta      = _clean_str(ruta_raw)
        ruta_digs = _ruta_digitos(ruta_raw)

        reclasificar_a, ruta_alerta, descartar = _analizar_ruta_y_flota(flota, anc_count, ruta_digs)
        if descartar:
            return None

        tms_raw            = tms_estado.get(cod)
        tms_cat, tms_label = _resolve_tms(tms_raw)
        tms_real           = _clean_str(tms_raw) if tms_cat is not None else ''

        is_van = flota != 'OF MOTORIZADOS'
        p = {
            'codigo':        cod,
            'flota':         flota,
            'bultos':        bultos,
            'inferido':      inferido,
            'recep':         True,
            'etiq':          etiq,
            'anc_count':     anc_count,
            'cono':          cono,
            'ruta':          ruta,
            'ruta_digs':     ruta_digs,
            'reclasificar_a':reclasificar_a,
            'ruta_alerta':   ruta_alerta,
            'tms_cat':       tms_cat,
            'tms_label':     tms_label,
            'tms_real':      tms_real,
            'salio':         _salio(tms_cat),
            'estado_anclaje':_estado_anclaje(anc_count, bultos, is_van),
        }
        p['estado_label'], p['estado_cat'] = _compute_estado(p)
        return p

    pedidos: list = []
    zeus_codes = set(z['_cod'])
    for _, row in z_validas.iterrows():
        p = _build_pedido(row['_cod'], row['_flota'], int(row['_bultos']), inferido=False)
        if p is not None:
            pedidos.append(p)

    # Mapa cono → flota (solo vans de Zeus)
    cono_to_flota: dict = {}
    for _, row in z_validas.iterrows():
        if row['_flota'] == 'OF MOTORIZADOS':
            continue
        c = anc_cono.get(row['_cod'])
        if c is not None and _clean_str(c) != '' and c not in cono_to_flota:
            cono_to_flota[c] = row['_flota']

    # Huérfanos (en Etiquetado/Anclaje pero no en Zeus)
    sin_recep: list = []
    seen: set = set()
    for cod in (etiq_codes | set(anc_counts.keys())):
        if cod in zeus_codes or cod in seen:
            continue
        seen.add(cod)
        anc_count = anc_counts.get(cod, 0)
        cono      = anc_cono.get(cod)
        ruta_raw  = anc_ruta.get(cod)
        ruta_digs = _ruta_digitos(ruta_raw)
        ruta      = _clean_str(ruta_raw)

        # Descartar rutas de 4+ dígitos
        if ruta_digs >= 4:
            continue

        # Inferencia: 1) cono compartido, 2) ruta+anclaje como fallback
        flota_inferida = None
        if anc_count > 0 and cono is not None and _clean_str(cono) != '':
            flota_inferida = cono_to_flota.get(cono)
        if not flota_inferida and ruta_digs > 0:
            flota_inferida = _flota_por_ruta(ruta_digs, anc_count)

        if flota_inferida:
            p = _build_pedido(cod, flota_inferida, max(anc_count, 1), inferido=True)
            if p is not None:
                pedidos.append(p)
            continue

        # No se pudo inferir → Sin flota/Sin recepción
        tms_raw            = tms_estado.get(cod)
        tms_cat, tms_label = _resolve_tms(tms_raw)
        tms_real           = _clean_str(tms_raw) if tms_cat is not None else ''
        sin_recep.append({
            'codigo':        cod,
            'flota':         '—',
            'inferido':      True,
            'etiq':          cod in etiq_codes,
            'anc_count':     anc_count,
            'bultos':        0,
            'cono':          cono,
            'ruta':          ruta,
            'ruta_digs':     ruta_digs,
            'reclasificar_a':None,
            'ruta_alerta':   None,
            'tms_cat':       tms_cat,
            'tms_label':     tms_label,
            'tms_real':      tms_real,
            'salio':         _salio(tms_cat),
            'estado_anclaje':'N/A',
            'estado_label':  'Sin recepción',
            'estado_cat':    'alert',
        })

    pedidos_df   = pd.DataFrame(pedidos)
    sin_recep_df = pd.DataFrame(sin_recep)
    funnel       = build_funnel(pedidos_df)

    return {
        'pedidos':       pedidos_df,
        'sin_recepcion': sin_recep_df,
        'funnel':        funnel,
        'tms_total_raw': None,
    }


def build_funnel(pedidos_df: pd.DataFrame) -> dict:
    def stats(df, is_mot):
        total = len(df)
        if total == 0:
            return {'total':0,'etiq':0,'anc':None,'salio':0,
                    'etiq_pct':0,'anc_pct':None,'salio_pct':0}
        etiq  = int(df['etiq'].sum())
        salio = int(df['salio'].sum())
        if is_mot:
            anc, anc_pct = None, None
        else:
            anc     = int(((df['anc_count'] >= df['bultos']) & (df['bultos'] > 0)).sum())
            anc_pct = round(anc / total * 100)
        return {'total':total,'etiq':etiq,'anc':anc,'salio':salio,
                'etiq_pct':round(etiq/total*100),
                'anc_pct':anc_pct,'salio_pct':round(salio/total*100)}

    por_flota = {fl: stats(
        pedidos_df[pedidos_df['flota']==fl] if not pedidos_df.empty else pedidos_df,
        fl=='OF MOTORIZADOS') for fl in FLOTAS_VALIDAS}

    if pedidos_df.empty:
        general = stats(pedidos_df, False)
    else:
        total = len(pedidos_df)
        etiq  = int(pedidos_df['etiq'].sum())
        salio = int(pedidos_df['salio'].sum())
        vans  = pedidos_df[pedidos_df['flota'] != 'OF MOTORIZADOS']
        anc   = int(((vans['anc_count'] >= vans['bultos']) & (vans['bultos'] > 0)).sum())
        general = {
            'total':    total,
            'etiq':     etiq,
            'anc':      anc,
            'salio':    salio,
            'etiq_pct': round(etiq/total*100) if total else 0,
            'anc_pct':  round(anc/len(vans)*100) if len(vans) else 0,
            'salio_pct':round(salio/total*100) if total else 0,
            'vans_total':len(vans),
        }
    return {'general': general, 'por_flota': por_flota}


def build_conos(pedidos_df: pd.DataFrame) -> pd.DataFrame:
    """Resumen por cono: migración TMS + discrepancias de bultos."""
    vans = pedidos_df[pedidos_df['flota'] != 'OF MOTORIZADOS'].copy()
    vans = vans[vans['cono'].notna() & (vans['cono'].astype(str).str.strip() != '')]
    if vans.empty:
        return pd.DataFrame(columns=[
            'cono','flota','total','migrados','sin_migrar','pct',
            'bultos_recibidos','bultos_anclados','dif_bultos','estado_anclaje_cono'])

    rows = []
    for cono, grp in vans.groupby('cono'):
        total            = len(grp)
        migrados         = int(grp['salio'].sum())
        bultos_recib     = int(grp['bultos'].sum())
        bultos_anc       = int(grp['anc_count'].sum())
        dif              = bultos_anc - bultos_recib
        if dif == 0:
            est_anc = 'Completo'
        elif dif < 0:
            est_anc = 'Parcial'
        else:
            est_anc = 'Exceso'
        rows.append({
            'cono':               cono,
            'flota':              grp['flota'].iloc[0],
            'total':              total,
            'migrados':           migrados,
            'sin_migrar':         total - migrados,
            'pct':                round(migrados/total*100) if total else 0,
            'bultos_recibidos':   bultos_recib,
            'bultos_anclados':    bultos_anc,
            'dif_bultos':         dif,
            'estado_anclaje_cono':est_anc,
        })
    df = pd.DataFrame(rows).sort_values('sin_migrar', ascending=False).reset_index(drop=True)
    return df
