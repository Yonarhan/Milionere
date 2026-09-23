"""1 comando -> vídeo pronto pra postar (tema -> roteiro validado -> imagens validadas -> vídeo -> .txt do post).

Uso:
    python pipeline.py                                   # menu: formato, estilo, quantidade
    python pipeline.py --formato historia --qtd 2
    python pipeline.py --formato parabola --estilo pixar
    python pipeline.py --formato historia --tema jonas-peixe
    python pipeline.py --retomar producao/roteiros/2026-09-23_historia-jonas-peixe.json   # pula o roteiro

Rode com o Python do motor (.venv-linux), que tem Pillow e imageio-ffmpeg.
Cada etapa grava o que decidiu em producao/validacao/<slug>.json (dá pra auditar por que algo passou ou não).
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import imagens  # noqa: E402
import provedores  # noqa: E402  (ComfyUI | Gemini | manual, conforme MILIONERE_IMAGEM/PLANO)
import roteirista  # noqa: E402
import validar  # noqa: E402

from caminhos import DADOS as SKILL  # noqa: E402  (presets, formatos, estilos, bíblia, referências)
from caminhos import RAIZ  # noqa: E402
from caminhos import PRODUCAO as PROD  # noqa: E402
USADOS = PROD / "usados.json"
from caminhos import PYTHON_MOTOR as PY_MPT  # noqa: E402
MAX_REESCRITAS = 4
MAX_REFACAO_IMAGEM = 2
OPCOES_POR_CENA = 3
DURACAO_OK = (15.0, 58.0)


def carregar(nome: str) -> dict:
    return {k: v for k, v in json.loads((SKILL / nome).read_text(encoding="utf-8")).items() if not k.startswith("_")}


def usados() -> set[str]:
    return set(json.loads(USADOS.read_text(encoding="utf-8"))) if USADOS.exists() else set()


def marcar_usado(chave: str) -> None:
    USADOS.write_text(json.dumps(sorted(usados() | {chave}), ensure_ascii=False, indent=2), encoding="utf-8")


class Registro:
    """Diário de validação de um vídeo: tudo que cada camada disse."""

    def __init__(self, slug: str):
        self.arq = PROD / "validacao" / f"{slug}.json"
        self.arq.parent.mkdir(parents=True, exist_ok=True)
        self.dados = json.loads(self.arq.read_text(encoding="utf-8")) if self.arq.exists() else {"etapas": []}

    def add(self, etapa: str, ok: bool, **info) -> None:
        self.dados["etapas"].append({"quando": f"{datetime.now():%H:%M:%S}", "etapa": etapa, "ok": ok, **info})
        self.arq.write_text(json.dumps(self.dados, ensure_ascii=False, indent=2), encoding="utf-8")


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- etapa 1: roteiro

def roteiro_validado(formato: dict, tema: dict, reg: Registro) -> dict | None:
    correcoes, anterior = None, None
    melhor = None  # (pontos, roteiro, problemas)
    historico: list[str] = []  # erros de fato/compreensão já apontados: a reescrita não pode voltar a cometê-los
    for tentativa in range(1, MAX_REESCRITAS + 1):
        log(f"roteiro: tentativa {tentativa} (claude -p)")
        r = roteirista.escrever(formato, tema, correcoes, anterior)
        falas = [c["fala"] for c in r["cenas"]]
        e1 = validar.camada1(r, formato, tema)
        reg.add("camada1", not e1, tentativa=tentativa, problemas=e1, falas=falas)
        if e1:
            log(f"  camada 1 reprovou ({len(e1)}): " + " | ".join(e1[:4]))
            correcoes, anterior = e1 + historico, r
            continue
        log("  camada 1 ok. camada 2: juiz independente")
        e2, juiz = validar.camada2(r, formato, tema)
        notas = {c["criterio"]: c["nota"] for c in juiz["criterios"]}
        reg.add("camada2", not e2, tentativa=tentativa, notas=notas, entendimento=juiz["entendimento"],
                erros_factuais=juiz["erros_factuais"], problemas=e2)
        log(f"  notas do juiz: {notas}")
        log(f"  o juiz entendeu: {juiz['entendimento']}")
        if e2:
            log(f"  camada 2 reprovou ({len(e2)}): " + " | ".join(e2[:4]))
            pontos = sum(notas.values()) - 5 * len(juiz["erros_factuais"])
            if melhor is None or pontos >= melhor[0]:
                melhor = (pontos, r, e2)
            # reescreve a partir da MELHOR versão até agora (uma reescrita ruim não vira base da próxima)
            correcoes, anterior = melhor[2] + historico, melhor[1]
            historico += [p for p in e2 if p.startswith("ERRO FACTUAL") or "compreensao" in p]
            continue
        r["_notas_juiz"] = notas
        return r
    return None


def empacotar(r: dict, formato_id: str, formato: dict, tema: dict, estilo: str, slug: str) -> dict:
    """Converte a saída do roteirista no formato que o produzir.py entende (mais os campos do pipeline)."""
    for p in r["personagens"]:
        if formato["epoca"] != "biblica":
            p["id_retrato"] = f"{slug}__{p['id']}"
    return {
        "slug": slug,
        "nicho": formato["nicho"],
        "formato": formato_id,
        "tema": tema["id"],
        "estilo": estilo,
        "epoca": formato["epoca"],
        "titulo": r["titulo"],
        "cenario_en": r["cenario_en"],
        "personagens": r["personagens"],
        "eventos": r["eventos"],
        "versiculo": r["versiculo"],
        "cenas": r["cenas"],
        "descricao": r["descricao"],
        "hashtags": r["hashtags"],
        "comentario_fixado": r["comentario_fixado"],
        "fontes": [f"{tema['ref']} ({biblia.TRADUCAO})"],
        "ganchos": r["ganchos"],
        "notas": {"roteirista": r["autoavaliacao"], "juiz": r.get("_notas_juiz", {})},
        "_creditos": [f"Imagens geradas por IA ({imagens.estilos()[estilo].get('modelo_credito', 'Stable Diffusion XL')})",
                      f"Texto bíblico: {biblia.TRADUCAO}"],
        "ajustes": {"voice_rate": 1.05},
    }


def salvar_fichas(r: dict) -> None:
    """Personagem bíblico novo vira ficha fixa: o próximo vídeo com ele usa a mesma cara."""
    if r["epoca"] != "biblica":
        return
    arq = biblia.ARQ_PERSONAGENS
    fichas = biblia.personagens()
    for p in r["personagens"]:
        fichas.setdefault(p["id"], {"nome": p["nome"], "nome_en": p["nome_en"], "descricao_visual": p["descricao_visual"]})
    arq.write_text(json.dumps(fichas, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- etapa 2: imagens

REPROVADAS = PROD / "midia" / "_reprovadas"  # alimentam o teste de regressão do juiz (regressao_juiz.py)


def guardar_reprovada(r: dict, arq: Path, veredito: dict) -> None:
    REPROVADAS.mkdir(parents=True, exist_ok=True)
    n = veredito["cena"]
    destino = REPROVADAS / f"{r['slug']}_cena{n:02d}_{datetime.now():%H%M%S%f}{arq.suffix}"
    shutil.copy(arq, destino)
    c = r["cenas"][n - 1]
    with open(REPROVADAS / "reprovadas.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"arquivo": destino.name, "fala": c["fala"], "personagens": c["personagens"],
                            "fichas": {p["id"]: p["nome"] for p in r["personagens"]}, "epoca": r["epoca"],
                            "prompt": c["imagem"], "motivo": veredito["problema"]}, ensure_ascii=False) + "\n")


def imagens_validadas(r: dict, arq_roteiro: Path, reg: Registro) -> None:
    pasta = PROD / "midia" / r["slug"]
    faltando = [i for i in range(1, len(r["cenas"]) + 1) if not any(pasta.glob(f"cena_{i:02d}.*"))]
    proc = provedores.garantir_comfy()
    try:
        if faltando:
            log(f"imagens: gerando {len(faltando)} cenas ({provedores.modo()}) (estilo {r['estilo']})")
            provedores.gerar_cenas(r, r["estilo"], pasta, so=faltando)
        log("camada 3: juiz visual (todas as cenas, uma por vez)")
        ruins = validar.camada3(r, pasta, r["epoca"])
        reg.add("camada3", not ruins, rodada=1, reprovadas=ruins)
        for c in ruins:
            guardar_reprovada(r, next(iter(sorted(pasta.glob(f"cena_{c['cena']:02d}.*")))), c)
        # cena aprovada fica travada; só as reprovadas voltam, com OPCOES_POR_CENA tentativas por rodada
        for rodada in range(1, MAX_REFACAO_IMAGEM + 1):
            if not ruins:
                break
            for c in ruins:
                log(f"  cena {c['cena']} reprovada: {c['problema']}")
                if c["imagem_corrigida"].strip():
                    r["cenas"][c["cena"] - 1]["imagem"] = c["imagem_corrigida"].strip()
            arq_roteiro.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"refação {rodada}: {OPCOES_POR_CENA} opções para as cenas {[c['cena'] for c in ruins]}")
            ainda = []
            for c in ruins:
                n = c["cena"]
                opcoes = provedores.gerar_opcoes(r, r["estilo"], pasta, n, OPCOES_POR_CENA)
                vereditos = validar.julgar_varias(r, [(n, o) for o in opcoes], r["epoca"])
                boa = next((o for o, v in zip(opcoes, vereditos) if v["ok"]), None)
                for o, v in zip(opcoes, vereditos):
                    if not v["ok"]:
                        guardar_reprovada(r, o, v)
                if boa:
                    for velho in pasta.glob(f"cena_{n:02d}.*"):
                        velho.unlink()
                    shutil.move(boa, pasta / f"cena_{n:02d}.png")
                    log(f"  cena {n} aprovada ({boa.name})")
                else:
                    ainda.append(vereditos[-1])
            reg.add("camada3", not ainda, rodada=rodada + 1, reprovadas=ainda)
            ruins = ainda
        shutil.rmtree(pasta / "opcoes", ignore_errors=True)
        if ruins:
            for c in ruins:
                log(f"  cena {c['cena']} reprovada: {c['problema']}")
            log("  AVISO: sobraram imagens reprovadas depois das refações; revise o painel antes de postar")
            r.setdefault("_avisos", []).append(f"imagens reprovadas: {[c['cena'] for c in ruins]}")
        else:
            log("  todas as imagens aprovadas")
    finally:
        provedores.derrubar(proc)  # libera a memória da placa pro render


# ---------------------------------------------------------------- etapa 3: vídeo

def produzir(arq_roteiro: Path, musica: str, reg: Registro) -> list[Path]:
    import sincronizar as sync

    variantes = {"com": [[]], "sem": [["--sem-musica"]], "ambas": [[], ["--sem-musica"]]}[musica]
    prontos = []
    for extra in variantes:
        log(f"render {'SEM música (TikTok)' if extra else 'com música (YouTube)'}")
        proc = subprocess.run([str(PY_MPT), str(Path(__file__).parent / "produzir.py"), str(arq_roteiro), *extra],
                              capture_output=True, text=True)
        saida = proc.stdout + proc.stderr
        avisos = [l for l in saida.splitlines() if l.startswith(("AVISO", "FALHOU"))]
        video = next((Path(l.split("] ", 1)[1].strip()) for l in saida.splitlines() if l.startswith("PRONTO")), None)
        if not video or not video.exists():
            reg.add("render", False, saida=saida[-3000:])
            log("  FALHOU o render:\n" + saida[-2000:])
            continue
        dur = sync.duracao_audio(video)
        ok = DURACAO_OK[0] <= dur <= DURACAO_OK[1]
        reg.add("camada4", ok, video=str(video), duracao=round(dur, 1), avisos=avisos)
        log(f"  camada 4: {dur:.1f}s {'ok' if ok else f'FORA de {DURACAO_OK}'}" + (f" | {avisos}" if avisos else ""))
        painel = next((l.split("] ", 1)[1].split()[0] for l in saida.splitlines() if l.startswith("painel")), None)
        if painel:
            log(f"  painel: {painel}")
        prontos.append(video)
    return prontos


# ---------------------------------------------------------------- orquestração

def um_video(formato_id: str, estilo: str | None, tema_id: str | None, musica: str) -> list[Path]:
    formatos = carregar("formatos.json")
    formato = formatos[formato_id]
    catalogo = biblia.temas()[formato["catalogo"]]
    if tema_id:
        tema = next((t for t in catalogo if t["id"] == tema_id), None)
        if not tema:
            sys.exit(f"tema '{tema_id}' não existe no catálogo '{formato['catalogo']}'")
    else:
        tema = biblia.sortear(formato_id, formato["catalogo"], usados())
    estilo = estilo or formato["estilo"]
    slug = f"{formato_id}-{tema['id']}"
    reg = Registro(slug)
    log(f"=== {formato['nome']} | {tema['titulo']} ({tema['ref']}) | estilo {estilo}")

    r = roteiro_validado(formato, tema, reg)
    if not r:
        log(f"DESISTI de '{slug}': o roteiro não passou nas validações em {MAX_REESCRITAS} tentativas. Veja {reg.arq}")
        return []
    roteirista.reescrever_imagens(r)  # prompts de imagem no formato que o SDXL obedece
    pacote = empacotar(r, formato_id, formato, tema, estilo, slug)
    salvar_fichas(pacote)
    arq = PROD / "roteiros" / f"{date.today():%Y-%m-%d}_{slug}.json"
    arq.write_text(json.dumps([pacote], ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"roteiro aprovado -> {arq.relative_to(RAIZ)}")
    for c in pacote["cenas"]:
        log(f"   «{c['fala']}»")
    return imagens_e_video(arq, musica, reg)


def imagens_e_video(arq: Path, musica: str, reg: Registro | None = None) -> list[Path]:
    r = json.loads(arq.read_text(encoding="utf-8"))[0]
    reg = reg or Registro(r["slug"])
    imagens_validadas(r, arq, reg)
    arq.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
    prontos = produzir(arq, musica, reg)
    if prontos:
        marcar_usado(f"{r['formato']}:{r['tema']}")
    return prontos


def menu() -> argparse.Namespace:
    formatos, estilos = carregar("formatos.json"), carregar("estilos.json")

    def escolher(titulo: str, opcoes: dict, padrao: str) -> str:
        chaves = list(opcoes)
        print(f"\n{titulo}")
        for i, k in enumerate(chaves, 1):
            print(f"  {i}) {opcoes[k]['nome']}{'  (padrão)' if k == padrao else ''}")
        resp = input("> ").strip()
        return chaves[int(resp) - 1] if resp.isdigit() and 0 < int(resp) <= len(chaves) else padrao

    f = escolher("Formato:", formatos, "historia")
    e = escolher("Estilo das imagens:", estilos, formatos[f]["estilo"])
    q = input("\nQuantos vídeos? [1] > ").strip()
    m = input("Música: 1) com e sem (padrão)  2) só com  3) só sem > ").strip()
    return argparse.Namespace(formato=f, estilo=e, qtd=int(q) if q.isdigit() else 1, tema=None,
                              musica={"2": "com", "3": "sem"}.get(m, "ambas"), retomar=None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formato", choices=list(carregar("formatos.json")))
    ap.add_argument("--estilo", choices=list(carregar("estilos.json")))
    ap.add_argument("--tema", help="id do tema em biblia/temas.json (senão sorteia um não usado)")
    ap.add_argument("--qtd", type=int, default=1)
    ap.add_argument("--musica", choices=["com", "sem", "ambas"], default="ambas")
    ap.add_argument("--retomar", help="roteiro já aprovado: faz só imagens + vídeo")
    args = ap.parse_args()
    if not args.formato and not args.retomar:
        args = menu()

    inicio = time.time()
    prontos: list[Path] = []
    if args.retomar:
        prontos = imagens_e_video(Path(args.retomar).resolve(), args.musica)
    else:
        for n in range(args.qtd):
            prontos += um_video(args.formato, args.estilo, args.tema if n == 0 else None, args.musica)
    log(f"FIM em {(time.time() - inicio) / 60:.1f} min. Vídeos prontos:")
    for p in prontos:
        log(f"  {p}  (+ {p.with_suffix('.txt').name})")


if __name__ == "__main__":
    main()
