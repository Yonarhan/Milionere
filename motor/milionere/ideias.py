"""Caça ideias em Shorts que já viralizaram (em qualquer idioma) para recriar em português.

Uso:
    python ideias.py                          # busca padrão: ciências em inglês
    python ideias.py "black hole facts" "weird animals"   # buscas próprias
    python ideias.py --canais                 # Shorts mais vistos dos canais de ciência de referência (melhor)
    python ideias.py --canais @zackdfilms     # canais específicos
    python ideias.py --transcricao <url>      # baixa o texto falado de um Short (legenda automática)

Saída: tabela dos Shorts mais vistos (≤ 90 s) e producao/ideias/<data>.md.
Regra: fato não tem dono, roteiro e imagens sim. Nunca copiar texto nem reaproveitar o vídeo;
sempre checar o fato (muito Short viral espalha fato errado) e escrever do nosso jeito.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import caminhos  # noqa: E402
from caminhos import RAIZ  # noqa: E402
from caminhos import MOTOR as MPT  # noqa: E402
from caminhos import PYTHON_MOTOR as PYTHON  # noqa: E402
BUSCAS_PADRAO = [
    "space facts", "black hole facts", "weird planet facts",
    "biology facts", "weird animal facts", "human body facts",
    "chemistry facts", "physics facts", "math facts mind blowing",
]
CANAIS_PADRAO = ["@zackdfilms", "@kurzgesagt", "@veritasium", "@Vsauce", "@TheActionLab", "@ScienceInsider"]
FILTRO_CURTO = "EgIYAQ%3D%3D"  # filtro do YouTube: vídeos com menos de 4 min


def ytdlp(*args: str) -> str:
    proc = subprocess.run([str(PYTHON), "-m", "yt_dlp", *args], capture_output=True, text=True, encoding="utf-8")
    return proc.stdout


def buscar(termo: str, n: int = 30) -> list[dict]:
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(termo + ' #shorts')}&sp={FILTRO_CURTO}"
    saida = ytdlp(url, "--flat-playlist", "--playlist-end", str(n), "-J")
    try:
        entradas = json.loads(saida).get("entries", [])
    except json.JSONDecodeError:
        return []
    return [
        {"titulo": e.get("title"), "canal": e.get("channel") or e.get("uploader"), "views": e.get("view_count") or 0,
         "dur": e.get("duration") or 0, "url": e.get("url"), "busca": termo}
        for e in entradas if e.get("duration") and e["duration"] <= 90
    ]


def shorts_do_canal(canal: str, n: int = 120) -> list[dict]:
    saida = ytdlp(f"https://www.youtube.com/{canal}/shorts", "--flat-playlist", "--playlist-end", str(n),
                  "--print", "%(view_count)s|%(url)s|%(title)s")
    videos = []
    for ln in saida.splitlines():
        partes = ln.split("|", 2)
        if len(partes) == 3 and partes[0].isdigit():
            videos.append({"titulo": partes[2], "canal": canal, "views": int(partes[0]), "dur": 60,
                           "url": partes[1], "busca": "canal"})
    return videos


def transcricao(url: str) -> str:
    pasta = caminhos.PRODUCAO / "ideias" / "transcricoes"
    pasta.mkdir(parents=True, exist_ok=True)
    ytdlp(url, "--skip-download", "--write-auto-subs", "--sub-langs", "en.*,pt.*", "--sub-format", "vtt",
          "-o", str(pasta / "%(id)s.%(ext)s"))
    arqs = sorted(pasta.glob("*.vtt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not arqs:
        return "(sem legenda automática disponível)"
    linhas, vistas = [], set()
    for ln in arqs[0].read_text(encoding="utf-8").splitlines():
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")) or ln in vistas:
            continue
        vistas.add(ln)
        linhas.append(ln)
    return " ".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("buscas", nargs="*")
    ap.add_argument("--transcricao")
    ap.add_argument("--canais", nargs="*", help="sem valores = canais de referência")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    if args.transcricao:
        print(transcricao(args.transcricao))
        return

    vistos, todos = set(), []
    if args.canais is not None:
        for canal in args.canais or CANAIS_PADRAO:
            todos += shorts_do_canal(canal)
            print(f"  canal: {canal}", file=sys.stderr)
    for termo in ([] if args.canais is not None and not args.buscas else (args.buscas or BUSCAS_PADRAO)):
        for v in buscar(termo):
            if v["url"] not in vistos:
                vistos.add(v["url"])
                todos.append(v)
        print(f"  buscou: {termo}", file=sys.stderr)
    todos.sort(key=lambda v: -v["views"])

    linhas = ["| views | título | canal | busca | link |", "|---:|---|---|---|---|"]
    for v in todos[: args.top]:
        linhas.append(f"| {v['views']:,} | {v['titulo']} | {v['canal']} | {v['busca']} | {v['url']} |".replace(",", "."))
    tabela = "\n".join(linhas)
    destino = caminhos.PRODUCAO / "ideias" / f"{date.today():%Y-%m-%d}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(f"# Shorts mais vistos ({date.today():%d/%m/%Y})\n\n{tabela}\n", encoding="utf-8")
    print(tabela)
    print(f"\nsalvo em {destino}")


if __name__ == "__main__":
    main()
