"""Vídeo nativo: roteiro pelo Claude + fotos, pinturas e vídeos de acervos grátis + montagem no ffmpeg.

Nada de gerar imagem com IA: roda em PC fraco, sem GPU para Stable Diffusion/Flux. Por cena:
    1. candidatos de todas as fontes do preset do nicho (fontes.py: Pexels, Pixabay, NASA, museus em domínio
       público, Openverse, iNaturalist...)
    2. folhas com as miniaturas numeradas (6 cenas por folha, para o Claude enxergar)
    3. o Claude escolhe a melhor de cada cena numa chamada só por vídeo (papel juiz: modelo barato)
    4. produzir.py monta com as escolhas (foto/pintura vira movimento; vídeo é cortado no tempo da fala)

    python nativo.py astronomia "Fato que dá uau" "O planeta onde chove vidro de lado"
    python nativo.py gospel historia zaqueu            # tema do catálogo bíblico: roteiro com o texto exato
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import curadoria  # noqa: E402
import llm  # noqa: E402
import medidor  # noqa: E402

CENAS_POR_FOLHA = 6
SCHEMA_ESCOLHA = {
    "type": "object", "additionalProperties": False, "required": ["escolhas"],
    "properties": {"escolhas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["cena", "candidato", "nova_busca"],
        "properties": {"cena": {"type": "integer"},
                       "candidato": {"type": "integer", "description": "o N do rótulo cena.N; 0 se nenhum serve de verdade"},
                       "nova_busca": {"type": "string", "description": "se candidato = 0: termo em inglês, concreto e "
                                      "curto, para achar um VÍDEO de banco que mostre a cena; senão vazio"}}}}},
}
# museu cataloga Jesus como "Christ": a busca por "Jesus" quase não acha pintura
NOME_NO_MUSEU = {"jesus": "Christ", "maria": "Virgin Mary", "pedro": "Saint Peter", "paulo": "Saint Paul"}
# desenho e ilustração no meio de foto real deixam o vídeo com cara de colagem (o 1º vídeo nativo pegou um cartum)
NAO_REALISTA = ["cartoon", "comic", "illustration", "vector", "clipart", "clip art", "drawing", "sketch", "anime",
                "3d render", "3d model", "icon", "logo", "infographic", "emoji", "mascot"]
# vídeo de agência com apresentador, entrevista ou texto na tela (ex.: série "What's Up" da NASA)
FALADOS = ["what's up", "whats up", "skywatching tips", "briefing", "interview", "press conference", "lecture",
           "webinar", "q&a", "explains", "explained", "tutorial"]
# formatos com os mesmos personagens em todas as cenas: foto de banco mostra uma pessoa diferente por cena
FORMATOS_SO_IA = {"parabola"}


def _presets() -> dict:
    return json.loads((caminhos.DADOS / "presets.json").read_text(encoding="utf-8"))


def termos_de_busca(r: dict) -> None:
    """Preenche `foto` (fotos de acervo) e `arte` (pinturas/NASA) de cada cena a partir da `busca` em inglês.
    Pintura de museu só em história da época bíblica: numa parábola moderna ela entrava no meio do escritório."""
    fichas = {p["id"]: p for p in r.get("personagens", [])}
    biblico = r["nicho"] == "gospel" and r.get("epoca", "biblica") == "biblica"
    for c in r["cenas"]:
        busca = (c.get("busca") or "").split("|")[0].strip()
        c.setdefault("foto", busca)
        if biblico:
            nomes = [NOME_NO_MUSEU.get(i, fichas.get(i, {}).get("nome_en") or fichas.get(i, {}).get("nome", ""))
                     for i in c.get("personagens", [])]
            nomes = [n for n in nomes if n]
            # pintura: quem aparece (como o museu chama) + o começo da busca ("Christ Saint Peter stormy sea")
            c.setdefault("arte", " ".join(nomes[:2] + busca.split()[:2]) or busca)
        elif r["nicho"] == "astronomia":
            c.setdefault("arte", busca)


def _limpar(cands: list[dict]) -> list[dict]:
    return [c for c in cands if not any(p in f"{c.get('desc', '')} {c.get('link', '')}".lower() for p in NAO_REALISTA + FALADOS)]


def _ordenar(cands: list[dict], preset: dict, r: dict) -> list[dict]:
    """História bíblica: a pintura é o que mostra Jesus e os personagens (vídeo de banco não mostra), então as de
    museu ocupam as 3 primeiras vagas. Nos outros vídeos, vídeo de banco (movimento) vem antes de foto."""
    cands = _limpar(cands)
    if r["nicho"] == "gospel" and r.get("epoca", "biblica") == "biblica":
        arte = set(preset.get("fontes_arte", []))
        pinturas = curadoria._alternar([c for c in cands if c["ref"].split(":")[0] in arte])
        resto = [c for c in cands if c["ref"].split(":")[0] not in arte]
        return pinturas[:3] + resto[:curadoria.POR_LINHA - min(3, len(pinturas))] + pinturas[3:] + resto[curadoria.POR_LINHA:]
    videos = [c for c in cands if c["tipo"] == "video"]
    fotos = [c for c in cands if c["tipo"] != "video"]
    return videos[:5] + fotos[:3] + videos[5:] + fotos[3:]


def _escolher(r: dict, cenas: list[int], cache: dict, pasta: Path, rodada: int) -> dict[int, dict]:
    """Uma chamada ao Claude olhando as folhas das `cenas`. Devolve {cena: {"candidato": N, "nova_busca": ...}}."""
    folhas = []
    for k in range(0, len(cenas), CENAS_POR_FOLHA):
        grupo = cenas[k:k + CENAS_POR_FOLHA]
        if grupo == list(range(grupo[0], grupo[0] + len(grupo))):  # cenas seguidas: uma folha, numeradas em ordem
            destino = pasta / f"folha_r{rodada}_{k // CENAS_POR_FOLHA + 1}.png"
            curadoria.folha_geral([r["cenas"][i - 1] for i in grupo], cache, destino, inicio=grupo[0])
            folhas.append(destino)
            continue
        for i in grupo:  # cenas soltas (2ª rodada): uma folha por cena, com o número certo
            destino = pasta / f"folha_r{rodada}_cena{i:02d}.png"
            curadoria.folha_geral([r["cenas"][i - 1]], cache, destino, inicio=i)
            folhas.append(destino)
    lista = "\n".join(f"{i}. fala: «{r['cenas'][i - 1]['fala']}» · deveria mostrar: "
                      f"{r['cenas'][i - 1].get('imagem') or r['cenas'][i - 1].get('busca', '')}" for i in cenas)
    biblico = r["nicho"] == "gospel" and r.get("epoca", "biblica") == "biblica"
    prompt = (
        f"Abra com a ferramenta Read as {len(folhas)} imagens: {', '.join(str(f) for f in folhas)}.\n"
        "Cada linha de uma folha é uma cena de um vídeo curto vertical (a fala narrada está em amarelo à esquerda). "
        "As miniaturas da linha têm o rótulo 'cena.N' (F = foto ou pintura, V = vídeo).\n\n"
        "Para CADA cena, escolha a miniatura que mostra O QUE A FALA DIZ. Quem assiste precisa ver na imagem a ação "
        "ou a coisa narrada naquele segundo; imagem só 'do mesmo tema' deixa o vídeo desconexo.\n"
        "- o assunto certo: o animal, o planeta, a ação (gritar, pedir desculpa, afundar), o lugar;\n"
        + ("- história bíblica: pintura da própria história ou cena de época; nada moderno, nenhum símbolo de outra "
           "religião;\n" if biblico else
           "- tudo com cara de FOTO/VÍDEO REAL: nada de desenho, pintura antiga, estátua ou ilustração;\n") +
        "- nada de texto, logotipo, marca d'água, moldura de quadro, gráfico ou infográfico;\n"
        "- o vídeo todo com o mesmo clima visual (não misture estilos);\n"
        "- não use a mesma imagem (ou quase igual) em duas cenas;\n"
        "- empate: prefira vídeo (V), que tem movimento.\n"
        "Se NENHUMA miniatura da linha mostra a fala de verdade, responda candidato 0 e escreva em `nova_busca` um termo "
        "em inglês, curto e concreto, para achar um vídeo de banco que mostre a cena (ex.: 'angry boss shouting office').\n\n"
        f"# O que cada cena precisa\n{lista}\n\nDevolva uma escolha por cena listada."
    )
    with medidor.etapa("curadoria"):
        # o modelo do roteirista: o barato (Haiku) escolheu um cartum com vídeos bons na mesma linha
        j = llm.chamar(prompt, SCHEMA_ESCOLHA, ler_arquivos_em=pasta, papel="roteirista")
    return {e["cena"]: e for e in j["escolhas"] if e["cena"] in cenas}


def curar(r: dict, log=print) -> dict:
    """Busca candidatos, monta as folhas e deixa o Claude escolher. Cena sem candidato bom ganha uma 2ª rodada com a
    busca que o próprio Claude sugeriu. Grava `escolha` nas cenas e o candidatos.json que o produzir.py usa."""
    preset = _presets()[r["nicho"]]
    pasta = caminhos.PRODUCAO / "curadoria" / r["slug"]
    pasta.mkdir(parents=True, exist_ok=True)
    termos_de_busca(r)
    log("buscando fotos e vídeos grátis para cada cena")
    with ThreadPoolExecutor(4) as ex:
        cands = list(ex.map(lambda c: _ordenar(curadoria.candidatos_para(c, preset), preset, r), r["cenas"]))
    cache = {str(i): c for i, c in enumerate(cands, 1)}
    todas = [i for i, c in enumerate(cands, 1) if c]
    usados, escolhidas = set(), 0

    def aplicar(decisoes: dict[int, dict]) -> list[tuple[int, str]]:
        nonlocal escolhidas
        refazer = []
        for i, e in sorted(decisoes.items()):
            opcoes = cache[str(i)][:curadoria.POR_LINHA]
            n = e["candidato"]
            escolha = opcoes[n - 1] if 1 <= n <= len(opcoes) else None
            if escolha and escolha["ref"] in usados:  # a mesma imagem em duas cenas: fica para a 2ª rodada
                escolha = None
            if escolha:
                r["cenas"][i - 1]["escolha"] = [escolha["ref"]]
                usados.add(escolha["ref"])
                escolhidas += 1
            elif e.get("nova_busca", "").strip():
                refazer.append((i, e["nova_busca"].strip()))
        return refazer

    refazer = []
    if todas:
        log("escolhendo as imagens (uma chamada ao Claude para o vídeo todo)")
        refazer = aplicar(_escolher(r, todas, cache, pasta, 1))
    if refazer:
        log(f"2ª rodada com buscas novas para as cenas {[i for i, _ in refazer]}")
        for i, termo in refazer:
            c = r["cenas"][i - 1]
            novos = _ordenar(curadoria.candidatos_para({**c, "busca": termo, "foto": termo, "arte": ""}, preset), preset, r)
            cache[str(i)] = [x for x in novos if x["ref"] not in usados] or cache[str(i)]
            c["busca"] = termo  # a busca automática da montagem (se ainda sobrar sem escolha) usa o termo melhor
        aplicar(_escolher(r, [i for i, _ in refazer], cache, pasta, 2))
    (pasta / "candidatos.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    sem = [i for i, c in enumerate(r["cenas"], 1) if not c.get("escolha")]
    log(f"curadoria: {escolhidas} cenas escolhidas" + (f"; sem escolha (busca automática no Pexels): {sem}" if sem else ""))
    return {"escolhidas": escolhidas, "sem_escolha": sem}


def montar(r: dict, pasta: Path, musica: str, log=print) -> list[Path]:
    """Roda o produzir.py (voz, legenda, cortes e render no ffmpeg) e devolve os vídeos prontos."""
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "roteiro.json"
    arq.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [str(caminhos.PYTHON_MOTOR), str(Path(__file__).with_name("produzir.py")), str(arq)]
    cmd += {"sem": ["--sem-musica"], "ambas": ["--duas-versoes"]}.get(musica, [])
    log("montando o vídeo (voz, legenda e ffmpeg)")
    proc = subprocess.run(cmd, cwd=caminhos.MOTOR, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    (pasta / "log.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    videos = [Path(l.split("] ", 1)[1].strip()) for l in proc.stdout.splitlines() if l.startswith("PRONTO")]
    videos = [v for v in videos if v.exists()]
    if not videos:
        falha = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("FALHOU")), "")
        raise RuntimeError(falha or f"a montagem falhou: veja {pasta / 'log.txt'}")
    return videos


def roteiro_biblico(formato_id: str, tema_id: str, log=print) -> dict:
    """Tema do catálogo bíblico: o roteiro validado do pipeline (texto exato da Bíblia, camadas 1 e 2)."""
    import biblia
    import pipeline
    formato = pipeline.carregar("formatos.json")[formato_id]
    tema = next(t for t in biblia.temas()[formato["catalogo"]] if t["id"] == tema_id)
    slug = f"nativo-{formato_id}-{tema_id}"
    original = pipeline.log
    pipeline.log = lambda m: (original(m), log(m))
    try:
        with medidor.etapa("roteiro"):
            r = pipeline.roteiro_validado(formato, tema, pipeline.Registro(slug))
    finally:
        pipeline.log = original
    if not r:
        raise RuntimeError(f"o roteiro não passou nas validações em {pipeline.MAX_REESCRITAS} tentativas")
    pacote = pipeline.empacotar(r, formato_id, formato, tema, formato["estilo"], slug)
    pacote["_avisos"] = list(r.get("_avisos", []))
    pacote["_creditos"] = [f"Texto bíblico: {biblia.TRADUCAO}"]  # sem imagem de IA: os créditos das fotos entram na montagem
    return pacote


def roteiro_generico(nicho: str, formato_nome: str, tema: str, slug: str, log=print) -> dict:
    """Outros nichos (e temas livres): roteirista guiado + juiz, no formato que o produzir.py entende."""
    import servico_pipeline as sp
    r = sp._roteiro_generico({"nicho": nicho, "formato_nome": formato_nome, "tema_livre": tema},
                             lambda etapa, msg: log(msg or etapa))
    if r.get("_avisos"):
        log(f"o juiz não aprovou nenhuma das tentativas: vai a melhor versão, com {len(r['_avisos'])} aviso(s) na revisão")
    epoca = "moderna" if nicho != "gospel" or "parábola" in formato_nome.lower() or "parabola" in formato_nome.lower() else "biblica"
    return {"slug": slug, "nicho": sp.PRESET_DO_NICHO.get(nicho, "curiosidades"), "titulo": r["titulo"], "epoca": epoca,
            "cenas": [{"fala": c["fala"], "busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
            "descricao": r["descricao"], "hashtags": r["hashtags"], "comentario_fixado": r["comentario_fixado"],
            "_avisos": [f"juiz: {a}" for a in r.get("_avisos", [])]}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nicho")
    ap.add_argument("formato", help="id do formato (gospel) ou nome do formato")
    ap.add_argument("tema", help="id do tema do catálogo (gospel) ou o tema livre")
    ap.add_argument("--musica", choices=["com", "sem"], default="sem")
    a = ap.parse_args()
    if a.nicho == "gospel":
        r = roteiro_biblico(a.formato, a.tema)
    else:
        r = roteiro_generico(a.nicho, a.formato, a.tema, f"nativo-{date.today():%m%d}-{abs(hash(a.tema)) % 10**6}")
    curar(r)
    for v in montar(r, caminhos.PRODUCAO / "nativo" / r["slug"], a.musica):
        print(f"PRONTO {v}")


if __name__ == "__main__":
    main()
