"""Thumbnail (capa) do Short, feita junto com cada vídeo: um quadro limpo de uma cena (sem legenda) com o gancho
em letras grandes no alto, no estilo da legenda do canal (amarelo com contorno preto).

A cena da capa: campo "thumb_cena" do roteiro (1 = primeira); sem ele, a primeira cena com "animar" (a de mais
impacto) ou a 2ª. O quadro vem de producao/midia/<slug>/cena_NN.* e, sem ela, do vídeo final.

Uso avulso (vídeo já pronto):
    python thumbnail.py roteiro.json videos_prontos/<data>_<slug>.mp4
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

import caminhos

W, H = 1080, 1920
FONTE = caminhos.MOTOR / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _cena(r: dict) -> int:
    if r.get("thumb_cena"):
        return int(r["thumb_cena"])
    cenas = r.get("cenas", [])
    return next((i for i, c in enumerate(cenas, 1) if c.get("animar")), 2 if len(cenas) > 1 else 1)


def _quadro(origem: Path, destino: Path, segundo: float) -> bool:
    proc = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{segundo:.2f}", "-i", str(origem),
                           "-frames:v", "1", str(destino)])
    return proc.returncode == 0 and destino.exists()


def base_da_capa(r: dict, video: Path, tmp: Path) -> Image.Image:
    n = _cena(r)
    midia = caminhos.PRODUCAO / "midia" / r["slug"]
    achados = sorted(midia.glob(f"cena_{n:02d}[!0-9]*")) if midia.exists() else []
    img = next((p for p in achados if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}), None)
    vid = next((p for p in achados if p.suffix.lower() in {".mp4", ".mov"}), None)
    codigo = caminhos.PRODUCAO / "cenas_codigo" / f"{r['slug']}.json"
    if codigo.exists():  # animação em código: redesenha a cena sem os textos dela (o gancho ocupa o alto)
        import animacao_codigo
        cena = json.loads(codigo.read_text(encoding="utf-8"))["cenas"][n - 1]
        cena = {**cena, "camera": "fixa", "susto": False,
                "elementos": [e for e in cena["elementos"] if e["tipo"] != "texto"]}
        animacao_codigo.quadro(cena, round(1.5 * animacao_codigo.FPS)).write_to_png(str(tmp))
        img = tmp
    elif vid and _quadro(vid, tmp, 1.2):  # 1,2 s: objetos e textos da cena já entraram
        img = tmp
    if not img and _quadro(video, tmp, 1.0):
        img = tmp
    base = Image.open(img).convert("RGB") if img else Image.new("RGB", (W, H), "white")
    # preenche 1080x1920 sem distorcer
    esc = max(W / base.width, H / base.height)
    base = base.resize((round(base.width * esc), round(base.height * esc)), Image.LANCZOS)
    x, y = (base.width - W) // 2, (base.height - H) // 2
    return base.crop((x, y, x + W, y + H))


def escrever_gancho(img: Image.Image, texto: str) -> Image.Image:
    d = ImageDraw.Draw(img)
    texto = texto.upper()
    for tam in (150, 130, 115, 100, 88):
        fonte = ImageFont.truetype(str(FONTE), tam)
        linhas = textwrap.wrap(texto, width=max(8, int(W * 0.9 / (tam * 0.62))))
        if len(linhas) <= 3 and all(d.textlength(l, font=fonte) <= W * 0.92 for l in linhas):
            break
    y = 190
    for linha in linhas:
        larg = d.textlength(linha, font=fonte)
        d.text(((W - larg) / 2, y), linha, font=fonte, fill="#FFE600", stroke_width=max(8, tam // 11),
               stroke_fill="black")
        y += round(tam * 1.12)
    return img


def gerar(r: dict, video: Path, destino: Path) -> Path | None:
    texto = r.get("gancho_tela") or r.get("titulo", "")
    tmp = destino.with_name(destino.stem + "_quadro.png")
    try:
        img = escrever_gancho(base_da_capa(r, video, tmp), texto.strip())
        img.save(destino, quality=92)
        return destino
    except Exception as e:  # a capa nunca derruba a entrega do vídeo
        print(f"AVISO  [{r['slug']}] thumbnail falhou: {e}")
        return None
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    roteiro = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))[0]
    video = Path(sys.argv[2])
    print(gerar(roteiro, video, video.with_name(video.stem.removesuffix("_sem-musica") + "_thumb.jpg")))
