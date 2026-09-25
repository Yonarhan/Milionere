"""Texto bíblico de referência (fonte da verdade para roteiro e validação) + catálogo de temas.

Tradução: Bíblia Portuguesa Mundial (BPM), domínio público (eBible.org, porbrbsl). Português atual ("você"),
usa "SENHOR". Só os 66 livros protestantes.

Uso:
    python biblia.py "Lucas 22:54-62"          # imprime o trecho
    python biblia.py "João 11:1-6; 11:32-44"   # vários trechos
    python biblia.py --sortear historia        # sorteia um tema ainda não usado do formato
    python biblia.py --montar                  # (re)gera biblia/bpm.json a partir do arquivo do eBible
"""

import argparse
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from caminhos import DADOS as SKILL  # noqa: E402  (presets, formatos, estilos, bíblia, referências)
PASTA = SKILL / "biblia"
ARQ_BPM = PASTA / "bpm.json"
ARQ_TEMAS = PASTA / "temas.json"
ARQ_PERSONAGENS = PASTA / "personagens.json"
TRADUCAO = "Bíblia Portuguesa Mundial (domínio público)"

# código BibleWorks (arquivo do eBible) -> nome em português, na ordem canônica
LIVROS = {
    "GEN": "Gênesis", "EXO": "Êxodo", "LEV": "Levítico", "NUM": "Números", "DEU": "Deuteronômio",
    "JOS": "Josué", "JDG": "Juízes", "RUT": "Rute", "1SA": "1 Samuel", "2SA": "2 Samuel",
    "1KI": "1 Reis", "2KI": "2 Reis", "1CH": "1 Crônicas", "2CH": "2 Crônicas", "EZR": "Esdras",
    "NEH": "Neemias", "EST": "Ester", "JOB": "Jó", "PSA": "Salmos", "PRO": "Provérbios",
    "ECC": "Eclesiastes", "SOL": "Cânticos", "ISA": "Isaías", "JER": "Jeremias", "LAM": "Lamentações",
    "EZE": "Ezequiel", "DAN": "Daniel", "HOS": "Oséias", "JOE": "Joel", "AMO": "Amós",
    "OBA": "Obadias", "JON": "Jonas", "MIC": "Miquéias", "NAH": "Naum", "HAB": "Habacuque",
    "ZEP": "Sofonias", "HAG": "Ageu", "ZEC": "Zacarias", "MAL": "Malaquias",
    "MAT": "Mateus", "MAR": "Marcos", "LUK": "Lucas", "JOH": "João", "ACT": "Atos",
    "ROM": "Romanos", "1CO": "1 Coríntios", "2CO": "2 Coríntios", "GAL": "Gálatas", "EPH": "Efésios",
    "PHI": "Filipenses", "COL": "Colossenses", "1TH": "1 Tessalonicenses", "2TH": "2 Tessalonicenses",
    "1TI": "1 Timóteo", "2TI": "2 Timóteo", "TIT": "Tito", "PHM": "Filemom", "HEB": "Hebreus",
    "JAM": "Tiago", "1PE": "1 Pedro", "2PE": "2 Pedro", "1JO": "1 João", "2JO": "2 João",
    "3JO": "3 João", "JUD": "Judas", "REV": "Apocalipse",
}
APELIDOS = {"salmo": "PSA", "cantares": "SOL", "canticodoscanticos": "SOL", "canticosdoscanticos": "SOL",
            "atosdosapostolos": "ACT", "apocalipsedejoao": "REV"}


def _chave(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


_POR_NOME = {_chave(n): c for c, n in LIVROS.items()} | APELIDOS


def montar() -> None:
    """Converte o arquivo 'verso por linha' do eBible em bpm.json {livro: {cap: {vers: texto}}}."""
    origem = PASTA / "fontes" / "porbrbsl" / "porbrbsl_vpl.txt"
    dados: dict = {}
    for linha in origem.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\w{3}) (\d+):(\d+) (.*)", linha)
        if m and m.group(1) in LIVROS:
            livro, cap, vers, texto = m.groups()
            dados.setdefault(livro, {}).setdefault(cap, {})[vers] = texto.strip()
    ARQ_BPM.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    print(f"{ARQ_BPM}: {sum(len(v) for c in dados.values() for v in c.values())} versículos")


_CACHE: dict = {}


def texto() -> dict:
    if not _CACHE:
        _CACHE.update(json.loads(ARQ_BPM.read_text(encoding="utf-8")))
    return _CACHE


class RefInvalida(ValueError):
    pass


def versiculos(ref: str) -> list[tuple[str, str]]:
    """'Lucas 22:54-62; 23:1' -> [('Lucas 22:54', texto), ...]. Aceita cap inteiro ('Rute 1'),
    faixa entre capítulos ('Gênesis 37:36-39:2') e vários trechos separados por ';' ou ','."""
    biblia = texto()
    saida: list[tuple[str, str]] = []
    ref = re.sub(r"\s+e\s+(?=\d)", "; ", ref)  # 'Gênesis 39:9 e 39:12' (o roteirista escreve assim às vezes)
    livro, cap_atual, sep = None, None, ";"
    for parte, prox in zip(*[iter(re.split(r"([;,])", ref) + [";"])] * 2):
        parte, sep_antes, sep = parte.strip(), sep, prox
        if not parte:
            continue
        m = re.match(r"^((?:[123]\s*)?[^\d:]+?)\s*(\d.*)$", parte)
        if m and not m.group(1).strip().isdigit():
            nome = _chave(m.group(1))
            if nome not in _POR_NOME:
                raise RefInvalida(f"livro desconhecido: '{m.group(1).strip()}' em '{ref}'")
            livro, resto = _POR_NOME[nome], m.group(2)
        elif livro:
            resto = parte
            # 'Gênesis 37:4,18-20': depois da vírgula, número sem ':' é versículo do mesmo capítulo (lia 18-20 como
            # capítulos e o evento caía "fora do trecho", reprovando a série do José)
            if sep_antes == "," and cap_atual and ":" not in resto:
                resto = f"{cap_atual}:{resto}"
        else:
            raise RefInvalida(f"referência sem livro: '{parte}'")

        m = re.match(r"^(\d+)(?::(\d+))?(?:\s*-\s*(\d+)(?::(\d+))?)?$", resto.replace(" ", ""))
        if not m:
            raise RefInvalida(f"formato não reconhecido: '{parte}'")
        c1, v1, a, b = m.groups()
        cap_atual = (a if b is not None else c1) if v1 is not None else None
        caps = biblia[livro]
        if c1 not in caps:
            raise RefInvalida(f"{LIVROS[livro]} não tem capítulo {c1}")
        if v1 is None:  # capítulo inteiro, ou 'Rute 1-2'
            c2 = a or c1
            inicio, fim = (int(c1), 1), (int(c2), 999)
        elif b is not None:  # 37:36-39:2
            inicio, fim = (int(c1), int(v1)), (int(a), int(b))
        else:  # 22:54-62 ou 22:54
            inicio, fim = (int(c1), int(v1)), (int(c1), int(a or v1))
        achou = False
        for cap in range(inicio[0], fim[0] + 1):
            for v, t in caps.get(str(cap), {}).items():
                if (cap, int(v)) >= inicio and (cap, int(v)) <= fim:
                    saida.append((f"{LIVROS[livro]} {cap}:{v}", t))
                    achou = True
        if not achou:
            raise RefInvalida(f"versículo inexistente: '{parte}'")
    return saida


def trecho(ref: str) -> str:
    return "\n".join(f"[{r}] {t}" for r, t in versiculos(ref))


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def temas() -> dict:
    return json.loads(ARQ_TEMAS.read_text(encoding="utf-8"))


O_QUE_E = {
    "historias": "um EPISÓDIO narrativo da Bíblia (acontecimento com começo, conflito e virada), contado em ~40s",
    "proverbios": "UM versículo de Provérbios (ou Eclesiastes) com um conselho prático do dia a dia",
    "personagens": "UM personagem bíblico e a virada da vida dele, em 30s",
    "versiculos": "um versículo famoso e a história/contexto por trás dele, que pouca gente conhece",
}
MINIMO_LIVRES = 3  # abaixo disso o catálogo é reposto sozinho (repor_temas) antes de sortear
_SCHEMA_TEMAS = {"type": "object", "additionalProperties": False, "required": ["temas"], "properties": {"temas": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["id", "titulo", "ref", "angulo", "personagens"],
                               "properties": {"id": {"type": "string"}, "titulo": {"type": "string"},
                                              "ref": {"type": "string"}, "angulo": {"type": "string"},
                                              "personagens": {"type": "array", "items": {"type": "string"}}}}}}}


def _versos(ref: str) -> set[str]:
    try:
        return {r for r, _ in versiculos(ref)}
    except RefInvalida:
        return set()


def repor_temas(catalogo: str, qtd: int = 10) -> list[dict]:
    """Pede ao LLM temas NOVOS tirados da Bíblia e só aceita os que passam na checagem: referência existe na BPM,
    não repete título nem cobre o mesmo trecho (>40% dos versículos) de tema já cadastrado. Grava em temas.json."""
    import llm

    todos = temas()
    atuais = todos[catalogo]
    feitos = "\n".join(f"- {t['titulo']} ({t['ref']})" for c in todos.values() if isinstance(c, list) for t in c)
    exemplos = json.dumps(atuais[:2], ensure_ascii=False, indent=1)
    ids_personagens = ", ".join(sorted(personagens()))
    prompt = (f"Você monta a pauta de um canal gospel de YouTube Shorts (Brasil). Proponha {qtd + 4} temas NOVOS para o "
              f"catálogo '{catalogo}': cada tema é {O_QUE_E.get(catalogo, 'um trecho bíblico')}.\n\n"
              f"JÁ FEITOS (não repita o episódio, o personagem principal nem o mesmo trecho):\n{feitos}\n\n"
              f"Formato dos existentes (siga o estilo do 'angulo': um fato surpreendente, concreto, em linguagem simples):\n"
              f"{exemplos}\n\nRegras:\n- `ref` em português com os nomes dos livros da Bíblia (ex.: '1 Samuel 17:4-11; "
              "17:45-50'), só trechos que existem de verdade; 1 a 4 faixas curtas com o essencial.\n"
              "- Prefira episódios com imagem forte e conflito (perigo, milagre, traição, virada) e conhecidos o bastante "
              "pra despertar curiosidade.\n- `id` curto em minúsculas com hífen, sem acento.\n"
              f"- `personagens`: ids de quem aparece; reuse estes quando for a mesma pessoa: {ids_personagens}. "
              "Para outros, crie id em minúsculas com hífen.")
    propostos = llm.chamar(prompt, _SCHEMA_TEMAS, papel="roteirista")["temas"]

    ids = {t["id"] for c in todos.values() if isinstance(c, list) for t in c}
    # checa contra TODOS os catálogos: o mesmo episódio como "história" e como "personagem" vira vídeo repetido
    existentes = [t for c in todos.values() if isinstance(c, list) for t in c]
    titulos = {normalizar(t["titulo"]) for t in existentes}
    cobertos = [_versos(t["ref"]) for t in existentes]
    aceitos = []
    for t in propostos:
        versos = _versos(t["ref"])
        if not versos:
            print(f"  tema recusado (referência inválida): {t['titulo']} ({t['ref']})")
            continue
        if normalizar(t["titulo"]) in titulos or any(len(versos & c) > 0.4 * min(len(versos), len(c)) for c in cobertos if c):
            print(f"  tema recusado (já feito): {t['titulo']} ({t['ref']})")
            continue
        base, n = re.sub(r"[^a-z0-9]+", "-", normalizar(t["id"])).strip("-") or "tema", 2
        t["id"] = base
        while t["id"] in ids:
            t["id"], n = f"{base}-{n}", n + 1
        t["prioridade"] = 2
        t["origem"] = "automatico"
        aceitos.append(t)
        ids.add(t["id"])
        titulos.add(normalizar(t["titulo"]))
        cobertos.append(versos)
        if len(aceitos) == qtd:
            break
    todos[catalogo] = atuais + aceitos
    ARQ_TEMAS.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  catálogo '{catalogo}': +{len(aceitos)} temas novos da Bíblia ({len(propostos) - len(aceitos)} recusados)")
    return aceitos


def sortear(formato: str, catalogo: str, usados: set[str], rng: random.Random | None = None) -> dict:
    """Um tema do catálogo ainda não usado neste formato (prioridade maior primeiro, sorteio dentro dela).
    Com poucos temas livres, repõe o catálogo com temas novos da Bíblia (repor_temas) antes de sortear."""
    livres = [t for t in temas()[catalogo] if f"{formato}:{t['id']}" not in usados]
    if len(livres) < MINIMO_LIVRES:
        try:
            repor_temas(catalogo)
        except Exception as e:  # noqa: BLE001 - sem LLM agora: sorteia do que sobrou
            print(f"  não consegui repor o catálogo '{catalogo}': {e}")
        livres = [t for t in temas()[catalogo] if f"{formato}:{t['id']}" not in usados]
    if not livres:
        raise RuntimeError(f"catálogo '{catalogo}' esgotado para o formato '{formato}'")
    melhor = max(t.get("prioridade", 1) for t in livres)
    return (rng or random).choice([t for t in livres if t.get("prioridade", 1) == melhor])


def personagens() -> dict:
    return json.loads(ARQ_PERSONAGENS.read_text(encoding="utf-8")) if ARQ_PERSONAGENS.exists() else {}


def salvar_personagens(novos: list[dict]) -> None:
    """Guarda a descrição visual de personagens novos para os próximos vídeos usarem a mesma."""
    atuais = personagens()
    for p in novos:
        atuais.setdefault(p["id"], {"nome": p["nome"], "descricao_visual": p["descricao_visual"]})
    ARQ_PERSONAGENS.write_text(json.dumps(atuais, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", nargs="?")
    ap.add_argument("--montar", action="store_true")
    ap.add_argument("--sortear", metavar="FORMATO")
    args = ap.parse_args()
    if args.montar:
        montar()
    elif args.sortear:
        formatos = json.loads((SKILL / "formatos.json").read_text(encoding="utf-8"))
        print(json.dumps(sortear(args.sortear, formatos[args.sortear]["catalogo"], set()), ensure_ascii=False, indent=2))
    elif args.ref:
        try:
            print(trecho(args.ref))
        except RefInvalida as e:
            sys.exit(str(e))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
