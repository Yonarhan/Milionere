"""Confere no Pexels se cada palavra-chave tem vídeos verticais suficientes.

Uso:
    python checar_keywords.py "jellyfish, deep sea, fish swimming"
    python checar_keywords.py --arquivo roteiros.json

Saída: uma linha por palavra-chave com a quantidade de vídeos verticais
(>= 3s) encontrados e um aviso quando a cena provavelmente vai ficar fraca.
"""

import argparse
import json
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
CONFIG = RAIZ / "motor" / "config.toml"
MINIMO_BOM = 5


def chave_pexels() -> str:
    with open(CONFIG, "rb") as f:
        chaves = tomllib.load(f).get("app", {}).get("pexels_api_keys") or []
    if not chaves:
        sys.exit("Nenhuma chave do Pexels em config.toml")
    return chaves[0]


def contar_verticais(termo: str, chave: str) -> tuple[int, int]:
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": termo, "per_page": 40, "orientation": "portrait"}
    )
    req = urllib.request.Request(url, headers={"Authorization": chave, "User-Agent": "roteirista-shorts"})
    with urllib.request.urlopen(req, timeout=20) as r:
        dados = json.load(r)
    bons = [v for v in dados.get("videos", []) if v.get("duration", 0) >= 3]
    return len(bons), dados.get("total_results", 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="?", help="palavras-chave separadas por vírgula")
    ap.add_argument("--arquivo", help="roteiros.json; confere as keywords de todos os roteiros")
    args = ap.parse_args()

    grupos: list[tuple[str, list[str]]] = []
    if args.arquivo:
        for r in json.loads(Path(args.arquivo).read_text(encoding="utf-8")):
            if "cenas" in r:
                termos = [t.strip() for c in r["cenas"] for t in c["busca"].split("|")[:1]]
            else:
                termos = r["keywords"]
            grupos.append((r["slug"], termos))
    elif args.keywords:
        grupos.append(("keywords", [k.strip() for k in args.keywords.split(",") if k.strip()]))
    else:
        ap.error("informe as keywords ou --arquivo")

    chave = chave_pexels()
    fracas = 0
    for nome, termos in grupos:
        print(f"\n== {nome}")
        for t in termos:
            n, total = contar_verticais(t, chave)
            status = "OK   " if n >= MINIMO_BOM else "FRACA"
            fracas += n < MINIMO_BOM
            print(f"  {status} {n:>2} verticais (total {total:>5})  {t}")
    if fracas:
        print(f"\n{fracas} palavra(s)-chave fraca(s): troque por algo mais concreto e visual.")


if __name__ == "__main__":
    main()
