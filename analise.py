"""
Camada de análise: todos os números do app saem daqui.

Regra do projeto: o pandas calcula, a IA só interpreta.
As funções são puras (recebem um DataFrame e devolvem tabelas),
para serem fáceis de testar.
"""
from __future__ import annotations

import pandas as pd

COLUNAS_OBRIGATORIAS = [
    "pedido_id", "data", "dia_semana", "hora_pedido", "regiao", "restaurante",
    "categoria", "modal", "chuva", "distancia_km", "tempo_preparo_min",
    "tempo_espera_entregador_min", "tempo_prometido_min", "tempo_real_min",
    "atraso_min", "atrasou",
]

ORDEM_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
PICO_INICIO, PICO_FIM = 19, 21   # pico do jantar, inclusive
LIMITE_DISTANCIA_KM = 4          # fronteira usada para bicicleta
NOITE_A_PARTIR = 19              # "noite" para sexta e sábado
N_MINIMO = 50                    # segmentos menores que isso não sustentam conclusão


def colunas_faltando(df: pd.DataFrame) -> list[str]:
    """Colunas obrigatórias que não estão no arquivo enviado."""
    return [c for c in COLUNAS_OBRIGATORIAS if c not in df.columns]


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Cria as colunas auxiliares usadas nas análises."""
    d = df.copy()
    d["atrasou_bool"] = d["atrasou"].astype(str).str.strip().str.lower().eq("sim")
    d["chuva_bool"] = d["chuva"].astype(str).str.strip().str.lower().eq("sim")
    d["pico"] = d["hora_pedido"].between(PICO_INICIO, PICO_FIM)
    d["faixa_distancia"] = d["distancia_km"].le(LIMITE_DISTANCIA_KM).map(
        {True: f"Até {LIMITE_DISTANCIA_KM} km", False: f"Acima de {LIMITE_DISTANCIA_KM} km"}
    )
    d["noite"] = d["hora_pedido"].ge(NOITE_A_PARTIR)
    return d


def kpis(d: pd.DataFrame) -> dict:
    """Números dos cartões da visão geral."""
    atrasados = d[d["atrasou_bool"]]
    return {
        "pedidos": int(len(d)),
        "taxa_atraso_pct": round(float(d["atrasou_bool"].mean()) * 100, 1) if len(d) else 0.0,
        "atraso_medio_min": round(float(atrasados["atraso_min"].mean()), 1) if len(atrasados) else 0.0,
        "pedidos_atrasados": int(len(atrasados)),
    }


def _agregar(d: pd.DataFrame, por: str | list[str]) -> pd.DataFrame:
    g = d.groupby(por, observed=True)["atrasou_bool"].agg(pedidos="size", atrasados="sum")
    g["taxa_atraso_pct"] = (g["atrasados"] / g["pedidos"] * 100).round(1)
    return g.reset_index()


def taxa_por(d: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Taxa de atraso por um segmento (região, modal, restaurante...)."""
    t = _agregar(d, coluna)
    if coluna == "dia_semana":
        t["_ordem"] = t[coluna].map({dia: i for i, dia in enumerate(ORDEM_DIAS)})
        return t.sort_values("_ordem").drop(columns="_ordem").reset_index(drop=True)
    if coluna == "hora_pedido":
        return t.sort_values(coluna).reset_index(drop=True)
    return t.sort_values("taxa_atraso_pct", ascending=False).reset_index(drop=True)


def chuva_x_pico(d: pd.DataFrame) -> pd.DataFrame:
    rotulo = d["chuva_bool"].map({True: "Com chuva", False: "Sem chuva"}) + " · " + \
        d["pico"].map({True: f"pico ({PICO_INICIO}h–{PICO_FIM}h)", False: "fora do pico"})
    t = _agregar(d.assign(segmento=rotulo), "segmento")
    return t.sort_values("taxa_atraso_pct", ascending=False).reset_index(drop=True)


def modal_x_distancia(d: pd.DataFrame) -> pd.DataFrame:
    rotulo = d["modal"] + " · " + d["faixa_distancia"].str.lower()
    t = _agregar(d.assign(segmento=rotulo), "segmento")
    return t.sort_values("taxa_atraso_pct", ascending=False).reset_index(drop=True)


def fim_de_semana_noite(d: pd.DataFrame) -> pd.DataFrame:
    """Sexta e sábado à noite comparados com as outras noites."""
    noites = d[d["noite"]]
    rotulo = noites["dia_semana"].where(
        noites["dia_semana"].isin(["Sexta", "Sábado"]), "Outras noites"
    ) + f" (a partir das {NOITE_A_PARTIR}h)"
    rotulo = rotulo.str.replace("Sexta (", "Sexta à noite (", regex=False) \
                   .str.replace("Sábado (", "Sábado à noite (", regex=False)
    t = _agregar(noites.assign(segmento=rotulo), "segmento")
    return t.sort_values("taxa_atraso_pct", ascending=False).reset_index(drop=True)


def tempos_medios(d: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Tempo médio (e variação) de preparo e de espera por segmento."""
    t = d.groupby(coluna).agg(
        pedidos=("pedido_id", "size"),
        preparo_medio_min=("tempo_preparo_min", "mean"),
        preparo_desvio_min=("tempo_preparo_min", "std"),
        espera_media_min=("tempo_espera_entregador_min", "mean"),
        distancia_media_km=("distancia_km", "mean"),
    ).round(1)
    return t.sort_values("preparo_medio_min", ascending=False).reset_index()


def _linhas(t: pd.DataFrame, chave: str, taxa_geral: float) -> list[dict]:
    """
    Linhas do resumo. 'excesso_atrasados' = atrasos acima do esperado se o segmento
    tivesse a taxa geral: mede o impacto (taxa x volume) já calculado pelo pandas.
    """
    return [
        {"segmento": str(r[chave]), "n": int(r["pedidos"]), "atrasados": int(r["atrasados"]),
         "taxa_atraso_pct": float(r["taxa_atraso_pct"]),
         "excesso_atrasados": int(round(r["atrasados"] - r["pedidos"] * taxa_geral))}
        for _, r in t.iterrows()
    ]


def resumo_para_ia(d: pd.DataFrame) -> dict:
    """
    Resumo compacto (poucos KB) que vai para a IA.
    Só agregados, sempre com o tamanho da amostra (n) de cada segmento.
    """
    k = kpis(d)
    tg = float(d["atrasou_bool"].mean())

    def L(t, chave):
        return _linhas(t, chave, tg)

    return {
        "observacao": (
            f"Estatísticas já calculadas. Taxa = % de pedidos atrasados. "
            "n = número de pedidos do segmento. 'excesso_atrasados' = atrasos a mais do que o "
            "esperado se o segmento tivesse a taxa geral (mede o impacto: taxa x volume). "
            f"Segmentos com n < {N_MINIMO} não sustentam conclusão."
        ),
        "geral": {
            "pedidos": k["pedidos"],
            "taxa_atraso_pct": k["taxa_atraso_pct"],
            "atraso_medio_min_entre_atrasados": k["atraso_medio_min"],
        },
        "por_segmento": {
            "regiao": L(taxa_por(d, "regiao"), "regiao"),
            "hora_pedido": L(taxa_por(d, "hora_pedido"), "hora_pedido"),
            "modal": L(taxa_por(d, "modal"), "modal"),
            "chuva": L(taxa_por(d, "chuva"), "chuva"),
            "dia_semana": L(taxa_por(d, "dia_semana"), "dia_semana"),
            "restaurante": L(taxa_por(d, "restaurante"), "restaurante"),
        },
        "combinacoes": {
            "chuva_x_pico_jantar": L(chuva_x_pico(d), "segmento"),
            "modal_x_distancia": L(modal_x_distancia(d), "segmento"),
            "noites_sexta_sabado_vs_outras": L(fim_de_semana_noite(d), "segmento"),
        },
        "tempos_medios": {
            "por_restaurante": tempos_medios(d, "restaurante").to_dict(orient="records"),
            "por_regiao": tempos_medios(d, "regiao").to_dict(orient="records"),
        },
    }


# ---------- mapa ----------
TAMANHO_CELULA_KM = 1.5
MIN_PEDIDOS_CELULA = 8   # células com menos pedidos não são pintadas (amostra pequena engana)


def grade_atraso(d: pd.DataFrame, tamanho_km: float = TAMANHO_CELULA_KM,
                 minimo: int = MIN_PEDIDOS_CELULA) -> pd.DataFrame:
    """
    Agrupa os pedidos numa grade de quadrados (~tamanho_km de lado) e calcula a taxa de
    atraso de cada quadrado. Devolve só os quadrados com pelo menos `minimo` pedidos,
    com os 4 cantos prontos para desenhar no mapa.
    """
    passo_lat = tamanho_km / 111.0
    passo_lon = tamanho_km / (111.0 * 0.917)  # cos(23,5°) ~ 0,917 em São Paulo
    g = d.assign(
        i=(d["latitude"] // passo_lat).astype(int),
        j=(d["longitude"] // passo_lon).astype(int),
    ).groupby(["i", "j"]).agg(pedidos=("pedido_id", "size"), atrasados=("atrasou_bool", "sum"),
                              regiao=("regiao", lambda s: s.mode().iat[0])).reset_index()
    g = g[g["pedidos"] >= minimo].copy()
    g["taxa_atraso_pct"] = (g["atrasados"] / g["pedidos"] * 100).round(1)
    lat0, lon0 = g["i"] * passo_lat, g["j"] * passo_lon
    g["poligono"] = [
        [[lo, la], [lo + passo_lon, la], [lo + passo_lon, la + passo_lat], [lo, la + passo_lat]]
        for la, lo in zip(lat0, lon0)
    ]
    return g.drop(columns=["i", "j"]).reset_index(drop=True)


TAMANHOS_KM = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


def grade_adaptativa(d: pd.DataFrame, cobertura_minima: float = 0.7) -> tuple[pd.DataFrame, float]:
    """Menor quadrado que ainda mostra pelo menos 70% dos pedidos (poucos dados -> quadrados maiores)."""
    g, t = pd.DataFrame(), TAMANHOS_KM[-1]
    for t in TAMANHOS_KM:
        g = grade_atraso(d, t)
        if len(d) and g["pedidos"].sum() / len(d) >= cobertura_minima:
            break
    return g, t
