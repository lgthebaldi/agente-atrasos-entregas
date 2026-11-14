"""
Interface Streamlit do Agente de Análise de Atrasos.
Rodar localmente:  streamlit run app.py
"""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import agente
import analise

BASE_EXEMPLO = Path(__file__).parent / "data" / "entregas_ficticias.csv"
DIAGNOSTICO_SALVO = Path(__file__).parent / "data" / "diagnostico_exemplo.json"
ORIGEM_EXEMPLO = "Base de exemplo (fictícia)"
COR_BARRA = "#2a78d6"     # azul (série única)
COR_REFERENCIA = "#898781"  # cinza neutro para a linha da média

st.set_page_config(page_title="Agente de Atrasos em Entregas", page_icon="🛵", layout="wide")


# ---------- dados ----------
@st.cache_data(show_spinner=False)
def _ler_exemplo(assinatura: tuple) -> pd.DataFrame:
    # `assinatura` (tamanho, data do arquivo) entra na chave do cache: se o CSV mudar,
    # o cache se renova, mesmo que o servidor não reinicie.
    return pd.read_csv(BASE_EXEMPLO)


def carregar_exemplo() -> pd.DataFrame:
    info = BASE_EXEMPLO.stat()
    return _ler_exemplo((info.st_size, info.st_mtime_ns))


def ler_upload(arquivo) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(arquivo)
    except Exception:
        st.error("Não consegui ler o arquivo. Envie um CSV separado por vírgulas, em UTF-8.")
        return None
    faltando = analise.colunas_faltando(df)
    if faltando:
        st.error(
            "O arquivo não tem todas as colunas esperadas. Faltam: **"
            + ", ".join(faltando)
            + "**. Use o mesmo formato da base de exemplo."
        )
        return None
    if df.empty:
        st.error("O arquivo está vazio.")
        return None
    return df


# ---------- IA ----------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def diagnostico_em_cache(resumo_json: str, modelos: tuple[str, ...]) -> dict:
    """
    O mesmo resumo gera o mesmo pedido à IA; o resultado é reaproveitado por todos
    os visitantes por 6 h. Erros não ficam em cache. Isso poupa a cota gratuita do Gemini.
    """
    return agente.gerar_diagnostico(json.loads(resumo_json), modelos=list(modelos))


def obter_diagnostico(resumo: dict, eh_exemplo: bool) -> dict:
    resumo_json = json.dumps(resumo, ensure_ascii=False, sort_keys=True)
    if eh_exemplo:
        # Base de exemplo: só o modelo principal; se falhar, mostra a execução validada salva.
        try:
            return diagnostico_em_cache(resumo_json, (agente.modelos_a_tentar()[0],))
        except agente.ErroDiagnostico:
            salvo = json.loads(DIAGNOSTICO_SALVO.read_text(encoding="utf-8"))
            return {**salvo, "salvo": True}
    # Base enviada pelo usuário: principal + modelos reserva.
    return diagnostico_em_cache(resumo_json, tuple(agente.modelos_a_tentar()))


# ---------- gráficos ----------
def grafico_barras(tabela: pd.DataFrame, coluna: str, titulo: str, media: float,
                   ordenar: bool = True) -> alt.LayerChart:
    """Barras horizontais de taxa de atraso, com linha da média geral."""
    t = tabela.copy()
    t[coluna] = t[coluna].astype(str)
    t["taxa_txt"] = t["taxa_atraso_pct"].map(lambda v: f"{v:.1f}%".replace(".", ","))
    ordem = t[coluna].tolist() if not ordenar else \
        t.sort_values("taxa_atraso_pct", ascending=False)[coluna].tolist()
    y = alt.Y(f"{coluna}:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=260),
              scale=alt.Scale(paddingInner=0.35, paddingOuter=0.2))
    x = alt.X("taxa_atraso_pct:Q", title="% de pedidos atrasados",
              scale=alt.Scale(domain=[0, 100]))
    dica = [
        alt.Tooltip(f"{coluna}:N", title="Segmento"),
        alt.Tooltip("taxa_txt:N", title="Atrasados (%)"),
        alt.Tooltip("atrasados:Q", title="Atrasados"),
        alt.Tooltip("pedidos:Q", title="Pedidos"),
    ]
    barras = alt.Chart(t).mark_bar(color=COR_BARRA, cornerRadiusEnd=4).encode(
        y=y, x=x, tooltip=dica
    )
    rotulos = alt.Chart(t).mark_text(align="left", dx=4).encode(
        y=y, x=x, text="taxa_txt:N"
    )
    linha = alt.Chart(pd.DataFrame({"media": [media], "media_txt": [f"{media:.1f}%".replace(".", ",")]})).mark_rule(
        color=COR_REFERENCIA, strokeDash=[4, 4], strokeWidth=1.5
    ).encode(x="media:Q", tooltip=[alt.Tooltip("media_txt:N", title="Média geral")])
    return (barras + rotulos + linha).properties(title=titulo)


def mostrar_grafico(tabela, coluna, titulo, media, ordenar=True, nota=None):
    altura = 110 + 36 * len(tabela)
    st.altair_chart(grafico_barras(tabela, coluna, titulo, media, ordenar),
                    width="stretch", height=altura)
    if nota:
        st.caption(nota)
    with st.expander("Ver tabela"):
        st.dataframe(
            tabela.rename(columns={coluna: "Segmento", "pedidos": "Pedidos",
                                   "atrasados": "Atrasados", "taxa_atraso_pct": "% atrasados"}),
            hide_index=True, width="stretch",
        )


# ---------- telas ----------
def tela_inicio():
    st.title("🛵 Onde estão os atrasos das suas entregas?")
    st.write(
        "Envie a base de pedidos e veja **onde os atrasos se concentram, por que acontecem "
        "e o que fazer**. Os números são calculados direto dos dados; a IA só interpreta."
    )
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Testar agora")
        st.write("Base fictícia com 5.000 pedidos de 3 meses.")
        if st.button("Usar base de exemplo", type="primary", width="stretch"):
            st.session_state.df = carregar_exemplo()
            st.session_state.origem = ORIGEM_EXEMPLO
            st.rerun()
    with col2:
        st.subheader("Usar seus dados")
        arquivo = st.file_uploader("Arquivo CSV no mesmo formato da base de exemplo", type="csv")
        if arquivo is not None:
            df = ler_upload(arquivo)
            if df is not None:
                st.session_state.df = df
                st.session_state.origem = f"Arquivo enviado: {arquivo.name}"
                st.rerun()
        st.download_button(
            "Baixar a base de exemplo (modelo de formato)",
            data=BASE_EXEMPLO.read_bytes(), file_name="entregas_ficticias.csv", mime="text/csv",
        )


def tela_visao_geral(d: pd.DataFrame):
    k = analise.kpis(d)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pedidos analisados", f"{k['pedidos']:,}".replace(",", "."))
    c2.metric("Taxa de atraso", f"{k['taxa_atraso_pct']:.1f}%".replace(".", ","))
    c3.metric("Atraso médio (entre os atrasados)", f"{k['atraso_medio_min']:.1f} min".replace(".", ","))
    st.caption(
        f"{k['pedidos_atrasados']:,} pedidos chegaram depois do tempo prometido. ".replace(",", ".")
        + "Na próxima aba você vê onde eles se concentram."
    )


def tela_onde_esta(d: pd.DataFrame):
    media = analise.kpis(d)["taxa_atraso_pct"]
    st.caption(
        f"A linha tracejada é a média geral ({media:.1f}%)".replace(".", ",")
        + ". Passe o mouse nas barras para ver os detalhes."
    )

    st.subheader("Combinações que mais explicam o atraso")
    c1, c2 = st.columns(2)
    with c1:
        mostrar_grafico(analise.chuva_x_pico(d), "segmento", "Chuva × pico do jantar", media)
    with c2:
        mostrar_grafico(analise.modal_x_distancia(d), "segmento", "Modal × distância", media)
    mostrar_grafico(analise.fim_de_semana_noite(d), "segmento", "Sexta e sábado à noite", media)

    st.subheader("Atraso por segmento")
    c1, c2 = st.columns(2)
    with c1:
        mostrar_grafico(analise.taxa_por(d, "regiao"), "regiao", "Por região", media)
        mostrar_grafico(analise.taxa_por(d, "modal"), "modal", "Por modal", media)
        mostrar_grafico(analise.taxa_por(d, "dia_semana"), "dia_semana", "Por dia da semana",
                        media, ordenar=False)
    with c2:
        mostrar_grafico(analise.taxa_por(d, "restaurante"), "restaurante", "Por restaurante", media)
        mostrar_grafico(analise.taxa_por(d, "chuva"), "chuva", "Com ou sem chuva", media)
        mostrar_grafico(analise.taxa_por(d, "hora_pedido"), "hora_pedido", "Por hora do pedido",
                        media, ordenar=False)


def tela_diagnostico(d: pd.DataFrame):
    st.write(
        "A IA recebe **só as estatísticas já calculadas** (as mesmas dos gráficos) e escreve "
        "os padrões que mais explicam os atrasos, com a causa provável e o que fazer."
    )
    resumo = analise.resumo_para_ia(d)
    eh_exemplo = st.session_state.get("origem") == ORIGEM_EXEMPLO
    if st.button("Gerar diagnóstico", type="primary", disabled="diagnostico" in st.session_state):
        with st.spinner("A IA está analisando as estatísticas… (leva cerca de 15 segundos)"):
            try:
                st.session_state.diagnostico = obter_diagnostico(resumo, eh_exemplo)
            except agente.ErroDiagnostico as e:
                st.session_state.pop("diagnostico", None)
                st.error(str(e))
                return

    r = st.session_state.get("diagnostico")
    if not r:
        return
    dg = r["diagnostico"]
    if r.get("salvo"):
        st.info(
            "A cota gratuita da IA acabou por hoje, então este é um diagnóstico **real salvo** de uma "
            "execução anterior sobre esta mesma base (validado: encontrou os 4 padrões plantados).",
            icon="💾",
        )
    st.warning("Diagnóstico gerado por IA a partir das estatísticas acima; confirme antes de agir.", icon="⚠️")
    st.subheader("Resumo")
    st.write(dg["resumo"])

    if not dg["padroes"]:
        st.success("A IA não encontrou nenhum padrão claro de atraso nesta base.")
    for i, p in enumerate(dg["padroes"], start=1):
        with st.container(border=True):
            st.markdown(f"#### {i}. {p['padrao']}")
            st.markdown(f"**📊 Evidência:** {p['evidencia']}")
            c1, c2 = st.columns(2)
            c1.markdown(f"**🔎 Causa provável**\n\n{p['causa_provavel']}")
            c2.markdown(f"**✅ Ação sugerida**\n\n{p['acao_sugerida']}")
            st.markdown(f"**📈 Métrica para acompanhar:** {p['metrica_para_acompanhar']}")

    st.markdown(f"**Limitações:** {dg['limitacoes']}")
    st.caption(f"Gerado por {r['modelo']} em {r['segundos']:.1f} s".replace(".", ","))
    with st.expander("Ver exatamente o que foi enviado para a IA"):
        st.caption("Só números agregados, nenhuma linha de pedido. Cada segmento traz o número de pedidos (n).")
        st.json(resumo, expanded=False)


# ---------- mapa ----------
# Rampa sequencial de um só tom (laranja), do claro (pouco atraso) ao escuro (muito atraso).
FAIXAS_MAPA = [  # (limite superior da faixa em %, cor RGB, rótulo)
    (15, [253, 224, 204], "até 15%"),
    (30, [249, 186, 146], "15–30%"),
    (45, [243, 143, 92], "30–45%"),
    (60, [229, 101, 45], "45–60%"),
    (75, [186, 72, 24], "60–75%"),
    (101, [128, 45, 12], "acima de 75%"),
]


def cor_faixa(taxa: float) -> list[int]:
    for limite, cor, _ in FAIXAS_MAPA:
        if taxa < limite:
            return cor
    return FAIXAS_MAPA[-1][1]


def legenda_mapa() -> str:
    itens = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:14px;white-space:nowrap">'
        f'<span style="width:14px;height:14px;border-radius:3px;margin-right:6px;'
        f'background:rgb({c[0]},{c[1]},{c[2]})"></span>{rotulo}</span>'
        for _, c, rotulo in FAIXAS_MAPA
    )
    return f'<div style="font-size:0.85rem;line-height:1.9">% de pedidos atrasados: {itens}</div>'


def tela_mapa(d: pd.DataFrame):
    if not {"latitude", "longitude"} <= set(d.columns):
        st.info("Esta base não tem as colunas latitude e longitude, então o mapa não está disponível. "
                "A base de exemplo tem.")
        return
    st.write(
        "Cada quadrado reúne os pedidos daquela área e é pintado pela **% de pedidos atrasados**. "
        "Use os filtros para ver **quando** e **onde** o atraso aparece."
    )
    c1, c2, c3 = st.columns([2, 1.2, 1.2])
    horas = c1.slider("Hora do pedido", 10, 23, (10, 23))
    chuva = c2.radio("Chuva", ["Todas", "Com chuva", "Sem chuva"], horizontal=True)
    modal = c3.radio("Modal", ["Todos", "Moto", "Bicicleta"], horizontal=True)
    st.caption("💡 Experimente: 19h–21h com chuva. Ou só Bicicleta.")

    f = d[d["hora_pedido"].between(*horas)]
    if chuva != "Todas":
        f = f[f["chuva_bool"] == (chuva == "Com chuva")]
    if modal != "Todos":
        f = f[f["modal"] == modal]
    if f.empty:
        st.warning("Nenhum pedido com esses filtros.")
        return

    geral = analise.kpis(d)["taxa_atraso_pct"]
    k = analise.kpis(f)
    m1, m2, m3 = st.columns(3)
    m1.metric("Pedidos no filtro", f"{k['pedidos']:,}".replace(",", "."))
    diferenca = k["taxa_atraso_pct"] - geral
    m2.metric("Taxa de atraso", f"{k['taxa_atraso_pct']:.1f}%".replace(".", ","),
              delta=None if abs(diferenca) < 0.05 else
              f"{diferenca:+.1f}".replace(".", ",") + " pontos vs. média geral",
              delta_color="inverse")
    m3.metric("Atraso médio (atrasados)", f"{k['atraso_medio_min']:.1f} min".replace(".", ","))

    grade, tamanho = analise.grade_adaptativa(f)
    if grade.empty:
        st.warning("Poucos pedidos com esses filtros para desenhar o mapa com segurança.")
        return
    grade["cor"] = grade["taxa_atraso_pct"].map(cor_faixa)
    grade["taxa_txt"] = grade["taxa_atraso_pct"].map(lambda v: f"{v:.1f}%".replace(".", ","))
    camada = pdk.Layer(
        "PolygonLayer", data=grade, get_polygon="poligono", get_fill_color="cor",
        get_line_color=[255, 255, 255], line_width_min_pixels=1, opacity=0.8,
        pickable=True, auto_highlight=True,
    )
    vista = pdk.ViewState(latitude=-23.565, longitude=-46.58, zoom=10.2)
    st.pydeck_chart(pdk.Deck(
        layers=[camada], initial_view_state=vista, map_provider="carto", map_style="light",
        tooltip={"html": "<b>{taxa_txt}</b> atrasados<br/>{atrasados} de {pedidos} pedidos<br/>{regiao}"},
    ), height=520)
    st.markdown(legenda_mapa(), unsafe_allow_html=True)
    cobertos = grade["pedidos"].sum()
    milhar = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    st.caption(
        f"Quadrados de ~{str(tamanho).replace('.', ',')} km. Áreas com menos de "
        f"{analise.MIN_PEDIDOS_CELULA} pedidos não são pintadas, porque amostras pequenas enganam "
        f"({milhar(int(cobertos))} de {milhar(len(f))} pedidos aparecem). Localizações fictícias."
    )

    with st.expander("Taxa de atraso por região, com estes filtros"):
        t = analise.taxa_por(f, "regiao")
        st.dataframe(t.rename(columns={"regiao": "Região", "pedidos": "Pedidos", "atrasados": "Atrasados",
                                       "taxa_atraso_pct": "% atrasados"}), hide_index=True, width="stretch")


# ---------- app ----------
if "df" not in st.session_state:
    tela_inicio()
else:
    d = analise.preparar(st.session_state.df)
    topo1, topo2 = st.columns([4, 1])
    topo1.caption(f"📂 {st.session_state.origem}")
    if topo2.button("Trocar base", width="stretch"):
        for chave in ("df", "origem", "diagnostico"):
            st.session_state.pop(chave, None)
        st.rerun()
    st.title("🛵 Diagnóstico de atrasos")
    aba1, aba_mapa, aba2, aba3 = st.tabs(
        ["📊 Visão geral", "🗺️ Mapa", "📍 Onde está o atraso", "🤖 Diagnóstico da IA"])
    with aba1:
        tela_visao_geral(d)
    with aba2:
        tela_onde_esta(d)
    with aba_mapa:
        tela_mapa(d)
    with aba3:
        tela_diagnostico(d)
