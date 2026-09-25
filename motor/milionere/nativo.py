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
import re
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
        "type": "object", "additionalProperties": False, "required": ["cena", "candidato", "nota", "reserva", "nova_busca"],
        "properties": {"cena": {"type": "integer"},
                       "candidato": {"type": "integer", "description": "o N do rótulo cena.N; 0 se nenhum serve de verdade"},
                       "nota": {"type": "integer", "minimum": 0, "maximum": 3,
                                "description": "o quanto o escolhido mostra a fala: 3 = a ação/coisa exata, 2 = o assunto "
                                               "certo, 1 = só o mesmo tema, 0 = nada a ver"},
                       "reserva": {"type": "integer", "description": "outro N que também mostra a fala (nota 2 ou 3), "
                                   "para a 2ª tomada de uma fala longa; 0 se não há"},
                       "nova_busca": {"type": "string", "description": "se nota < 2: 2 ou 3 buscas em inglês separadas "
                                      "por |, cada uma com 2 a 4 palavras concretas mostrando a AÇÃO da fala; senão vazio"}}}}},
}
# nota mínima para aceitar a imagem sem tentar outra busca (2 = mostra o assunto da fala; 1 = só o tema)
NOTA_ACEITA = 2
# museu cataloga Jesus como "Christ": a busca por "Jesus" quase não acha pintura
NOME_NO_MUSEU = {"jesus": "Christ", "maria": "Virgin Mary", "pedro": "Saint Peter", "paulo": "Saint Paul"}
# desenho e ilustração no meio de foto real deixam o vídeo com cara de colagem (o 1º vídeo nativo pegou um cartum)
NAO_REALISTA = ["cartoon", "comic", "illustration", "vector", "clipart", "clip art", "drawing", "sketch", "anime",
                "3d render", "3d model", "icon", "logo", "infographic", "emoji", "mascot",
                "subscribe", "like button", "bell icon"]  # o fim do vídeo já tem o cartão INSCREVA-SE
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
        buscas = [b.strip() for b in (c.get("busca") or "").split("|") if b.strip()]
        busca = buscas[0] if buscas else ""
        c.setdefault("foto", "|".join(buscas[:2]))  # as 2 primeiras: mais candidatos que mostram a ação da fala
        if biblico:
            nomes = [NOME_NO_MUSEU.get(i, fichas.get(i, {}).get("nome_en") or fichas.get(i, {}).get("nome", ""))
                     for i in c.get("personagens", [])]
            nomes = [n for n in nomes if n]
            # pintura: quem aparece (como o museu chama) + o começo da busca ("Christ Saint Peter stormy sea")
            c.setdefault("arte", " ".join(nomes[:2] + busca.split()[:2]) or busca)
        elif r["nicho"] == "astronomia":
            c.setdefault("arte", "|".join(buscas[:2]))


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


def _titulo(c: dict) -> str:
    """O título do candidato para o escolhedor ler: o da NASA diz "Mars' Ancient Ocean", coisa que a miniatura
    pequena (ou preta, em vídeo sem prévia) não mostra. Slug do Pexels vira texto ("waves-crashing-123" -> "waves
    crashing")."""
    t = re.sub(r"[-_]+", " ", c.get("desc") or "")
    t = re.sub(r"\s+\d{4,}\s*$", "", t).strip()
    return f"{t[:70]} ({c['ref'].split(':')[0]})" if t else c["ref"].split(":")[0]


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
                      f"{r['cenas'][i - 1].get('imagem') or r['cenas'][i - 1].get('busca', '')}\n"
                      + "\n".join(f"   {i}.{j} {_titulo(x)}" for j, x in enumerate(cache.get(str(i), [])[:curadoria.POR_LINHA], 1))
                      for i in cenas)
    biblico = r["nicho"] == "gospel" and r.get("epoca", "biblica") == "biblica"
    prompt = (
        f"Abra com a ferramenta Read as {len(folhas)} imagens: {', '.join(str(f) for f in folhas)}.\n"
        "Cada linha de uma folha é uma cena de um vídeo curto vertical (a fala narrada está em amarelo à esquerda). "
        "As miniaturas da linha têm o rótulo 'cena.N' (F = foto ou pintura, V = vídeo). Abaixo, cada cena lista o "
        "título de cada candidato: use a miniatura E o título juntos (título da NASA/ESA costuma dizer exatamente o "
        "que o vídeo mostra). Miniatura preta = vídeo sem prévia: só escolha se o título mostrar a fala.\n"
        "A cena 1 é o gancho: ela precisa da imagem mais forte e mais exata do vídeo.\n\n"
        "Para CADA cena, escolha a miniatura que mostra O QUE A FALA DIZ. Quem assiste precisa ver na imagem a ação "
        "ou a coisa narrada naquele segundo; imagem só 'do mesmo tema' deixa o vídeo desconexo.\n"
        "- o assunto certo: o animal, o planeta, a ação (gritar, pedir desculpa, afundar), o lugar;\n"
        "- o VERBO da fala conta: 'as ondas avançam' pede onda grande avançando sobre a costa (mar calmo = nota 1); "
        "'a cidade seria engolida' pede água invadindo rua (cidade seca = nota 1);\n"
        "- dê a `nota` com honestidade: nota 1 faz o sistema buscar de novo, e isso é melhor que aceitar imagem fraca;\n"
        + ("- história bíblica: pintura da própria história ou cena de época; nada moderno, nenhum símbolo de outra "
           "religião;\n" if biblico else
           "- tudo com cara de FOTO/VÍDEO REAL: nada de desenho, pintura antiga, estátua ou ilustração;\n") +
        "- nada de texto, logotipo, marca d'água, moldura de quadro, gráfico ou infográfico;\n"
        "- o vídeo todo com o mesmo clima visual (não misture estilos);\n"
        "- não use a mesma imagem (ou quase igual) em duas cenas;\n"
        "- empate: prefira vídeo (V), que tem movimento.\n"
        "Escolha sempre a melhor miniatura que houver (candidato 0 só se nenhuma tem nada a ver) e, quando a nota for "
        "menor que 2, escreva em `nova_busca` 2 ou 3 buscas em inglês separadas por |, curtas e concretas, que mostrem "
        "a ação (ex.: 'giant wave hitting coast | tsunami wave city | storm surge flooding street'). "
        "Em `reserva`, outro N que também mostre a fala (serve quando a fala é longa e ganha 2 tomadas).\n\n"
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
    fraca: dict[int, tuple[int, dict]] = {}  # cena -> (nota, candidato) da 1ª rodada, caso a 2ª não ache melhor

    def aplicar(decisoes: dict[int, dict], ultima: bool = False) -> list[tuple[int, str]]:
        """Nota >= NOTA_ACEITA: fica. Abaixo disso: guarda como reserva e pede a 2ª rodada com a busca nova; na
        última rodada fica a de maior nota entre as duas (melhor que a busca automática, que pega o 1º do Pexels)."""
        nonlocal escolhidas
        refazer = []
        for i, e in sorted(decisoes.items()):
            opcoes = cache[str(i)][:curadoria.POR_LINHA]

            def pega(n):  # a mesma imagem em duas cenas não vale
                return opcoes[n - 1] if 1 <= n <= len(opcoes) and opcoes[n - 1]["ref"] not in usados else None

            escolha, nota = pega(e["candidato"]), e.get("nota", NOTA_ACEITA)
            nova = e.get("nova_busca", "").strip()
            if escolha and nota < NOTA_ACEITA and not ultima and nova:
                fraca[i] = (nota, escolha)
                refazer.append((i, nova))
                continue
            if ultima and i in fraca and fraca[i][1]["ref"] not in usados and (not escolha or fraca[i][0] > nota):
                escolha = fraca[i][1]
            if escolha:
                reserva = pega(e.get("reserva", 0))
                refs = [escolha["ref"]] + ([reserva["ref"]] if reserva and reserva["ref"] != escolha["ref"] else [])
                r["cenas"][i - 1]["escolha"] = refs
                usados.update(refs)
                escolhidas += 1
            elif nova and not ultima:
                refazer.append((i, nova))
        return refazer

    refazer = []
    if todas:
        log("escolhendo as imagens (uma chamada ao Claude para o vídeo todo)")
        refazer = aplicar(_escolher(r, todas, cache, pasta, 1))
    if refazer:
        log(f"2ª rodada com buscas novas para as cenas {[i for i, _ in refazer]}")
        for i, termo in refazer:
            c = r["cenas"][i - 1]
            arte = termo if r["nicho"] == "astronomia" else ""  # astronomia: a NASA também entra na busca nova
            novos = _ordenar(curadoria.candidatos_para({**c, "busca": termo, "foto": termo, "arte": arte}, preset), preset, r)
            novos = [x for x in novos if x["ref"] not in usados]
            # a escolha fraca da 1ª rodada continua na lista (no fim), para a montagem achar o arquivo se ela ficar
            guardada = [fraca[i][1]] if i in fraca and all(x["ref"] != fraca[i][1]["ref"] for x in novos) else []
            cache[str(i)] = (novos + guardada) if novos else cache[str(i)]
            c["busca"] = termo.split("|")[0].strip()  # a busca automática da montagem (se sobrar sem escolha)
        aplicar(_escolher(r, [i for i, _ in refazer], cache, pasta, 2), ultima=True)
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
