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
import medidor  # noqa: E402  (custo e uso por etapa)
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
LIMIAR_BANCO = 0.70  # reuso do banco; 0.55 (padrão do serviço) trouxe cena de outra história (rodada 04 da noite)
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

def roteiro_validado(formato: dict, tema: dict, reg: Registro, correcoes: list[str] | None = None,
                     anterior: dict | None = None) -> dict | None:
    """correcoes/anterior: começa já reescrevendo (a série manda de volta a parte que o juiz da série apontou)."""
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
        "tiktok_titulo": r.get("tiktok_titulo", ""),
        "tiktok_legenda": r.get("tiktok_legenda", ""),
        "fontes": [f"{tema['ref']} ({biblia.TRADUCAO})"],
        "ganchos": r["ganchos"],
        "gancho_tela": r.get("gancho_tela", ""),
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


def do_banco(r: dict, pasta: Path, faltando: list[int]) -> dict[int, int]:
    """Antes de gerar: cena que já tem imagem aprovada parecida no banco (mesmo nicho e estilo) reusa ela.
    Devolve {cena: id no banco}. O banco nunca derruba o vídeo."""
    achadas: dict[int, int] = {}
    try:
        import banco_imagens
        pasta.mkdir(parents=True, exist_ok=True)
        import hashlib
        # imagem que já está neste vídeo não volta do banco (senão a mesma imagem aparece em duas cenas)
        no_video = {hashlib.sha1(a.read_bytes()).hexdigest()[:20] for a in pasta.glob("cena_*.*")}
        pers = {p["id"]: p for p in r.get("personagens", [])}
        # a imagem do banco também tem que ser genérica (sem personagem): uma cena de multidão do Zaqueu recebia
        # Jesus e Bartimeu (nota 0,84)
        genericas = {i["id"] for i in banco_imagens.listar(r["nicho"]) if not i["personagens"]}
        for n in faltando:
            c = r["cenas"][n - 1]
            if c.get("personagens"):
                # cena com personagem é narrativa: a busca por significado trazia cena de OUTRA história com o mesmo
                # personagem (Jesus da tempestade no Bartimeu, nota 0,78). Só paisagem, objeto e chamada se reusam.
                continue
            # quem aparece vem do roteiro (a fala nem sempre cita o nome: "ele dormiu")
            nomes = " ".join(pers[i]["nome"] for i in c.get("personagens", []) if i in pers)
            # fala + o que a imagem mostra: só a fala ("Jesus respondeu") casava com qualquer cena de Jesus
            texto = " | ".join(x for x in (f"{c['fala']} ({nomes})" if nomes else c["fala"], c.get("imagem", "")) if x)
            a = next((a for a in banco_imagens.buscar(r["nicho"], texto, excluir=set(achadas.values()),
                                                        estilo=r["estilo"])
                      if a["nota"] >= LIMIAR_BANCO and a["id"] in genericas
                      and hashlib.sha1(a["arquivo"].read_bytes()).hexdigest()[:20] not in no_video), None)
            if a:
                shutil.copy(a["arquivo"], pasta / f"cena_{n:02d}{a['arquivo'].suffix}")
                achadas[n] = a["id"]
                log(f"  cena {n} veio do banco (nota {a['nota']:.2f}): {a['descricao'][:70]}")
    except Exception as e:
        log(f"  banco de imagens indisponível: {e}")
    return achadas


def alimentar_banco(r: dict, pasta: Path, do_banco_ids: dict[int, int], reprovadas: set[int]) -> None:
    """Depois do juiz: marca o uso das que vieram do banco e guarda as novas aprovadas."""
    try:
        import banco_imagens
        banco_imagens.marcar_uso(list(do_banco_ids.values()))
        novas = 0
        for n, c in enumerate(r["cenas"], 1):
            if n in do_banco_ids or n in reprovadas:
                continue
            img = validar.imagem_da_cena(pasta, n)
            desc = " | ".join(x for x in (c["fala"], c.get("imagem", "")) if x)
            if img and banco_imagens.adicionar(img, r["nicho"], desc, c.get("personagens"), r["estilo"], "ia-time",
                                               "Imagem gerada por IA", True, "time"):
                novas += 1
        log(f"  banco: {len(do_banco_ids)} reusadas, {novas} novas guardadas")
    except Exception as e:
        log(f"  banco de imagens indisponível: {e}")


def _hash_cena(pasta: Path, n: int) -> str | None:
    import hashlib
    arq = validar.imagem_da_cena(pasta, n)
    return hashlib.sha1(arq.read_bytes()).hexdigest() if arq else None


def _aprovadas(pasta: Path) -> dict:
    arq = pasta / "aprovadas.json"
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}


def _marcar_aprovadas(pasta: Path, cenas: list[int]) -> None:
    """Guarda o hash de cada imagem aprovada pelo juiz (retomada não julga de novo o mesmo arquivo)."""
    ap = _aprovadas(pasta)
    ap.update({str(n): _hash_cena(pasta, n) for n in cenas})
    (pasta / "aprovadas.json").write_text(json.dumps(ap, indent=1), encoding="utf-8")


def imagens_validadas(r: dict, arq_roteiro: Path, reg: Registro) -> None:
    pasta = PROD / "midia" / r["slug"]
    faltando = [i for i in range(1, len(r["cenas"]) + 1) if not any(pasta.glob(f"cena_{i:02d}.*"))]
    reusadas = do_banco(r, pasta, faltando) if faltando else {}
    faltando = [i for i in faltando if i not in reusadas]
    proc = provedores.garantir_comfy()
    try:
        if faltando:
            log(f"imagens: gerando {len(faltando)} cenas ({provedores.modo()}) (estilo {r['estilo']})")
            # banco=False: a consulta com filtro já foi feita em do_banco(); a do provedor reusava cena de outra
            # história (Zaqueu na árvore no ladrão na cruz, nota 0,90)
            provedores.gerar_cenas(r, r["estilo"], pasta, so=faltando, banco=False)
        # cena já aprovada (mesmo arquivo, pelo hash) não volta ao juiz: o juiz não é determinístico e trocava o veredito
        aprovadas = _aprovadas(pasta)
        pendentes = [n for n in range(1, len(r["cenas"]) + 1) if aprovadas.get(str(n)) != _hash_cena(pasta, n)]
        log(f"camada 3: juiz visual ({len(pendentes)} cenas; {len(r['cenas']) - len(pendentes)} já aprovadas antes)")
        ruins = validar.camada3(r, pasta, r["epoca"], so=pendentes) if pendentes else []
        reg.add("camada3", not ruins, rodada=1, reprovadas=ruins)
        _marcar_aprovadas(pasta, [n for n in pendentes if n not in {c["cena"] for c in ruins}])
        for c in ruins:
            guardar_reprovada(r, validar.imagem_da_cena(pasta, c["cena"]), c)
            log(f"  cena {c['cena']} reprovada: {c['problema']}")
        # refação sequencial: UMA opção por vez; o juiz analisa antes da próxima existir, e o prompt corrigido
        # por ele entra na tentativa seguinte (antes: 3 opções de uma vez, e em 7 de 8 casos 1-2 eram desperdício)
        maximo = OPCOES_POR_CENA * MAX_REFACAO_IMAGEM
        ainda = []
        for c in ruins:
            n, v = c["cena"], c
            for tentativa in range(1, maximo + 1):
                if v["imagem_corrigida"].strip():
                    r["cenas"][n - 1]["imagem"] = v["imagem_corrigida"].strip()
                    arq_roteiro.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
                log(f"refação cena {n}: tentativa {tentativa}/{maximo}")
                opcao = provedores.gerar_opcoes(r, r["estilo"], pasta, n, 1)[0]
                v = validar.julgar_imagem(r, n, opcao, r["epoca"])
                if v["ok"]:
                    for velho in pasta.glob(f"cena_{n:02d}.*"):
                        velho.unlink()
                    shutil.move(opcao, pasta / f"cena_{n:02d}.png")
                    _marcar_aprovadas(pasta, [n])
                    log(f"  cena {n} aprovada ({opcao.name}, tentativa {tentativa})")
                    break
                guardar_reprovada(r, opcao, v)
                log(f"  cena {n} reprovada: {v['problema']}")
            else:
                ainda.append(v)
        reg.add("camada3", not ainda, rodada=2, reprovadas=ainda)
        ruins = ainda
        shutil.rmtree(pasta / "opcoes", ignore_errors=True)
        if ruins:
            for c in ruins:
                log(f"  cena {c['cena']} reprovada: {c['problema']}")
            log("  AVISO: sobraram imagens reprovadas depois das refações; revise o painel antes de postar")
            r.setdefault("_avisos", []).append(f"imagens reprovadas: {[c['cena'] for c in ruins]}")
        else:
            log("  todas as imagens aprovadas")
        alimentar_banco(r, pasta, reusadas, {c["cena"] for c in ruins})
    finally:
        provedores.derrubar(proc)  # libera a memória da placa pro render


# ---------------------------------------------------------------- etapa 2b: animação (vídeo misto)

def animacao(r: dict, reg: Registro) -> None:
    """Poucas cenas-chave viram clipe do Wan 14B (cena_NN.mp4); o resto segue imagem. MILIONERE_ANIMAR=0 desliga,
    =N anima N cenas. Falha na animação não derruba o vídeo: ele sai só com imagens."""
    import os
    import animar
    qtd = int(os.environ.get("MILIONERE_ANIMAR", animar.QTD_PADRAO))
    if qtd <= 0 or not (imagens.COMFY / "models" / "unet" / animar.ALTO[0]).exists():
        return  # sem o Wan 14B instalado (instalar_comfy.sh --animacao) o vídeo sai só com imagens
    cenas = animar.escolher(r, qtd)
    log(f"animação: cenas {cenas} no Wan 2.2 14B (~5 min cada)")
    inicio = time.time()
    try:
        feitas = animar.animar(r, PROD / "midia" / r["slug"], cenas)
        reg.add("animacao", True, cenas=cenas, feitas=feitas, segundos=round(time.time() - inicio))
        log(f"  animação ok em {time.time() - inicio:.0f}s")
    except Exception as e:  # noqa: BLE001
        reg.add("animacao", False, cenas=cenas, erro=str(e)[:1500])
        log(f"  AVISO: animação falhou, vídeo sai só com imagens: {e}")
        r.setdefault("_avisos", []).append(f"animação falhou: {str(e)[:200]}")


# ---------------------------------------------------------------- etapa 3: vídeo

def produzir(arq_roteiro: Path, musica: str, reg: Registro) -> list[Path]:
    import sincronizar as sync

    # "ambas": monta UMA vez (sem música) e a versão com música é só a mistura do áudio (antes: 2 renders completos)
    extra = {"com": [], "sem": ["--sem-musica"], "ambas": ["--duas-versoes"]}[musica]
    log({"com": "render com música (YouTube)", "sem": "render SEM música (TikTok)",
         "ambas": "render sem música + mistura da versão com música"}[musica])
    proc = subprocess.run([str(PY_MPT), str(Path(__file__).parent / "produzir.py"), str(arq_roteiro), *extra],
                          capture_output=True, text=True)
    saida = proc.stdout + proc.stderr
    avisos = [l for l in saida.splitlines() if l.startswith(("AVISO", "FALHOU"))]
    videos = [Path(l.split("] ", 1)[1].strip()) for l in saida.splitlines() if l.startswith("PRONTO")]
    prontos = []
    if not any(v.exists() for v in videos):
        reg.add("render", False, saida=saida[-3000:])
        log("  FALHOU o render:\n" + saida[-2000:])
    for video in (v for v in videos if v.exists()):
        dur = sync.duracao_audio(video)
        ok = DURACAO_OK[0] <= dur <= DURACAO_OK[1]
        reg.add("camada4", ok, video=str(video), duracao=round(dur, 1), avisos=avisos)
        log(f"  camada 4 ({video.name}): {dur:.1f}s {'ok' if ok else f'FORA de {DURACAO_OK}'}" + (f" | {avisos}" if avisos else ""))
        prontos.append(video)
    painel = next((l.split("] ", 1)[1].split()[0] for l in saida.splitlines() if l.startswith("painel")), None)
    if painel:
        log(f"  painel: {painel}")
    return prontos


# ---------------------------------------------------------------- orquestração

def um_video(formato_id: str, estilo: str | None, tema_id: str | None, musica: str, so_roteiro: bool = False) -> list[Path]:
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

    with medidor.etapa("roteiro"):
        r = roteiro_validado(formato, tema, reg)
    if not r:
        log(f"DESISTI de '{slug}': o roteiro não passou nas validações em {MAX_REESCRITAS} tentativas. Veja {reg.arq}")
        return []
    # (sem roteirista.reescrever_imagens: o roteirista já escreve os prompts com regras_imagem(); era 1 chamada a mais)
    pacote = empacotar(r, formato_id, formato, tema, estilo, slug)
    salvar_fichas(pacote)
    arq = PROD / "roteiros" / f"{date.today():%Y-%m-%d}_{slug}.json"
    arq.parent.mkdir(parents=True, exist_ok=True)  # no painel /canal a produção fica em servico/media/producao (pasta nova)
    arq.write_text(json.dumps([pacote], ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"roteiro aprovado -> {arq.relative_to(RAIZ)}")
    for c in pacote["cenas"]:
        log(f"   «{c['fala']}»")
    if so_roteiro:
        # esteira: o roteiro fica pronto enquanto a GPU faz o vídeo anterior; o tema é reservado já, senão o
        # próximo sorteio (rodando em paralelo) pode pegar o mesmo
        marcar_usado(f"{formato_id}:{tema['id']}")
        log(f"roteiro pronto -> {arq}")
        return []
    return imagens_e_video(arq, musica, reg)


def imagens_e_video(arq: Path, musica: str, reg: Registro | None = None) -> list[Path]:
    r = json.loads(arq.read_text(encoding="utf-8"))[0]
    r["_avisos"] = []  # recalculados nesta rodada (aviso de uma rodada antiga, já corrigido, travava a postagem)
    reg = reg or Registro(r["slug"])
    with medidor.etapa("imagens"):
        imagens_validadas(r, arq, reg)
    arq.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")
    with medidor.etapa("animacao"):
        animacao(r, reg)
    arq.write_text(json.dumps([r], ensure_ascii=False, indent=2), encoding="utf-8")  # _avisos da animação
    with medidor.etapa("render"):
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
    ap.add_argument("--musica", choices=["com", "sem", "ambas"], default="sem",
                    help="um vídeo só (com ou sem música); ambas = monta uma vez e mistura a música numa 2ª cópia")
    ap.add_argument("--retomar", help="roteiro já aprovado: faz só imagens + vídeo")
    ap.add_argument("--so-roteiro", action="store_true", help="para depois do roteiro aprovado (esteira da noite)")
    args = ap.parse_args()
    if not args.formato and not args.retomar:
        args = menu()

    with medidor.medir() as m:
        prontos = _rodar(args)
        salvar_custos(m.resumo(), prontos)


def salvar_custos(resumo: dict, prontos: list[Path]) -> None:
    """Custo e uso da rodada (medidor.py): uma linha no log e um JSON em producao/custos/ para o relatório."""
    pe = resumo["por_etapa"]
    img = sum(e["imagens"] for e in pe.values())
    gpu = sum(i["segundos"] for i in pe.values() if i["imagens"]) if img else 0
    log(f"custo: US$ {resumo['usd']:.2f} (R$ {resumo['brl']:.2f}) | {sum(e['chamadas'] for e in pe.values())} chamadas "
        f"de IA | {img} imagens | " + " | ".join(f"{k} {v['segundos'] / 60:.1f} min" for k, v in pe.items()))
    pasta = PROD / "custos"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = prontos[0].stem if prontos else f"sem-video-{datetime.now():%H%M%S}"
    (pasta / f"{datetime.now():%Y-%m-%d_%H%M}_{nome}.json").write_text(
        json.dumps({**resumo, "videos": [str(p) for p in prontos], "gpu_imagens_s": round(gpu, 1)},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _rodar(args: argparse.Namespace) -> list[Path]:
    inicio = time.time()
    prontos: list[Path] = []
    if args.retomar:
        arq = Path(args.retomar).resolve()
        r = json.loads(arq.read_text(encoding="utf-8"))[0]
        # mesmas linhas do fluxo normal: o painel (monitor.py) acha o tema, a pasta de imagens e as falas
        log(f"=== Retomando | {r['titulo']} | estilo {r['estilo']}")
        log(f"roteiro aprovado -> {arq.relative_to(RAIZ) if arq.is_relative_to(RAIZ) else arq}")
        for c in r["cenas"]:
            log(f"   «{c['fala']}»")
        prontos = imagens_e_video(arq, args.musica)
    else:
        for n in range(args.qtd):
            prontos += um_video(args.formato, args.estilo, args.tema if n == 0 else None, args.musica,
                                getattr(args, "so_roteiro", False))
    log(f"FIM em {(time.time() - inicio) / 60:.1f} min. Vídeos prontos:")
    for p in prontos:
        log(f"  {p}  (+ {p.with_suffix('.txt').name})")
    return prontos


if __name__ == "__main__":
    main()
