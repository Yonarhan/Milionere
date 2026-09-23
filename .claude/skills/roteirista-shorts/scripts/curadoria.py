"""Monta folhas de curadoria: para cada cena, até 12 candidatos numerados de várias fontes.

Uso:
    python curadoria.py roteiros.json                 # todas as cenas de todos os roteiros
    python curadoria.py roteiros.json --slug lazaro   # só um roteiro
    python curadoria.py roteiros.json --cenas 3,11    # refaz só algumas cenas (ex.: depois de mudar a busca)

Saída em producao/curadoria/<slug>/:
    cena_01.png ...     folha com a fala no topo e os candidatos numerados (V = vídeo, F = foto/pintura)
    candidatos.json     {"1": [candidato, ...], ...} — usado pelo produzir.py para achar o que foi escolhido

Depois de olhar as folhas, grave a escolha em cada cena do roteiros.json:
    "escolha": ["pexels:123", "wikimedia:456"]   (1 item por tomada; se faltar, repete o último)
"""

import argparse
import io
import json
import re
import textwrap
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import fontes

SKILL = Path(__file__).resolve().parents[1]
RAIZ = Path(__file__).resolve().parents[4]
MPT = RAIZ / "MoneyPrinterTurbo"
FONTE = MPT / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"
MAX_CANDIDATOS = 18
LADO_W, LADO_H = 240, 300  # cada miniatura


def miniatura(url: str) -> Image.Image:
    url = re.sub(r"/\d+px-", "/330px-", url) if "upload.wikimedia.org" in url else url  # prévia leve
    for tentativa in range(4):
        try:
            req = urllib.request.Request(url, headers=fontes.UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGB")
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == 3:
                raise
            time.sleep(2 + 2 * tentativa)  # Wikimedia limita pedidos seguidos
    if "wikimedia" in url:
        time.sleep(0.4)
    img.thumbnail((LADO_W, LADO_H))
    fundo = Image.new("RGB", (LADO_W, LADO_H), (20, 20, 20))
    fundo.paste(img, ((LADO_W - img.width) // 2, (LADO_H - img.height) // 2))
    return fundo


def folha(numero: int, fala: str, cands: list[dict], destino: Path) -> None:
    colunas = 6
    linhas = max(1, (len(cands) + colunas - 1) // colunas)
    topo = 90
    img = Image.new("RGB", (colunas * LADO_W, topo + linhas * LADO_H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    f_topo, f_num = ImageFont.truetype(str(FONTE), 26), ImageFont.truetype(str(FONTE), 30)
    d.text((10, 8), "\n".join(textwrap.wrap(f"CENA {numero}: {fala}", 95)[:2]), font=f_topo, fill=(255, 230, 0))
    for i, c in enumerate(cands):
        x, y = (i % colunas) * LADO_W, topo + (i // colunas) * LADO_H
        try:
            img.paste(miniatura(c["thumb"]), (x, y))
        except Exception:
            d.text((x + 20, y + 120), "sem prévia", font=f_topo, fill=(200, 60, 60))
        rotulo = f"{i + 1} {'V' if c['tipo'] == 'video' else 'F'} {c['ref'].split(':')[0]}"
        d.text((x + 6, y + 4), rotulo, font=f_num, fill=(255, 255, 0), stroke_width=3, stroke_fill=(0, 0, 0))
    img.save(destino)


POR_LINHA = 8  # candidatos por cena na folha geral


def folha_geral(cenas: list[dict], cache: dict, destino: Path) -> None:
    """Uma folha só por vídeo: 1 linha por cena, rótulo "cena.número" em cada miniatura."""
    lw, lh, txt = 150, 200, 360
    img = Image.new("RGB", (txt + POR_LINHA * lw, len(cenas) * lh), (0, 0, 0))
    d = ImageDraw.Draw(img)
    f_txt, f_num = ImageFont.truetype(str(FONTE), 20), ImageFont.truetype(str(FONTE), 24)
    miniaturas = {}
    with ThreadPoolExecutor(8) as ex:
        tarefas = {ex.submit(miniatura, c["thumb"]): (i, j) for i, cena in enumerate(cenas, 1)
                   for j, c in enumerate(cache.get(str(i), [])[:POR_LINHA])}
        for fut, pos in tarefas.items():
            try:
                miniaturas[pos] = fut.result()
            except Exception:
                pass
    for i, cena in enumerate(cenas, 1):
        y = (i - 1) * lh
        d.text((8, y + 8), "\n".join(textwrap.wrap(f"{i}. {cena['fala']}", 30)[:6]), font=f_txt, fill=(255, 230, 0))
        for j, c in enumerate(cache.get(str(i), [])[:POR_LINHA]):
            x = txt + j * lw
            if (i, j) in miniaturas:
                img.paste(miniaturas[(i, j)].resize((lw, lh)), (x, y))
            rot = f"{i}.{j + 1}{'F' if c['tipo'] == 'foto' else 'V'}"
            d.text((x + 4, y + 2), rot, font=f_num, fill=(255, 255, 0), stroke_width=3, stroke_fill=(0, 0, 0))
    img.save(destino)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--slug")
    ap.add_argument("--cenas", help="números das cenas, ex.: 3,11")
    ap.add_argument("--detalhe", action="store_true", help="também gera 1 folha grande por cena (mais lento de revisar)")
    args = ap.parse_args()

    presets = json.loads((SKILL / "presets.json").read_text(encoding="utf-8"))
    so_cenas = {int(x) for x in args.cenas.split(",")} if args.cenas else None
    for r in json.loads(Path(args.arquivo).read_text(encoding="utf-8")):
        if args.slug and args.slug not in r["slug"]:
            continue
        preset = presets[r["nicho"]]
        pasta = RAIZ / "producao" / "curadoria" / r["slug"]
        pasta.mkdir(parents=True, exist_ok=True)
        cache_arq = pasta / "candidatos.json"
        cache = json.loads(cache_arq.read_text(encoding="utf-8")) if cache_arq.exists() else {}
        def buscar(i_cena):
            i, cena = i_cena
            cands = fontes.buscar_candidatos(cena, preset.get("fontes_video", ["pexels", "pixabay"]),
                                             preset.get("fontes_arte", []), MPT / "config.toml",
                                             preset.get("evitar_termos"), preset.get("fontes_foto"))
            # folha geral mostra ~7 por cena: até 4 fotos/artes (mais específicas) + vídeos
            def alternar(lista):  # 1 de cada fonte por vez, para nenhuma fonte ocupar a folha toda
                por_fonte = {}
                for c in lista:
                    por_fonte.setdefault(c["ref"].split(":")[0], []).append(c)
                filas, saida = list(por_fonte.values()), []
                while any(filas):
                    for f in filas:
                        if f:
                            saida.append(f.pop(0))
                return saida

            fotos = alternar([c for c in cands if c["tipo"] == "foto"])
            videos = alternar([c for c in cands if c["tipo"] == "video"])
            return i, (fotos[:3] + videos[:5] + fotos[3:] + videos[5:])[:MAX_CANDIDATOS]

        alvo = [(i, c) for i, c in enumerate(r["cenas"], 1) if not so_cenas or i in so_cenas]
        with ThreadPoolExecutor(4) as ex:  # buscas em paralelo
            for i, cands in ex.map(buscar, alvo):
                cache[str(i)] = cands
                if args.detalhe:
                    folha(i, r["cenas"][i - 1]["fala"], cands, pasta / f"cena_{i:02d}.png")
        cache_arq.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        folha_geral(r["cenas"], cache, pasta / "folha_geral.png")
        print(f"[{r['slug']}] folha geral -> {pasta / 'folha_geral.png'}  (escolha: número 'cena.N')")


if __name__ == "__main__":
    main()
