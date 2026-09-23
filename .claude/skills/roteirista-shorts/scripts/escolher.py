"""Grava as escolhas da folha geral no roteiro.

Uso: python escolher.py roteiros.json <slug> "1.3 2.1 3.5 5.2,5.4 ..."
     (cena.N separados por espaço; vírgula = 2 tomadas na mesma cena;
      "2=3.5" = usar na cena 2 o candidato 5 da linha da cena 3)
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]

arquivo, slug, escolhas = sys.argv[1], sys.argv[2], sys.argv[3]
roteiros = json.loads(Path(arquivo).read_text(encoding="utf-8"))
r = next(x for x in roteiros if slug in x["slug"])
cand = json.loads((RAIZ / "producao" / "curadoria" / r["slug"] / "candidatos.json").read_text(encoding="utf-8"))
for grupo in escolhas.split():
    refs = []
    destino = int(grupo.split("=")[0]) if "=" in grupo else None
    for item in grupo.split("=")[-1].split(","):
        cena, n = (int(x) for x in item.split("."))
        c = cand[str(cena)][n - 1]
        refs.append(c["ref"])
        print(f"cena {cena}: {c['ref']}  {c['desc'][:60]}")
    r["cenas"][(destino or cena) - 1]["escolha"] = refs
Path(arquivo).write_text(json.dumps(roteiros, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
