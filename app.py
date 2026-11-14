"""
Interface Streamlit do Agente de Análise de Atrasos.
Rodar localmente:  streamlit run app.py
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import analise

BASE_EXEMPLO = Path(__file__).parent / "data" / "entregas_ficticias.csv"
COR_BARRA = "#2a78d6"     # azul (série única)
COR_REFERENCIA = "#898781"  # cinza neutro para a linha da média

st.set_page_config(page_title="Agente de Atrasos em Entregas", page_icon="🛵", layout="wide")


# ---------- dados ----------
@st.cache_data(show_spinner=False)
def carregar_exemplo() -> pd.DataFrame:
    return pd.read_csv(BASE_EXEMPLO)


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
            st.session_state.origem = "Base de exemplo (fictícia)"
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
    st.info("🚧 O diagnóstico da IA chega no próximo passo.")


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
    aba1, aba2, aba3 = st.tabs(["📊 Visão geral", "📍 Onde está o atraso", "🤖 Diagnóstico da IA"])
    with aba1:
        tela_visao_geral(d)
    with aba2:
        tela_onde_esta(d)
    with aba3:
        tela_diagnostico(d)
