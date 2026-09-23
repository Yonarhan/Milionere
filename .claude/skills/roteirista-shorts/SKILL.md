---
name: roteirista-shorts
description: Sistema de roteirização e produção de YouTube Shorts/TikTok sem rosto com o motor (curiosidades, astronomia, gospel). Use quando o usuário pedir roteiro, ideia de vídeo, "próximo vídeo", lote de vídeos, refinar/melhorar um vídeo, ou gerar vídeos pelo motor.
---

# Roteirista de Shorts

> **Código e dados moram em `motor/milionere/`** (pacote do pipeline). Este arquivo só guarda as
> instruções. Configuração por `.env` na raiz: ver `motor/milionere/caminhos.py` (MILIONERE_VOZ,
> MILIONERE_LLM, MILIONERE_IMAGEM, MILIONERE_PLANO). Rode os scripts de dentro de `motor/`.

Pipeline completo: **tema → pesquisa → ganchos → roteiro → passe anti-IA → nota → keywords
verificadas → produção em lote → pacote de postagem → aprendizado**.

Arquivos desta skill:
- `motor/milionere/dados/referencias/ganchos.md` — fórmulas de gancho e finais. Ler SEMPRE antes de escrever.
- `motor/milionere/dados/referencias/anti-ia.md` — passe de humanização para roteiro falado. Ler SEMPRE antes de revisar.
- `motor/milionere/dados/referencias/nichos.md` — estrutura, tom, música e keywords por nicho.
- `motor/milionere/dados/referencias/persona-gospel.md` — fórmula VALIDADA do nicho gospel (ler sempre que o nicho for gospel).
- Músicas: `motor/storage/bgm/<prefixo>_*.mp3`; créditos obrigatórios em `storage/bgm/creditos.json` (vão sozinhos pro post).
- `motor/milionere/dados/presets.json` — configuração do motor por nicho (voz, legenda, ritmo, música).
- `motor/milionere/checar_keywords.py` — confere no Pexels se cada keyword tem vídeo vertical.
- `motor/milionere/produzir.py` — gera os vídeos em lote e organiza em `videos_prontos/`.
- `../../../producao/aprendizados.md` — o que já funcionou ou não. Ler antes de começar, atualizar no fim.

Caminhos: motor em `motor/`. Python do venv — Linux/WSL: `motor/.venv-linux/bin/python`
(recriar com `cd motor && UV_PROJECT_ENVIRONMENT=.venv-linux uv sync --frozen`); Windows:
`motor\.venv\Scripts\python.exe`. Os scripts escolhem sozinhos pelo sistema.
Rode os scripts com esse Python.

## 0. Pipeline automático gospel (1 comando → vídeo pronto)

```
motor/.venv-linux/bin/python motor/milionere/pipeline.py            # menu
... pipeline.py --formato historia|parabola|proverbio|personagem [--estilo cinema|oleo|pixar] [--qtd N] [--tema id]
... pipeline.py --retomar producao/roteiros/<arquivo>.json    # roteiro já aprovado: só imagens + vídeo
```
Fluxo: tema (sorteado de `motor/milionere/dados/biblia/temas.json`, sem repetir `producao/usados.json`) → roteiro via `claude -p --safe-mode`
com o texto EXATO da Bíblia Portuguesa Mundial (domínio público, `motor/milionere/dados/biblia/bpm.json`) → **camada 1** (código: tamanho,
gancho, CTA, vocabulário de IA, versículo idêntico à fonte, eventos dentro do trecho e em ordem, cenas na ordem dos
eventos, personagens declarados) → **camada 2** (juiz LLM em conversa nova: fidelidade, ordem, personagens, compreensão,
gancho, ritmo, linguagem, payoff; nota < 4 ou erro factual = reescreve, máx. 3) → imagens no ComfyUI local (padrão
para histórias: `--estilo cinema_flux`, Flux schnell GGUF; SDXL erra ação/mãos) → **camada 3** (juiz visual, 1 imagem por
vez em resolução cheia, anatomia primeiro; cena aprovada fica travada; reprovada ganha 3 opções e fica a 1ª aprovada,
máx. 2 rodadas) → `produzir.py` com e sem música (pausa inserida onde o TTS colou frases) → **camada 4** (duração 15–58 s). Tudo o que cada camada disse fica em `producao/validacao/<slug>.json`.

- Formatos: `motor/milionere/dados/formatos.json` (receita, faixa de palavras, estilo padrão). Estilos: `motor/milionere/dados/estilos.json` (edite/crie à vontade).
- Personagens fixos: `motor/milionere/dados/biblia/personagens.json` (id → aparência). Personagem bíblico novo é salvo sozinho na 1ª aparição.
- Texto bíblico: `python motor/milionere/biblia.py "Lucas 22:54-62"`.
- ComfyUI em `~/projects/milionere/ComfyUI` (instalar: `motor/milionere/instalar_comfy.sh`; `--animacao` baixa o Wan 2.2 para `movimento: ia`).
  O pipeline sobe o ComfyUI se estiver fora do ar e derruba no fim.

## 1. Briefing

Descubra (pergunte só o que faltar): **nicho** (chave do presets.json), **quantos vídeos**,
**tema** (ou "sugira"). Leia `producao/aprendizados.md` e aplique o que estiver lá.

**Caçar ideias que já viralizaram:** `python motor/milionere/ideias.py --canais` lista os Shorts mais vistos de canais de
ciência de referência (Zack D. Films, Kurzgesagt, Veritasium...) — muito melhor que a busca geral, que traz lixo.
`--transcricao <url>` baixa o texto falado de um Short. Regra: fato não tem dono, roteiro e imagens sim — nunca
traduzir o roteiro deles nem usar o vídeo; checar o fato (Short viral erra muito) e escrever do nosso jeito.

**Recriar a partir de um Short de sucesso (fluxo validado 2026-09-23):** `ideias.py --canais` → escolher o fato →
`ideias.py --transcricao <url>` → checar na FONTE PRIMÁRIA (o Short do Zack D. sobre enguias dizia "3 minutos antes do
ácido", o estudo não diz isso — cortar) → gancho e roteiro NOSSOS → registrar a origem no campo `inspiracao`.
NUNCA baixar/repostar o vídeo deles (Content ID, strike, "conteúdo reutilizado" = sem monetização).
Vídeo reaproveitável de verdade só: NASA (domínio público), Pexels/Pixabay, e YouTube com licença Creative Commons (com crédito).

Se for para sugerir temas: proponha 5–8 por nicho, cada um com o gancho candidato em 1 linha,
evitando temas já feitos (veja `producao/roteiros/`). Use WebSearch para achar assuntos em alta
quando fizer sentido (notícias de ciência/espaço da semana, datas comemorativas cristãs).

## 2. Pesquisa e checagem

- Curiosidades/astronomia: confirme cada fato em pelo menos 1 fonte confiável (WebSearch/WebFetch).
  Anote as fontes no roteiro (campo `fontes`). Na dúvida, corte o fato.
- Gospel: confirme o versículo exato (livro, capítulo:versículo, tradução).
- Nunca invente número, estudo, citação ou versículo.
- **Extrapolação é liberada (pedido do usuário, 2026-09-23):** não precisa referenciar tudo. Cheque só o FATO CENTRAL
  do vídeo; o resto pode ser cenário, dramatização e imaginação, desde que soe como hipótese ("imagina", "provavelmente",
  "ia virar") e não contradiga ciência básica de forma grosseira (erro óbvio vira comentário de "fake").

## 3. Gancho

Siga `motor/milionere/dados/referencias/ganchos.md`: 5 opções, nota, escolha. Mostre ao usuário em formato curto.

## 4. Roteiro

- Siga a estrutura do nicho em `motor/milionere/dados/referencias/nichos.md` e a faixa de palavras do `motor/milionere/dados/presets.json`.
- Uma ideia por frase. Frases de 3 a 14 palavras. Ponto final frequente (o TTS respira no ponto).
- Primeira frase = gancho escolhido. Última frase = final com loop, virada ou CTA do nicho.
- Escreva pensando nas imagens: cada frase precisa de uma cena filmável com imagem de banco.

## 5. Passe anti-IA

Aplique `motor/milionere/dados/referencias/anti-ia.md` inteiro e faça o teste final.

## 6. Nota de qualidade (portão)

Dê nota 1–5, com 1 linha de justificativa cada:

| Critério | Pergunta |
|---|---|
| Gancho | Eu pararia de rolar o feed? |
| Clareza | Entendo tudo ouvindo uma vez, sem ver a tela? |
| Ritmo | Tem alguma frase que dá pra cortar sem perder nada? (se sim, nota ≤3) |
| Payoff | O final entrega algo (surpresa, emoção, risada)? |
| Precisão | Todo fato está checado? |
| Imagem | Cada frase tem uma cena de banco de imagens clara? |

**Qualquer nota < 4 → reescreva e dê nota de novo.** Mostre a tabela final ao usuário.

## 7. Cenas (fala + imagem) — SEMPRE neste formato

Escreva o roteiro já dividido em `cenas`: cada cena = `{"fala": "<1 frase curta>", "busca": "<termo Pexels>"}`.
O `produzir.py` mede na narração em que segundo cada fala começa e corta o vídeo daquela cena
no tempo exato (modo sincronizado, `motor/milionere/sincronizar.py`). Sem isso as imagens não acompanham a fala.

- `busca` em inglês, concreta e filmável ("man praying at sunrise", não "faith"). Use `|` para
  dar uma alternativa: `"hourglass|hourglass sand time"`.
- A imagem tem que mostrar O QUE A FALA DIZ naquele momento (tempo passando → hourglass; conta → bills calculator).
- Uma cena por frase (10–16 cenas num vídeo de 30s). Cenas longas viram 2 tomadas sozinhas (`corte_max` do preset).
- Verifique as buscas antes com `checar_keywords.py` (aceita "a, b, c").

## 7b. Curadoria visual (OBRIGATÓRIA) — Claude escolhe cada imagem olhando

A busca automática pega o 1º resultado e sai desconexo. Então, para cada cena:
1. Além de `busca` (vídeo de banco, inglês), dê `arte` quando existir ilustração específica:
   - gospel: pinturas clássicas do episódio ("raising of Lazarus|Rembrandt Lazarus", "Jonah and the whale painting")
     e fotos históricas de lugares bíblicos ("tomb of Lazarus Bethany") — Wikimedia/Met, domínio público;
   - astronomia: imagens reais da NASA ("Andromeda galaxy", "solar flare");
   - curiosidades: gravuras/fotos históricas no Wikimedia quando o tema for histórico.
2. `python motor/milionere/curadoria.py <roteiros.json> --slug <slug>` (~15 s, buscas em paralelo) → UMA folha
   `producao/curadoria/<slug>/folha_geral.png` (1 linha por cena, rótulos `cena.N`; `--detalhe` gera folhas por cena).
3. Abra (Read) a folha geral e escolha o número que mostra literalmente o que a fala diz (pessoa certa,
   clima certo, época certa — nada de tênis/celular em cena bíblica, nada de gente rindo em cena de dor).
   Se nenhum serve, troque `busca`/`arte` e rode de novo com `--cenas N`.
4. Grave as escolhas de uma vez: `python motor/milionere/escolher.py <roteiros.json> <slug> "1.1 2.3,2.4 3.3 ..."`
   (vírgula = 2 tomadas na mesma cena). Pinturas/fotos viram clipe com zoom lento; os créditos das obras
   entram sozinhos no `.txt` do post.

## 7c. Imagens geradas por IA (melhor resultado para histórias bíblicas)

Banco nenhum tem "Jesus chorando no túmulo". Para as cenas-chave (4–8 por vídeo), o usuário gera no app
do Gemini (grátis; a API de imagem do Gemini exige faturamento — cota grátis = 0 em 2026-09-22):
1. Entregue UM prompt por mensagem (senão o Gemini junta tudo numa imagem só), cada um começando com
   "Generate ONE single image, vertical 9:16." + descrição fixa dos personagens + cena + bloco de estilo +
   "No text, no watermark, no halo, no modern objects." A partir do 2º: "Use the same Jesus from the first image."
   Personagens e estilo padrão em `motor/milionere/dados/referencias/personagens-biblicos.md`.
2. Ele salva em `producao/midia/<slug>/cena_NN.jpg` (NN = número da cena; `cena_NNb.jpg` = 2ª tomada).
3. Arquivos dessa pasta têm PRIORIDADE sobre curadoria/busca. 1 imagem numa cena longa vira 1 tomada contínua.
Cenas genéricas (ampulheta, nascer do sol, mãos na Bíblia, abraço) seguem no banco com curadoria.

## 8. Salvar e produzir

Salve os roteiros aprovados em `producao/roteiros/<AAAA-MM-DD>_<lote>.json` no formato descrito
em `motor/milionere/produzir.py` (slug, nicho, titulo, roteiro, keywords, descricao, hashtags,
comentario_fixado, fontes, ajustes). Depois:

1. `python motor/milionere/produzir.py <arquivo> --seco` — confere duração estimada e avisos.
2. Se o usuário quiser ouvir antes: `--so-audio` (gera só a narração em `videos_prontos/`).
3. `python motor/milionere/produzir.py <arquivo>` — gera os vídeos. Pode levar alguns minutos por vídeo;
   rode em background e avise o usuário.

Os vídeos saem em `videos_prontos/<data>_<slug>.mp4` com um `.txt` do post ao lado.

**Revisão visual obrigatória:** depois de gerar, abra (Read) o `painel.png` que o script indica e
confira tomada por tomada: a imagem combina com a fala? o clima é o certo (nada de gente rindo em
cena de dor)? No gospel, nada de outra religião (mesquita, templo budista etc. — o preset já filtra
por `evitar_termos`, mas confira). Troque a `busca` das cenas ruins e gere de novo antes de entregar.
A montagem final é feita por `motor/milionere/renderizar.py` (ffmpeg + placa de vídeo, ~10s por vídeo).

## 8b. Padrão: Claude gera o vídeo

O padrão é Claude rodar `produzir.py` e entregar o vídeo pronto em `videos_prontos/` — o usuário
não preenche a WebUI. Só entregue a ficha de `motor/milionere/dados/referencias/ficha-webui.md` (ordem e rótulos da tela)
se o usuário pedir para preencher ele mesmo ou quiser replicar um vídeo na WebUI.

## 9. Pacote de postagem

Para cada vídeo, o `.txt` já tem título, descrição, hashtags e comentário fixado. Regras:
- Título ≤ 60 caracteres, com a curiosidade (não repetir o gancho palavra por palavra).
- Descrição: 1–2 frases + "Vídeos: Pexels" + 3–5 hashtags (sempre #shorts).
- Lembrar: marcar conteúdo sintético = Sim; postar pelo app no celular permite adicionar som em alta.
- TikTok: o usuário posta SEM música e escolhe um áudio do TikTok → gerar também com `--sem-musica` e entregar a
  legenda curta do TikTok (1 frase + 5–6 hashtags, incluindo #fyp). Deixar a voz em volume alto; ele baixa o áudio do TikTok no app.

## 10. Aprendizado

Quando o usuário der feedback (gostou/não gostou, views, retenção), registre em
`producao/aprendizados.md` como regra curta e acionável, com a data. Exemplo:
`- 2026-09-22: música triste em curiosidades = ruim. Usar suspense/animado.`
Se a regra mudar um preset (voz, velocidade, música), altere também `motor/milionere/dados/presets.json`.
