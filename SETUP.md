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
