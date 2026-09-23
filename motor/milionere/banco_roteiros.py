"""Banco de roteiros por nicho: exemplos aprovados + erros que o juiz já apontou. É a memória que guia a IA.

    adicionar(nicho, formato, tema, titulo, falas, notas, origem)   # roteiro aprovado vira exemplo
    buscar_exemplos(nicho, tema, k=3)                               # os mais parecidos e mais bem avaliados
    registrar_erros(nicho, formato, problemas)                      # reprovações do juiz (camadas 1 e 2)
    erros_comuns(nicho, n=8)                                        # o que mais se repete: vira "não faça" no prompt
    registrar_desempenho(roteiro_id, views, retencao)               # dado real do post: pesa nos exemplos

CLI:  python banco_roteiros.py --indexar-repo | --exemplos "tema" --nicho gospel | --erros gospel
Onde fica: <PRODUCAO>/banco/roteiros.sqlite3. Mesma busca por significado do banco de imagens.
"""

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
from banco_imagens import NICHO_DO_PRESET, _embed  # noqa: E402


def _db() -> sqlite3.Connection:
    pasta = caminhos.PRODUCAO / "banco"
    pasta.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pasta / "roteiros.sqlite3")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS roteiros (id INTEGER PRIMARY KEY, chave TEXT UNIQUE, nicho TEXT, formato TEXT, tema TEXT,
            titulo TEXT, falas TEXT, notas TEXT, origem TEXT, views INTEGER, retencao REAL, criado TEXT, emb BLOB);
        CREATE TABLE IF NOT EXISTS erros (id INTEGER PRIMARY KEY, nicho TEXT, formato TEXT, texto TEXT, criado TEXT);""")
    return con


def _chave(nicho: str, falas: list[str]) -> str:
    return nicho + ":" + re.sub(r"\W+", "", unicodedata.normalize("NFKD", " ".join(falas).lower()))[:300]


def adicionar(nicho: str, formato: str, tema: str, titulo: str, falas: list[str], notas: dict | None = None,
              origem: str = "ia") -> int | None:
    falas = [f.strip() for f in falas if f and f.strip()]
    if len(falas) < 3:
        return None
    con = _db()
    ja = con.execute("SELECT id FROM roteiros WHERE chave=?", (_chave(nicho, falas),)).fetchone()
    if ja:
        con.close()
        return ja[0]
    v = _embed([f"{tema}. {titulo}. " + " ".join(falas)])
    cur = con.execute("INSERT INTO roteiros (chave,nicho,formato,tema,titulo,falas,notas,origem,criado,emb) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (_chave(nicho, falas), nicho, formato, tema, titulo, json.dumps(falas, ensure_ascii=False),
                       json.dumps(notas or {}, ensure_ascii=False), origem, datetime.now().isoformat(timespec="seconds"),
                       v[0].tobytes() if v is not None else None))
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid


def registrar_desempenho(roteiro_id: int, views: int | None = None, retencao: float | None = None) -> None:
    con = _db()
    con.execute("UPDATE roteiros SET views=COALESCE(?,views), retencao=COALESCE(?,retencao) WHERE id=?", (views, retencao, roteiro_id))
    con.commit()
    con.close()


def _qualidade(notas: dict, views, retencao) -> float:
    """0 a ~1: média das notas do juiz (1-5) + bônus pelo desempenho real quando existir."""
    vals = [v for v in (notas or {}).values() if isinstance(v, (int, float))]
    q = (sum(vals) / len(vals) - 1) / 4 if vals else 0.6
    if retencao:
        q += min(retencao, 1.0) * 0.3
    if views:
        q += min(views / 10000, 1.0) * 0.2
    return q


def buscar_exemplos(nicho: str, tema: str, k: int = 3, excluir_tema: str = "") -> list[dict]:
    import numpy as np

    con = _db()
    linhas = con.execute("SELECT id,formato,tema,titulo,falas,notas,views,retencao,emb FROM roteiros WHERE nicho=?", (nicho,)).fetchall()
    con.close()
    q = _embed([tema])
    res = []
    for (rid, formato, tm, titulo, falas, notas, views, ret, emb) in linhas:
        if excluir_tema and tm == excluir_tema:
            continue
        sim = float(np.frombuffer(emb, dtype="float32") @ q[0]) if (q is not None and emb) else 0.0
        qual = _qualidade(json.loads(notas or "{}"), views, ret)
        res.append({"id": rid, "formato": formato, "tema": tm, "titulo": titulo, "falas": json.loads(falas),
                    "pontos": round(0.6 * sim + 0.4 * qual, 3)})
    return sorted(res, key=lambda r: -r["pontos"])[:k]


def registrar_erros(nicho: str, formato: str, problemas: list[str]) -> None:
    if not problemas:
        return
    con = _db()
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany("INSERT INTO erros (nicho,formato,texto,criado) VALUES (?,?,?,?)",
                    [(nicho, formato, p[:400], agora) for p in problemas if p.strip()])
    con.commit()
    con.close()


def _tipo(texto: str) -> str:
    """Agrupa erros parecidos pelo começo ('gancho com 11 palavras' ~ 'gancho com 9 palavras')."""
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    t = re.sub(r"«.*?»|\".*?\"|\d+", "", t)
    return " ".join(t.split()[:6])


def erros_comuns(nicho: str, n: int = 8) -> list[tuple[str, int]]:
    con = _db()
    linhas = con.execute("SELECT texto FROM erros WHERE nicho=? ORDER BY id DESC LIMIT 400", (nicho,)).fetchall()
    con.close()
    grupos: dict[str, list[str]] = {}
    for (t,) in linhas:
        grupos.setdefault(_tipo(t), []).append(t)
    top = sorted(grupos.values(), key=len, reverse=True)[:n]
    return [(g[0], len(g)) for g in top]


def indexar_repo() -> int:
    """Os roteiros já aprovados do time (producao/roteiros) entram como exemplos."""
    n = 0
    for arq in sorted((caminhos.RAIZ / "producao").glob("roteiros/*.json")):
        for r in json.loads(arq.read_text(encoding="utf-8")):
            if not r.get("cenas"):
                continue
            nicho = NICHO_DO_PRESET.get(r.get("nicho", ""), r.get("nicho", ""))
            notas = (r.get("notas") or {}).get("juiz") or {}
            if adicionar(nicho, r.get("formato", ""), r.get("tema") or r.get("slug", ""), r.get("titulo", ""),
                         [c["fala"] for c in r["cenas"]], notas, "time"):
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexar-repo", action="store_true")
    ap.add_argument("--exemplos")
    ap.add_argument("--nicho", default="gospel")
    ap.add_argument("--erros")
    a = ap.parse_args()
    if a.indexar_repo:
        print("roteiros no banco: +", indexar_repo())
    if a.exemplos:
        for e in buscar_exemplos(a.nicho, a.exemplos):
            print(f"{e['pontos']:.2f}  {e['titulo']}  | {e['falas'][0]}")
    if a.erros:
        for t, c in erros_comuns(a.erros):
            print(f"{c:>3}x  {t}")


if __name__ == "__main__":
    main()
