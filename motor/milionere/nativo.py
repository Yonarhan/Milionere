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
        "type": "object", "additionalProperties": False, "required": ["cena", "candidato"],
        "properties": {"cena": {"type": "integer"},
                       "candidato": {"type": "integer", "description": "o N do rótulo cena.N; 0 se nenhum serve"}}}}},
}
# museu cataloga Jesus como "Christ": a busca por "Jesus" quase não acha pintura
NOME_NO_MUSEU = {"jesus": "Christ", "maria": "Virgin Mary", "pedro": "Saint Peter", "paulo": "Saint Paul"}


def _presets() -> dict:
    return json.loads((caminhos.DADOS / "presets.json").read_text(encoding="utf-8"))


def termos_de_busca(r: dict) -> None:
    """Preenche `foto` (fotos de acervo) e `arte` (pinturas/NASA) de cada cena a partir da `busca` em inglês."""
    fichas = {p["id"]: p for p in r.get("personagens", [])}
    for c in r["cenas"]:
        busca = (c.get("busca") or "").split("|")[0].strip()
        c.setdefault("foto", busca)
        if r["nicho"] == "gospel":
            nomes = [NOME_NO_MUSEU.get(i, fichas.get(i, {}).get("nome_en") or fichas.get(i, {}).get("nome", ""))
                     for i in c.get("personagens", [])]
            nomes = [n for n in nomes if n]
            # pintura: quem aparece (como o museu chama) + o começo da busca ("Christ Saint Peter stormy sea")
            c.setdefault("arte", " ".join(nomes[:2] + busca.split()[:2]) or busca)
        elif r["nicho"] == "astronomia":
            c.setdefault("arte", busca)


def _arte_primeiro(cands: list[dict], preset: dict, nicho: str) -> list[dict]:
    """No gospel a pintura é o que mostra Jesus e os personagens (vídeo de banco não mostra): as de museu ocupam
    as 3 primeiras vagas da linha da folha, antes das fotos e vídeos genéricos."""
    if nicho != "gospel":
        return cands
    arte = set(preset.get("fontes_arte", []))
    pinturas = curadoria._alternar([c for c in cands if c["ref"].split(":")[0] in arte])
    resto = [c for c in cands if c["ref"].split(":")[0] not in arte]
    return pinturas[:3] + resto[:curadoria.POR_LINHA - min(3, len(pinturas))] + pinturas[3:] + resto[curadoria.POR_LINHA:]


def curar(r: dict, log=print) -> dict:
    """Busca candidatos, monta as folhas e deixa o Claude escolher. Grava `escolha` nas cenas e o
    candidatos.json que o produzir.py usa. Devolve {"escolhidas": n, "sem_escolha": [cenas]}."""
    preset = _presets()[r["nicho"]]
    pasta = caminhos.PRODUCAO / "curadoria" / r["slug"]
    pasta.mkdir(parents=True, exist_ok=True)
    termos_de_busca(r)
    log("buscando fotos e vídeos grátis para cada cena")
    with ThreadPoolExecutor(4) as ex:
        cands = list(ex.map(lambda c: _arte_primeiro(curadoria.candidatos_para(c, preset), preset, r["nicho"]), r["cenas"]))
    cache = {str(i): c for i, c in enumerate(cands, 1)}
    (pasta / "candidatos.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    com_opcao = [i for i, c in enumerate(cands, 1) if c]
    if not com_opcao:
        log("nenhuma fonte achou nada: fica a busca automática do Pexels na montagem")
        return {"escolhidas": 0, "sem_escolha": list(range(1, len(r["cenas"]) + 1))}

    folhas = []
    for k in range(0, len(r["cenas"]), CENAS_POR_FOLHA):
        destino = pasta / f"folha_{k // CENAS_POR_FOLHA + 1}.png"
        curadoria.folha_geral(r["cenas"][k:k + CENAS_POR_FOLHA], cache, destino, inicio=k + 1)
        folhas.append(destino)
    lista = "\n".join(f"{i}. fala: «{c['fala']}» · deveria mostrar: {c.get('imagem') or c.get('busca', '')}"
                      for i, c in enumerate(r["cenas"], 1))
    prompt = (
        f"Abra com a ferramenta Read as {len(folhas)} imagens: {', '.join(str(f) for f in folhas)}.\n"
        "Cada linha de uma folha é uma cena de um vídeo curto vertical (a fala narrada está em amarelo à esquerda). "
        "As miniaturas da linha têm o rótulo 'cena.N' (F = foto ou pintura, V = vídeo).\n\n"
        f"Nicho do vídeo: {r['nicho']}. Para CADA cena, escolha a miniatura que melhor ilustra a fala:\n"
        "- mostra o assunto da fala (o animal, o planeta, o personagem, o lugar), não algo genérico parecido;\n"
        "- nada de texto, logotipo, marca d'água, moldura de quadro ou museu, nem gráfico/infográfico;\n"
        + ("- história bíblica: pintura ou cena de época; nada moderno e nenhum símbolo de outra religião;\n"
           if r["nicho"] == "gospel" else "") +
        "- varie: não escolha a mesma imagem (ou quase igual) para duas cenas;\n"
        "- empate: prefira vídeo (V), que tem movimento;\n"
        "- se nenhuma da linha servir, candidato 0.\n\n"
        f"# O que cada cena precisa\n{lista}\n\nDevolva uma escolha por cena, com o número da cena e o N do rótulo."
    )
    log("escolhendo as imagens (uma chamada ao Claude para o vídeo todo)")
    with medidor.etapa("curadoria"):
        j = llm.chamar(prompt, SCHEMA_ESCOLHA, ler_arquivos_em=pasta, papel="juiz")
    usados, escolhidas = set(), 0
    por_cena = {e["cena"]: e["candidato"] for e in j["escolhas"]}
    for i, c in enumerate(r["cenas"], 1):
        opcoes = cache[str(i)][:curadoria.POR_LINHA]
        n = por_cena.get(i, 0)
        escolha = opcoes[n - 1] if 1 <= n <= len(opcoes) else None
        if escolha and escolha["ref"] in usados:  # a mesma imagem em duas cenas: pega a próxima livre da linha
            escolha = next((o for o in opcoes if o["ref"] not in usados), None)
        if escolha:
            c["escolha"] = [escolha["ref"]]
            usados.add(escolha["ref"])
            escolhidas += 1
    sem = [i for i, c in enumerate(r["cenas"], 1) if not c.get("escolha")]
    log(f"curadoria: {escolhidas} cenas escolhidas" + (f"; sem escolha (busca automática): {sem}" if sem else ""))
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
    pacote["_creditos"] = [f"Texto bíblico: {biblia.TRADUCAO}"]  # sem imagem de IA: os créditos das fotos entram na montagem
    return pacote


def roteiro_generico(nicho: str, formato_nome: str, tema: str, slug: str, log=print) -> dict:
    """Outros nichos (e temas livres): roteirista guiado + juiz, no formato que o produzir.py entende."""
    import servico_pipeline as sp
    r = sp._roteiro_generico({"nicho": nicho, "formato_nome": formato_nome, "tema_livre": tema},
                             lambda etapa, msg: log(msg or etapa))
    if r.get("_avisos"):
        raise RuntimeError("o juiz reprovou o roteiro nas 3 tentativas: " + " | ".join(r["_avisos"][:3]))
    return {"slug": slug, "nicho": sp.PRESET_DO_NICHO.get(nicho, "curiosidades"), "titulo": r["titulo"],
            "cenas": [{"fala": c["fala"], "busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
            "descricao": r["descricao"], "hashtags": r["hashtags"], "comentario_fixado": r["comentario_fixado"]}


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
