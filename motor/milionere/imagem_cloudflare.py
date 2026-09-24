"""Provedor de imagem Cloudflare Workers AI: FLUX.2 [klein] 4B, dentro da cota grátis (10 mil neurons/dia, ~55 imagens).

Mesmo prompt do ComfyUI e do Gemini (imagens.prompt_cena). Até 4 imagens de referência (input_image_0..3,
menores que 512 px): o retrato do personagem principal e a imagem do banco que mais parece com a cena,
para manter o rosto e o estilo. Credenciais no .env: CLOUDFLARE_ACCOUNT_ID e CLOUDFLARE_API_TOKEN.
Sem credencial ou com a cota do dia estourada, levanta SemCota e o chamador cai para o próximo provedor.
"""

import base64
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagens  # noqa: E402

MODELO = "@cf/black-forest-labs/flux-2-klein-4b"
URL = "https://api.cloudflare.com/client/v4/accounts/{}/ai/run/" + MODELO
LARGURA, ALTURA = 768, 1344  # 9:16, múltiplos de 16 (6 blocos de 512 px: ~180 neurons por imagem)
MAX_REFS = 4
REFERENCIA = ("Keep the same characters, faces, clothes and visual style as in the reference image(s), "
              "but compose a NEW scene exactly as described.")


class SemCota(Exception):
    pass


def credenciais() -> tuple[str, str]:
    conta, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""), os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not (conta and token):
        raise SemCota("faltam CLOUDFLARE_ACCOUNT_ID e CLOUDFLARE_API_TOKEN no .env")
    return conta, token


def disponivel() -> bool:
    try:
        credenciais()
        return True
    except SemCota:
        return False


def _miniatura(p: Path) -> bytes:
    """A API só aceita referência menor que 512x512."""
    from PIL import Image
    with Image.open(p) as im:
        im = im.convert("RGB")
        im.thumbnail((504, 504))
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return buf.getvalue()


def gerar(prompt: str, referencias: list[Path], destino: Path) -> Path:
    import requests

    conta, token = credenciais()
    refs = [r for r in referencias if r and Path(r).exists()][:MAX_REFS]
    campos = {"prompt": (None, (prompt + (" " + REFERENCIA if refs else ""))[:2048]),
              "width": (None, str(LARGURA)), "height": (None, str(ALTURA))}
    for i, r in enumerate(refs):
        campos[f"input_image_{i}"] = (f"ref{i}.png", _miniatura(Path(r)), "image/png")
    resp = requests.post(URL.format(conta), headers={"Authorization": f"Bearer {token}"}, files=campos, timeout=180)
    try:
        corpo = resp.json()
    except ValueError:
        corpo = {}
    erros = " ".join(str(e.get("message", e)) for e in corpo.get("errors", []) or [])
    if resp.status_code == 429 or "allocation" in erros.lower() or "quota" in erros.lower():
        raise SemCota(f"cota da Cloudflare esgotada hoje ({erros or resp.status_code})")
    if resp.status_code in (401, 403):
        raise SemCota(f"credencial da Cloudflare recusada ({erros or resp.status_code})")
    if not resp.ok or not corpo.get("success", True):
        raise RuntimeError(f"Cloudflare {resp.status_code}: {erros or resp.text[:300]}")
    dados = base64.b64decode(corpo["result"]["image"])
    from PIL import Image
    destino.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(dados)) as im:  # a API devolve JPEG ou PNG: grava sempre no formato do destino
        im.convert("RGB").save(destino)
    return destino


def retrato_principal(roteiro: dict, nome_estilo: str, cena: dict) -> Path | None:
    personagens = {p["id"]: p for p in roteiro.get("personagens", [])}
    principal = next((i for i in cena.get("personagens", []) if i in personagens), None)
    if not principal:
        return None
    ret = imagens.RETRATOS / nome_estilo / f"{personagens[principal].get('id_retrato', principal)}.png"
    return ret if ret.exists() else None


def gerar_cena(roteiro: dict, nome_estilo: str, n: int, destino: Path, refs_extra: list[Path] | None = None) -> Path:
    estilo = imagens.estilos()[nome_estilo]
    personagens = {p["id"]: p for p in roteiro.get("personagens", [])}
    cena = roteiro["cenas"][n - 1]
    prompt = "ONE single image, vertical 9:16. " + imagens.prompt_cena(cena, personagens, estilo, roteiro.get("cenario_en", ""))
    refs = [r for r in [retrato_principal(roteiro, nome_estilo, cena), *(refs_extra or [])] if r]
    gerar(prompt, refs, destino)
    print(f"  cena {n:>2} cloudflare  {destino.name}  refs={len(refs)}  «{cena['fala'][:50]}»")
    return destino
