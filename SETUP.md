# Como rodar o projeto (Windows)

Visão geral do projeto: [RESUMO_DO_PROJETO.md](RESUMO_DO_PROJETO.md)

## 1. Requisitos
- Python 3.11 ou 3.12 e Git
- Placa NVIDIA é opcional (acelera a montagem). Sem ela, o sistema usa o processador.

## 2. Instalar o MoneyPrinterTurbo (dependência, fica fora do repositório)
Na pasta do projeto:
```powershell
git clone --depth 1 https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt yt-dlp
copy config.example.toml config.toml
```

## 3. Colocar as SUAS chaves em `MoneyPrinterTurbo/config.toml`
Cada colaborador usa as próprias chaves (grátis). **Nunca faça commit desse arquivo.**
- `pexels_api_keys = ["..."]` → https://www.pexels.com/api/
- `pixabay_api_keys = ["..."]` → https://pixabay.com/api/docs/
- `gemini_api_key = "..."` (opcional; imagens por IA exigem faturamento) → https://aistudio.google.com/apikey

## 4. Músicas (opcional)
Coloque MP3s em `MoneyPrinterTurbo/storage/bgm/` com os prefixos `gospel_`, `curiosidade_` e `espaco_`.
Os créditos obrigatórios ficam em `storage/bgm/creditos.json` (formato: `{"arquivo.mp3": "texto do crédito"}`).

## 5. Gerar um vídeo
```powershell
cd MoneyPrinterTurbo
$sk = "..\.claude\skills\roteirista-shorts\scripts"
.\.venv\Scripts\python.exe "$sk\curadoria.py" "..\producao\roteiros\<roteiro>.json"
.\.venv\Scripts\python.exe "$sk\produzir.py"  "..\producao\roteiros\<roteiro>.json" --sem-musica
```
As imagens próprias (ex.: geradas no Gemini) vão em `producao/midia/<slug>/cena_NN.jpg`.
O vídeo sai em `videos_prontos/`. O fluxo completo está em `.claude/skills/roteirista-shorts/SKILL.md`.
