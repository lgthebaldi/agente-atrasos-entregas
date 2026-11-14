"""
Camada de IA: prompt + chamada ao modelo + leitura da resposta em JSON.

A IA não calcula nada. Ela recebe o resumo pronto de analise.resumo_para_ia()
e devolve um diagnóstico estruturado, citando só os números que recebeu.

Dois provedores, com troca automática:
- Gemini (Google AI Studio): modelo principal, validado com o validacao.py.
- Groq: reserva com cota bem maior no plano gratuito (~1.000 chamadas/dia).
"""
from __future__ import annotations

import copy
import json
import os
import time

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

MODELO_PADRAO = "gemini-3.6-flash"
# Ordem de reserva. O limite gratuito do Gemini é por modelo (~20 chamadas/dia);
# o do Groq é ~1.000/dia. Obs.: "gemini-3.5-flash" é atendido pelo 3.6 e divide a
# mesma cota, por isso não serve de reserva.
MODELOS_RESERVA = ["qwen/qwen3.8-27b", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# Modelos que acertaram os 4 padrões plantados em todas as execuções do validacao.py.
MODELOS_VALIDADOS = ["gemini-3.6-flash", "qwen/qwen3.8-27b"]
TEMPERATURA = 0.2
# Raciocínio do Gemini ("minimal", "low", "medium", "high"). "minimal" foi escolhido
# com o validacao.py: acertou os 4 padrões em todas as execuções e responde em ~15 s.
NIVEL_RACIOCINIO_PADRAO = "minimal"
# Raciocínio dos modelos gpt-oss no Groq ("low", "medium", "high"); o qwen ignora.
ESFORCO_GROQ = "low"
MAX_TOKENS_RESPOSTA_GROQ = 3000
TENTATIVAS_POR_MODELO = 2
ESPERA_ENTRE_TENTATIVAS_S = 4

PROMPT_SISTEMA = """\
Você é um analista de operações de uma plataforma de delivery.
Recebe estatísticas agregadas de atrasos de entregas (já calculadas; não recalcule).

Tarefa: identificar de 3 a 5 padrões que mais explicam os atrasos e propor ações.

Regras:
- Use SOMENTE os números fornecidos. Nunca invente dados.
- Não faça contas: não some, não subtraia e não tire média de números. Se um padrão envolve
  mais de um segmento, cite os números de cada um separadamente.
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
- Não use nomes técnicos de campos (como excesso_atrasados ou taxa_atraso_pct): escreva por extenso,
  por exemplo "355 atrasos acima do esperado".
- Escreva números no padrão brasileiro, com vírgula decimal (ex.: 28,2%).
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
    """Erro com mensagem amigável para mostrar na tela; `detalhe` guarda a causa técnica."""

    def __init__(self, mensagem: str, detalhe: str = ""):
        super().__init__(mensagem)
        self.detalhe = detalhe


class _Falha(Exception):
    """Falha de uma chamada. acao: 'repetir', 'pular_modelo', 'pular_provedor' ou 'parar'."""

    def __init__(self, acao: str, mensagem: str = "", cota: bool = False):
        super().__init__(mensagem)
        self.acao, self.cota = acao, cota


# ---------- chaves e modelos ----------
CHAVES = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}


def provedor(modelo: str) -> str:
    return "gemini" if modelo.startswith("gemini") else "groq"


def obter_chave(nome_provedor: str = "gemini") -> str | None:
    """Chave do .env (local) ou dos Secrets do Streamlit Cloud."""
    variavel = CHAVES[nome_provedor]
    chave = os.getenv(variavel)
    if chave:
        return chave
    try:
        import streamlit as st
        return st.secrets.get(variavel)
    except Exception:
        return None


def modelos_a_tentar() -> list[str]:
    principal = os.getenv("GEMINI_MODEL") or MODELO_PADRAO
    return [principal] + [m for m in MODELOS_RESERVA if m != principal]


def nivel_raciocinio() -> str | None:
    return os.getenv("GEMINI_THINKING_LEVEL") or NIVEL_RACIOCINIO_PADRAO


# ---------- Gemini ----------
def _chamar_gemini(modelo: str, conteudo: str, chave: str, nivel: str | None) -> str:
    from google import genai
    from google.genai import errors, types

    config = types.GenerateContentConfig(
        system_instruction=PROMPT_SISTEMA,
        temperature=TEMPERATURA,
        response_mime_type="application/json",
        response_schema=Diagnostico,
        thinking_config=types.ThinkingConfig(thinking_level=nivel) if nivel else None,
    )
    try:
        resposta = genai.Client(api_key=chave).models.generate_content(
            model=modelo, contents=conteudo, config=config)
    except errors.APIError as e:
        if e.code == 429 and "PerDay" in str(e):
            raise _Falha("pular_modelo", str(e), cota=True) from e  # cota do dia acabou
        if e.code == 429:
            raise _Falha("repetir", str(e), cota=True) from e
        if e.code in (500, 502, 503, 504):
            raise _Falha("repetir", str(e)) from e
        if e.code == 404:
            raise _Falha("pular_modelo", str(e)) from e
        if e.code in (400, 401, 403):
            raise _Falha("pular_provedor", "O Gemini recusou a chave de API (GEMINI_API_KEY).") from e
        raise _Falha("pular_modelo", str(e)) from e
    return resposta.text or ""


# ---------- Groq ----------
def _schema_estrito(modelo_pydantic: type[BaseModel]) -> dict:
    """JSON Schema com additionalProperties=false em todos os objetos (modo estrito do Groq)."""
    schema = copy.deepcopy(modelo_pydantic.model_json_schema())

    def fechar(no):
        if isinstance(no, dict):
            if no.get("type") == "object":
                no["additionalProperties"] = False
                no["required"] = list(no.get("properties", {}))
            for v in no.values():
                fechar(v)
        elif isinstance(no, list):
            for v in no:
                fechar(v)

    fechar(schema)
    return schema


def _chamar_groq(modelo: str, conteudo: str, chave: str) -> str:
    import groq

    extras = {"reasoning_effort": ESFORCO_GROQ} if modelo.startswith("openai/gpt-oss") else {}
    try:
        resposta = groq.Groq(api_key=chave, max_retries=0).chat.completions.create(
            model=modelo,
            messages=[{"role": "system", "content": PROMPT_SISTEMA},
                      {"role": "user", "content": conteudo}],
            temperature=TEMPERATURA,
            # A resposta usa ~1.600 tokens. Um teto explícito evita que o Groq reserve o
            # máximo do modelo no limite de 8.000 tokens/min do plano gratuito.
            max_completion_tokens=MAX_TOKENS_RESPOSTA_GROQ,
            response_format={"type": "json_schema", "json_schema": {
                "name": "diagnostico", "strict": True, "schema": _schema_estrito(Diagnostico)}},
            **extras,
        )
    except groq.RateLimitError as e:
        # Limite por minuto (~1 diagnóstico/min) ou por dia: em ambos, esperar 4 s não resolve.
        raise _Falha("pular_modelo", str(e), cota=True) from e
    except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as e:
        raise _Falha("repetir", str(e)) from e
    except groq.APIStatusError as e:
        if e.status_code in (401, 403):
            raise _Falha("pular_provedor", "O Groq recusou a chave de API (GROQ_API_KEY).") from e
        if e.status_code == 404:
            raise _Falha("pular_modelo", str(e)) from e
        raise _Falha("repetir", str(e)) from e  # ex.: 400 quando a resposta não segue o schema
    return resposta.choices[0].message.content or ""


# ---------- orquestração ----------
def gerar_diagnostico(resumo: dict, chave: str | None = None,
                      nivel: str | None = None, modelos: list[str] | None = None) -> dict:
    """
    Envia o resumo ao primeiro modelo disponível e devolve o diagnóstico validado,
    mais metadados (modelo usado e tempo). Lança ErroDiagnostico se nenhum responder.
    `chave` (opcional) vale para o Gemini; as demais vêm do .env / Secrets.
    """
    nivel = nivel or nivel_raciocinio()
    conteudo = "Estatísticas de atraso (JSON):\n" + json.dumps(resumo, ensure_ascii=False, separators=(",", ":"))
    chaves = {p: (chave if p == "gemini" and chave else obter_chave(p)) for p in CHAVES}
    lista = modelos or modelos_a_tentar()
    lista = [m for m in lista if chaves[provedor(m)]]
    if not lista:
        raise ErroDiagnostico(
            "Nenhuma chave de IA configurada. Coloque GEMINI_API_KEY (e, se quiser, GROQ_API_KEY) "
            "no arquivo .env (local) ou em Settings → Secrets (Streamlit Cloud)."
        )

    bloqueados: set[str] = set()   # modelos ou provedores que não adianta tentar de novo
    ultima: _Falha | None = None
    mensagens_chave: list[str] = []
    for modelo in lista:
        for n_tentativa in range(TENTATIVAS_POR_MODELO):
            if modelo in bloqueados or provedor(modelo) in bloqueados:
                break
            if n_tentativa > 0:
                time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
            inicio = time.perf_counter()
            try:
                if provedor(modelo) == "gemini":
                    texto = _chamar_gemini(modelo, conteudo, chaves["gemini"], nivel)
                else:
                    texto = _chamar_groq(modelo, conteudo, chaves["groq"])
            except _Falha as f:
                ultima = f
                if f.acao == "pular_modelo":
                    bloqueados.add(modelo)
                elif f.acao == "pular_provedor":
                    bloqueados.add(provedor(modelo))
                    mensagens_chave.append(str(f))
                continue
            except Exception as e:  # rede, timeout etc.
                ultima = _Falha("repetir", str(e))
                continue

            try:
                diagnostico = Diagnostico.model_validate_json(texto)
            except ValidationError:
                ultima = _Falha("repetir", "resposta fora do formato")
                continue
            return {
                "diagnostico": diagnostico.model_dump(),
                "modelo": modelo,
                "nivel_raciocinio": (nivel or "padrão do modelo") if provedor(modelo) == "gemini" else ESFORCO_GROQ,
                "segundos": round(time.perf_counter() - inicio, 1),
            }

    detalhe = str(ultima)[:500] if ultima else ""
    if mensagens_chave and len(mensagens_chave) == len({provedor(m) for m in lista}):
        raise ErroDiagnostico(" ".join(mensagens_chave) + " Confira as chaves configuradas.", detalhe)
    if ultima is not None and ultima.cota:
        raise ErroDiagnostico(
            "O limite de uso gratuito da IA foi atingido por agora. Espere cerca de 1 minuto e tente de novo.",
            detalhe,
        )
    raise ErroDiagnostico(
        "A IA está sobrecarregada ou indisponível no momento. Espere alguns segundos e tente de novo.",
        detalhe,
    )
