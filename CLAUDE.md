# Contexto do projeto — Agente de Análise de Atrasos em Entregas

> Documento de contexto para o Claude Code. Resume tudo o que foi decidido antes de começar a construir.
> Leia inteiro antes de escrever código. Em caso de dúvida sobre escopo, priorize o **MVP** (seção 6).

---

## 0. Estado atual e como retomar (atualizado em 15/11/2026)

> As seções 1 a 16 abaixo são o plano original. **O estado real é este bloco.**

### Onde está
- App no ar: https://agente-atrasos.streamlit.app · Repositório: https://github.com/lgthebaldi/agente-atrasos-entregas
- `main` tem: análise com pandas, 4 abas (Visão geral, **Mapa** de São Paulo com filtros, Onde está o atraso, Diagnóstico da IA), agente com Gemini (`gemini-3.6-flash`, raciocínio `minimal`), `validacao.py`, README com GIF, LICENSE e `cover.png`.
- **O Streamlit Cloud publica sozinho a cada push no `main`.** Mudança de código arriscada vai em branch e só entra no `main` depois de testada.
- Branch `groq-reserva`: integração com o Groq (`qwen/qwen3.8-27b`). **Não está no `main`** (ver pendência 2).
- Commits saem no nome do Luis (git config local) e mantêm o Claude como coautor.

### Chaves numa sessão de nuvem (leia antes de dizer "falta chave")
- As chaves **não são variáveis de ambiente de verdade**. Ficam como *segredos de rede* do ambiente **"GEN IA iFood"** (`generativelanguage.googleapis.com` com o cabeçalho `x-goog-api-key` e `api.groq.com` com `Authorization: Bearer`). O proxy da sessão coloca a chave real na chamada.
- Por isso o ambiente define `GEMINI_API_KEY=proxy-injected` e `GROQ_API_KEY=proxy-injected`: é um **valor de mentira** só para o código achar uma variável. O proxy o troca pela chave real. Não é segredo.
- **Nunca peça nem cole uma chave real no chat.** Se faltar chave: (1) confira se a sessão foi criada no ambiente **GEN IA iFood** (e não no "Default", que não tem as chaves); (2) se vier erro `401/403` ou `request blocked: no rule allows host`, espere cerca de 1 minuto e tente de novo.
- A rede do ambiente é limitada. Hosts liberados além dos padrões: `agente-atrasos.streamlit.app`, `share.streamlit.io`, `basemaps.cartocdn.com`, `tiles.basemaps.cartocdn.com`, `lgthebaldi.github.io`.
- No computador do Luis, a chave real fica no `.env` (fora do git).

### Cotas do plano gratuito (gaste com cuidado)
- **Gemini:** cerca de 20 chamadas por dia **por modelo**. `gemini-3.5-flash` divide a cota com o `3.6`. Erro 429 "PerDay" não adianta esperar.
- **Groq:** 1.000 chamadas por dia, mas só 8.000 tokens por minuto (cerca de 1 diagnóstico por minuto): deixe **70 s ou mais** entre execuções.
- O app guarda o diagnóstico em cache por 6 h (chave: resumo + versão do prompt) e, se a cota acabar, mostra um diagnóstico real já validado (`data/diagnostico_exemplo.json`).

### Pendências, em ordem
1. **Revalidar o Gemini com o prompt atual** (a última validação foi antes do ajuste de vírgula decimal e de "sem nomes técnicos"): `python validacao.py --execucoes 3 --modelo gemini-3.6-flash --pausa 30` e **o teste negativo no modelo principal** (`python gerar_dados.py --controle`, depois `python validacao.py --base data/entregas_controle.csv --controle --execucoes 3`). Hoje o negativo só foi feito no modelo reserva `lite`. Atualizar a tabela de resultados do README.
2. **Groq:** o `qwen` acha os 4 padrões (4/4), mas **inventa padrões fracos** na base sem padrões (ex.: "Zona Leste" com 1,4 ponto acima da média). Antes de entrar no `main`: o **pandas** deve marcar no resumo quais segmentos são relevantes (≥ 8 pontos acima da média e n ≥ 50), em vez de deixar a IA decidir; depois revalidar positivo e negativo. Só então mesclar `groq-reserva`.
3. (Opcional) Aba "Como validei" dentro do app, mostrando os resultados.

### Não fazer
- Não baixar o limite de 8 pontos só para o teste passar (corrija a causa, como o impacto já calculado pelo pandas).
- Não commitar chaves; conferir `git diff --cached` antes de cada push.
- Não misturar com o projeto 2 ("Chega bem até você?", com Ollama): ele vive em outra pasta/repositório.

---

## 1. Por que este projeto existe

- Sou estudante de Engenharia de Controle e Automação (Unicamp, formatura no 2º semestre de 2027) e estagiário de engenharia na indústria.
- Estou me candidatando ao **Programa de Estágio GEN IA 2027 do iFood**, trilha **AI Builder**, com 1ª área de interesse **Operações e Logística** e 2ª **Produto**.
- **Prazo de inscrição: 17/11/2026.** Meta de envio: 16/11. O projeto precisa estar no ar até domingo, 15/11, à noite. Se não estiver, a inscrição vai sem ele.
- O formulário tem um campo opcional "GitHub / repositório / portfólio". Este projeto é o link que vai nesse campo.
- A vaga AI Builder pede, no portfólio: *"automações que economizaram horas reais, ferramentas internas deployadas, dashboards funcionais, agentes que resolvem problemas de negócio e demos de produtos construídos do zero em dias"*.
- Competências listadas na vaga: prompt engineering avançado, orquestração de agentes (Claude, GPT, Gemini), automações (n8n, Make, Zapier), vibe coding (Cursor, v0, Bolt, Replit), APIs sem backend profundo e análise de dados com IA.

## 2. A ideia em uma frase

Um gestor de operações sobe a base de entregas, e o app mostra **onde os atrasos se concentram, por que acontecem e o que fazer**, em linguagem simples, com o diagnóstico escrito por IA e **validado**.

## 3. Decisão de arquitetura principal

**A IA não calcula, ela interpreta.**

- O **pandas** calcula todas as estatísticas (taxas de atraso por segmento e por combinação).
- A **IA (Gemini)** recebe só a tabela resumida (poucos KB) e escreve o diagnóstico e o plano de ação, **citando apenas os números que recebeu**.
- Motivos: custo baixo, resposta rápida e menos alucinação. Não enviar as 5.000 linhas cruas para o modelo.

## 4. Camadas

| # | Camada | O que faz | Ferramenta |
|---|---|---|---|
| 1 | Dados | Base fictícia de 5.000 pedidos com padrões plantados, reproduzível (seed 42) | `gerar_dados.py` |
| 2 | Análise | KPIs e taxas de atraso por segmento e por combinação | pandas |
| 3 | IA | Recebe o resumo e devolve diagnóstico estruturado (padrão, causa provável, ação, métrica) | API do Gemini |
| 4 | Validação | Verifica se a IA encontra os 4 padrões plantados e se não inventa padrões numa base sem eles | `validacao.py` |
| 5 | Interface | Telas para usuário de negócio | Streamlit |
| 6 | Publicação | GitHub público + Streamlit Community Cloud, chave protegida | GitHub, Streamlit Cloud |
| 7 | Documentação | README contando a história | Markdown |

## 5. Dados

### 5.1 Esquema do CSV (`data/entregas_ficticias.csv`)

| Coluna | Tipo | Descrição |
|---|---|---|
| pedido_id | texto | Ex.: PED100000 |
| data | data ISO | 2026-08-01 a 2026-10-30 |
| dia_semana | texto | Segunda … Domingo |
| hora_pedido | inteiro | 10 a 23 |
| regiao | texto | Centro, Zona Sul, Zona Oeste, Zona Norte, Zona Leste |
| restaurante | texto | 12 restaurantes fictícios |
| categoria | texto | Lanches, Pizza, Japonesa etc. |
| modal | texto | Moto ou Bicicleta |
| chuva | texto | Sim / Não |
| distancia_km | float | |
| tempo_preparo_min | inteiro | |
| tempo_espera_entregador_min | inteiro | |
| tempo_prometido_min | inteiro | |
| tempo_real_min | inteiro | |
| atraso_min | inteiro | max(0, real − prometido) |
| atrasou | texto | Sim / Não |
| latitude | float | Fictícia, sorteada dentro da zona (gerador separado, seed 2026) |
| longitude | float | Idem; usadas só no mapa, não entram no resumo da IA |

### 5.2 Padrões plantados (a "resposta certa" para a validação)

Taxa geral de atraso: **28,2%**. Valores medidos na base gerada:

| # | Padrão | Evidência |
|---|---|---|
| 1 | **Chuva no pico do jantar (19h–21h)** | 81,2% de atraso, contra ~21% sem chuva. Chuva fora do pico: 48,1% |
| 2 | **Bicicleta acima de 4 km** | 91,4% de atraso, contra 35,6% em bicicleta até 4 km. Moto: 17,5% |
| 3 | **Dois restaurantes com gargalo na cozinha** (Pizzaria Bella Massa e Churrascaria Fogo Bravo) | ~60% de atraso cada, contra ~25% dos demais; tempo de preparo alto e instável |
| 4 | **Zona Leste** (distâncias maiores e menos entregadores) | 36,3%, contra 21,8% no Centro. Sexta e sábado também acima da média: 34,2% e 32,1% no dia todo; 39,7% (n=370) e 38,8% (n=345) a partir das 19h |

Se o CSV não estiver disponível, regenere com `python gerar_dados.py` (grava em `data/entregas_ficticias.csv`).

## 6. Escopo

### MVP (obrigatório até domingo)
- Camadas 1, 2, 3, 5 e 6.
- Telas 1 a 4 (seção 7).
- Validação manual: rodar, conferir se os 4 padrões aparecem e registrar o resultado no README.

### Extras (só se sobrar tempo)
- `validacao.py` automatizado + tela 5.
- Base de controle **sem padrões** (variação do gerador com os efeitos desligados) para testar se a IA inventa padrões.
- GIF ou vídeo curto da demo no README.

### Fora do escopo
- Login, banco de dados, backend próprio, modelos de ML treinados, dados reais de qualquer empresa.

## 7. Telas (Streamlit)

1. **Início:** botão "Usar base de exemplo" ou upload de CSV no mesmo esquema. Validar colunas e mostrar erro amigável se faltar alguma.
2. **Visão geral:** cartões com total de pedidos, taxa de atraso e atraso médio (entre os atrasados).
3. **Onde está o atraso:** gráficos de taxa de atraso por região, hora, modal, chuva, dia da semana e restaurante, mais as combinações chuva × pico e modal × faixa de distância.
4. **Diagnóstico da IA:** botão "Gerar diagnóstico". Mostra de 3 a 5 padrões, cada um com: padrão, evidência (número), causa provável, ação sugerida e métrica para acompanhar. Mostrar também um aviso: "diagnóstico gerado por IA a partir das estatísticas acima; confirme antes de agir".
5. **Validação (extra):** "A IA encontrou X de 4 padrões plantados e Y padrões falsos na base de controle".

Interface em português, simples, pensada para um gestor sem conhecimento técnico.

## 8. Camada de IA

### 8.1 Configuração
- Usar o SDK oficial do Google (`google-genai`). Confira na documentação atual o nome do pacote e o modelo **Flash** disponível no plano gratuito do Google AI Studio.
- Nome do modelo em variável de ambiente (`GEMINI_MODEL`), com um padrão no código.
- Chave em `GEMINI_API_KEY`: localmente via `.env` (com `python-dotenv`); no Streamlit Cloud via `st.secrets`. O código deve aceitar os dois.
- Pedir resposta em **JSON** (structured output, se o SDK suportar) e tratar falhas de parsing com uma mensagem amigável.
- Temperatura baixa (ex.: 0,2) para respostas consistentes.

### 8.2 O que enviar ao modelo
Um resumo compacto gerado por `analise.py`, por exemplo:
- Taxa geral de atraso e número de pedidos.
- Taxa de atraso e n por: região, hora (ou faixas), modal, chuva, dia da semana, restaurante.
- Combinações: chuva × pico (19h–21h), modal × distância (≤4 km / >4 km), dia × noite (sexta e sábado ≥19h).
- Tempo médio de preparo e de espera por restaurante e por região.

Incluir o tamanho da amostra (n) de cada segmento, para a IA não tirar conclusão de grupos pequenos.

### 8.3 Rascunho do prompt (ajustar se necessário)

```
Você é um analista de operações de uma plataforma de delivery.
Recebe estatísticas agregadas de atrasos de entregas (já calculadas; não recalcule).

Tarefa: identificar de 3 a 5 padrões que mais explicam os atrasos e propor ações.

Regras:
- Use SOMENTE os números fornecidos. Nunca invente dados.
- Cada padrão deve citar a evidência numérica (taxa do segmento vs. referência e o n).
- Ignore segmentos com menos de 50 pedidos.
- Se não houver diferença relevante (ex.: menos de 8 pontos percentuais acima da média geral), diga que não há padrão claro em vez de forçar uma conclusão.
- Ordene do maior para o menor impacto (taxa × volume).
- Ações devem ser práticas e testáveis em poucas semanas.

Responda em JSON:
{
  "resumo": "2 frases para um gestor",
  "padroes": [
    {
      "padrao": "...",
      "evidencia": "...",
      "causa_provavel": "...",
      "acao_sugerida": "...",
      "metrica_para_acompanhar": "..."
    }
  ],
  "limitacoes": "o que estes dados não permitem concluir"
}
```

## 9. Validação

- **Positiva:** na base de exemplo, o diagnóstico deve mencionar os 4 padrões da seção 5.2. Checagem simples: busca por palavras-chave por padrão (ex.: "chuva" + "pico/19h/jantar"; "bicicleta" + "4 km/distância"; nome de pelo menos um dos 2 restaurantes; "Zona Leste").
- **Negativa (extra):** numa base gerada sem os efeitos, o modelo deve dizer que não há padrão claro, ou apontar no máximo diferenças pequenas.
- Rodar algumas vezes (ex.: 3) e registrar no README quantas vezes acertou cada padrão.
- Essa validação é o principal diferencial do projeto: na entrevista, o gestor vai perguntar "como você valida a solução de IA?".

## 10. Estrutura do repositório

```
agente-atrasos/
├── app.py              # interface Streamlit
├── analise.py          # cálculos com pandas (funções puras, testáveis)
├── agente.py           # prompt + chamada ao Gemini + parsing do JSON
├── validacao.py        # teste dos padrões (extra)
├── gerar_dados.py      # gera a base fictícia (Anexo A)
├── data/
│   └── entregas_ficticias.csv
├── requirements.txt
├── .env.example        # GEMINI_API_KEY=  /  GEMINI_MODEL=
├── .gitignore          # inclui .env e .streamlit/secrets.toml
└── README.md
```

## 11. Segurança (obrigatório)

- **Nunca** commitar a chave de API. `.env` e `.streamlit/secrets.toml` no `.gitignore` desde o primeiro commit.
- Antes de cada push, conferir com `git status` / `git diff --cached` que nenhum segredo entrou.
- No Streamlit Cloud, a chave vai em **Settings → Secrets**.
- Apenas dados fictícios. Nada de dados, nomes de sistemas ou métricas de empresas reais.

## 12. Publicação

1. Repositório público no GitHub com nome claro (ex.: `agente-atrasos-entregas`).
2. Deploy no Streamlit Community Cloud apontando para `app.py`.
3. Configurar `GEMINI_API_KEY` nos Secrets.
4. Testar o link público em uma janela anônima.
5. Colocar o link do app no topo do README.

## 13. README (estrutura)

1. **Título + link da demo** (e GIF, se houver).
2. **Problema:** atrasos de entrega afetam cliente, entregador e restaurante.
3. **Solução:** o que o app faz, em 3 linhas.
4. **Como funciona:** diagrama simples das camadas; destacar "pandas calcula, IA interpreta".
5. **Como usei IA para construir:** feito com vibe coding (Claude Code) em ~1 dia; IA dentro do produto via API do Gemini.
6. **Como validei:** padrões plantados, resultado (X de 4, em N execuções), teste negativo se feito.
7. **Exemplo de saída:** um trecho do diagnóstico gerado.
8. **Limitações:** dados fictícios; correlação não é causalidade; a IA depende da qualidade das estatísticas.
9. **Próximos passos:** dados reais/streaming, previsão de chuva para agir antes do pico, alerta à cozinha quando o preparo estoura, teste A/B das ações.
10. **Como rodar localmente.**

Tom: claro, para recrutador não técnico, sem exageros.

## 14. Competências que o projeto deve evidenciar

| Pedido pela vaga | Onde aparece |
|---|---|
| Prompt engineering avançado | Prompt com papel, dados estruturados, regras anti-alucinação e saída em JSON |
| Vibe coding | Projeto construído com Claude Code em ~1 dia |
| APIs sem backend profundo | Integração direta com a API do Gemini |
| Análise de dados com IA | pandas calcula, IA interpreta e recomenda |
| Ferramenta deployada / demo em dias | App público no Streamlit Cloud |
| Resolver problema de negócio | Atraso de entregas (Operações e Logística) |

Valores da cultura iFood que o projeto reforça: Priorize 80/20 e Entregue (MVP enxuto), Falhe Rápido e Aprenda, Mentalidade de Dono (feito para o gestor usar sozinho) e validação como pensamento analítico.

## 15. Plano de sábado (≈4h)

| Bloco | Tarefa | Tempo |
|---|---|---|
| 1 | Pasta, ambiente virtual, `requirements.txt`, `.env`, `.gitignore`, CSV | 30 min |
| 2 | `analise.py` + telas 1 a 3 | 1h |
| 3 | `agente.py` (prompt) + tela 4 | 1h |
| 4 | Testar os 4 padrões e ajustar o prompt | 45 min |
| 5 | GitHub + Streamlit Cloud + Secrets | 45 min |

Domingo: README, currículo e LinkedIn. Segunda (16/11): envio da inscrição.

## 16. Definição de pronto

- [ ] App abre no link público sem erro.
- [ ] Base de exemplo carrega com um clique.
- [ ] Gráficos mostram as taxas por segmento e combinação.
- [ ] Diagnóstico da IA aparece em até ~30 s e cita os 4 padrões na base de exemplo.
- [ ] Nenhum segredo no repositório.
- [ ] README completo com link da demo e seção "Como validei".

---

## Anexo A — `gerar_dados.py`

```python
"""
Gera uma base FICTÍCIA de entregas para o projeto "Agente de Análise de Atrasos".
Nenhum dado real é usado. Os padrões abaixo foram plantados de propósito,
para que o agente consiga descobri-los e explicá-los:

  1. Chuva + pico do jantar (19h-21h) aumenta muito o atraso.
  2. Região "Zona Leste" tem distâncias maiores e menos entregadores -> mais atraso.
  3. Dois restaurantes têm tempo de preparo alto e instável (gargalo na cozinha).
  4. Entregas de bicicleta acima de 4 km atrasam bem mais que de moto.
  5. Sexta e sábado à noite têm fila maior de pedidos.
"""
import numpy as np
import pandas as pd

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
    dia = dias[data.dayofweek]
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
    if rest in gargalos:
        preparo = rng.normal(24, 8)
    if pico:
        preparo += 3
    preparo = max(5, preparo)

    # espera por entregador
    espera = rng.exponential(3) / regioes[regiao]["oferta"]
    if chuva:
        espera += rng.exponential(5)
    if fim_semana_noite:
        espera += rng.exponential(4)

    # deslocamento
    vel = 22 if modal == "Moto" else 13
    if chuva:
        vel *= 0.75
    desloc = dist / vel * 60
    if modal == "Bicicleta" and dist > 4:
        desloc *= 1.35

    real = preparo + espera + desloc + rng.normal(0, 2)
    if chuva and pico:
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
df.to_csv("entregas_ficticias.csv", index=False, encoding="utf-8")
print(f"{len(df)} pedidos gerados -> entregas_ficticias.csv")
```

Para a base de controle sem padrões (extra), crie uma variação deste script em que: todos os restaurantes usam `preparo = rng.normal(14, 3)`, a oferta é 1,0 em todas as regiões, a chuva não altera espera nem velocidade, não há bônus `chuva and pico` nem `fim_semana_noite`, e a bicicleta não tem o multiplicador acima de 4 km.

---

## Anexo B — Contexto da candidatura (referência, não é tarefa de código)

- **Etapas do GEN IA 2027:** inscrição → entrevista automatizada por IA (WhatsApp, texto e áudio, adaptativa) → desafio técnico online (na 1ª edição: HackerRank, 1h30, atividades com IA, sem trocar de aba nem colar) → entrevista com recrutamento → entrevista técnica ou case (ao vivo) → entrevista com liderança → início em fev/2027.
- **Respostas do formulário:** trilha AI Builder; áreas Operações e Logística / Produto; formatura no 2º semestre de 2027; ferramentas: prompt engineering e orquestração de agentes, automações integrando IA, vibe coding + APIs de IA (e "tudo combinado com resultado mensurável" se aplicável); portfólio: automações que economizaram horas, ferramentas/dashboards/agentes, soluções em produção com resultado mensurável. Não marcar "Todas as opções acima".
- **Ideias de melhoria para levar à entrevista (perspectiva do consumidor):**
  - Principal: **"Chega bem até você?"** — IA lê avaliações ("chegou frio", "veio murcho"), cruza com distância e sinaliza pratos que viajam bem ou sugere a versão que viaja melhor. O iFood lançou em jul/2026 uma bag rígida para pizzas, então o problema é reconhecido, mas não achei indicador para o consumidor.
  - Secundária: **pedido por orçamento** — "R$ 50 para 2 pessoas", IA monta combinações com preço final incluindo taxa. O Ailo (assistente de IA do iFood no WhatsApp) recomenda por preferência e tempo, mas não encontrei filtro de preço.
  - Operações: **"FPY do pedido"** — % de pedidos perfeitos, quebrado por etapa (preparo × coleta × entrega), com Pareto de causas e alerta em tempo real; posicionar como evolução da Toqan para restaurantes.
- **Este projeto conecta com o case provável** ("o tempo de entrega subiu de 32 para 37 min; diagnostique"): quebrar o tempo por etapa, segmentar por região/horário/clima/modal, propor ações rápidas e testáveis, validar com piloto.
