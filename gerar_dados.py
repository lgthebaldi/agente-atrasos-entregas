"""
Gera uma base FICTÍCIA de entregas para o projeto "Agente de Análise de Atrasos".
Nenhum dado real é usado. Os padrões abaixo foram plantados de propósito,
para que o agente consiga descobri-los e explicá-los:

  1. Chuva + pico do jantar (19h-21h) aumenta muito o atraso.
  2. Região "Zona Leste" tem distâncias maiores e menos entregadores -> mais atraso.
  3. Dois restaurantes têm tempo de preparo alto e instável (gargalo na cozinha).
  4. Entregas de bicicleta acima de 4 km atrasam bem mais que de moto.
  5. Sexta e sábado à noite têm fila maior de pedidos.

Uso:
  python gerar_dados.py              -> data/entregas_ficticias.csv (com os padrões)
  python gerar_dados.py --controle   -> data/entregas_controle.csv  (SEM os padrões;
                                        serve para testar se a IA inventa padrões)
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--controle", action="store_true", help="gera a base sem padrões plantados")
CONTROLE = ap.parse_args().controle
PADROES = not CONTROLE

rng = np.random.default_rng(42)
N = 5000

regioes = {
    "Centro":     {"dist": 2.5, "oferta": 1.00},
    "Zona Sul":   {"dist": 3.5, "oferta": 0.95},
    "Zona Oeste": {"dist": 3.8, "oferta": 0.90},
    "Zona Norte": {"dist": 4.2, "oferta": 0.85},
    "Zona Leste": {"dist": 5.8, "oferta": 0.60},
}
restaurantes = [
    ("Burger da Vila", "Lanches"), ("Pizzaria Bella Massa", "Pizza"),
    ("Sushi Kaze", "Japonesa"), ("Marmitaria Dona Rosa", "Brasileira"),
    ("Açaí Tropical", "Açaí"), ("Pastelaria Feira Livre", "Lanches"),
    ("Cantina Nonna", "Italiana"), ("Poke House", "Saudável"),
    ("Churrascaria Fogo Bravo", "Brasileira"), ("Temaki Express", "Japonesa"),
    ("Esfiharia do Oriente", "Árabe"), ("Padaria Pão Quente", "Padaria"),
]
gargalos = {"Pizzaria Bella Massa", "Churrascaria Fogo Bravo"}
dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

linhas = []
inicio = pd.Timestamp("2026-08-01")
for i in range(N):
    data = inicio + pd.Timedelta(days=int(rng.integers(0, 91)))
    hora = int(rng.choice(range(10, 24), p=np.array(
        [2, 6, 9, 7, 3, 2, 2, 3, 6, 11, 12, 9, 5, 3], float) / 80))
    dia = dias[data.day_of_week]
    regiao = rng.choice(list(regioes), p=[0.22, 0.22, 0.2, 0.18, 0.18])
    rest, cat = restaurantes[int(rng.integers(0, len(restaurantes)))]
    chuva = rng.random() < 0.18
    modal = rng.choice(["Moto", "Bicicleta"], p=[0.75, 0.25])

    dist = max(0.5, rng.normal(regioes[regiao]["dist"], 1.2))
    if modal == "Bicicleta":
        dist = min(dist, 7.0)

    pico = 19 <= hora <= 21
    fim_semana_noite = dia in ("Sexta", "Sábado") and hora >= 19

    # preparo
    preparo = rng.normal(14, 3)
    if PADROES and rest in gargalos:
        preparo = rng.normal(24, 8)
    if pico:
        preparo += 3
    preparo = max(5, preparo)

    # espera por entregador
    espera = rng.exponential(3) / (regioes[regiao]["oferta"] if PADROES else 1.0)
    if PADROES and chuva:
        espera += rng.exponential(5)
    if PADROES and fim_semana_noite:
        espera += rng.exponential(4)

    # deslocamento
    vel = 22 if modal == "Moto" else 13
    if PADROES and chuva:
        vel *= 0.75
    desloc = dist / vel * 60
    if PADROES and modal == "Bicicleta" and dist > 4:
        desloc *= 1.35

    real = preparo + espera + desloc + rng.normal(0, 2)
    if PADROES and chuva and pico:
        real += rng.normal(8, 3)

    prometido = 15 + dist * 3.5 + (5 if pico else 0)
    prometido = round(prometido / 5) * 5 + 10

    real = round(max(10, real))
    atraso = max(0, real - prometido)
    linhas.append({
        "pedido_id": f"PED{100000 + i}",
        "data": data.date().isoformat(),
        "dia_semana": dia,
        "hora_pedido": hora,
        "regiao": regiao,
        "restaurante": rest,
        "categoria": cat,
        "modal": modal,
        "chuva": "Sim" if chuva else "Não",
        "distancia_km": round(dist, 1),
        "tempo_preparo_min": round(preparo),
        "tempo_espera_entregador_min": round(espera),
        "tempo_prometido_min": int(prometido),
        "tempo_real_min": int(real),
        "atraso_min": int(atraso),
        "atrasou": "Sim" if atraso > 0 else "Não",
    })

df = pd.DataFrame(linhas).sort_values(["data", "hora_pedido"]).reset_index(drop=True)

# Coordenadas FICTÍCIAS do endereço de entrega, sorteadas dentro de cada zona de São Paulo
# (centro aproximado e espalhamento em graus). Usa um gerador separado, então as colunas
# acima ficam idênticas e os padrões plantados não mudam.
CENTROS_ZONA = {
    "Centro":     (-23.548, -46.638, 0.012, 0.012),
    "Zona Oeste": (-23.570, -46.715, 0.020, 0.022),
    "Zona Sul":   (-23.640, -46.680, 0.030, 0.025),
    "Zona Norte": (-23.480, -46.630, 0.022, 0.030),
    "Zona Leste": (-23.550, -46.480, 0.028, 0.045),
}
rng_geo = np.random.default_rng(2026)
lat_c, lon_c, dlat, dlon = (df["regiao"].map(lambda r, i=i: CENTROS_ZONA[r][i]).to_numpy() for i in range(4))
df["latitude"] = np.round(rng_geo.normal(lat_c, dlat), 5)
df["longitude"] = np.round(rng_geo.normal(lon_c, dlon), 5)
nome = "entregas_controle.csv" if CONTROLE else "entregas_ficticias.csv"
saida = Path(__file__).parent / "data" / nome
saida.parent.mkdir(exist_ok=True)
df.to_csv(saida, index=False, encoding="utf-8")
print(f"{len(df)} pedidos gerados -> {saida}")
