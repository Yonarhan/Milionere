"""Teste de regressão do juiz visual: um juiz novo só entra se mantiver a linha de erros do atual.

O gabarito é o juiz atual (Claude, `llm.chamar`) sobre um conjunto fixo de imagens:
  - boas: cenas aprovadas de vídeos entregues;
  - SDXL: o backup do Pedro em SDXL (vários defeitos reais);
  - difíceis: Flux com os prompts que ele mais erra (close de mão, dedo apontando, gente se tocando, multidão).

Uso:
    python regressao_juiz.py montar                          # gera as difíceis e grava o gabarito (usa o juiz atual)
    python regressao_juiz.py rodar --juiz ollama:qwen2.5vl:7b  # compara um juiz com o gabarito
    python regressao_juiz.py rodar --juiz claude             # confere a estabilidade do próprio juiz atual

Regra para aprovar um juiz: pega 100% dos defeitos do gabarito. Reprovar imagem boa custa só tempo de GPU;
deixar passar defeito derruba o vídeo.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagens  # noqa: E402
import validar  # noqa: E402

from caminhos import RAIZ  # noqa: E402

TESTES = Path(__file__).resolve().parent / "testes"
PASTA = RAIZ / "producao" / "midia" / "_regressao_juiz"  # imagens (fora do git, pesadas)
GABARITO = TESTES / "juiz_visual.json"          # rótulos (no git)
ROTEIROS = RAIZ / "producao" / "roteiros"

# prompts que o Flux schnell erra: (fala, personagens, imagem, roteiro de onde vêm as fichas)
DIFICEIS = [
    ("Na hora, Jesus estendeu a mão e segurou Pedro.", ["jesus", "pedro"],
     "extreme close-up of Jesus hand firmly gripping Peter's wrist, pulling him out of stormy water", "pedro-agua"),
    ("Jesus respondeu: Vem!", ["jesus"],
     "medium shot of Jesus pointing his finger straight at the camera, stormy sea behind", "pedro-agua"),
    ("Na hora, Jesus estendeu a mão e segurou Pedro.", ["jesus", "pedro"],
     "Jesus and Peter embracing each other waist-deep in water, hands on each other's backs", "pedro-agua"),
    ("Pedro pediu: se é você, manda eu ir até aí.", ["pedro"],
     "close-up of Peter's hands clasped in prayer, fingers interlocked, inside a wooden boat", "pedro-agua"),
    ("Eles gritaram: É um fantasma!", [],
     "crowd of terrified fishermen in a small boat pointing at a ghostly figure on the water", "pedro-agua"),
    ("Os marinheiros jogaram Jonas, e o mar parou.", ["jonas", "marinheiro"],
     "sailors throwing Jonah overboard, several men gripping his arms and legs", "jonas-peixe"),
    ("Dentro do peixe, Jonas orou, e Deus ouviu.", ["jonas"],
     "Jonah kneeling inside the belly of a giant fish, both hands raised in prayer, fingers spread", "jonas-peixe"),
    ("Jesus respondeu: Vem!", ["jesus"],
     "Jesus reaching his open hand toward the camera, foreshortened palm in the foreground", "pedro-agua"),
]
SEEDS_POR_PROMPT = 3


def _roteiro(slug: str, versao: str | None = None) -> dict:
    arq = f"producao/roteiros/2026-09-23_historia-{slug}.json"
    if versao:  # versão antiga do git (o backup SDXL do Pedro segue a ordem e as falas de antes)
        txt = subprocess.run(["git", "show", f"{versao}:{arq}"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    else:
        txt = (RAIZ / arq).read_text(encoding="utf-8")
    return json.loads(txt)[0]


def _item(origem: str, arq: Path, r: dict, n: int) -> dict:
    c = r["cenas"][n - 1]
    return {"id": f"{origem}_{arq.stem}", "arquivo": arq.name, "fala": c["fala"], "personagens": c["personagens"],
            "fichas": {p["id"]: p["nome"] for p in r["personagens"]}, "epoca": r.get("epoca", "biblica")}


def _como_roteiro(it: dict) -> dict:
    """Monta o mínimo que validar.julgar_imagem espera de um roteiro (1 cena)."""
    return {"cenas": [{"fala": it["fala"], "personagens": it["personagens"]}],
            "personagens": [{"id": k, "nome": v} for k, v in it["fichas"].items()]}


def montar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    itens = []
    for slug in ("pedro-agua", "jonas-peixe"):
        r = _roteiro(slug)
        for n in range(1, len(r["cenas"]) + 1):
            origem = RAIZ / "producao" / "midia" / f"historia-{slug}" / f"cena_{n:02d}.png"
            destino = PASTA / f"boa_{slug}_{n:02d}.png"
            shutil.copy(origem, destino)
            itens.append(_item("boa", destino, r, n))
    antigo = _roteiro("pedro-agua", versao="5912384")
    for origem in sorted((RAIZ / "producao" / "midia" / "historia-pedro-agua_sdxl_backup").glob("cena_*.png")):
        n = int(origem.stem.split("_")[1])
        destino = PASTA / f"sdxl_pedro_{n:02d}.png"
        shutil.copy(origem, destino)
        itens.append(_item("sdxl", destino, antigo, n))

    estilo = imagens.estilos()["cinema_flux"]
    proc = imagens.garantir_comfy()
    try:
        for k, (fala, pers, prompt, slug) in enumerate(DIFICEIS, 1):
            r = _roteiro(slug)
            fichas = {p["id"]: p for p in r["personagens"]}
            cena = {"fala": fala, "personagens": pers, "imagem": prompt}
            positivo = imagens.prompt_cena(cena, fichas, estilo, r.get("cenario_en", ""))
            for s in range(1, SEEDS_POR_PROMPT + 1):
                destino = PASTA / f"dificil_{k:02d}_{s}.png"
                if not destino.exists():
                    inicio = time.time()
                    imagens.gerar(positivo, "", estilo, destino, seed=1000 * k + s)
                    print(f"  difícil {k}.{s} {time.time() - inicio:4.0f}s  {prompt[:60]}")
                itens.append({"id": f"dificil_{destino.stem}", "arquivo": destino.name, "fala": fala, "personagens": pers,
                              "fichas": {p["id"]: p["nome"] for p in r["personagens"]}, "epoca": "biblica",
                              "prompt": prompt})
    finally:
        imagens.derrubar(proc)

    print(f"gabarito: julgando {len(itens)} imagens com o juiz atual (claude)")
    for it, v in zip(itens, _julgar(itens, "claude")):
        it["esperado_ok"], it["motivo"] = v["ok"], v["problema"]
    GABARITO.parent.mkdir(parents=True, exist_ok=True)
    GABARITO.write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8")
    ruins = sum(not it["esperado_ok"] for it in itens)
    print(f"gabarito salvo em {GABARITO}: {len(itens)} imagens, {ruins} com defeito, {len(itens) - ruins} boas")


def _julgar(itens: list[dict], juiz: str) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor
    paralelo = 1 if juiz.startswith("ollama:") else validar.JUIZES_EM_PARALELO

    def um(it):
        try:
            return validar.julgar_imagem(_como_roteiro(it), 1, PASTA / it["arquivo"], it["epoca"], juiz)
        except Exception as e:  # juiz que quebra conta como erro, não derruba o teste
            return {"ok": None, "problema": f"ERRO: {e}"}
    with ThreadPoolExecutor(paralelo) as ex:
        return list(ex.map(um, itens))


def rodar(juiz: str) -> None:
    itens = json.loads(GABARITO.read_text(encoding="utf-8"))
    inicio = time.time()
    vereditos = _julgar(itens, juiz)
    seg = time.time() - inicio
    defeitos = [(it, v) for it, v in zip(itens, vereditos) if not it["esperado_ok"]]
    boas = [(it, v) for it, v in zip(itens, vereditos) if it["esperado_ok"]]
    pegos = sum(v["ok"] is False for _, v in defeitos)
    aprovadas = sum(v["ok"] is True for _, v in boas)
    erros = sum(v["ok"] is None for v in vereditos)
    print(f"\njuiz {juiz}: {seg:.0f}s ({seg / len(itens):.1f}s por imagem)")
    print(f"  defeitos pegos: {pegos}/{len(defeitos)}  <- precisa ser 100%")
    print(f"  boas aprovadas: {aprovadas}/{len(boas)}  (reprovar boa custa só GPU)")
    if erros:
        print(f"  chamadas que falharam: {erros}")
    for it, v in defeitos:
        if v["ok"] is not False:
            print(f"  DEIXOU PASSAR {it['id']}: gabarito diz «{it['motivo']}»")
    for it, v in boas:
        if v["ok"] is False:
            print(f"  reprovou boa  {it['id']}: «{v['problema']}»")
    saida = GABARITO.with_name(f"resultado_{juiz.replace(':', '_').replace('/', '_')}.json")
    saida.write_text(json.dumps([{"id": it["id"], "esperado_ok": it["esperado_ok"], **v} for it, v in zip(itens, vereditos)],
                                ensure_ascii=False, indent=2), encoding="utf-8")
    aprovado = pegos == len(defeitos) and not erros
    print(f"  {'APROVADO' if aprovado else 'REPROVADO'} para substituir o juiz atual")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("montar")
    r = sub.add_parser("rodar")
    r.add_argument("--juiz", required=True)
    args = ap.parse_args()
    montar() if args.cmd == "montar" else rodar(args.juiz)


if __name__ == "__main__":
    main()
