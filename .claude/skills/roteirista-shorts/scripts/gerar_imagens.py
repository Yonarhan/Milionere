"""Gera pela API do Gemini as imagens das cenas que têm "prompt_ia" no roteiro.

Uso:
    python gerar_imagens.py roteiros.json            # gera o que falta
    python gerar_imagens.py roteiros.json --refazer 5,8

- Salva em producao/midia/<slug>/cena_NN.jpg (a mesma pasta que o produzir.py já usa).
- Pula cenas que já têm imagem (você ainda pode colocar imagens à mão).
- Consistência: a 1ª imagem gerada vai como REFERÊNCIA para as seguintes ("mesmo personagem").
- Se a API recusar (sem faturamento/cota), grava producao/midia/<slug>/prompts.txt para gerar no app.
"""

import argparse
import base64
import json
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
CONFIG = RAIZ / "MoneyPrinterTurbo" / "config.toml"
MODELOS = ["gemini-2.5-flash-image", "gemini-3.1-flash-image"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
REFERENCIA = "Use the same characters, faces, clothes and visual style as in the reference image."


class SemCota(Exception):
    pass


def gerar(prompt: str, chave: str, referencia: Path | None) -> bytes:
    partes = [{"text": prompt + (" " + REFERENCIA if referencia else "")}]
    if referencia:
        partes.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(referencia.read_bytes()).decode()}})
    corpo = {"contents": [{"parts": partes}],
             "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
    erro = ""
    for modelo in MODELOS:
        req = urllib.request.Request(URL.format(modelo), data=json.dumps(corpo).encode(),
                                     headers={"x-goog-api-key": chave, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            erro = f"{modelo}: {e.code} {e.read().decode()[:200]}"
            if e.code == 429:
                continue
            raise RuntimeError(erro)
        for p in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])
        erro = f"{modelo}: resposta sem imagem"
    raise SemCota(erro)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--refazer", help="números das cenas para gerar de novo, ex.: 5,8")
    args = ap.parse_args()
    refazer = {int(x) for x in args.refazer.split(",")} if args.refazer else set()
    chave = tomllib.load(open(CONFIG, "rb"))["app"].get("gemini_api_key", "")

    for r in json.loads(Path(args.arquivo).read_text(encoding="utf-8")):
        cenas = [(i, c) for i, c in enumerate(r["cenas"], 1) if c.get("prompt_ia")]
        if not cenas:
            continue
        pasta = RAIZ / "producao" / "midia" / r["slug"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "prompts.txt").write_text("\n\n".join(
            f"cena_{i:02d}.jpg\nGenerate ONE single image, vertical 9:16. {c['prompt_ia']}" for i, c in cenas), encoding="utf-8")
        referencia = None
        for i, cena in cenas:
            destino = pasta / f"cena_{i:02d}.jpg"
            existentes = list(pasta.glob(f"cena_{i:02d}*"))
            if existentes and i not in refazer:
                referencia = referencia or existentes[0]
                print(f"[{r['slug']}] cena {i:>2}: já existe, pulando")
                continue
            try:
                destino.write_bytes(gerar(cena["prompt_ia"], chave, referencia))
            except SemCota as e:
                print(f"[{r['slug']}] SEM COTA na API do Gemini ({e}).\n"
                      f"  -> gere no app com os prompts de {pasta / 'prompts.txt'} ou ative o faturamento no AI Studio.")
                break
            referencia = referencia or destino
            print(f"[{r['slug']}] cena {i:>2}: gerada -> {destino.name}")


if __name__ == "__main__":
    main()
