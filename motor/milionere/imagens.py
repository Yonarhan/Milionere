"""Gera as imagens das cenas no ComfyUI local (SDXL + IP-Adapter para manter o mesmo rosto).

Cada personagem ganha um retrato de referência (biblia/retratos/<estilo>/<id>.png), gerado uma vez e
reusado em todos os vídeos. Em cada cena, o rosto do personagem principal entra pelo IP-Adapter e a
descrição fixa dele entra no prompt. Assim o Jesus de hoje é o mesmo Jesus da semana que vem.

Uso:
    python imagens.py roteiro.json                 # gera todas as cenas em producao/midia/<slug>/
    python imagens.py roteiro.json --cenas 3 7     # refaz só essas cenas (seed nova)
    python imagens.py --teste "a lighthouse at dusk"
"""

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import caminhos  # noqa: E402
from caminhos import DADOS as SKILL  # noqa: E402  (presets, formatos, estilos, bíblia, referências)
from caminhos import RAIZ  # noqa: E402
from caminhos import COMFY  # noqa: E402
URL = "http://127.0.0.1:8188"
# Host tem 32GB e o Windows já usa ~15GB: o WSL inteiro precisa ficar perto de 15GB. Acima de HIGH o kernel
# joga cache/anon pro swap (lento, mas seguro); em MAX mata o ComfyUI.
COMFY_RAM_HIGH = "9G"
COMFY_RAM_MAX = "11G"
RETRATOS = SKILL / "biblia" / "retratos"
LARGURA, ALTURA = 768, 1344  # resolução nativa do SDXL mais próxima de 9:16
IPADAPTER = "ip-adapter-plus-face_sdxl_vit-h.safetensors"
CLIP_VISION = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"


def estilos() -> dict:
    return {k: v for k, v in json.loads((SKILL / "estilos.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def _get(caminho: str, timeout: float = 10):
    with urllib.request.urlopen(URL + caminho, timeout=timeout) as r:
        return json.load(r)


def no_ar() -> bool:
    try:
        _get("/system_stats", timeout=3)
        return True
    except (urllib.error.URLError, OSError):
        return False


def garantir_comfy() -> subprocess.Popen | None:
    """Sobe o ComfyUI se não estiver rodando. Devolve o processo (para derrubar no fim) ou None se já estava no ar."""
    if no_ar():
        return None
    log = open(caminhos.PRODUCAO / "comfy.log", "w")
    cmd = [str(COMFY / ".venv" / "bin" / "python"), "main.py", "--listen", "127.0.0.1",
           "--port", "8188", "--disable-auto-launch",
           # WSL: a memória fixada (pinned) do driver dxg esgota e o ComfyUI trava ao carregar o IP-Adapter
           "--disable-dynamic-vram", "--disable-pinned-memory"]
    if shutil.which("systemd-run"):
        # Teto de RAM: sem ele, um modelo grande (Wan 14B) esgota os 16GB do WSL e a VM inteira cai.
        # Com o teto, o kernel mata só o ComfyUI (OOM) e o resto da máquina segue de pé.
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", f"MemoryHigh={COMFY_RAM_HIGH}",
               "-p", f"MemoryMax={COMFY_RAM_MAX}", "-p", "MemorySwapMax=4G", *cmd]
    import os
    env = dict(os.environ)
    # cron não define o barramento do usuário e o systemd-run --user falhava calado (turno de 24/09 sem vídeo)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    proc = subprocess.Popen(cmd, cwd=COMFY, stdout=log, stderr=subprocess.STDOUT, env=env)
    for _ in range(180):
        if no_ar():
            return proc
        if proc.poll() is not None:
            sys.exit(f"ComfyUI não subiu, veja {log.name}")
        time.sleep(1)
    sys.exit("ComfyUI demorou demais para subir")


def derrubar(proc: subprocess.Popen | None) -> None:
    if proc:
        proc.terminate()
        proc.wait(timeout=30)


def workflow_flux(positivo: str, estilo: dict, seed: int) -> dict:
    """Flux schnell GGUF: cfg 1 e sem IP-Adapter; a consistência vem da descrição fixa + seed. Negativo só via NAG."""
    wf = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": estilo["unet"]}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                                                         "clip_name2": "clip_l.safetensors", "type": "flux",
                                                         "device": "cpu"}},  # texto na CPU: o modelo fica fixo na VRAM
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux_ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positivo, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": LARGURA, "height": ALTURA, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": estilo["passos"], "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "roteirista"}},
    }
    if estilo.get("nag_negativo"):
        _com_nag(wf, estilo)
    return wf


def _com_nag(wf: dict, estilo: dict) -> None:
    """NAG (custom_nodes/ComfyUI-NAG): prompt negativo de verdade em modelo destilado de cfg 1 (Flux schnell).
    Tira o que o juiz mais reprova (calçado, relógio, metal) sem citar isso no prompt positivo.
    Desligado: o ComfyUI-NAG (nov/2025) não carrega no ComfyUI atual. Liga com "nag_negativo" no estilo."""
    wf["11"] = {"class_type": "CLIPTextEncode", "inputs": {"text": estilo["nag_negativo"], "clip": ["2", 0]}}
    k = wf["7"]["inputs"]
    wf["7"] = {"class_type": "KSamplerWithNAG", "inputs": {
        **k, "nag_negative": ["11", 0], "nag_scale": estilo.get("nag_scale", 5.0), "nag_tau": estilo.get("nag_tau", 2.5),
        "nag_alpha": estilo.get("nag_alpha", 0.25), "nag_sigma_end": estilo.get("nag_sigma_end", 0.75)}}


def workflow_zimage(positivo: str, estilo: dict, seed: int) -> dict:
    """Z-Image Turbo (Alibaba) GGUF: text encoder Qwen3-4B, cfg 1 sem negativo, shift AuraFlow 3, ~9 passos."""
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": estilo["unet"]}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": estilo["text_encoder"], "type": "lumina2",
                                                  "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": estilo["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positivo, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": LARGURA, "height": ALTURA, "batch_size": 1}},
        "10": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": estilo.get("shift", 3.0)}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": estilo["passos"], "cfg": 1.0, "sampler_name": estilo["sampler"],
            "scheduler": estilo["scheduler"], "denoise": 1.0}},
        # decodifica em blocos: o VAEDecode normal expulsa o modelo da VRAM e ele recarrega na cena seguinte
        "8": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["7", 0], "vae": ["3", 0], "tile_size": 512,
                                                   "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "roteirista"}},
    }


def montar_workflow(positivo: str, negativo: str, estilo: dict, seed: int, referencia: str | None, peso_ref: float) -> dict:
    if estilo.get("motor") == "flux":
        return workflow_flux(positivo, estilo, seed)
    if estilo.get("motor") == "zimage":
        return workflow_zimage(positivo, estilo, seed)
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": estilo["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positivo, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negativo, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": LARGURA, "height": ALTURA, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed, "steps": estilo["passos"], "cfg": estilo["cfg"], "sampler_name": estilo["sampler"],
            "scheduler": estilo["scheduler"], "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "roteirista"}},
    }
    if referencia and peso_ref > 0:
        wf.update({
            "10": {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": IPADAPTER}},
            "11": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CLIP_VISION}},
            "12": {"class_type": "LoadImage", "inputs": {"image": referencia}},
            "13": {"class_type": "IPAdapterAdvanced", "inputs": {
                "model": ["1", 0], "ipadapter": ["10", 0], "image": ["12", 0], "clip_vision": ["11", 0],
                "weight": peso_ref, "weight_type": "linear", "combine_embeds": "concat",
                # o rosto só entra depois que o texto definiu pose e composição (senão tudo vira retrato de frente)
                "start_at": estilo.get("ip_inicio", 0.35), "end_at": 0.9, "embeds_scaling": "V only"}},
        })
        wf["5"]["inputs"]["model"] = ["13", 0]
    return wf


def gerar(positivo: str, negativo: str, estilo: dict, destino: Path, seed: int,
          referencia: Path | None = None, peso_ref: float = 0.0) -> Path:
    nome_ref = None
    if referencia:
        nome_ref = f"ref_{referencia.parent.name}_{referencia.name}"
        shutil.copy(referencia, COMFY / "input" / nome_ref)
    wf = montar_workflow(positivo, negativo, estilo, seed, nome_ref, peso_ref)
    corpo = json.dumps({"prompt": wf, "client_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(URL + "/prompt", data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.load(r)["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI recusou o workflow: {e.read().decode()[:1500]}") from e
    for _ in range(600):
        hist = _get(f"/history/{pid}")
        if pid in hist:
            item = hist[pid]
            if item.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"ComfyUI falhou: {json.dumps(item['status'])[:1500]}")
            img = next(i for saida in item["outputs"].values() for i in saida.get("images", []))
            origem = COMFY / "output" / img.get("subfolder", "") / img["filename"]
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(origem, destino)
            return destino
        time.sleep(1)
    raise RuntimeError("ComfyUI não terminou a imagem em 10 minutos")


def negativo_de(estilo: dict, biblico: bool) -> str:
    return estilo["negativo"] + (", " + estilo["negativo_biblico"] if biblico else "")


def retrato(p: dict, nome_estilo: str, biblico: bool) -> Path:
    """Retrato de referência do personagem nesse estilo (gerado 1 vez, reusado em todos os vídeos)."""
    chave = p.get("id_retrato", p["id"])  # personagem de parábola moderna é do vídeo, não do canal
    destino = RETRATOS / nome_estilo / f"{chave}.png"
    if destino.exists():
        return destino
    estilo = estilos()[nome_estilo]
    positivo = (f"head and shoulders portrait of {p['descricao_visual']}, looking at the camera, calm expression, "
                f"plain dark background, {estilo['prompt']}")
    print(f"  retrato novo: {p['id']} ({nome_estilo})")
    return gerar(positivo, negativo_de(estilo, biblico), estilo, destino, seed=_seed_fixa(chave))


def _seed_fixa(texto: str) -> int:
    return zlib.crc32(texto.encode()) % (2**31)


def prompt_cena(cena: dict, personagens: dict, estilo: dict, cenario: str, biblico: bool = False) -> str:
    quem = [f"{personagens[i]['nome_en']}: {personagens[i]['descricao_visual']}" for i in cena.get("personagens", [])
            if i in personagens]
    epoca = estilo.get("prompt_biblico", "") if biblico else ""
    partes = [cena["imagem"], *quem, cenario, epoca, estilo["prompt"], "vertical composition"]
    return ", ".join(p.strip().rstrip(".") for p in partes if p and p.strip())


def _gerar_cena(roteiro: dict, nome_estilo: str, n: int, destino: Path, seed: int) -> Path:
    estilo = estilos()[nome_estilo]
    biblico = roteiro.get("epoca", "biblica") == "biblica"
    personagens = {p["id"]: p for p in roteiro.get("personagens", [])}
    cena = roteiro["cenas"][n - 1]
    principal = next((personagens[i] for i in cena.get("personagens", []) if i in personagens), None)
    # IP-Adapter só em close: em plano médio/aberto ele copia a pose do retrato e mata a ação da cena
    close = (re.match(r"\s*(extreme |medium |tight )?close[- ]?up|\s*portrait", cena["imagem"], re.I)
             and not re.search(r"\b(hands?|feet|foot|wrist)\b", cena["imagem"][:60], re.I))
    usa_ref = estilo.get("motor") != "flux" and estilo.get("ip_peso", 0) > 0
    ref = retrato(principal, nome_estilo, biblico) if usa_ref and principal and cena.get("rosto_visivel", True) and close else None
    inicio = time.time()
    gerar(prompt_cena(cena, personagens, estilo, roteiro.get("cenario_en", ""), biblico), negativo_de(estilo, biblico), estilo,
          destino, seed, ref, estilo["ip_peso"] if ref else 0.0)
    print(f"  cena {n:>2} {time.time() - inicio:4.0f}s  {destino.name}  «{cena['fala'][:50]}»")
    return destino


def gerar_cenas(roteiro: dict, nome_estilo: str, pasta: Path, so: list[int] | None = None, nova_seed: bool = False) -> list[Path]:
    base = _seed_fixa(roteiro["slug"])
    feitos = []
    for n in range(1, len(roteiro["cenas"]) + 1):
        if so and n not in so:
            continue
        seed = base + n + (random.randint(1, 10**6) if nova_seed else 0)
        for velho in pasta.glob(f"cena_{n:02d}*"):
            velho.unlink()
        feitos.append(_gerar_cena(roteiro, nome_estilo, n, pasta / f"cena_{n:02d}.png", seed))
    return feitos


def gerar_opcoes(roteiro: dict, nome_estilo: str, pasta: Path, n: int, k: int = 3) -> list[Path]:
    """k versões da cena n com seeds novas, em pasta/opcoes/ (fora do glob cena_NN* que o render usa)."""
    destino = pasta / "opcoes"
    destino.mkdir(parents=True, exist_ok=True)
    for velho in destino.glob(f"cena_{n:02d}_*"):
        velho.unlink()
    return [_gerar_cena(roteiro, nome_estilo, n, destino / f"cena_{n:02d}_{j}.png", random.randint(0, 2**31 - 1))
            for j in range(1, k + 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("roteiro", nargs="?")
    ap.add_argument("--estilo")
    ap.add_argument("--cenas", type=int, nargs="*")
    ap.add_argument("--teste")
    args = ap.parse_args()
    proc = garantir_comfy()
    try:
        if args.teste:
            est = estilos()[args.estilo or "cinema"]
            d = gerar(f"{args.teste}, {est['prompt']}", est["negativo"], est, caminhos.PRODUCAO / "teste_comfy.png", 42)
            print(d)
            return
        r = json.loads(Path(args.roteiro).read_text(encoding="utf-8"))
        r = r[0] if isinstance(r, list) else r
        gerar_cenas(r, args.estilo or r.get("estilo", "cinema"), caminhos.PRODUCAO / "midia" / r["slug"], args.cenas,
                    nova_seed=bool(args.cenas))
    finally:
        derrubar(proc)


if __name__ == "__main__":
    main()
