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
$sk = "..\.claude\skills\roteirista-shorts\scripts"
.\.venv\Scripts\python.exe "$sk\curadoria.py" "..\producao\roteiros\<roteiro>.json"
.\.venv\Scripts\python.exe "$sk\produzir.py"  "..\producao\roteiros\<roteiro>.json" --sem-musica
```
Pipeline automático do gospel (Linux/WSL + ComfyUI): `motor/.venv-linux/bin/python .claude/skills/roteirista-shorts/scripts/pipeline.py`

As imagens próprias (ex.: geradas no Gemini) vão em `producao/midia/<slug>/cena_NN.jpg`. O vídeo sai em `videos_prontos/`.
O fluxo completo está em `.claude/skills/roteirista-shorts/SKILL.md`.

## 6. Interface web (opcional)
```powershell
cd motor
.\.venv\Scripts\python.exe -m streamlit run .\webui\Main.py
```

Licenças de terceiros: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
