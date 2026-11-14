"""
Validação do agente: a IA encontra os padrões plantados? Ela inventa números?

Uso:
    python validacao.py                       # 3 execuções com a configuração padrão
    python validacao.py --execucoes 5 --nivel minimal
    python validacao.py --base caminho.csv --controle   # base sem padrões (teste negativo)

Checagens:
1. Padrões plantados (seção 5.2 do CLAUDE.md): busca por palavras-chave em cada padrão.
2. Números: todo número citado nos padrões precisa existir no resumo enviado à IA
   (ou ser um dos limites do próprio prompt, como 19h, 4 km e 50 pedidos).
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd

import agente
import analise

BASE_PADRAO = Path(__file__).parent / "data" / "entregas_ficticias.csv"


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


# Cada padrão plantado: todas as listas precisam ter pelo menos um termo presente.
PADROES_PLANTADOS = {
    "Chuva no pico do jantar": [["chuva"], ["pico", "19h", "jantar"]],
    "Bicicleta acima de 4 km": [["bicicleta"], ["4 km", "4km", "distancia", "longa"]],
    "Restaurantes com gargalo": [["fogo bravo", "bella massa"]],
    "Zona Leste": [["zona leste"]],
}


def _texto_padrao(p: dict) -> str:
    return _norm(" ".join(str(v) for v in p.values()))


def padrao_casa(texto: str, regras: list[list[str]]) -> bool:
    return all(any(_norm(t) in texto for t in grupo) for grupo in regras)


def checar_padroes(diagnostico: dict) -> tuple[dict[str, bool], list[str]]:
    """Quais padrões plantados apareceram e quais padrões da IA não casam com nenhum."""
    textos = [(_texto_padrao(p), p["padrao"]) for p in diagnostico["padroes"]]
    encontrados = {nome: any(padrao_casa(t, r) for t, _ in textos)
                   for nome, r in PADROES_PLANTADOS.items()}
    extras = [nome for t, nome in textos
              if not any(padrao_casa(t, r) for r in PADROES_PLANTADOS.values())]
    return encontrados, extras


def _numeros_do_resumo(obj, saida: set[float]) -> set[float]:
    if isinstance(obj, dict):
        for v in obj.values():
            _numeros_do_resumo(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _numeros_do_resumo(v, saida)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        saida.add(float(obj))
    elif isinstance(obj, str):
        for n in re.findall(r"\d+(?:[.,]\d+)?", obj):
            saida.add(float(n.replace(",", ".")))
    return saida


def _para_numero(bruto: str) -> float:
    """Entende '28,2', '28.2' e o milhar brasileiro '1.232' (= 1232)."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", bruto):
        return float(bruto.replace(".", "").replace(",", "."))
    return float(bruto.replace(",", "."))


# Limites que vêm do próprio prompt/negócio, não dos dados
LIMITES_DO_PROMPT = {19, 21, 4, 50, 8, 2, 3, 5}


def checar_numeros(diagnostico: dict, resumo: dict) -> list[str]:
    """Números citados nos padrões que não existem no resumo (possível invenção)."""
    conhecidos = _numeros_do_resumo(resumo, set()) | {float(x) for x in LIMITES_DO_PROMPT}
    suspeitos = []
    for p in diagnostico["padroes"]:
        texto = " ".join([p["evidencia"], p["causa_provavel"]])
        for bruto in re.findall(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?", texto):
            x = _para_numero(bruto)
            tem_decimal = "," in bruto or (("." in bruto) and not re.fullmatch(r"\d{1,3}(?:\.\d{3})+", bruto))
            tolerancia = 0.05 if tem_decimal else 0.5  # "~25 min" pode arredondar 25,3
            if not any(abs(x - k) <= tolerancia for k in conhecidos):
                suspeitos.append(bruto)
    return suspeitos


def validar(base: Path, execucoes: int, nivel: str | None, modelo: str | None, controle: bool,
            pausa_s: float = 8) -> dict:
    d = analise.preparar(pd.read_csv(base))
    resumo = analise.resumo_para_ia(d)
    resultados = []
    for i in range(1, execucoes + 1):
        if i > 1:
            time.sleep(pausa_s)  # respeita o limite de chamadas por minuto do plano gratuito
        try:
            r = agente.gerar_diagnostico(resumo, nivel=nivel, modelos=[modelo] if modelo else None)
        except agente.ErroDiagnostico as e:
            print(f"Execução {i}: FALHOU ({e}) | detalhe: {e.detalhe[:300]}")
            resultados.append({"execucao": i, "erro": str(e), "detalhe": e.detalhe})
            continue
        encontrados, extras = checar_padroes(r["diagnostico"])
        suspeitos = checar_numeros(r["diagnostico"], resumo)
        resultados.append({
            "execucao": i, "modelo": r["modelo"], "nivel": r["nivel_raciocinio"],
            "segundos": r["segundos"], "encontrados": encontrados, "extras": extras,
            "numeros_suspeitos": suspeitos, "n_padroes": len(r["diagnostico"]["padroes"]),
            "diagnostico": r["diagnostico"],
        })
        acertos = sum(encontrados.values())
        if controle:
            print(f"Execução {i}: {len(r['diagnostico']['padroes'])} padrões apontados "
                  f"| números suspeitos: {suspeitos or 'nenhum'} | {r['segundos']} s")
        else:
            print(f"Execução {i}: {acertos}/4 padrões | extras: {extras or 'nenhum'} "
                  f"| números suspeitos: {suspeitos or 'nenhum'} | {r['segundos']} s ({r['modelo']})")
    return {"base": str(base), "controle": controle, "resultados": resultados}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=BASE_PADRAO)
    ap.add_argument("--execucoes", type=int, default=3)
    ap.add_argument("--nivel", default=None, help="minimal, low, medium ou high")
    ap.add_argument("--modelo", default=None, help="força um modelo (sem reserva)")
    ap.add_argument("--controle", action="store_true", help="base sem padrões plantados (teste negativo)")
    ap.add_argument("--pausa", type=float, default=8, help="segundos entre execuções")
    ap.add_argument("--salvar", type=Path, default=None, help="grava o resultado completo em JSON")
    args = ap.parse_args()

    saida = validar(args.base, args.execucoes, args.nivel, args.modelo, args.controle, args.pausa)
    rs = [r for r in saida["resultados"] if "erro" not in r]
    falhas = len(saida["resultados"]) - len(rs)
    if falhas:
        print(f"Execuções que falharam (cota/indisponibilidade): {falhas}")
    if not rs:
        return
    if not args.controle:
        print("\nAcertos por padrão:")
        for nome in PADROES_PLANTADOS:
            print(f"  {nome}: {sum(r['encontrados'][nome] for r in rs)}/{len(rs)}")
    print(f"Tempo médio: {sum(r['segundos'] for r in rs) / len(rs):.1f} s")
    if args.salvar:
        args.salvar.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Resultado salvo em {args.salvar}")


if __name__ == "__main__":
    main()
