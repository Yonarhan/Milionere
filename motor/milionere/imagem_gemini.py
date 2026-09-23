"""Provedor de imagem Gemini (Nano Banana) pela API: plano pago ou chave própria.

Usa o mesmo prompt do ComfyUI (imagens.prompt_cena) e manda como referência o retrato fixo do
personagem principal (dados/biblia/retratos/<estilo>/<id>.png) e/ou a 1ª imagem já aprovada do vídeo,
para manter o mesmo rosto. Sem cota/faturamento, levanta SemCota e o chamador cai para o ComfyUI.
"""

import base64
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import imagens  # noqa: E402

MODELOS = ["gemini-2.5-flash-image", "gemini-3.1-flash-image"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
REFERENCIA = "Use the same characters, faces, clothes and visual style as in the reference image(s)."


class SemCota(Exception):
    pass


def chave() -> str:
    """Chave própria do usuário (o Django define por job) ou a chave do projeto em motor/config.toml."""
    if caminhos.PLANO == "chave_propria" and os.environ.get("MILIONERE_CHAVE_GEMINI"):
        return os.environ["MILIONERE_CHAVE_GEMINI"]
    with open(caminhos.CONFIG_MOTOR, "rb") as f:
        return tomllib.load(f).get("app", {}).get("gemini_api_key", "")


def gerar(prompt: str, referencias: list[Path], api_key: str) -> bytes:
    partes = [{"text": prompt + (" " + REFERENCIA if referencias else "")}]
    for ref in referencias:
        mime = "image/png" if ref.suffix.lower() == ".png" else "image/jpeg"
        partes.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(ref.read_bytes()).decode()}})
    corpo = {"contents": [{"parts": partes}],
             "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
    erro = "sem chave do Gemini"
    for modelo in MODELOS if api_key else []:
        req = urllib.request.Request(URL.format(modelo), data=json.dumps(corpo).encode(),
                                     headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            erro = f"{modelo}: HTTP {e.code}"
            if e.code in (429, 403):
                continue
            raise RuntimeError(f"{erro}: {e.read().decode()[:300]}") from e
        for p in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])
        erro = f"{modelo}: resposta sem imagem"
    raise SemCota(erro)


def gerar_cena(roteiro: dict, nome_estilo: str, n: int, destino: Path, api_key: str) -> Path:
    estilo = imagens.estilos()[nome_estilo]
    personagens = {p["id"]: p for p in roteiro.get("personagens", [])}
    cena = roteiro["cenas"][n - 1]
    prompt = "Generate ONE single image, vertical 9:16. " + imagens.prompt_cena(
        cena, personagens, estilo, roteiro.get("cenario_en", ""))
    refs = []
    principal = next((i for i in cena.get("personagens", []) if i in personagens), None)
    if principal:
        chave_ret = personagens[principal].get("id_retrato", principal)
        ret = imagens.RETRATOS / nome_estilo / f"{chave_ret}.png"
        if ret.exists():
            refs.append(ret)
    primeira = next(iter(sorted(destino.parent.glob("cena_*.*"))), None)
    if primeira and primeira != destino and len(refs) < 2:
        refs.append(primeira)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(gerar(prompt, refs, api_key))
    print(f"  cena {n:>2} gemini  {destino.name}  «{cena['fala'][:50]}»")
    return destino
