"""Anima as cenas-chave de um roteiro com o Wan 2.2 I2V 14B (vídeo misto: poucas cenas em movimento, o resto imagem).

Gera producao/midia/<slug>/cena_NN.mp4 ao lado da cena_NN.png aprovada; a montagem (sincronizar.montar_tomadas)
prefere o .mp4. Só anima poucas cenas porque cada uma custa ~5 min na RTX 4060 de 8GB.

Memória (WSL com ~15GB, host limitado a 30GB): os dois especialistas de 7GB e o encoder de texto de 6.4GB nunca
ficam na RAM juntos. Ordem: texto de todas as cenas (GPU, salvo em disco) -> /free -> ruído alto de todas as cenas
(modelo carregado uma vez) -> /free -> ruído baixo de todas -> quadros.

Uso:
    python animar.py producao/roteiros/2026-09-24_historia-zaqueu.json          # escolhe as cenas sozinho
    python animar.py <roteiro.json> --cenas 1 6 9                                 # força estas
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import caminhos  # noqa: E402
import imagens  # noqa: E402
from sincronizar import FFMPEG  # noqa: E402

QTD_PADRAO = 3  # gancho + meio + clímax; ~15 min por vídeo
LARGURA, ALTURA = 480, 832  # vertical, múltiplo de 16; o render amplia para 1080x1920
QPS = 16  # nativo do Wan
MAX_QUADROS = 81  # 5s
PALAVRAS_POR_SEGUNDO = 2.4  # medido nas tomadas do Zaqueu (fala por cena, sem as pausas entre cenas)
SEED = 1234
ALTO = ("Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf", "wan22_i2v_high_lightx2v_4step.safetensors")
BAIXO = ("Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf", "wan22_i2v_low_lightx2v_4step.safetensors")
ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan_2.1_vae.safetensors"
MOVIMENTO = ", subtle natural movement, gentle breeze, slow cinematic camera push-in, realistic film, sharp faces"
NEG = ("static, frozen, blurry, distorted face, deformed hands, extra limbs, extra fingers, morphing, flicker, "
       "text, watermark, modern objects")


def escolher(r: dict, qtd: int = QTD_PADRAO) -> list[int]:
    """Cenas marcadas com "animar": true no roteiro; senão gancho (1), meio e clímax (sem a cena final de CTA)."""
    marcadas = [i for i, c in enumerate(r["cenas"], 1) if c.get("animar")]
    if marcadas:
        return marcadas
    n = len(r["cenas"])
    ultima = n - 1 if n > 3 else n  # a última costuma ser o "Escreve amém"
    candidatas = [1, round(ultima * 0.45), round(ultima * 0.75), ultima]
    return sorted(dict.fromkeys(c for c in candidatas if 1 <= c <= n))[:qtd]


def quadros(fala: str) -> int:
    """Duração estimada da fala + folga, em quadros 4k+1 (exigência do Wan). Se sobrar, a montagem corta;
    se faltar, congela o último quadro."""
    seg = len(fala.split()) / PALAVRAS_POR_SEGUNDO + 0.4
    return min(MAX_QUADROS, max(33, 4 * math.ceil(seg * QPS / 4) + 1))


# ---------------------------------------------------------------- workflows do ComfyUI

def wf_texto(prompts: dict[str, str]) -> dict:
    wf = {"1": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENCODER, "type": "wan", "device": "default"}}}
    for k, (nome, texto) in enumerate(prompts.items()):
        wf[f"e{k}"] = {"class_type": "CLIPTextEncode", "inputs": {"text": texto, "clip": ["1", 0]}}
        wf[f"s{k}"] = {"class_type": "SalvarCondicionamento", "inputs": {"conditioning": [f"e{k}", 0], "nome": nome}}
    return wf


def _base(img: str, pos: str, neg: str, especialista: tuple[str, str], n_quadros: int) -> dict:
    unet, lora = especialista
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": 1.0}},
        "3": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 5.0}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "LoadImage", "inputs": {"image": img}},
        "6": {"class_type": "CarregarCondicionamento", "inputs": {"nome": pos}},
        "7": {"class_type": "CarregarCondicionamento", "inputs": {"nome": neg}},
        "8": {"class_type": "WanImageToVideo", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "vae": ["4", 0],
                                                          "width": LARGURA, "height": ALTURA, "length": n_quadros,
                                                          "batch_size": 1, "start_image": ["5", 0]}},
    }


def _amostrador(latente: list, inicio: int, fim: int, ruido: bool) -> dict:
    return {"class_type": "KSamplerAdvanced", "inputs": {
        "model": ["3", 0], "positive": ["8", 0], "negative": ["8", 1], "latent_image": latente,
        "add_noise": "enable" if ruido else "disable", "noise_seed": SEED, "steps": 4, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "start_at_step": inicio, "end_at_step": fim,
        "return_with_leftover_noise": "enable" if fim < 4 else "disable"}}


def wf_alto(img: str, pos: str, neg: str, n_quadros: int, prefixo: str) -> dict:
    wf = _base(img, pos, neg, ALTO, n_quadros)
    wf["9"] = _amostrador(["8", 2], 0, 2, True)
    wf["10"] = {"class_type": "SaveLatent", "inputs": {"samples": ["9", 0], "filename_prefix": f"latents/{prefixo}"}}
    return wf


def wf_baixo(img: str, pos: str, neg: str, n_quadros: int, latente: str, prefixo: str) -> dict:
    wf = _base(img, pos, neg, BAIXO, n_quadros)
    wf["9"] = {"class_type": "LoadLatent", "inputs": {"latent": latente}}
    wf["10"] = _amostrador(["9", 0], 2, 4, False)
    wf["11"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["10", 0], "vae": ["4", 0], "tile_size": 512,
                                                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}}
    wf["12"] = {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefixo}}
    return wf


# ---------------------------------------------------------------- execução

def _post(caminho: str, dados: dict) -> dict:
    req = urllib.request.Request(imagens.URL + caminho, data=json.dumps(dados).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        corpo = urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI recusou {caminho}: {e.read().decode()[:1500]}") from e
    return json.loads(corpo) if corpo else {}


def _rodar(wf: dict, proc) -> dict:
    pid = _post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
    inicio = time.time()
    while True:
        time.sleep(3)
        if proc and proc.poll() is not None:
            raise RuntimeError("ComfyUI caiu (provável teto de RAM do cgroup); veja producao/comfy.log")
        try:  # sob pressão de memória o servidor responde devagar: não confundir lentidão com queda
            h = json.load(urllib.request.urlopen(f"{imagens.URL}/history/{pid}", timeout=30)).get(pid)
        except OSError:
            continue
        if h and (h.get("status", {}).get("completed") is not None or h.get("outputs")):
            if h["status"].get("status_str") == "error":
                raise RuntimeError(json.dumps(h["status"])[:1500])
            return h
        if time.time() - inicio > 3600:
            raise RuntimeError("etapa do Wan passou de 1h")


def _liberar() -> None:
    _post("/free", {"unload_models": True, "free_memory": True})
    time.sleep(5)  # o /free vale quando a fila processa a flag


def _saidas(h: dict, tipo: str) -> list[Path]:
    return [imagens.COMFY / "output" / o.get("subfolder", "") / o["filename"]
            for out in h["outputs"].values() for o in out.get(tipo, [])]


def _no_disponivel() -> bool:
    try:
        return "CarregarCondicionamento" in json.load(urllib.request.urlopen(
            f"{imagens.URL}/object_info/CarregarCondicionamento", timeout=10))
    except (OSError, ValueError):
        return False


def animar(r: dict, pasta: Path, cenas: list[int] | None = None) -> list[int]:
    """Gera cena_NN.mp4 para as cenas escolhidas que ainda não têm. Devolve as cenas animadas agora."""
    cenas = cenas or escolher(r)
    faltam = [i for i in cenas if (pasta / f"cena_{i:02d}.png").exists() and not (pasta / f"cena_{i:02d}.mp4").exists()]
    if not faltam:
        return []
    proc = imagens.garantir_comfy()
    try:
        if not _no_disponivel():
            raise RuntimeError("nó CarregarCondicionamento ausente no ComfyUI: rode instalar_comfy.sh --animacao "
                               "e reinicie o ComfyUI")
        base = f"{r['slug']}_{uuid.uuid4().hex[:6]}"
        neg = f"{base}_neg"
        pos = {i: f"{base}_{i:02d}" for i in faltam}
        n_q = {i: quadros(r["cenas"][i - 1]["fala"]) for i in faltam}
        t0 = time.time()
        _rodar(wf_texto({**{pos[i]: r["cenas"][i - 1]["imagem"].rstrip(". ") + MOVIMENTO for i in faltam}, neg: NEG}), proc)
        _liberar()
        print(f"  animação: texto de {len(faltam)} cenas em {time.time() - t0:.0f}s", flush=True)

        latentes = {}
        for i in faltam:
            img = f"{r['slug']}_cena_{i:02d}.png"
            shutil.copy(pasta / f"cena_{i:02d}.png", imagens.COMFY / "input" / img)
            lat = _saidas(_rodar(wf_alto(img, pos[i], neg, n_q[i], pos[i]), proc), "latents")[0]
            latentes[i] = f"{pos[i]}_alta.latent"
            shutil.move(lat, imagens.COMFY / "input" / latentes[i])
            print(f"  animação: cena {i} 1/2 ({time.time() - t0:.0f}s)", flush=True)
        _liberar()

        for i in faltam:
            img = f"{r['slug']}_cena_{i:02d}.png"
            h = _rodar(wf_baixo(img, pos[i], neg, n_q[i], latentes[i], pos[i]), proc)
            quadros_png = _saidas(h, "images")
            tmp = pasta / f".cena_{i:02d}_quadros"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir()
            for k, q in enumerate(quadros_png):
                shutil.move(q, tmp / f"{k:04d}.png")
            parcial = pasta / f".cena_{i:02d}.mp4"
            subprocess.run([FFMPEG, "-v", "error", "-y", "-framerate", str(QPS), "-i", str(tmp / "%04d.png"),
                            "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(parcial)], check=True)
            parcial.rename(pasta / f"cena_{i:02d}.mp4")  # só aparece para a montagem quando completo
            shutil.rmtree(tmp)
            (imagens.COMFY / "input" / latentes[i]).unlink(missing_ok=True)
            print(f"  animação: cena {i} pronta ({time.time() - t0:.0f}s)", flush=True)
        _liberar()
    finally:
        imagens.derrubar(proc)
    return faltam


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roteiro", type=Path)
    ap.add_argument("--cenas", type=int, nargs="*")
    args = ap.parse_args()
    r = json.loads(args.roteiro.read_text(encoding="utf-8"))[0]
    pasta = caminhos.PRODUCAO / "midia" / r["slug"]
    print(f"cenas: {args.cenas or escolher(r)}")
    feitas = animar(r, pasta, args.cenas)
    print(f"animadas: {feitas or 'nenhuma (já existiam)'}")


if __name__ == "__main__":
    main()
