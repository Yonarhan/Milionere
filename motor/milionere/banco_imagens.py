"""Banco de imagens por nicho (v1): toda imagem aprovada entra; toda cena nova consulta antes de gerar ou buscar.

Uso:
    python banco_imagens.py --indexar-repo                 # importa as imagens já aprovadas do time (producao/midia)
    python banco_imagens.py --buscar "Jesus chorou" --nicho gospel
    python banco_imagens.py --listar [--nicho gospel]

Onde fica: <PRODUCAO>/banco/indice.sqlite3 + <PRODUCAO>/banco/<nicho>/<hash>.<ext>
(no serviço, PRODUCAO = servico/media/producao). v1 em SQLite; na produção vira Postgres + pgvector.

Busca por significado com um modelo aberto e grátis (paraphrase-multilingual-MiniLM, via fastembed/onnx):
a fala em português encontra imagens descritas em inglês. Sem o modelo, cai para busca por palavras.
Regras: mesmo nicho; personagem da fala tem que bater com o da imagem; uploads privados só voltam
para o próprio dono; a mesma imagem não repete dentro de um vídeo.
"""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402

MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_MODELOS = caminhos.MOTOR / "storage" / "modelos"
LIMIAR_REUSO = 0.55          # abaixo disso a imagem não ilustra bem a fala: melhor buscar/gerar
NICHO_DO_PRESET = {"gospel": "gospel", "astronomia": "astronomia", "curiosidades": "animais"}
EXTRAS_PERSONAGENS = {"jesus": "jesus", "pedro": "pedro", "lazaro": "lazaro", "maria": "maria", "marta": "marta",
                      "jonas": "jonas", "moises": "moises", "davi": "davi", "paulo": "paulo"}


def _pasta() -> Path:
    p = caminhos.PRODUCAO / "banco"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_pasta() / "indice.sqlite3")
    con.execute("""CREATE TABLE IF NOT EXISTS imagens (
        id INTEGER PRIMARY KEY, hash TEXT UNIQUE, nicho TEXT, arquivo TEXT, descricao TEXT, personagens TEXT,
        estilo TEXT, origem TEXT, credito TEXT, compartilhada INTEGER, dono TEXT, usos INTEGER DEFAULT 0,
        ultimo_uso TEXT, criado TEXT, emb BLOB)""")
    return con


# ------------------------------------------------------------------ texto -> vetor

_modelo = None


def _embed(textos: list[str]):
    """Vetores normalizados (numpy) ou None se o modelo não estiver disponível."""
    global _modelo
    try:
        import numpy as np
        from fastembed import TextEmbedding
    except ImportError:
        return None
    if _modelo is None:
        CACHE_MODELOS.mkdir(parents=True, exist_ok=True)
        _modelo = TextEmbedding(MODELO, cache_dir=str(CACHE_MODELOS))
    v = np.array(list(_modelo.embed(textos)), dtype="float32")
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def _palavras(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", _sem_acento(t))}


def detectar_personagens(texto: str) -> list[str]:
    nomes = dict(EXTRAS_PERSONAGENS)
    arq = caminhos.DADOS / "biblia" / "personagens.json"
    if arq.exists():
        for pid, p in json.loads(arq.read_text(encoding="utf-8")).items():
            nomes[_sem_acento(p.get("nome", pid)).split()[0]] = pid
    t = _sem_acento(texto)
    achados = [(m.start(), pid) for nome, pid in nomes.items() for m in [re.search(rf"\b{re.escape(nome)}\b", t)] if m]
    return list(dict.fromkeys(pid for _, pid in sorted(achados)))  # na ordem em que aparecem (1º = principal)


# ------------------------------------------------------------------ escrita

def adicionar(arquivo: Path, nicho: str, descricao: str, personagens: list[str] | None = None, estilo: str = "",
              origem: str = "", credito: str = "", compartilhada: bool = True, dono: str = "") -> int | None:
    """Guarda a imagem no banco do nicho (sem duplicar pelo conteúdo). Devolve o id."""
    arquivo = Path(arquivo)
    if not arquivo.exists() or arquivo.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    h = hashlib.sha1(arquivo.read_bytes()).hexdigest()[:20]
    con = _db()
    ja = con.execute("SELECT id FROM imagens WHERE hash=?", (h,)).fetchone()
    if ja:
        con.close()
        return ja[0]
    destino = _pasta() / nicho / f"{h}{arquivo.suffix.lower()}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(arquivo, destino)
    pers = personagens if personagens is not None else detectar_personagens(descricao)
    v = _embed([descricao])
    cur = con.execute(
        "INSERT INTO imagens (hash,nicho,arquivo,descricao,personagens,estilo,origem,credito,compartilhada,dono,criado,emb)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (h, nicho, str(destino.relative_to(_pasta())), descricao, json.dumps(pers), estilo, origem, credito,
         int(compartilhada), dono, datetime.now().isoformat(timespec="seconds"), v[0].tobytes() if v is not None else None))
    con.commit()
    novo = cur.lastrowid
    con.close()
    return novo


def marcar_uso(ids: list[int]) -> None:
    if not ids:
        return
    con = _db()
    agora = datetime.now().isoformat(timespec="seconds")
    con.executemany("UPDATE imagens SET usos=usos+1, ultimo_uso=? WHERE id=?", [(agora, i) for i in ids])
    con.commit()
    con.close()


# ------------------------------------------------------------------ busca

def buscar(nicho: str, texto: str, dono: str = "", excluir: set[int] | None = None, k: int = 5) -> list[dict]:
    """As k imagens do nicho que melhor ilustram o texto, com nota de 0 a 1."""
    import numpy as np

    con = _db()
    linhas = con.execute("SELECT id,arquivo,descricao,personagens,origem,credito,compartilhada,dono,usos,emb FROM imagens "
                         "WHERE nicho=? AND (compartilhada=1 OR dono=?)", (nicho, dono or "\x00")).fetchall()
    con.close()
    linhas = [l for l in linhas if l[0] not in (excluir or set())]
    if not linhas:
        return []
    citados = detectar_personagens(texto)
    alvo, principal = set(citados), (citados[0] if citados else None)
    q = _embed([texto])
    res = []
    for (iid, arq, desc, pers, origem, credito, comp, dn, usos, emb) in linhas:
        if q is not None and emb:
            nota = float(np.frombuffer(emb, dtype="float32") @ q[0])
        else:  # sem modelo: sobreposição de palavras
            a, b = _palavras(texto), _palavras(desc)
            nota = len(a & b) / max(1, len(a))
        pimg = set(json.loads(pers or "[]"))
        if alvo and not (alvo & pimg):
            nota -= 0.25        # a fala fala de Pedro e a imagem é de outra pessoa
        elif alvo & pimg:
            nota += 0.10 if principal in pimg else 0.03
        elif pimg and not alvo:
            nota -= 0.05        # cena sem personagem: prefere paisagem/objeto
        nota -= min(usos, 20) * 0.005  # leve rodízio: as mais usadas descem um pouco
        res.append({"id": iid, "nota": round(nota, 3), "arquivo": _pasta() / arq, "descricao": desc,
                    "origem": origem, "credito": credito})
    return sorted(res, key=lambda r: -r["nota"])[:k]


def listar(nicho: str | None = None) -> list[dict]:
    con = _db()
    q = "SELECT id,nicho,arquivo,descricao,personagens,origem,usos,compartilhada,criado FROM imagens"
    linhas = con.execute(q + (" WHERE nicho=?" if nicho else "") + " ORDER BY id DESC", ((nicho,) if nicho else ())).fetchall()
    con.close()
    return [{"id": l[0], "nicho": l[1], "arquivo": str(_pasta() / l[2]), "rel": l[2], "descricao": l[3],
             "personagens": json.loads(l[4] or "[]"), "origem": l[5], "usos": l[6], "compartilhada": bool(l[7]), "criado": l[8]}
            for l in linhas]


# ------------------------------------------------------------------ carga inicial

def indexar_repo() -> int:
    """Importa as imagens já aprovadas pelo time: producao/midia/<slug>/cena_NN.* dos roteiros do repositório."""
    repo = caminhos.RAIZ / "producao"
    n = 0
    for arq in sorted(repo.glob("roteiros/*.json")):
        for r in json.loads(arq.read_text(encoding="utf-8")):
            pasta = repo / "midia" / r.get("slug", "")
            if not r.get("cenas") or not pasta.is_dir():
                continue
            nicho = NICHO_DO_PRESET.get(r.get("nicho", ""), r.get("nicho", ""))
            for i, c in enumerate(r["cenas"], 1):
                img = next((p for p in sorted(pasta.glob(f"cena_{i:02d}*")) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), None)
                if not img:
                    continue
                # só o que descreve a IMAGEM (termos de busca de banco não descrevem a imagem gerada)
                desc = " | ".join(x for x in (c["fala"], c.get("imagem", "")) if x)
                pers = c.get("personagens") or detectar_personagens(desc)
                if adicionar(img, nicho, desc, pers, r.get("estilo", "cinema"), "ia-time", "Imagem gerada por IA", True, "time"):
                    n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexar-repo", action="store_true")
    ap.add_argument("--buscar")
    ap.add_argument("--nicho")
    ap.add_argument("--listar", action="store_true")
    a = ap.parse_args()
    if a.indexar_repo:
        print(f"imagens no banco: +{indexar_repo()} (total {len(listar())})")
    if a.buscar:
        for r in buscar(a.nicho or "gospel", a.buscar):
            print(f"{r['nota']:.2f}  {r['arquivo'].name}  {r['descricao'][:90]}")
    if a.listar:
        for r in listar(a.nicho):
            print(r["id"], r["nicho"], r["origem"], r["usos"], r["personagens"], r["descricao"][:70])


if __name__ == "__main__":
    main()
