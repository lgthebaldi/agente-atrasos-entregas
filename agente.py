"""
Camada de IA: prompt + chamada ao Gemini + leitura da resposta em JSON.

A IA não calcula nada. Ela recebe o resumo pronto de analise.resumo_para_ia()
e devolve um diagnóstico estruturado, citando só os números que recebeu.
"""
from __future__ import annotations

import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

MODELO_PADRAO = "gemini-3.6-flash"
# Reservas com cota própria no plano gratuito (o limite é por modelo, ~20 chamadas/dia).
# Obs.: "gemini-3.5-flash" é atendido pelo 3.6 e divide a mesma cota, por isso não é reserva.
MODELOS_RESERVA = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
TEMPERATURA = 0.2
# Nível de raciocínio do modelo ("minimal", "low", "medium", "high").
# "minimal" foi escolhido com o validacao.py: acertou os 4 padrões em todas as
# execuções, responde em ~15 s e gasta menos cota do plano gratuito (ver README).
NIVEL_RACIOCINIO_PADRAO = "minimal"
TENTATIVAS_POR_MODELO = 2
ESPERA_ENTRE_TENTATIVAS_S = 4

PROMPT_SISTEMA = """\
Você é um analista de operações de uma plataforma de delivery.
Recebe estatísticas agregadas de atrasos de entregas (já calculadas; não recalcule).

Tarefa: identificar de 3 a 5 padrões que mais explicam os atrasos e propor ações.

Regras:
- Use SOMENTE os números fornecidos. Nunca invente dados.
- Cada padrão deve citar a evidência numérica: a taxa do segmento, a taxa de referência e o n.
- Ignore segmentos com menos de 50 pedidos.
- Se não houver diferença relevante (menos de 8 pontos percentuais acima da média geral),
  diga que não há padrão claro em vez de forçar uma conclusão. Nesse caso, a lista de padrões
  pode ter menos de 3 itens ou ficar vazia.
- Prefira as combinações (ex.: chuva × pico, modal × distância) quando elas explicarem
  melhor o atraso do que o segmento isolado.
- Ordene do maior para o menor impacto, usando o campo excesso_atrasados (já calculado).
- Ações devem ser práticas e testáveis em poucas semanas.
- Escreva em português do Brasil, para um gestor sem conhecimento técnico.
"""


class Padrao(BaseModel):
    padrao: str = Field(description="Nome curto do padrão")
    evidencia: str = Field(description="Números que sustentam o padrão: taxa do segmento vs. referência e n")
    causa_provavel: str
    acao_sugerida: str
    metrica_para_acompanhar: str


class Diagnostico(BaseModel):
    resumo: str = Field(description="2 frases para um gestor")
    padroes: list[Padrao]
    limitacoes: str = Field(description="O que estes dados não permitem concluir")


class ErroDiagnostico(Exception):
    """Erro com mensagem amigável para mostrar na tela."""


def obter_chave() -> str | None:
    """Chave do .env (local) ou dos Secrets do Streamlit Cloud."""
    chave = os.getenv("GEMINI_API_KEY")
    if chave:
        return chave
    try:
        import streamlit as st
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def modelos_a_tentar() -> list[str]:
    principal = os.getenv("GEMINI_MODEL") or MODELO_PADRAO
    return [principal] + [m for m in MODELOS_RESERVA if m != principal]


def nivel_raciocinio() -> str | None:
    return os.getenv("GEMINI_THINKING_LEVEL") or NIVEL_RACIOCINIO_PADRAO


def gerar_diagnostico(resumo: dict, chave: str | None = None,
                      nivel: str | None = None, modelos: list[str] | None = None) -> dict:
    """
    Envia o resumo ao Gemini e devolve o diagnóstico validado, mais metadados
    (modelo usado e tempo de resposta). Lança ErroDiagnostico em caso de falha.
    """
    nivel = nivel or nivel_raciocinio()
    chave = chave or obter_chave()
    if not chave:
        raise ErroDiagnostico(
            "A chave do Gemini não está configurada. Coloque GEMINI_API_KEY no arquivo .env "
            "(local) ou em Settings → Secrets (Streamlit Cloud)."
        )

    cliente = genai.Client(api_key=chave)
    config = types.GenerateContentConfig(
        system_instruction=PROMPT_SISTEMA,
        temperature=TEMPERATURA,
        response_mime_type="application/json",
        response_schema=Diagnostico,
        thinking_config=types.ThinkingConfig(thinking_level=nivel) if nivel else None,
    )
    conteudo = "Estatísticas de atraso (JSON):\n" + json.dumps(resumo, ensure_ascii=False)

    ultimo_erro = None
    indisponiveis: set[str] = set()
    tentativas = [(m, n) for m in (modelos or modelos_a_tentar()) for n in range(TENTATIVAS_POR_MODELO)]
    for modelo, n_tentativa in tentativas:
        if modelo in indisponiveis:
            continue
        if n_tentativa > 0:
            time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
        inicio = time.perf_counter()
        try:
            resposta = cliente.models.generate_content(model=modelo, contents=conteudo, config=config)
        except errors.APIError as e:
            ultimo_erro = e
            # sobrecarga ou limite de uso: tenta de novo; modelo indisponível: pula para o próximo
            if e.code == 429 and "PerDay" in str(e):
                indisponiveis.add(modelo)  # cota do dia acabou: não adianta esperar
                continue
            if e.code in (429, 500, 502, 503, 504):
                continue
            if e.code == 404:
                indisponiveis.add(modelo)
                continue
            if e.code in (400, 401, 403):
                raise ErroDiagnostico(
                    "O Gemini recusou a chave de API. Confira se GEMINI_API_KEY está correta."
                ) from e
            raise ErroDiagnostico(f"O Gemini retornou um erro inesperado ({e.code}). Tente novamente.") from e
        except Exception as e:  # rede, timeout etc.
            ultimo_erro = e
            continue

        try:
            diagnostico = Diagnostico.model_validate_json(resposta.text or "")
        except ValidationError as e:
            raise ErroDiagnostico(
                "A IA respondeu num formato inesperado. Clique em gerar de novo."
            ) from e
        return {
            "diagnostico": diagnostico.model_dump(),
            "modelo": modelo,
            "nivel_raciocinio": nivel or "padrão do modelo",
            "segundos": round(time.perf_counter() - inicio, 1),
        }

    if isinstance(ultimo_erro, errors.APIError) and ultimo_erro.code == 429:
        raise ErroDiagnostico(
            "O limite de uso gratuito do Gemini foi atingido por agora. Espere cerca de 1 minuto e tente de novo."
        ) from ultimo_erro
    raise ErroDiagnostico(
        "O Gemini está sobrecarregado ou indisponível no momento. Espere alguns segundos e tente de novo."
    ) from ultimo_erro
