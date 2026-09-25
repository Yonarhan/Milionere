# Como rodar o projeto

Visão geral: [RESUMO_DO_PROJETO.md](RESUMO_DO_PROJETO.md) · Produto e roadmap: [docs/PRODUTO.md](docs/PRODUTO.md)

## 1. Requisitos
- Python 3.11 ou 3.12 e Git
- Placa NVIDIA é opcional (acelera a montagem). Sem ela, o sistema usa o processador.

## 2. Instalar o motor (voz, legenda e interface web)
Tudo já está no repositório, na pasta `motor/`.

**Windows**
```powershell
cd motor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt yt-dlp
copy config.example.toml config.toml
```

**Linux/WSL**
```bash
cd motor && UV_PROJECT_ENVIRONMENT=.venv-linux uv sync --frozen && cp config.example.toml config.toml
```

## 3. Colocar as SUAS chaves em `motor/config.toml`
Cada colaborador usa as próprias chaves (grátis). **Esse arquivo nunca vai para o Git** (está no `.gitignore`).
- `pexels_api_keys = ["..."]` → https://www.pexels.com/api/
- `pixabay_api_keys = ["..."]` → https://pixabay.com/api/docs/
- `gemini_api_key = "..."` (opcional; imagens por IA exigem faturamento) → https://aistudio.google.com/apikey

## 4. Músicas (opcional)
Coloque MP3s em `motor/storage/bgm/` com os prefixos `gospel_`, `curiosidade_` e `espaco_`.
Os créditos obrigatórios ficam em `motor/storage/bgm/creditos.json` (formato: `{"arquivo.mp3": "texto do crédito"}`).

## 5. Gerar um vídeo
```powershell
cd motor
$sk = ".\milionere"
.\.venv\Scripts\python.exe "$sk\curadoria.py" "..\producao\roteiros\<roteiro>.json"
.\.venv\Scripts\python.exe "$sk\produzir.py"  "..\producao\roteiros\<roteiro>.json" --sem-musica
```
Pipeline automático do gospel (Linux/WSL + ComfyUI), de dentro de `motor/`: `.venv-linux/bin/python milionere/pipeline.py`
Configuração opcional: copie `.env.exemplo` para `.env` na raiz (voz, LLM, provedor de imagem, plano).

As imagens próprias (ex.: geradas no Gemini) vão em `producao/midia/<slug>/cena_NN.jpg`. O vídeo sai em `videos_prontos/`.
O fluxo completo está em `.claude/skills/roteirista-shorts/SKILL.md`.

## 6. Interface web (opcional)
```powershell
cd motor
.\.venv\Scripts\python.exe -m streamlit run .\webui\Main.py
```

Licenças de terceiros: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 7. Serviço (site) — MVP local
O protótipo, agora ligado ao pipeline de verdade (Django):
```powershell
.\motor\.venv\Scripts\python.exe -m pip install -r servico\requirements.txt
cd servico
..\motor\.venv\Scripts\python.exe manage.py migrate
..\motor\.venv\Scripts\python.exe manage.py runserver
```
Abra http://127.0.0.1:8000 → nicho → tema → (Gerar roteiro) → Gerar vídeo. O vídeo aparece na tela e pode ser baixado.
Jobs, entradas e erros ficam no admin (`manage.py createsuperuser` → /admin). Arquivos do serviço: `servico/media/` (fora do git).
Arquitetura de produção (Celery, Postgres, R2…): [docs/SERVICO.md](docs/SERVICO.md).

### Banco de imagens por nicho
Toda cena nova consulta o banco do nicho antes de buscar no Pexels ou gerar; toda imagem aprovada entra no banco.
Carga inicial com as imagens já aprovadas do time (rodar uma vez, de dentro de `motor/`):
```powershell
$env:MILIONERE_PRODUCAO = "..\servico\media\producao"
.\.venv\Scripts\python.exe milionere\banco_imagens.py --indexar-repo
```
Ver o banco: http://127.0.0.1:8000/banco · A busca por significado usa um modelo aberto e grátis (baixa ~120 MB na 1ª vez).

### Lote automático (popular o canal)
Vídeos end-to-end sem ninguém mexer: tema do catálogo → roteiro validado → imagens (ComfyUI) validadas → vídeo + texto do post.
```powershell
cd motor
.\.venv\Scripts\python.exe milionere\lote.py --status          # temas livres por formato
.\.venv\Scripts\python.exe milionere\lote.py --qtd 2           # 2 vídeos, alternando formatos
```
Saída: `videos_prontos/` (com música p/ YouTube, `_sem-musica` p/ TikTok) e a lista do que falta postar em `producao/fila_postagem.md`.
Um vídeo que falha não para o lote; as imagens e roteiros aprovados entram nos bancos no fim.

Agendar todo dia às 2h (Windows, na máquina com a GPU e o `claude` logado):
```powershell
schtasks /Create /TN "Milionere lote" /SC DAILY /ST 02:00 /TR "cmd /c cd /d C:\caminho\milionere\motor && .venv\Scripts\python.exe milionere\lote.py --qtd 2 >> ..\producao\lote.log 2>&1"
```
Linux (cron): `0 2 * * * cd ~/milionere/motor && .venv-linux/bin/python milionere/lote.py --qtd 2 >> ../producao/lote.log 2>&1`

### Painel de produção do canal (`/canal`)
Controle interno da geração automática: meta de vídeos por dia em cada nicho, **um vídeo por vez**, fila, revisão
(aprovar/reprovar com motivo, que vira lição para a IA) e marcação de postado no YouTube/TikTok.
Rode o site e, num segundo terminal, o produtor (na máquina com a GPU e o `claude` logado):
```powershell
cd servico
..\motor\.venv\Scripts\python.exe manage.py migrate
..\motor\.venv\Scripts\python.exe manage.py produtor          # fica rodando; Ctrl+C para parar
```
Abra http://127.0.0.1:8000/canal, ligue os nichos e ajuste a meta. Gospel com tema do catálogo usa o pipeline bíblico
completo (ComfyUI + 4 camadas); astronomia, animais e temas livres usam o roteirista guiado + banco/Pexels.

### Animações (Manim) para o Space Atlas
Cenas explicativas animadas (órbitas, distâncias, a luz viajando), verticais 1080x1920, no mesmo visual do canal.
```powershell
cd motor
.\.venv\Scripts\python.exe -m pip install manim        # uma vez (só no ambiente do projeto)
.\.venv\Scripts\python.exe milionere\animacoes\luz_do_sol.py   # -> milionere\animacoes\saida\luz_do_sol.mp4
```
Para usar num vídeo, copie o .mp4 para `producao/midia/<slug>/cena_NN.mp4` (mídia manual tem prioridade na montagem).

**Séries (2 a 5 partes).** No cartão do nicho: *Gerar série agora* (ou ▶▶ num tema da pauta) e, para o automático,
*vídeo único / série / misto* (misto = 1 série a cada N vídeos), com o teto de partes. A IA usa só as partes que a
história aguenta. Fluxo (`motor/milionere/serie.py`, orquestrado em `servico/estudio/producao.py`):
plano (trecho, virada e gancho de cada parte, personagens fixos) → juiz do plano → cada parte pelos juízes de sempre →
juiz da série (continuidade, repetição, nomes/papéis, ganchos que ligam; reescreve só a parte apontada) → imagens e vídeo
de cada parte → juiz visual da série (o mesmo personagem com a mesma cara; divergência vira aviso na revisão).
A série vai para *Para revisar* como um bloco: aprova ou reprova inteira; a postagem é marcada parte por parte.
Temas com `"serie": true` em `biblia/temas.json` têm preferência nas séries e ficam fora do vídeo único automático.
O gospel fecha sempre com o amém **e** o pedido de inscrição "pra continuar sendo abençoado" (conferido na camada 1).

## 8. Vídeo misto (animação) e turno da noite com postagem no YouTube

**Animação (Wan 2.2 14B):** `bash motor/milionere/instalar_comfy.sh --animacao` baixa os modelos (~22GB). O pipeline
anima 3 cenas-chave por vídeo (~5 min cada na RTX 4060); `MILIONERE_ANIMAR=0` desliga, `=2` anima 2. O ComfyUI roda
com teto de RAM (cgroup, `COMFY_RAM_HIGH/MAX` em `imagens.py`): se estourar, morre só ele, não o WSL.

**Postagem (API do YouTube, grátis):**
1. Google Cloud: projeto com a *YouTube Data API v3* ativa, tela de consentimento (Externo) com os links de
   `docs/index.html` e `docs/privacidade.html` (GitHub Pages) e o app **publicado** (em "Testando" o token vence em 7 dias).
2. ID do cliente OAuth "App para computador" -> salvar em `motor/segredos/youtube_cliente.json` (fora do git).
3. `motor/.venv-linux/bin/python motor/milionere/postar.py --autorizar` (uma vez).
4. `postar.py --pendentes` sobe como PRIVADO o que está pronto, sem aviso e ainda não postado (`producao/postados.json`).

**Turno da noite:** `crontab -e` ->
`0 20 * * * /home/rafael/projects/milionere/milionere/motor/milionere/noite.sh`
Gera vídeo atrás de vídeo até as 7h (`FIM_HORA`) e desliga o ComfyUI no fim. O upload é outro cron, 1 vídeo
(privado) a cada 3h a partir das 23h: `0 2-23/3 * * * ... postar.py --pendentes --limite 1` (log em `producao/noite/postagem.log`).
Log em `producao/noite/turno_<data>.log`. O WSL precisa estar aberto (deixe um terminal do Ubuntu aberto à noite).
De manhã: YouTube Studio -> conferir cada vídeo privado -> Público (comentário fixado: à mão, está no `.txt`).
