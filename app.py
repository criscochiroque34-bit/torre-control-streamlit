"""
Torre de Control · Despacho Nocturno — interfaz Streamlit (v4)
Procesa archivos pesados con pandas (TMS de millones de filas en segundos).
Toda la lógica de negocio vive en engine.py.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

from engine import (
    run_engine, build_conos, read_excel_positional, read_tms,
    FLOTAS_VALIDAS, FLOTA_LABELS,
)

st.set_page_config(page_title="Torre de Control · Despacho", layout="wide", page_icon="📦")

st.markdown("""
<style>
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;white-space:nowrap}
.b-ok{background:#0d2818;color:#2ea043;border:1px solid #1a4a25}
.b-warn{background:#241c08;color:#d29922;border:1px solid #4a3a0a}
.b-alert{background:#2a0f0f;color:#f85149;border:1px solid #4a1515}
.b-orange{background:#251608;color:#e8892b;border:1px solid #4a2a08}
.b-priority{background:#1a0a2a;color:#c084fc;border:1px solid #6b3fa0}
.b-gray{background:#1a2130;color:#8b98a5;border:1px solid #283041}
.b-cyan{background:#08222a;color:#3fb6d3;border:1px solid #1d5566}
.funnel{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0}
.fstep{flex:1;min-width:120px;background:#1c2230;border:1px solid #283041;border-radius:9px;padding:10px 13px}
.fstep .l{font-size:11px;color:#8b98a5;text-transform:uppercase;letter-spacing:.04em}
.fstep .v{font-size:21px;font-weight:700;margin-top:2px}
.fstep .p{font-size:12px;color:#8b98a5}
.fstep.s1 .v{color:#e6edf3}.fstep.s2 .v{color:#4d9fff}.fstep.s3 .v{color:#5dcaa5}.fstep.s4 .v{color:#2ea043}
.salida-ok{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px;background:#0d2818;color:#2ea043;border:1px solid #1a4a25}
.salida-no{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px;background:#241c08;color:#d29922;border:1px solid #4a3a0a}
</style>
""", unsafe_allow_html=True)


def tms_label_or_none(row):
    lbl = row.get('tms_label')
    if lbl is None or (isinstance(lbl, float) and pd.isna(lbl)):
        return 'Sin registro TMS'
    return lbl


def anc_text(row, is_van):
    if not is_van:
        return 'N/A'
    return f"{int(row['anc_count'])}/{int(row['bultos'])}"


def ruta_display(row):
    r = row.get('ruta', '')
    if r is None or (isinstance(r, float) and pd.isna(r)) or str(r) == '':
        r = '—'
    if row.get('ruta_alerta'):
        return f"{r} \u26a0"
    return str(r)


if 'result' not in st.session_state:
    st.session_state.result = None

st.title("📦 Torre de Control · Despacho Nocturno")

with st.sidebar:
    st.header("1. Archivos")
    f_zeus = st.file_uploader("Zeus (Excel)", type=["xlsx", "xls"], key="zeus")
    f_etiq = st.file_uploader("Etiquetado (Excel)", type=["xlsx", "xls"], key="etiq")
    f_anc = st.file_uploader("Anclaje (Excel)", type=["xlsx", "xls"], key="anc")
    f_tms = st.file_uploader("TMS (ZIP o CSV)", type=["zip", "csv"], key="tms")

    st.header("2. Ventana de análisis")
    if 'desde_date' not in st.session_state:
        _now = datetime.now()
        _d = _now - timedelta(hours=14)
        st.session_state.desde_date = _d.date()
        st.session_state.desde_time = _d.time()
        st.session_state.hasta_date = _now.date()
        st.session_state.hasta_time = _now.time()

    c1, c2 = st.columns(2)
    with c1:
        desde_date = st.date_input("Desde — fecha", key="desde_date")
        desde_time = st.time_input("Desde — hora", key="desde_time")
    with c2:
        hasta_date = st.date_input("Hasta — fecha", key="hasta_date")
        hasta_time = st.time_input("Hasta — hora", key="hasta_time")

    desde = pd.Timestamp(datetime.combine(desde_date, desde_time))
    hasta = pd.Timestamp(datetime.combine(hasta_date, hasta_time))

    st.divider()
    procesar = st.button("🚀 Procesar", type="primary", use_container_width=True)
    if st.button("🗑️ Limpiar", use_container_width=True):
        st.session_state.result = None
        st.rerun()

if procesar:
    if not f_zeus:
        st.error("Falta cargar el archivo Zeus.")
    elif desde >= hasta:
        st.error("La fecha 'Desde' debe ser anterior a 'Hasta'.")
    else:
        with st.spinner("Procesando archivos..."):
            try:
                zeus_df = read_excel_positional(f_zeus)
                etiq_df = read_excel_positional(f_etiq) if f_etiq else pd.DataFrame()
                anc_df = read_excel_positional(f_anc) if f_anc else pd.DataFrame()

                tms_df, tms_total = (None, 0)
                if f_tms:
                    tms_df, tms_total = read_tms(f_tms, f_tms.name)

                if etiq_df.empty:
                    etiq_df = pd.DataFrame(columns=range(5))
                if anc_df.empty:
                    anc_df = pd.DataFrame(columns=range(11))

                result = run_engine(zeus_df, etiq_df, anc_df, tms_df, desde, hasta)
                result['tms_total_raw'] = tms_total
                result['win'] = (desde, hasta)
                st.session_state.result = result
                st.success(f"Listo · {len(result['pedidos'])} pedidos"
                           + (f" · TMS: {tms_total:,} filas → {len(tms_df)} únicos" if f_tms else ""))
            except Exception as e:
                st.error(f"Error al procesar: {e}")

result = st.session_state.result
if result is None:
    st.info("Carga los archivos en la barra lateral, define la ventana y presiona **Procesar**.")
    st.stop()

pedidos = result['pedidos']
sin_recep = result['sin_recepcion']
funnel = result['funnel']
desde, hasta = result['win']

st.caption(f"📅 Ventana: {desde.strftime('%d/%m %H:%M')} → {hasta.strftime('%d/%m %H:%M')}"
           + (f"  ·  TMS: {result['tms_total_raw']:,} filas procesadas" if result.get('tms_total_raw') else ""))

if pedidos.empty:
    st.warning("No se encontraron pedidos de las flotas válidas en esta ventana. "
               "Revisa la ventana de fechas o las columnas de los archivos.")
    st.stop()

# ---- EMBUDO GENERAL ----
g = funnel['general']
st.markdown("##### Avance general del despacho")
anc_v = g['anc'] if g.get('anc') is not None else 0
anc_p = g['anc_pct'] if g.get('anc_pct') is not None else 0
vans_total = g.get('vans_total', 0)
st.markdown(f"""
<div class="funnel">
  <div class="fstep s1"><div class="l">Recepcionado</div><div class="v">{g['total']}</div><div class="p">100%</div></div>
  <div class="fstep s2"><div class="l">Etiquetado</div><div class="v">{g['etiq']}</div><div class="p">{g['etiq_pct']}%</div></div>
  <div class="fstep s3"><div class="l">Anclado (vans)</div><div class="v">{anc_v}</div><div class="p">{anc_p}% · {vans_total} vans</div></div>
  <div class="fstep s4"><div class="l">Salió a reparto</div><div class="v">{g['salio']}</div><div class="p">{g['salio_pct']}%</div></div>
</div>
""", unsafe_allow_html=True)

# ---- ACTION BAR ----
n_pend = int(pedidos['estado_cat'].isin(['alert', 'warn', 'orange']).sum())
n_cuar = int((pedidos['estado_cat'] == 'priority').sum())
n_reclass = int(pedidos['reclasificar_a'].notna().sum())

k1, k2, k3 = st.columns(3)
k1.metric("⏳ Pendientes (no salieron)", n_pend)
k2.metric("🟣 Cuarentena", n_cuar)
k3.metric("🔁 Reclasificar", n_reclass)

if n_reclass > 0:
    with st.expander(f"🔁 Reclasificar — la ruta indica otra flota ({n_reclass})"):
        rec = pedidos[pedidos['reclasificar_a'].notna()].copy()
        rec['Flota actual'] = rec['flota'].map(FLOTA_LABELS).fillna(rec['flota'])
        rec['Debería ser'] = rec['reclasificar_a'].map(FLOTA_LABELS).fillna(rec['reclasificar_a'])
        rec['Salida'] = rec['salio'].map({True: 'Salió', False: 'No salió'})
        rec['TMS'] = rec.apply(tms_label_or_none, axis=1)
        rec = rec.rename(columns={'codigo': 'Código', 'ruta': 'Ruta', 'estado_label': 'Estado'})
        st.dataframe(rec[['Código', 'Flota actual', 'Ruta', 'Debería ser', 'Salida', 'TMS', 'Estado']],
                     hide_index=True, use_container_width=True)
        st.caption("Regla: ruta de 3 dígitos = Dinámico, 2 dígitos = Estático. "
                   "Motos ancladas también caen aquí. Siguen su flujo (igual se despachan).")

flota_options = ["Todas"] + [FLOTA_LABELS[f] for f in FLOTAS_VALIDAS]
flota_sel = st.radio("Flota", flota_options, horizontal=True, label_visibility="collapsed")
label_to_key = {v: k for k, v in FLOTA_LABELS.items()}
flota_key = label_to_key.get(flota_sel)

tab_pedidos, tab_pendientes, tab_conos = st.tabs(["📦 Pedidos", "⏳ Pendientes", "🔵 Conos"])


def salida_pills(ps):
    salieron = int(ps['salio'].sum())
    no = len(ps) - salieron
    return (f'<span class="salida-ok">✅ {salieron} salieron</span> '
            f'<span class="salida-no">⏳ {no} no</span>')


def pct_row(ps, is_van):
    total = len(ps)
    etiq = round(int(ps['etiq'].sum()) / total * 100) if total else 0
    salio = round(int(ps['salio'].sum()) / total * 100) if total else 0
    no_salio = 100 - salio
    if is_van:
        anc_ok = int(((ps['anc_count'] >= ps['bultos']) & (ps['bultos'] > 0)).sum())
        anc_str = f"{round(anc_ok / total * 100) if total else 0}%"
    else:
        anc_str = "N/A"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Etiquetado", f"{etiq}%")
    c2.metric("Anclado", anc_str)
    c3.metric("Salió a reparto", f"{salio}%")
    c4.metric("No salió", f"{no_salio}%")


def render_detail_table(df_section, is_van):
    if df_section.empty:
        return
    view = df_section.copy()
    view['Código'] = view.apply(
        lambda r: f"🔶 {r['codigo']}" if r.get('inferido') else r['codigo'], axis=1)
    view['Etiq'] = view['etiq'].map({True: 'Sí', False: 'No'})
    view['Anclaje'] = view.apply(lambda r: anc_text(r, is_van), axis=1)
    view['Ruta'] = view.apply(ruta_display, axis=1)
    view['TMS'] = view.apply(tms_label_or_none, axis=1)
    view['Estado'] = view['estado_label']
    view = view.rename(columns={'bultos': 'Bultos'})
    st.dataframe(view[['Código', 'Bultos', 'Etiq', 'Anclaje', 'Ruta', 'TMS', 'Estado']],
                 hide_index=True, use_container_width=True)


with tab_pedidos:
    flotas_show = FLOTAS_VALIDAS if flota_key is None else [flota_key]
    if pedidos['inferido'].any():
        st.caption("🔶 = sin recepción en Zeus — flota inferida por su cono de anclaje")
    for fl in flotas_show:
        ps = pedidos[pedidos['flota'] == fl]
        if ps.empty:
            continue
        is_van = fl != 'OF MOTORIZADOS'
        total = len(ps)
        etiq_ok = int(ps['etiq'].sum())
        anc_ok = int(((ps['anc_count'] >= ps['bultos']) & (ps['bultos'] > 0)).sum()) if is_van else None
        salieron = int(ps['salio'].sum())
        no_salieron = total - salieron

        flow = f"Recep {total} · Etiq {etiq_ok}"
        flow += f" · Anclaje {anc_ok}" if is_van else " · Anclaje N/A"
        header = f"**{FLOTA_LABELS[fl]}** · {total} pedidos  —  {flow}  —  ✅ {salieron} salieron · ⏳ {no_salieron} no"

        with st.expander(header, expanded=(no_salieron > 0)):
            pct_row(ps, is_van)
            no_salio_df = ps[~ps['salio']]
            if no_salio_df.empty:
                st.success("✓ Todos los pedidos de esta flota ya salieron a reparto")
            else:
                st.markdown(f"**No salieron — requieren acción ({len(no_salio_df)})**")
                render_detail_table(no_salio_df, is_van)

            with st.expander(f"Ver los {total} pedidos completos"):
                render_detail_table(ps, is_van)

    if not sin_recep.empty and flota_key is None:
        with st.expander(f"⚪ Sin flota / Sin recepción — {len(sin_recep)} códigos"):
            view = sin_recep.copy()
            view['Etiq'] = view['etiq'].map({True: 'Sí', False: 'No'})
            view['TMS'] = view.apply(tms_label_or_none, axis=1)
            view = view.rename(columns={'codigo': 'Código', 'anc_count': 'Anclaje (filas)', 'ruta': 'Ruta'})
            st.dataframe(view[['Código', 'Etiq', 'Anclaje (filas)', 'Ruta', 'TMS']],
                         hide_index=True, use_container_width=True)


with tab_pendientes:
    flotas_show = FLOTAS_VALIDAS if flota_key is None else [flota_key]
    any_pend = False
    for fl in flotas_show:
        ps = pedidos[pedidos['flota'] == fl]
        if ps.empty:
            continue
        is_van = fl != 'OF MOTORIZADOS'
        pend = ps[ps['estado_cat'].isin(['alert', 'warn', 'orange'])]
        st.markdown(f"#### {FLOTA_LABELS[fl]} · {len(ps)} pedidos")
        st.markdown(salida_pills(ps), unsafe_allow_html=True)
        pct_row(ps, is_van)
        if pend.empty:
            st.success("✓ Sin pendientes en esta flota")
        else:
            any_pend = True
            render_detail_table(pend, is_van)
        st.divider()
    if not any_pend:
        st.info("No hay pedidos pendientes en la selección actual.")


with tab_conos:
    pool = pedidos if flota_key is None else pedidos[pedidos['flota'] == flota_key]
    conos = build_conos(pool)
    if conos.empty:
        st.info("No hay conos con anclaje en esta ventana.")
    else:
        prioridad = conos[(conos['migrados'] > 0) & (conos['sin_migrar'] > 0)]
        pendiente = conos[conos['migrados'] == 0]
        completo = conos[conos['sin_migrar'] == 0]

        def render_conos(df_conos, titulo):
            if df_conos.empty:
                return
            st.markdown(f"**{titulo}**")
            for _, c in df_conos.iterrows():
                total, migr, nomig = int(c['total']), int(c['migrados']), int(c['sin_migrar'])
                pct = int(c['pct'])
                if nomig == 0:
                    estado = "🟢 Completo"
                elif migr == 0:
                    estado = "🟡 Pendiente"
                else:
                    estado = f"🔴 {nomig} sin migrar"
                hdr = (f"{c['cono']} · {FLOTA_LABELS.get(c['flota'], c['flota'])} · "
                       f"{migr}/{total} salieron ({pct}%) · {estado}")
                with st.expander(hdr, expanded=(nomig > 0 and migr > 0)):
                    items = pool[(pool['cono'] == c['cono']) & (pool['flota'] != 'OF MOTORIZADOS')].copy()
                    items['Salida'] = items.apply(
                        lambda r: ('Salió · ' + str(r['tms_label'])) if r['salio']
                        else ('No salió · ' + (str(r['tms_label']) if pd.notna(r['tms_label']) else 'Sin registro')),
                        axis=1)
                    items = items.rename(columns={'codigo': 'Código', 'bultos': 'Bultos'})
                    st.dataframe(items[['Código', 'Bultos', 'Salida']],
                                 hide_index=True, use_container_width=True)

        render_conos(prioridad, "🔴 Prioridad — sin migrar (ubicar ya)")
        render_conos(pendiente, "🟡 Aún sin despachar (0 salieron)")
        render_conos(completo, "🟢 Completos")


st.divider()


def to_excel_bytes(pedidos_df, sin_recep_df):
    out = pd.concat([pedidos_df, sin_recep_df], ignore_index=True)
    out_view = pd.DataFrame({
        'Código': out['codigo'],
        'Flota': out['flota'].map(FLOTA_LABELS).fillna(out['flota']),
        'Bultos': out['bultos'],
        'Etiquetado': out['etiq'].map({True: 'Sí', False: 'No'}),
        'Anclaje': out.apply(
            lambda r: 'N/A' if r['flota'] == 'OF MOTORIZADOS'
            else f"{int(r['anc_count'])}/{int(r['bultos']) if pd.notna(r['bultos']) else 0}", axis=1),
        'Ruta': out['ruta'] if 'ruta' in out.columns else '',
        'Reclasificar a': out['reclasificar_a'].map(FLOTA_LABELS).fillna(out['reclasificar_a']) if 'reclasificar_a' in out.columns else '',
        'Cono': out['cono'].fillna(''),
        'Salió': out['salio'].map({True: 'Sí', False: 'No'}) if 'salio' in out.columns else 'No',
        'Estado TMS': out.apply(tms_label_or_none, axis=1),
        'Estado final': out['estado_label'],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        out_view.to_excel(writer, index=False, sheet_name='Despacho')
    buf.seek(0)
    return buf


excel_bytes = to_excel_bytes(pedidos, sin_recep)
st.download_button(
    "⬇ Descargar Excel",
    data=excel_bytes,
    file_name=f"torre_control_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
