"""
Torre de Control · Despacho Nocturno — Streamlit v4
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

from engine import (
    run_engine, build_conos, read_excel_positional, read_tms,
    FLOTAS_VALIDAS, FLOTA_LABELS, _estado_anclaje,
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
.b-noaction{background:#1a1a1a;color:#6e7681;border:1px solid #30363d}
.funnel{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0}
.fstep{flex:1;min-width:120px;background:#1c2230;border:1px solid #283041;border-radius:9px;padding:10px 13px}
.fstep .l{font-size:11px;color:#8b98a5;text-transform:uppercase;letter-spacing:.04em}
.fstep .v{font-size:21px;font-weight:700;margin-top:2px}
.fstep .p{font-size:12px;color:#8b98a5}
.fstep.s1 .v{color:#e6edf3}.fstep.s2 .v{color:#4d9fff}
.fstep.s3 .v{color:#5dcaa5}.fstep.s4 .v{color:#2ea043}
.salida-ok{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;
  border-radius:20px;background:#0d2818;color:#2ea043;border:1px solid #1a4a25}
.salida-no{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;
  border-radius:20px;background:#241c08;color:#d29922;border:1px solid #4a3a0a}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers de display
# ---------------------------------------------------------------------------
def tms_real_or_none(row) -> str:
    """Estado TMS real y completo tal como viene del archivo."""
    real = row.get('tms_real', '')
    if not real or (isinstance(real, float) and pd.isna(real)):
        return 'Sin registro TMS'
    return str(real)


def anc_text(row, is_van: bool) -> str:
    if not is_van:
        return 'N/A'
    return f"{int(row['anc_count'])}/{int(row['bultos'])}"


def ruta_display(row) -> str:
    r = str(row.get('ruta', '') or '').strip() or '—'
    if row.get('ruta_alerta'):
        return f"{r} ⚠"
    return r


def estado_anclaje_icon(estado: str) -> str:
    return {'Completo':'✅ Completo','Parcial':'🔴 Parcial',
            'Exceso':'🟠 Exceso','Sin anclar':'⬛ Sin anclar','N/A':'—'}.get(estado, estado)


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------
if 'result' not in st.session_state:
    st.session_state.result = None

st.title("📦 Torre de Control · Despacho Nocturno")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Archivos")
    f_zeus = st.file_uploader("Zeus (Excel)", type=["xlsx","xls"], key="zeus")
    f_etiq = st.file_uploader("Etiquetado (Excel)", type=["xlsx","xls"], key="etiq")
    f_anc  = st.file_uploader("Anclaje (Excel)", type=["xlsx","xls"], key="anc")
    f_tms  = st.file_uploader("TMS (ZIP o CSV)", type=["zip","csv"], key="tms")

    st.header("2. Ventana de análisis")
    if 'desde_date' not in st.session_state:
        _now = datetime.now()
        _d   = _now - timedelta(hours=14)
        st.session_state.desde_date = _d.date()
        st.session_state.desde_time = _d.time()
        st.session_state.hasta_date = _now.date()
        st.session_state.hasta_time = _now.time()

    c1, c2 = st.columns(2)
    with c1:
        desde_date = st.date_input("Desde — fecha", key="desde_date")
        desde_time = st.time_input("Desde — hora",  key="desde_time")
    with c2:
        hasta_date = st.date_input("Hasta — fecha", key="hasta_date")
        hasta_time = st.time_input("Hasta — hora",  key="hasta_time")

    desde = pd.Timestamp(datetime.combine(desde_date, desde_time))
    hasta = pd.Timestamp(datetime.combine(hasta_date, hasta_time))

    st.divider()
    procesar = st.button("🚀 Procesar", type="primary", use_container_width=True)
    if st.button("🗑️ Limpiar", use_container_width=True):
        st.session_state.result = None
        st.rerun()

# ---------------------------------------------------------------------------
# Procesamiento
# ---------------------------------------------------------------------------
if procesar:
    if not f_zeus:
        st.error("Falta cargar el archivo Zeus.")
    elif desde >= hasta:
        st.error("La fecha 'Desde' debe ser anterior a 'Hasta'.")
    else:
        with st.spinner("Procesando archivos..."):
            try:
                zeus_df = read_excel_positional(f_zeus)
                etiq_df = read_excel_positional(f_etiq) if f_etiq else pd.DataFrame(columns=range(5))
                anc_df  = read_excel_positional(f_anc)  if f_anc  else pd.DataFrame(columns=range(11))

                tms_df, tms_total = None, 0
                if f_tms:
                    tms_df, tms_total = read_tms(f_tms, f_tms.name)

                result = run_engine(zeus_df, etiq_df, anc_df, tms_df, desde, hasta)
                result['tms_total_raw'] = tms_total
                result['win'] = (desde, hasta)
                st.session_state.result = result
                st.success(f"Listo · {len(result['pedidos'])} pedidos"
                           + (f" · TMS: {tms_total:,} filas → {len(tms_df)} únicos" if f_tms else ""))
            except Exception as ex:
                st.error(f"Error al procesar: {ex}")

# ---------------------------------------------------------------------------
# Guard: sin resultados
# ---------------------------------------------------------------------------
result = st.session_state.result
if result is None:
    st.info("Carga los archivos, define la ventana y presiona **Procesar**.")
    st.stop()

pedidos  = result['pedidos']
sin_recep= result['sin_recepcion']
funnel   = result['funnel']
desde, hasta = result['win']

st.caption(f"📅 {desde.strftime('%d/%m %H:%M')} → {hasta.strftime('%d/%m %H:%M')}"
           + (f"  ·  TMS: {result['tms_total_raw']:,} filas" if result.get('tms_total_raw') else ""))

if pedidos.empty:
    st.warning("No se encontraron pedidos de las flotas válidas en esta ventana.")
    st.stop()

# ---------------------------------------------------------------------------
# Embudo general
# ---------------------------------------------------------------------------
g = funnel['general']
st.markdown("##### Avance general del despacho")
anc_v    = g['anc']     if g.get('anc')     is not None else 0
anc_p    = g['anc_pct'] if g.get('anc_pct') is not None else 0
vans_tot = g.get('vans_total', 0)
st.markdown(f"""
<div class="funnel">
  <div class="fstep s1"><div class="l">Recepcionado</div>
    <div class="v">{g['total']}</div><div class="p">100%</div></div>
  <div class="fstep s2"><div class="l">Etiquetado</div>
    <div class="v">{g['etiq']}</div><div class="p">{g['etiq_pct']}%</div></div>
  <div class="fstep s3"><div class="l">Anclado (vans)</div>
    <div class="v">{anc_v}</div><div class="p">{anc_p}% · {vans_tot} vans</div></div>
  <div class="fstep s4"><div class="l">Salió a reparto</div>
    <div class="v">{g['salio']}</div><div class="p">{g['salio_pct']}%</div></div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Action bar
# ---------------------------------------------------------------------------
es_pendiente = pedidos['estado_cat'].isin(['alert','warn','orange'])
n_pend    = int(es_pendiente.sum())
n_cuar    = int((pedidos['estado_cat'] == 'priority').sum())
n_reclass = int(pedidos['reclasificar_a'].notna().sum())
n_no_salio= int((~pedidos['salio'] & ~pedidos['estado_cat'].isin(['priority','no_action'])).sum())

k1,k2,k3,k4 = st.columns(4)
k1.metric("⏳ Pendientes",   n_pend)
k2.metric("🔴 No salieron",  n_no_salio)
k3.metric("🔁 Reclasificar", n_reclass)
k4.metric("🟣 Cuarentena",   n_cuar, help="Informativo — no cuenta como pendiente")

if n_reclass > 0:
    with st.expander(f"🔁 Reclasificar — la ruta indica otra flota ({n_reclass})"):
        rec = pedidos[pedidos['reclasificar_a'].notna()].copy()
        rec['Flota actual'] = rec['flota'].map(FLOTA_LABELS).fillna(rec['flota'])
        rec['Debería ser']  = rec['reclasificar_a'].map(FLOTA_LABELS).fillna(rec['reclasificar_a'])
        rec['Salida']       = rec['salio'].map({True:'Salió', False:'No salió'})
        rec['Estado TMS']   = rec.apply(tms_real_or_none, axis=1)
        rec = rec.rename(columns={'codigo':'Código','ruta':'Ruta','estado_label':'Estado'})
        st.dataframe(rec[['Código','Flota actual','Ruta','Debería ser','Salida','Estado TMS','Estado']],
                     hide_index=True, use_container_width=True)
        st.caption("Ruta: 1 dígito = Motorizados · 2 = Estático · 3 = Dinámico. "
                   "Siguen su flujo normal (igual se despachan).")

# ---------------------------------------------------------------------------
# Filtro de flota + tabs
# ---------------------------------------------------------------------------
flota_options  = ["Todas"] + [FLOTA_LABELS[f] for f in FLOTAS_VALIDAS]
flota_sel      = st.radio("Flota", flota_options, horizontal=True, label_visibility="collapsed")
label_to_key   = {v:k for k,v in FLOTA_LABELS.items()}
flota_key      = label_to_key.get(flota_sel)

tab_pedidos, tab_pend, tab_conos = st.tabs(["📦 Pedidos","⏳ Pendientes","🔵 Conos"])


def salida_pills(ps):
    s  = int(ps['salio'].sum())
    ns = len(ps) - s
    return (f'<span class="salida-ok">✅ {s} salieron</span> '
            f'<span class="salida-no">⏳ {ns} no</span>')


def pct_row(ps, is_van):
    total  = len(ps)
    etiq   = round(int(ps['etiq'].sum())/total*100) if total else 0
    salio  = round(int(ps['salio'].sum())/total*100) if total else 0
    if is_van:
        anc_ok  = int(((ps['anc_count'] >= ps['bultos']) & (ps['bultos'] > 0)).sum())
        anc_str = f"{round(anc_ok/total*100) if total else 0}%"
    else:
        anc_str = "N/A"
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Etiquetado",    f"{etiq}%")
    c2.metric("Anclado",       anc_str)
    c3.metric("Salió a reparto",f"{salio}%")
    c4.metric("No salió",      f"{100-salio}%")


def render_detail_table(df_sec, is_van):
    if df_sec.empty:
        return
    v = df_sec.copy()
    v['Código']     = v.apply(lambda r: f"🔶 {r['codigo']}" if r.get('inferido') else r['codigo'], axis=1)
    v['Etiq']       = v['etiq'].map({True:'Sí', False:'No'})
    v['Anclaje']    = v.apply(lambda r: anc_text(r, is_van), axis=1)
    v['Ruta']       = v.apply(ruta_display, axis=1)
    v['Estado TMS'] = v.apply(tms_real_or_none, axis=1)
    v['Estado']     = v['estado_label']
    v = v.rename(columns={'bultos':'Bultos'})
    st.dataframe(v[['Código','Bultos','Etiq','Anclaje','Ruta','Estado TMS','Estado']],
                 hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# TAB PEDIDOS
# ---------------------------------------------------------------------------
with tab_pedidos:
    flotas_show = FLOTAS_VALIDAS if flota_key is None else [flota_key]
    if not pedidos.empty and pedidos['inferido'].any():
        st.caption("🔶 = sin recepción en Zeus — flota inferida por cono o ruta")

    for fl in flotas_show:
        ps = pedidos[pedidos['flota'] == fl]
        if ps.empty:
            continue
        is_van     = fl != 'OF MOTORIZADOS'
        total      = len(ps)
        etiq_ok    = int(ps['etiq'].sum())
        anc_ok     = int(((ps['anc_count'] >= ps['bultos']) & (ps['bultos'] > 0)).sum()) if is_van else None
        salieron   = int(ps['salio'].sum())
        no_salieron= total - salieron

        flow = f"Recep {total} · Etiq {etiq_ok}"
        flow += f" · Anclaje {anc_ok}" if is_van else " · Anclaje N/A"
        hdr  = (f"**{FLOTA_LABELS[fl]}** · {total} pedidos  —  {flow}  —  "
                f"✅ {salieron} salieron · ⏳ {no_salieron} no")

        with st.expander(hdr, expanded=(no_salieron > 0)):
            pct_row(ps, is_van)
            no_sal = ps[~ps['salio']]
            if no_sal.empty:
                st.success("✓ Todos los pedidos ya salieron a reparto")
            else:
                st.markdown(f"**No salieron — requieren acción ({len(no_sal)})**")
                render_detail_table(no_sal, is_van)
            with st.expander(f"Ver los {total} pedidos completos"):
                render_detail_table(ps, is_van)

    if not sin_recep.empty and flota_key is None:
        with st.expander(f"⚪ Sin flota / Sin recepción — {len(sin_recep)} códigos"):
            v = sin_recep.copy()
            v['Etiq']      = v['etiq'].map({True:'Sí', False:'No'})
            v['Estado TMS']= v.apply(tms_real_or_none, axis=1)
            v = v.rename(columns={'codigo':'Código','anc_count':'Anclaje (filas)','ruta':'Ruta'})
            st.dataframe(v[['Código','Etiq','Anclaje (filas)','Ruta','Estado TMS']],
                         hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB PENDIENTES
# ---------------------------------------------------------------------------
with tab_pend:
    pend_all = pedidos[pedidos['estado_cat'].isin(['alert','warn','orange'])].copy()
    if flota_key is not None:
        pend_all = pend_all[pend_all['flota'] == flota_key]

    st.markdown(f"**{len(pend_all)} pedidos pendientes**"
                + (f" · {FLOTA_LABELS[flota_key]}" if flota_key else " · todas las flotas")
                + "  —  usa los botones de arriba para filtrar por flota")

    if pend_all.empty:
        st.success("✓ No hay pedidos pendientes en la selección actual.")
    else:
        v = pend_all.copy()
        v['Código']     = v.apply(lambda r: f"🔶 {r['codigo']}" if r.get('inferido') else r['codigo'], axis=1)
        v['Flota']      = v['flota'].map(FLOTA_LABELS).fillna(v['flota'])
        v['Etiq']       = v['etiq'].map({True:'Sí', False:'No'})
        v['Anclaje']    = v.apply(lambda r: anc_text(r, r['flota'] != 'OF MOTORIZADOS'), axis=1)
        v['Ruta']       = v.apply(ruta_display, axis=1)
        v['Estado TMS'] = v.apply(tms_real_or_none, axis=1)
        v['Estado']     = v['estado_label']
        st.dataframe(
            v[['Código','Flota','bultos','Etiq','Anclaje','Ruta','Estado TMS','Estado']]
            .rename(columns={'bultos':'Bultos'}),
            hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB CONOS
# ---------------------------------------------------------------------------
with tab_conos:
    pool  = pedidos if flota_key is None else pedidos[pedidos['flota'] == flota_key]
    conos = build_conos(pool)

    if conos.empty:
        st.info("No hay conos con anclaje en esta ventana.")
    else:
        prioridad = conos[(conos['migrados'] > 0) & (conos['sin_migrar'] > 0)]
        pendiente = conos[conos['migrados'] == 0]
        completo  = conos[conos['sin_migrar'] == 0]

        def render_conos(df_c, titulo):
            if df_c.empty:
                return
            st.markdown(f"**{titulo}**")
            for _, c in df_c.iterrows():
                total = int(c['total']); migr = int(c['migrados']); nomig = int(c['sin_migrar'])
                pct   = int(c['pct'])
                b_rec = int(c['bultos_recibidos']); b_anc = int(c['bultos_anclados'])
                dif   = int(c['dif_bultos']); est_anc = c['estado_anclaje_cono']

                estado_mig = ("🟢 Completo" if nomig == 0 else
                              "🟡 Pendiente" if migr == 0 else f"🔴 {nomig} sin migrar")
                # alerta de anclaje en el header del cono
                anc_alert  = ""
                if est_anc == 'Parcial':
                    anc_alert = f" · 🔴 Anclaje parcial (faltan {abs(dif)} bultos)"
                elif est_anc == 'Exceso':
                    anc_alert = f" · 🟠 Anclaje en exceso (+{dif} bultos)"

                hdr = (f"{c['cono']} · {FLOTA_LABELS.get(c['flota'],c['flota'])} · "
                       f"{migr}/{total} salieron ({pct}%) · {estado_mig}{anc_alert}")

                with st.expander(hdr, expanded=(nomig > 0 and migr > 0)):
                    # Resumen de bultos del cono
                    ca,cb,cc,cd = st.columns(4)
                    ca.metric("Recibidos", b_rec)
                    cb.metric("Anclados",  b_anc)
                    cc.metric("Diferencia", f"{'+' if dif>0 else ''}{dif}")
                    cd.metric("Estado anclaje", estado_anclaje_icon(est_anc))

                    # Detalle de pedidos — pendientes primero
                    items = pool[
                        (pool['cono'] == c['cono']) & (pool['flota'] != 'OF MOTORIZADOS')
                    ].copy()
                    items['_orden'] = items['salio'].map({False:0, True:1})
                    items = items.sort_values('_orden')
                    items['Salida']  = items.apply(
                        lambda r: f"🟢 Salió · {r['tms_real'] or r['tms_label'] or '—'}" if r['salio']
                        else f"🔴 No salió · {r['tms_real'] or r['tms_label'] or 'Sin registro'}",
                        axis=1)
                    items['Anclaje'] = items.apply(lambda r: f"{int(r['anc_count'])}/{int(r['bultos'])}", axis=1)
                    items['Anclaje estado'] = items['estado_anclaje'].apply(estado_anclaje_icon)
                    items = items.rename(columns={'codigo':'Código','bultos':'Bultos'})
                    st.dataframe(items[['Código','Bultos','Anclaje','Anclaje estado','Salida']],
                                 hide_index=True, use_container_width=True)

        render_conos(prioridad, "🔴 Prioridad — sin migrar (ubicar ya)")
        render_conos(pendiente, "🟡 Aún sin despachar (0 salieron)")
        render_conos(completo,  "🟢 Completos")

# ---------------------------------------------------------------------------
# Descargables
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### ⬇ Descargas")
col_d1, col_d2 = st.columns(2)


def excel_pendientes(pedidos_df, sin_recep_df) -> bytes:
    """Reporte de pendientes: solo pedidos que requieren acción."""
    pend = pedidos_df[pedidos_df['estado_cat'].isin(['alert','warn','orange'])].copy()
    if pend.empty:
        # hoja vacía con encabezados
        pend = pd.DataFrame(columns=['codigo','flota','bultos','etiq',
                                      'anc_count','ruta','cono','tms_real','estado_label'])
    es_pend = pend['estado_cat'].isin(['alert','warn','orange'])
    view = pd.DataFrame({
        'Código':        pend.apply(lambda r: f"[sin recep] {r['codigo']}" if r.get('inferido') else r['codigo'], axis=1),
        'Flota':         pend['flota'].map(FLOTA_LABELS).fillna(pend['flota']),
        'Bultos':        pend['bultos'],
        'Etiquetado':    pend['etiq'].map({True:'Sí', False:'No'}),
        'Anclaje':       pend.apply(lambda r: anc_text(r, r['flota']!='OF MOTORIZADOS'), axis=1),
        'Ruta':          pend['ruta'].fillna(''),
        'Reclasificar a':pend['reclasificar_a'].map(FLOTA_LABELS).fillna(pend.get('reclasificar_a','')),
        'Cono':          pend['cono'].fillna(''),
        'Salió':         pend['salio'].map({True:'Sí', False:'No'}),
        'Estado TMS':    pend.apply(tms_real_or_none, axis=1),
        'Estado final':  pend['estado_label'],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
        view.to_excel(w, index=False, sheet_name='Pendientes')
    buf.seek(0)
    return buf.read()


def excel_bultos(pedidos_df) -> bytes:
    """Reporte de bultos: discrepancias de anclaje por pedido y cono."""
    # Solo pedidos con anclaje (vans)
    vans = pedidos_df[pedidos_df['flota'] != 'OF MOTORIZADOS'].copy()

    # Hoja 1: detalle por pedido
    def anc_est_label(r):
        return estado_anclaje_icon(r.get('estado_anclaje',''))

    det = pd.DataFrame({
        'Código':           vans.apply(lambda r: f"[sin recep] {r['codigo']}" if r.get('inferido') else r['codigo'], axis=1),
        'Flota':            vans['flota'].map(FLOTA_LABELS).fillna(vans['flota']),
        'Cono':             vans['cono'].fillna(''),
        'Ruta':             vans['ruta'].fillna(''),
        'Bultos recibidos': vans['bultos'],
        'Bultos anclados':  vans['anc_count'],
        'Diferencia':       vans['anc_count'] - vans['bultos'],
        'Estado anclaje':   vans.apply(anc_est_label, axis=1),
        'Salió':            vans['salio'].map({True:'Sí', False:'No'}),
        'Estado TMS':       vans.apply(tms_real_or_none, axis=1),
    })

    # Hoja 2: resumen por cono
    conos_df = build_conos(pedidos_df)
    if not conos_df.empty:
        resumen = pd.DataFrame({
            'Cono':              conos_df['cono'],
            'Flota':             conos_df['flota'].map(FLOTA_LABELS).fillna(conos_df['flota']),
            'Pedidos':           conos_df['total'],
            'Salieron':          conos_df['migrados'],
            'Sin salir':         conos_df['sin_migrar'],
            '% Salida':          conos_df['pct'].astype(str) + '%',
            'Bultos recibidos':  conos_df['bultos_recibidos'],
            'Bultos anclados':   conos_df['bultos_anclados'],
            'Diferencia bultos': conos_df['dif_bultos'],
            'Estado anclaje':    conos_df['estado_anclaje_cono'],
        })
    else:
        resumen = pd.DataFrame(columns=['Cono','Flota','Pedidos','Salieron',
                                         'Sin salir','% Salida','Bultos recibidos',
                                         'Bultos anclados','Diferencia bultos','Estado anclaje'])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
        det.to_excel(w,    index=False, sheet_name='Detalle por pedido')
        resumen.to_excel(w,index=False, sheet_name='Resumen por cono')
    buf.seek(0)
    return buf.read()


with col_d1:
    st.download_button(
        "⬇ Pendientes",
        data=excel_pendientes(pedidos, sin_recep),
        file_name=f"pendientes_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with col_d2:
    st.download_button(
        "⬇ Reporte Bultos / Anclaje",
        data=excel_bultos(pedidos),
        file_name=f"bultos_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
