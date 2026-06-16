"""
Torre de Control · Despacho Nocturno — versión Streamlit
Misma lógica de la versión web, pero con pandas para procesar
archivos pesados (TMS de millones de filas) en segundos.
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

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
st.markdown("""
<style>
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;white-space:nowrap}
.b-ok{background:#0f2417;color:#2ea043;border:1px solid #1a4a25}
.b-warn{background:#241c08;color:#d29922;border:1px solid #4a3a0a}
.b-alert{background:#2a0f0f;color:#f85149;border:1px solid #4a1515}
.b-orange{background:#251608;color:#e8892b;border:1px solid #4a2a08}
.b-priority{background:#1a0a2a;color:#c084fc;border:1px solid #6b3fa0}
.b-gray{background:#1a2130;color:#8b98a5;border:1px solid #27313d}
.pipe{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:4px 0}
.pipe-box{background:#1c2530;border:1px solid #27313d;border-radius:6px;padding:6px 12px;text-align:center;min-width:90px}
.pipe-box .v{font-weight:700;font-size:16px}
.pipe-box .l{font-size:10px;color:#8b98a5;text-transform:uppercase;letter-spacing:.04em}
.pipe-box .s{font-size:10px}
.pipe-arrow{color:#27313d;font-size:18px}
</style>
""", unsafe_allow_html=True)


def badge(label, cat):
    cls = {'ok': 'b-ok', 'warn': 'b-warn', 'alert': 'b-alert',
           'orange': 'b-orange', 'priority': 'b-priority'}.get(cat, 'b-gray')
    return f'<span class="badge {cls}">{label}</span>'


def tms_badge(row):
    if row['tms_cat'] is None or pd.isna(row['tms_cat']):
        return badge('Sin registro', 'gray')
    return badge(row['tms_label'], row['tms_cat'] if row['tms_cat'] in
                  ('ok', 'warn', 'alert', 'orange', 'priority') else
                  {'dispatched': 'ok', 'pending': 'warn', 'review': 'orange', 'quarantine': 'priority'}[row['tms_cat']])


def anc_text(row, is_van):
    if not is_van:
        return 'N/A'
    return f"{int(row['anc_count'])}/{int(row['bultos'])}"


# ---------------------------------------------------------------------------
# Estado de sesión
# ---------------------------------------------------------------------------
if 'result' not in st.session_state:
    st.session_state.result = None

st.title("📦 Torre de Control · Despacho Nocturno")

# ---------------------------------------------------------------------------
# Sidebar — carga de archivos + ventana
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Archivos")
    f_zeus = st.file_uploader("Zeus (Excel)", type=["xlsx", "xls"], key="zeus")
    f_etiq = st.file_uploader("Etiquetado (Excel)", type=["xlsx", "xls"], key="etiq")
    f_anc = st.file_uploader("Anclaje (Excel)", type=["xlsx", "xls"], key="anc")
    f_tms = st.file_uploader("TMS (ZIP o CSV)", type=["zip", "csv"], key="tms")

    st.header("2. Ventana de análisis")
    now = datetime.now()
    default_desde = now - timedelta(hours=14)
    c1, c2 = st.columns(2)
    with c1:
        desde_date = st.date_input("Desde — fecha", value=default_desde.date())
        desde_time = st.time_input("Desde — hora", value=default_desde.time())
    with c2:
        hasta_date = st.date_input("Hasta — fecha", value=now.date())
        hasta_time = st.time_input("Hasta — hora", value=now.time())

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
                etiq_df = read_excel_positional(f_etiq) if f_etiq else pd.DataFrame()
                anc_df = read_excel_positional(f_anc) if f_anc else pd.DataFrame()

                tms_df, tms_total = (None, 0)
                if f_tms:
                    tms_df, tms_total = read_tms(f_tms, f_tms.name)

                # columnas mínimas si vienen vacíos (evitar errores de indexado)
                if etiq_df.empty:
                    etiq_df = pd.DataFrame(columns=range(5))
                if anc_df.empty:
                    anc_df = pd.DataFrame(columns=range(11))

                result = run_engine(zeus_df, etiq_df, anc_df, tms_df, desde, hasta)
                result['tms_total_raw'] = tms_total
                result['win'] = (desde, hasta)
                st.session_state.result = result
                st.success(f"Listo · {len(result['pedidos'])} pedidos analizados"
                            + (f" · TMS: {tms_total:,} filas → {len(tms_df)} códigos únicos" if f_tms else ""))
            except Exception as e:
                st.error(f"Error al procesar: {e}")

# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
result = st.session_state.result
if result is None:
    st.info("Carga los archivos en la barra lateral, define la ventana y presiona **Procesar**.")
    st.stop()

pedidos = result['pedidos']
sin_recep = result['sin_recepcion']
desde, hasta = result['win']

st.caption(f"Ventana: {desde.strftime('%d/%m %H:%M')} → {hasta.strftime('%d/%m %H:%M')}"
           + (f"  ·  TMS: {result['tms_total_raw']:,} filas procesadas" if result['tms_total_raw'] else ""))

# ---------------------------------------------------------------------------
# Filtro de flota
# ---------------------------------------------------------------------------
flota_options = ["Todas"] + [FLOTA_LABELS[f] for f in FLOTAS_VALIDAS]
flota_sel = st.radio("Flota", flota_options, horizontal=True, label_visibility="collapsed")
label_to_key = {v: k for k, v in FLOTA_LABELS.items()}
flota_key = label_to_key.get(flota_sel)  # None si "Todas"

ped_view = pedidos if flota_key is None else pedidos[pedidos['flota'] == flota_key]

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Pedidos en ventana", len(ped_view))
c2.metric("Despachados", int((ped_view['estado_cat'] == 'ok').sum()))
c3.metric("En proceso", int((ped_view['estado_cat'] == 'warn').sum()) + int((ped_view['estado_cat'] == 'orange').sum()))
c4.metric("Alertas", int((ped_view['estado_cat'] == 'alert').sum()))
c5.metric("Cuarentena", int((ped_view['estado_cat'] == 'priority').sum()))

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_pedidos, tab_conos = st.tabs(["📦 Pedidos", "🔵 Conos"])

with tab_pedidos:
    flotas_to_show = FLOTAS_VALIDAS if flota_key is None else [flota_key]

    for fl in flotas_to_show:
        ps = pedidos[pedidos['flota'] == fl]
        if ps.empty:
            continue
        is_van = fl != 'OF MOTORIZADOS'
        total = len(ps)
        etiq_ok = int(ps['etiq'].sum())
        anc_ok = int(((ps['anc_count'] >= ps['bultos']) & (ps['bultos'] > 0)).sum()) if is_van else None
        tms_ok = int((ps['tms_cat'] == 'dispatched').sum())
        cuar = int((ps['estado_cat'] == 'priority').sum())
        alerts = int((ps['estado_cat'] == 'alert').sum())
        okc = int((ps['estado_cat'] == 'ok').sum())

        header = f"**{FLOTA_LABELS[fl]}** · {total} pedidos"
        badges = []
        if cuar:
            badges.append(f"🟣 {cuar} cuarentena")
        if alerts:
            badges.append(f"🔴 {alerts} alertas")
        badges.append(f"🟢 {okc} ok")
        header += "  —  " + "  ·  ".join(badges)

        with st.expander(header, expanded=(alerts > 0 or cuar > 0)):
            # Pipeline resumen
            anc_html = (f'<div class="pipe-box"><div class="v">{anc_ok}</div><div class="l">Anclaje</div>'
                        f'<div class="s" style="color:{"#f85149" if total-anc_ok>0 else "#2ea043"}">'
                        f'{"faltan "+str(total-anc_ok) if total-anc_ok>0 else "todos ✓"}</div></div>'
                        if is_van else
                        '<div class="pipe-box" style="opacity:.4"><div class="v">N/A</div><div class="l">Anclaje</div><div class="s">no aplica</div></div>')

            def box(label, val, missing):
                color = "#f85149" if missing > 0 else "#2ea043"
                sub = f"faltan {missing}" if missing > 0 else "todos ✓"
                return (f'<div class="pipe-box"><div class="v">{val}</div><div class="l">{label}</div>'
                        f'<div class="s" style="color:{color}">{sub}</div></div>')

            pipe_html = ('<div class="pipe">' + box('Recepción', total, 0) +
                         '<span class="pipe-arrow">→</span>' + box('Etiquetado', etiq_ok, total - etiq_ok) +
                         '<span class="pipe-arrow">→</span>' + anc_html +
                         '<span class="pipe-arrow">→</span>' + box('TMS', tms_ok, total - tms_ok) + '</div>')
            st.markdown(pipe_html, unsafe_allow_html=True)

            # --- Secciones de pendientes ---
            def render_section(title, color, df_section, extra_cols=()):
                if df_section.empty:
                    return
                st.markdown(f"<div style='font-size:12px;font-weight:600;color:{color};margin:10px 0 4px'>"
                             f"{title} — {len(df_section)}</div>", unsafe_allow_html=True)
                view = df_section.copy()
                view['Anclaje'] = view.apply(lambda r: anc_text(r, is_van), axis=1)
                view['TMS'] = view['tms_label'].fillna('Sin registro')
                view['Estado'] = view['estado_label']
                cols = ['codigo', 'bultos'] + list(extra_cols) + ['Anclaje', 'TMS', 'Estado']
                view = view.rename(columns={'codigo': 'Código', 'bultos': 'Bultos'})
                cols_renamed = ['Código', 'Bultos'] + list(extra_cols) + ['Anclaje', 'TMS', 'Estado']
                st.dataframe(view[cols_renamed], hide_index=True, use_container_width=True)

            sin_eti = ps[~ps['etiq']]
            render_section("🔴 Sin etiquetar", "#f85149", sin_eti)

            if is_van:
                sin_anc = ps[(ps['etiq']) & (ps['anc_count'] < ps['bultos'])]
                render_section("🔴 Sin anclar / anclaje incompleto", "#f85149", sin_anc)

            cuarentena = ps[ps['estado_cat'] == 'priority']
            render_section("🟣 Cuarentena — no deben salir", "#c084fc", cuarentena)

            pendientes = ps[ps['estado_cat'].isin(['warn', 'orange'])]
            render_section("🟡 Pendiente TMS / revisar", "#d29922", pendientes)

            if alerts == 0 and cuar == 0 and len(pendientes) == 0:
                st.success("✓ Todos los pedidos completos en esta ventana")

            # Ver todos
            with st.expander(f"Ver todos los {total} pedidos de {FLOTA_LABELS[fl]}"):
                allv = ps.copy()
                allv['Anclaje'] = allv.apply(lambda r: anc_text(r, is_van), axis=1)
                allv['TMS'] = allv['tms_label'].fillna('Sin registro')
                allv = allv.rename(columns={'codigo': 'Código', 'bultos': 'Bultos',
                                             'etiq': 'Etiquetado', 'estado_label': 'Estado'})
                st.dataframe(allv[['Código', 'Bultos', 'Etiquetado', 'Anclaje', 'TMS', 'Estado']],
                              hide_index=True, use_container_width=True)

    # Sin recepción
    if not sin_recep.empty and flota_key is None:
        with st.expander(f"⚪ Sin recepción — {len(sin_recep)} códigos (en etiquetado/anclaje/TMS pero no en Zeus)"):
            view = sin_recep.copy()
            view['TMS'] = view['tms_label'].fillna('Sin registro')
            view = view.rename(columns={'codigo': 'Código', 'etiq': 'Etiquetado', 'anc_count': 'Anclaje (filas)'})
            st.dataframe(view[['Código', 'Etiquetado', 'Anclaje (filas)', 'TMS']],
                          hide_index=True, use_container_width=True)

with tab_conos:
    conos = build_conos(ped_view)
    if conos.empty:
        st.info("No hay conos con anclaje en esta ventana.")
    else:
        st.caption(f"{len(conos)} conos · {int((conos['sin_migrar']>0).sum())} con pendientes "
                   "(ordenados por mayor cantidad sin migrar)")
        for _, c in conos.iterrows():
            total, migr, nomig = int(c['total']), int(c['migrados']), int(c['sin_migrar'])
            if nomig == 0:
                estado_b = badge('Completo', 'ok')
            elif migr == 0:
                estado_b = badge('Pendiente', 'warn')
            else:
                estado_b = badge(f'{nomig} sin migrar', 'alert')

            header = (f"**{c['cono']}** · {FLOTA_LABELS.get(c['flota'], c['flota'])} · "
                      f"{migr}/{total} migrados ({int(c['pct'])}%)")
            with st.expander(header, expanded=(nomig > 0)):
                st.markdown(estado_b, unsafe_allow_html=True)
                items = ped_view[(ped_view['cono'] == c['cono']) & (ped_view['flota'] != 'OF MOTORIZADOS')]
                view = items.copy()
                view['TMS'] = view['tms_label'].fillna('Sin registro')
                view = view.rename(columns={'codigo': 'Código', 'bultos': 'Bultos'})
                st.dataframe(view[['Código', 'Bultos', 'TMS']], hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
st.divider()


def to_excel_bytes(pedidos_df, sin_recep_df):
    out = pd.concat([pedidos_df, sin_recep_df], ignore_index=True)
    out_view = pd.DataFrame({
        'Código': out['codigo'],
        'Flota': out['flota'].map(FLOTA_LABELS).fillna(out['flota']),
        'Bultos': out['bultos'],
        'Recepción': out['recep'].fillna(False).map({True: 'Sí', False: 'No'}),
        'Etiquetado': out['etiq'].map({True: 'Sí', False: 'No'}),
        'Anclaje': out.apply(lambda r: 'N/A' if r['flota'] == 'OF MOTORIZADOS' else f"{int(r['anc_count'])}/{int(r['bultos']) if pd.notna(r['bultos']) else 0}", axis=1),
        'Cono': out['cono'].fillna(''),
        'Estado TMS': out['tms_label'].fillna('Sin registro'),
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
