"""Produção automática do nosso canal: um vídeo por vez, seguindo a meta diária de cada nicho.

Quem roda é o `manage.py produtor` (processo separado do site). O painel /canal só lê e muda o estado.
Gospel com tema do catálogo: pipeline bíblico completo (texto exato da Bíblia, ComfyUI, 4 camadas).
Os outros nichos (e temas livres): roteirista guiado + juiz, imagens do banco/Pexels, mesma montagem do site.
"""

import os
import subprocess
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import jobs
from .models import Canal, Pauta, Producao, Produtor, Serie

NICHOS = ["gospel", "astronomia", "animais"]
MODOS = ("unitario", "serie", "misto")
MAX_FALHAS_DIA = 3  # um nicho que falhou 3 vezes hoje descansa até amanhã (não fica gastando em loop)
# YouTube: volume alto de vídeos parecidos pesa como "produzido em massa" na revisão do YPP (política de conteúdo
# não original, jul/2025). Marcar mais que isso no mesmo dia pede confirmação no painel.
MAX_POSTS_YT_DIA = 2
ATIVOS = [Producao.Status.FILA, Producao.Status.GERANDO]


def _motor():
    sp = jobs._pipeline()  # põe motor/milionere no sys.path
    import biblia
    import pipeline
    return sp, pipeline, biblia


# ------------------------------------------------------------------ pauta

def preparar() -> None:
    """Cria os canais e traz para a pauta os temas do catálogo que ainda não estão lá (idempotente)."""
    sp, pipeline, biblia = _motor()
    for n in NICHOS:
        Canal.objects.get_or_create(nicho=n)
    usados = pipeline.usados()
    repo = settings.BASE_DIR.parent / "producao" / "usados.json"  # o que o time já produziu fora do site
    if repo.exists():
        import json
        usados |= set(json.loads(repo.read_text(encoding="utf-8")))
    formatos = {k: v for k, v in pipeline.carregar("formatos.json").items() if not k.startswith("_")}
    for fid, f in formatos.items():
        for t in biblia.temas().get(f["catalogo"], []):
            titulo = f"{t['titulo']} · {t['ref']}" if t.get("ref") and fid != "personagem" else t["titulo"]
            Pauta.objects.get_or_create(nicho="gospel", formato=fid, titulo=titulo[:200], defaults={
                "formato_nome": f["nome"], "tema_id": t["id"], "prioridade": t.get("prioridade", 1),
                "usado": f"{fid}:{t['id']}" in usados})
    cat = sp.catalogo()
    for n in NICHOS[1:]:
        for fid, f in cat["nichos"][n].get("formatos", {}).items():
            for tid, titulo in f["temas"]:
                Pauta.objects.get_or_create(nicho=n, formato=fid, titulo=titulo[:200], defaults={
                    "formato_nome": f["nome"], "tema_id": tid, "usado": tid in cat["prontos"]})


def formatos_do_nicho(nicho: str) -> dict[str, str]:
    sp, _, _ = _motor()
    return {fid: f["nome"] for fid, f in sp.catalogo()["nichos"][nicho].get("formatos", {}).items() if fid != "sermao"}


def _temas_serie() -> set[str]:
    """Temas do catálogo marcados como bons para série (história longa, várias viradas)."""
    _, _, biblia = _motor()
    return {t["id"] for lista in biblia.temas().values() if isinstance(lista, list) for t in lista if t.get("serie")}


def escolher_pauta(nicho: str, serie: bool = False) -> Pauta | None:
    """O formato com menos vídeos vai primeiro (canal variado); dentro dele, a maior prioridade e o mais antigo.
    Série prefere os temas marcados para série; vídeo único deixa esses temas para as séries (se houver outro)."""
    ocupadas = [*Producao.objects.filter(status__in=ATIVOS).values_list("pauta_id", flat=True),
                *Serie.objects.filter(status__in=ATIVOS).values_list("pauta_id", flat=True)]
    livres = list(Pauta.objects.filter(nicho=nicho, usado=False, falhas__lt=2).exclude(pk__in=ocupadas))
    canal = Canal.objects.filter(nicho=nicho).first()
    if canal and canal.imagens == "nativo":  # mesmos personagens em todas as cenas: banco de fotos não sustenta
        _motor()
        import nativo
        livres = [p for p in livres if p.formato not in nativo.FORMATOS_SO_IA]
    if not livres:
        return None
    longos = _temas_serie()
    if serie:
        melhores = [p for p in livres if p.tema_id in longos]
        livres = melhores or livres
    else:
        livres = [p for p in livres if p.tema_id not in longos] or livres
    feitos = {}
    for fmt in Producao.objects.filter(nicho=nicho).exclude(status=Producao.Status.FALHOU).values_list("formato", flat=True):
        feitos[fmt] = feitos.get(fmt, 0) + 1
    return min(livres, key=lambda p: (feitos.get(p.formato, 0), -p.prioridade, p.criado))


def hoje(nicho: str) -> tuple[int, int]:
    """(vídeos que contam para a meta de hoje, falhas de hoje)."""
    q = Producao.objects.filter(nicho=nicho, criado__date=timezone.localdate())
    feitos = q.exclude(status__in=[Producao.Status.FALHOU, Producao.Status.REPROVADO]).count()
    falhas = q.filter(status=Producao.Status.FALHOU).exclude(mensagem="cancelado por você")
    zeradas = Produtor.get().falhas_zeradas_em
    if zeradas:
        falhas = falhas.filter(criado__gt=zeradas)
    return feitos, falhas.count()


def enfileirar(nicho: str, pauta: Pauta | None = None, serie_max: int = 0, automatica: bool = False) -> Producao | Serie | None:
    """serie_max >= 2: uma série de até serie_max partes; senão, um vídeo único."""
    serie = serie_max >= 2
    pauta = pauta or escolher_pauta(nicho, serie)
    if not pauta:
        return None
    if serie:
        return Serie.objects.create(pauta=pauta, nicho=nicho, formato=pauta.formato, tema=pauta.titulo,
                                    max_partes=min(5, serie_max), automatica=automatica)
    return Producao.objects.create(pauta=pauta, nicho=nicho, formato=pauta.formato, tema=pauta.titulo)


def _vez_da_serie(c: Canal) -> bool:
    if c.modo == "serie":
        return True
    if c.modo != "misto":
        return False
    ultima = Serie.objects.filter(nicho=c.nicho).exclude(status=Producao.Status.FALHOU).order_by("-criado").first()
    unicos = Producao.objects.filter(nicho=c.nicho, serie=None).exclude(status=Producao.Status.FALHOU)
    if ultima:
        unicos = unicos.filter(criado__gt=ultima.criado)
    return unicos.count() >= max(1, c.serie_cada)


def proxima() -> Producao | Serie | None:
    """Pedido manual do painel primeiro (vídeo ou série, o mais antigo); senão, o nicho ativo mais longe da meta de
    hoje (respeitando o descanso), com vídeo único ou série conforme o modo do canal."""
    fila = [x for x in (Producao.objects.filter(status=Producao.Status.FILA, serie=None).order_by("criado").first(),
                        Serie.objects.filter(status=Producao.Status.FILA).order_by("criado").first()) if x]
    if fila:
        return min(fila, key=lambda x: x.criado)
    ultimo = Producao.objects.exclude(terminado=None).order_by("-terminado").first()
    if ultimo and timezone.now() - ultimo.terminado < timedelta(minutes=Produtor.get().intervalo_min):
        return None
    candidatos = []
    for c in Canal.objects.filter(ativo=True):
        feitos, falhas = hoje(c.nicho)
        if falhas < MAX_FALHAS_DIA and feitos < c.meta_dia:
            ult = Producao.objects.filter(nicho=c.nicho).order_by("-criado").values_list("criado", flat=True).first()
            candidatos.append((c.meta_dia - feitos, -(ult.timestamp() if ult else 0), c.nicho))
    for _, _, nicho in sorted(candidatos, reverse=True):
        c = Canal.objects.get(pk=nicho)
        p = enfileirar(nicho, serie_max=c.serie_max, automatica=True) if _vez_da_serie(c) else None
        p = p or enfileirar(nicho)
        if p:
            return p
    return None


# ------------------------------------------------------------------ execução

class _Diario:
    """Guarda o log da produção e mostra a última linha no painel."""

    def __init__(self, prod_id, modelo=Producao):
        self.id, self.linhas, self.modelo = prod_id, [], modelo
        self.avisos: list[str] = []  # o que o juiz apontou e não foi resolvido: aparece no card de revisão

    def __call__(self, msg: str, etapa: str | None = None) -> None:
        msg = (msg or "").strip()
        if msg:
            self.linhas += [f"[{timezone.localtime():%H:%M:%S}] {l}" for l in msg.splitlines()]
        campos = {"log": "\n".join(self.linhas[-500:])}
        if msg:
            campos["mensagem"] = msg.splitlines()[-1][:300]
        if etapa:
            campos["etapa"] = etapa
        self.modelo.objects.filter(pk=self.id).update(**campos)


def _etapa_gospel(msg: str) -> str | None:
    m = msg.lower()
    if m.startswith(("imagens:", "camada 3", "refação", "  cena")):
        return "imagens"
    if m.startswith(("render", "  camada 4")):
        return "montagem"
    return None


class _LogGospel:
    """Enquanto ativo, o log do pipeline bíblico também vai para o diário do painel."""

    def __init__(self, diario: _Diario):
        _, self.pipeline, _ = _motor()
        self.diario = diario

    def __enter__(self):
        self.original = self.pipeline.log

        def log(msg):
            self.original(msg)
            self.diario(msg, _etapa_gospel(msg))
        self.pipeline.log = log

    def __exit__(self, *_):
        self.pipeline.log = self.original


def _gospel(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    _, pipeline, _ = _motor()
    with _LogGospel(diario):
        videos = pipeline.um_video(prod.formato, None, prod.pauta.tema_id, musica)
    if not videos:
        raise RuntimeError("o render não gerou o vídeo (veja o log)")
    try:  # avisos do roteiro e das imagens que o pipeline gravou no roteiro final
        import json

        import caminhos
        arq = sorted((caminhos.PRODUCAO / "roteiros").glob(f"*_{prod.formato}-{prod.pauta.tema_id}.json"))[-1]
        diario.avisos += json.loads(arq.read_text(encoding="utf-8"))[0].get("_avisos", [])
    except Exception:  # noqa: BLE001
        pass
    # as imagens aprovadas já entram no banco dentro do pipeline (pipeline.alimentar_banco)
    return videos


def _generico(prod: Producao, musica: str, diario: _Diario, provedor: str) -> list[Path]:
    sp, _, _ = _motor()
    import caminhos

    log = lambda etapa, msg: diario(msg or etapa, etapa)  # noqa: E731
    pauta = prod.pauta
    r = sp._roteiro_generico({"nicho": prod.nicho, "formato": prod.formato,
                              "formato_nome": pauta.formato_nome if pauta else prod.formato, "tema_livre": prod.tema}, log)
    if r.get("_avisos"):
        diario.avisos += [f"juiz: {a}" for a in r["_avisos"]]
        diario(f"o juiz não aprovou nenhuma das tentativas: segue a melhor versão, com {len(r['_avisos'])} aviso(s)")
    diario("roteiro aprovado:\n" + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]), "roteiro")
    return _video_generico(prod, r, musica, diario, provedor)


def _video_generico(prod: Producao, r: dict, musica: str, diario: _Diario, provedor: str | None = None) -> list[Path]:
    sp, _, _ = _motor()
    log = lambda etapa, msg: diario(msg or etapa, etapa)  # noqa: E731
    entrada = {"nicho": prod.nicho, "formato": prod.formato, "tema_livre": prod.tema, "dono": "canal",
               "cenas": [{"fala": c["fala"], "busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
               "post": {"titulo": r["titulo"], "desc": r["descricao"], "tags": " ".join(r["hashtags"]),
                        "comentario": r["comentario_fixado"], "tiktok_titulo": r.get("tiktok_titulo", ""),
                        "tiktok_legenda": r.get("tiktok_legenda", "")},
               "mus": musica, **({"llm": provedor} if provedor else {})}  # com | sem: um vídeo só
    pasta = Path(settings.MEDIA_ROOT) / "canal" / str(prod.id)
    saida = sp.gerar_video(entrada, pasta, log)
    videos = [Path(v) for v in saida.get("videos") or [saida["video"]]]
    return videos


def _etapa_nativo(msg: str) -> str | None:
    m = msg.lower()
    if m.startswith(("buscando fotos", "escolhendo as imagens", "curadoria")):
        return "imagens"
    if m.startswith("montando"):
        return "montagem"
    return None


def _nativo(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    """Sem gerar imagem: roteiro + fotos, pinturas e vídeos de acervos grátis (curadoria automática) + ffmpeg."""
    _, pipeline, _ = _motor()
    import nativo

    def log(msg):
        diario(msg, _etapa_nativo(msg))
    pauta = prod.pauta
    if prod.formato in nativo.FORMATOS_SO_IA:
        raise RuntimeError("parábola moderna tem os mesmos personagens em todas as cenas: com banco de fotos cada "
                           "cena mostra uma pessoa diferente. Gere esse formato com Imagens: geradas por IA")
    biblico = prod.nicho == "gospel" and pauta and pauta.tema_id and pauta.origem == "catalogo"
    if biblico:
        r = nativo.roteiro_biblico(prod.formato, pauta.tema_id, log)
    else:
        r = nativo.roteiro_generico(prod.nicho, (pauta.formato_nome if pauta else "") or prod.formato, prod.tema,
                                    f"canal-{str(prod.id)[:8]}", log)
    diario("roteiro aprovado:\n" + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]), "imagens")
    diario.avisos += r.get("_avisos", [])
    nativo.curar(r, log)
    videos = nativo.montar(r, Path(settings.MEDIA_ROOT) / "canal" / str(prod.id), musica, log)
    if biblico:  # o tema do catálogo não volta (o pipeline marca isso sozinho só no modo IA)
        pipeline.marcar_usado(f"{prod.formato}:{pauta.tema_id}")
    return videos


ESTILO_POD = {"astronomia": "espaco_zimage"}  # nicho sem estilo aqui usa o do gospel (cinema_zimage)
ANIMAR_POD = 3  # cenas animadas pelo Wan por vídeo (gancho, meio e clímax)


def _ia_pod(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    """Imagens geradas por IA no ComfyUI do pod (MILIONERE_COMFY_URL), como o gospel do Rafael: o roteiro do nicho
    (escritor + juiz), o Z-Image gera cada cena e o Wan 2.2 anima as principais. O resto (voz, legenda, montagem) é
    a montagem de sempre, que prefere cena_NN.mp4 / cena_NN.png da pasta de mídia."""
    _motor()
    import animar
    import imagens
    import nativo

    def log(msg):
        diario(msg, _etapa_nativo(msg))
    if not imagens.REMOTO:
        raise RuntimeError("Imagens 'IA no pod' precisa do MILIONERE_COMFY_URL no .env (endereço do ComfyUI do pod)")
    if not imagens.no_ar():
        raise RuntimeError(f"o pod está desligado ou o ComfyUI não responde ({imagens.URL}): ligue o pod na RunPod")
    pauta = prod.pauta
    r = nativo.roteiro_generico(prod.nicho, (pauta.formato_nome if pauta else "") or prod.formato, prod.tema,
                                f"canal-{str(prod.id)[:8]}", log)
    diario("roteiro aprovado:\n" + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]), "imagens")
    diario.avisos += r.get("_avisos", [])
    estilo = ESTILO_POD.get(prod.nicho, "cinema_zimage")
    r["_movimento"] = imagens.estilos()[estilo].get("movimento_video", animar.MOVIMENTO)
    pasta = imagens.caminhos.PRODUCAO / "midia" / r["slug"]
    pasta.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    diario(f"gerando {len(r['cenas'])} imagens no pod (Z-Image, estilo {estilo})", "imagens")
    imagens.gerar_cenas(r, estilo, pasta)
    diario(f"imagens prontas em {time.time() - inicio:.0f}s", "imagens")
    cenas = animar.escolher(r, ANIMAR_POD)
    try:  # animação é bônus: se falhar, o vídeo sai com as imagens (com zoom)
        diario(f"animando as cenas {cenas} no pod (Wan 2.2)", "imagens")
        inicio = time.time()
        animar.animar(r, pasta, cenas)
        diario(f"animação pronta em {time.time() - inicio:.0f}s", "imagens")
    except Exception as e:  # noqa: BLE001
        diario(f"animação falhou, o vídeo segue só com imagens: {str(e)[:300]}", "imagens")
        diario.avisos.append(f"animação falhou: {str(e)[:200]}")
    return nativo.montar(r, Path(settings.MEDIA_ROOT) / "canal" / str(prod.id), musica, log)


def _url(p: Path) -> str:
    try:
        return settings.MEDIA_URL + p.resolve().relative_to(Path(settings.MEDIA_ROOT).resolve()).as_posix()
    except ValueError:
        return ""


def _titulo(post: str) -> str:
    linhas = [l.strip() for l in post.splitlines()]
    for i, l in enumerate(linhas):
        if l.upper().startswith("TÍTULO") and i + 1 < len(linhas):
            return linhas[i + 1]
    return ""


def _musica(nicho: str) -> str:
    canal = Canal.objects.filter(nicho=nicho).first()
    return canal.musica if canal and canal.musica in ("com", "sem") else "sem"  # um vídeo só


def _resultado(videos: list[Path]) -> dict:
    """Campos da Producao a partir dos vídeos prontos (o .txt do post fica ao lado do vídeo)."""
    videos = sorted(videos, key=lambda p: "_sem-musica" in p.stem)  # com música primeiro
    post = next((p.with_suffix(".txt").read_text(encoding="utf-8") for p in videos if p.with_suffix(".txt").exists()), "")
    return {"post": post, "titulo": _titulo(post)[:200],
            "videos": [{"nome": p.name, "url": _url(p), "variante": "sem" if "_sem-musica" in p.stem else "com"} for p in videos]}


# vozes do Edge TTS que falam português (as "Multilingual" são americanas lendo em pt-BR, com leve sotaque)
VOZES = [
    ("pt-BR-AntonioNeural-Male", "Antonio (masculina)"),
    ("pt-BR-FranciscaNeural-Female", "Francisca (feminina)"),
    ("pt-BR-ThalitaMultilingualNeural-Female", "Thalita (feminina, jovem)"),
    ("en-US-AndrewMultilingualNeural-Male", "Andrew (masculina, sotaque leve)"),
    ("en-US-BrianMultilingualNeural-Male", "Brian (masculina, sotaque leve)"),
    ("en-US-AvaMultilingualNeural-Female", "Ava (feminina, sotaque leve)"),
    ("en-US-EmmaMultilingualNeural-Female", "Emma (feminina, sotaque leve)"),
]
TEXTO_PREVIA = ("Oi! Essa é a voz do canal. Você sabia que um dia em Vênus dura mais do que um ano inteiro? "
                "Se inscreve pra não perder o próximo.")


def previa_voz(nicho: str, voz: str) -> Path:
    """mp3 curto com a voz no tom e na velocidade do nicho (gerado uma vez e guardado em media/vozes)."""
    import asyncio

    import edge_tts
    if voz not in dict(VOZES):
        raise ValueError("voz desconhecida")
    sp, _, _ = _motor()
    preset = sp._preset(nicho)
    tom = str(preset.get("voice_pitch", "") or "+0Hz")
    rate = float(preset.get("voice_rate", 1.0) or 1.0)
    velocidade = f"{round((rate - 1) * 100):+d}%"
    destino = Path(settings.MEDIA_ROOT) / "vozes" / f"{nicho}_{voz}_{tom}_{velocidade}.mp3".replace("%", "p")
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        nome = voz.rsplit("-", 1)[0]  # "pt-BR-AntonioNeural-Male" -> "pt-BR-AntonioNeural"
        asyncio.run(edge_tts.Communicate(TEXTO_PREVIA, nome, rate=velocidade, pitch=tom).save(str(destino)))
    return destino


def _opcoes_video(nicho: str) -> None:
    """As opções do vídeo do nicho viram variáveis de ambiente: o produzir.py (processo filho) lê. Um vídeo por vez,
    então não há dois jobs disputando as variáveis."""
    c = Canal.objects.filter(nicho=nicho).first()
    os.environ["MILIONERE_LEGENDA"] = "" if not c or c.legenda == "padrao" else c.legenda
    os.environ["MILIONERE_EFEITOS"] = "1" if c and c.efeitos else "0"
    os.environ["MILIONERE_VOLUME"] = "1" if c and c.volume else "0"
    os.environ["MILIONERE_VOZ"] = c.voz if c and c.voz else ""


_ATUAL: "Producao | Serie | None" = None  # o que o produtor está gerando agora (o vigia de cancelamento olha)


def executar_qualquer(item: "Producao | Serie") -> None:
    global _ATUAL
    _ATUAL = item
    _opcoes_video(item.nicho)
    (executar_serie if isinstance(item, Serie) else executar)(item)


def executar(prod: Producao) -> None:
    _motor()
    import llm
    import medidor

    canal = Canal.objects.filter(nicho=prod.nicho).first()
    provedor = Produtor.get().llm
    musica = _musica(prod.nicho)
    diario = _Diario(prod.pk)
    Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.GERANDO, etapa="roteiro", iniciado=timezone.now(),
                                               mensagem="começando")
    with medidor.medir() as m, llm.usar_provedor(provedor):
        try:
            biblico = prod.nicho == "gospel" and prod.pauta and prod.pauta.tema_id and prod.pauta.origem == "catalogo"
            if canal and canal.imagens == "nativo":
                videos = _nativo(prod, musica, diario)
            elif canal and canal.imagens == "ia_pod":
                videos = _ia_pod(prod, musica, diario)
            else:
                videos = _gospel(prod, musica, diario) if biblico else _generico(prod, musica, diario, provedor)
            Producao.objects.filter(pk=prod.pk).update(
                status=Producao.Status.REVISAR, etapa="post", avisos=diario.avisos,
                mensagem=f"pronto para revisar · {len(diario.avisos)} aviso(s) do juiz" if diario.avisos else "pronto para revisar",
                terminado=timezone.now(), custos=m.resumo(), **_resultado(videos))
            if prod.pauta_id:
                Pauta.objects.filter(pk=prod.pauta_id).update(usado=True)
        except BaseException as e:  # noqa: BLE001 - SystemExit do pipeline também vira falha legível
            if Producao.objects.filter(pk=prod.pk, cancelar=True).exists():
                diario("CANCELADO no painel")
                Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.FALHOU, mensagem="cancelado por você",
                                                           terminado=timezone.now(), custos=m.resumo())
                return  # cancelado não conta como falha do tema: ele volta na pauta
            if isinstance(e, KeyboardInterrupt):
                Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.FALHOU, erro="produtor interrompido",
                                                           terminado=timezone.now())
                raise
            diario(f"FALHOU: {e}")
            Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.FALHOU, mensagem=str(e)[:300],
                                                       erro=f"{e}\n\n{traceback.format_exc()[-4000:]}",
                                                       terminado=timezone.now(), custos=m.resumo())
            if prod.pauta_id:
                Pauta.objects.filter(pk=prod.pauta_id).update(falhas=prod.pauta.falhas + 1)


# ------------------------------------------------------------------ série (2 a 5 partes)

TEMPO_MAX_JUIZ_SERIE = 8 * 60  # rodadas do juiz da série (com as reescritas): passou, segue com os avisos


def executar_serie(s: Serie) -> None:
    """Plano -> juiz do plano -> roteiro de cada parte (juízes de sempre) -> juiz da série (reescreve só a parte
    apontada) -> imagens e vídeo de cada parte -> juiz visual da série -> revisão como um bloco só."""
    sp, pipeline, biblia = _motor()
    import medidor
    import serie as ms

    musica = _musica(s.nicho)
    diario = _Diario(s.pk, Serie)
    agora = timezone.now
    Serie.objects.filter(pk=s.pk).update(status=Producao.Status.GERANDO, etapa="plano", iniciado=agora(),
                                         mensagem="planejando a série")
    partes: list[Producao] = []
    with medidor.medir() as m:
        try:
            pauta = s.pauta
            biblico = s.nicho == "gospel" and pauta and pauta.tema_id and pauta.origem == "catalogo"
            if biblico:
                formato = pipeline.carregar("formatos.json")[s.formato]
                tema = next(t for t in biblia.temas()[formato["catalogo"]] if t["id"] == pauta.tema_id)
                fonte = tema["ref"] if formato["epoca"] == "biblica" else None
                chave = tema["id"]
            else:
                preset = sp._preset(s.nicho)
                formato = {"nome": (pauta.formato_nome if pauta else "") or s.formato, "receita": "",
                           "palavras": [preset["palavras_min"], preset["palavras_max"]]}
                tema, fonte, chave = {"titulo": s.tema, "angulo": ""}, None, str(s.pk)[:8]
            slug_serie = f"serie-{s.formato}-{chave}"
            avisos_roteiro: list[str] = []  # o que os juízes apontaram e não ficou resolvido (vai para a revisão)
            if biblico:  # história completa primeiro, depois o corte em episódios (motor/milionere/episodios.py)
                import episodios
                with _LogGospel(diario):
                    plano, roteiros = episodios.serie_biblica(s.formato, formato, tema, s.max_partes, slug_serie,
                                                              log=lambda msg: diario(msg, "roteiro"))
                avisos_roteiro += list(dict.fromkeys(a for _, pk in roteiros for a in pk.get("_avisos_juiz", [])))
                N = len(plano["partes"])
                Serie.objects.filter(pk=s.pk).update(plano=plano, titulo=plano["titulo_serie"][:200], etapa="roteiro")
                partes = [Producao.objects.create(serie=s, parte=k, pauta=pauta, nicho=s.nicho, formato=s.formato,
                                                  tema=f"{plano['titulo_serie']} · parte {k}/{N}: {x['titulo']}"[:200],
                                                  status=Producao.Status.GERANDO, iniciado=agora(), etapa="roteiro")
                          for k, x in enumerate(plano["partes"], 1)]
            else:
                plano = ms.planejar(s.nicho, formato, tema, s.max_partes, log=lambda msg: diario(msg, "plano"))
                N = len(plano["partes"])
                Serie.objects.filter(pk=s.pk).update(plano=plano, titulo=plano["titulo_serie"][:200], etapa="roteiro")
                partes = [Producao.objects.create(serie=s, parte=k, pauta=pauta, nicho=s.nicho, formato=s.formato,
                                                  tema=f"{plano['titulo_serie']} · parte {k}/{N}: {x['titulo']}"[:200],
                                                  status=Producao.Status.GERANDO, iniciado=agora(), etapa="roteiro")
                          for k, x in enumerate(plano["partes"], 1)]
                roteiros: list = [None] * N  # gospel: (arquivo, pacote); outros: o roteiro do roteirista genérico

                def falas(k: int) -> list[str]:
                    r = roteiros[k - 1][1] if biblico else roteiros[k - 1]
                    return [c["fala"] for c in r["cenas"]]

                def escrever(k: int, correcoes: list[str] | None = None) -> None:
                    anteriores = [falas(j) for j in range(1, k)]
                    diario(f"parte {k}/{N}: escrevendo" + (" de novo (juiz da série)" if correcoes else ""), "roteiro")
                    if biblico:
                        anterior = roteiros[k - 1][1] if correcoes and roteiros[k - 1] else None
                        with _LogGospel(diario):
                            roteiros[k - 1] = ms.roteiro_gospel(s.formato, tema, plano, k, slug_serie, anteriores, correcoes, anterior)
                    else:
                        x = plano["partes"][k - 1]
                        r = sp._roteiro_generico({"nicho": s.nicho, "formato": s.formato, "formato_nome": formato["nome"],
                                                  "tema_livre": f"{s.tema} (parte {k} de {N}: {x['titulo']})",
                                                  "serie": ms.contexto_parte(plano, k, s.nicho, anteriores, correcoes)},
                                                 lambda etapa, msg: diario(msg or etapa, "roteiro"))
                        if r.get("_avisos"):  # não joga a série fora: segue a melhor versão e o ponto vai para a revisão
                            avisos_roteiro.extend(f"parte {k}: {a}" for a in r["_avisos"][:3])
                        r["titulo"] = ms.titulo_parte(r["titulo"], k, N)
                        if r.get("tiktok_titulo"):
                            r["tiktok_titulo"] = ms.titulo_parte(r["tiktok_titulo"], k, N)
                        roteiros[k - 1] = r
                    diario(f"parte {k}/{N} aprovada:\n" + "\n".join(f"  «{f}»" for f in falas(k)), "roteiro")

                for k in range(1, N + 1):
                    escrever(k)
                comeco_juiz = time.time()
                for rodada in range(ms.RODADAS_SERIE + 1):
                    diario(f"juiz da série: lendo as {N} partes juntas (rodada {rodada + 1})", "roteiro")
                    vistos = [{"falas": falas(k), "personagens": (roteiros[k - 1][1] if biblico else {}).get("personagens", [])}
                              for k in range(1, N + 1)]
                    problemas = ms.julgar_roteiros(plano, vistos, s.nicho, fonte)
                    if not problemas:
                        diario("juiz da série: aprovada", "roteiro")
                        break
                    for k, p in problemas.items():
                        diario(f"  juiz da série, parte {k}: " + " | ".join(p), "roteiro")
                    estourou = time.time() - comeco_juiz > TEMPO_MAX_JUIZ_SERIE
                    if rodada == ms.RODADAS_SERIE or estourou:
                        # antes a série inteira ia fora aqui (27 min de roteiro aprovado parte a parte). O juiz ajuda,
                        # mas não segura o vídeo: segue esta versão e o que ele apontou vai para a revisão.
                        diario("juiz da série não aprovou tudo " + ("(passou do tempo)" if estourou else "depois das reescritas")
                               + ": segue esta versão, os pontos vão para a revisão", "roteiro")
                        avisos_roteiro.extend(f"juiz da série, parte {k}: {p[0]}" for k, p in problemas.items())
                        break
                    for k in sorted(problemas):
                        escrever(k, problemas[k])

            Serie.objects.filter(pk=s.pk).update(etapa="imagens")
            visuais = []
            for k, prod in enumerate(partes, 1):
                diario(f"parte {k}/{N}: imagens e vídeo", "imagens")
                Producao.objects.filter(pk=prod.pk).update(etapa="imagens", mensagem="imagens e vídeo")
                if biblico:
                    arq, pacote = roteiros[k - 1]
                    with _LogGospel(diario):
                        videos = pipeline.imagens_e_video(arq, musica)
                    import json
                    visuais.append((k, json.loads(arq.read_text(encoding="utf-8"))[0], pipeline.PROD / "midia" / pacote["slug"]))
                else:
                    videos = _video_generico(prod, roteiros[k - 1], musica, diario)
                if not videos:
                    raise RuntimeError(f"parte {k}: o render não passou nas validações (veja o log)")
                Producao.objects.filter(pk=prod.pk).update(etapa="post", mensagem="pronta, esperando as outras partes",
                                                           **_resultado(videos))
            avisos = list(avisos_roteiro)
            if visuais and any(r.get("personagens") for _, r, _ in visuais):
                diario("juiz visual da série: o mesmo personagem com a mesma cara em todas as partes", "montagem")
                visual = ms.julgar_visual(visuais, pipeline.PROD / "midia" / "_serie_visual" / slug_serie)
                avisos += visual
                for a in visual:
                    diario(f"  AVISO: {a}")
            fim, custos = agora(), m.resumo()
            por_parte = {k: (round(v / N, 4) if isinstance(v, (int, float)) else v) for k, v in custos.items()}
            Producao.objects.filter(serie=s).update(status=Producao.Status.REVISAR, mensagem="pronta para revisar",
                                                    terminado=fim, custos=por_parte)
            Serie.objects.filter(pk=s.pk).update(status=Producao.Status.REVISAR, etapa="post", terminado=fim, custos=custos,
                                                 avisos=avisos, mensagem=f"{N} partes prontas para revisar"
                                                 + (f" · {len(avisos)} aviso(s)" if avisos else ""))
            if pauta:
                Pauta.objects.filter(pk=pauta.pk).update(usado=True)
            if biblico:
                pipeline.marcar_usado(f"{s.formato}:{chave}")
        except BaseException as e:  # noqa: BLE001 - SystemExit do pipeline também vira falha legível
            curto = isinstance(e, ms.SerieInviavel)
            msg = "produtor interrompido" if isinstance(e, KeyboardInterrupt) else str(e)
            diario(f"FALHOU: {msg}")
            Producao.objects.filter(serie=s).update(status=Producao.Status.FALHOU, mensagem="a série falhou"[:300],
                                                    terminado=timezone.now())
            Serie.objects.filter(pk=s.pk).update(status=Producao.Status.FALHOU, mensagem=msg[:300], terminado=timezone.now(),
                                                 erro=f"{msg}\n\n{traceback.format_exc()[-4000:]}", custos=m.resumo())
            if isinstance(e, KeyboardInterrupt):
                raise
            if curto and s.automatica and s.pauta_id:  # tema curto no automático: vira vídeo único
                enfileirar(s.nicho, s.pauta)
            elif not curto and s.pauta_id:
                Pauta.objects.filter(pk=s.pauta_id).update(falhas=s.pauta.falhas + 1)


# ------------------------------------------------------------------ o processo

def _matar_filhos() -> None:
    """Derruba os processos que o produtor abriu (claude -p, produzir.py, ffmpeg), com os filhos deles. Poupa o
    conhost (o console do próprio produtor): matá-lo fazia todo claude -p seguinte sair na hora sem escrever nada."""
    eu = os.getpid()
    try:
        if os.name == "nt":
            saida = subprocess.run(["powershell", "-NoProfile", "-Command",
                                    f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={eu}' | Where-Object {{ "
                                    f"$_.Name -notin 'conhost.exe','powershell.exe' }}).ProcessId"],
                                   capture_output=True, text=True, timeout=30).stdout.split()
            for pid in saida:
                subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
        else:
            subprocess.run(["pkill", "-TERM", "-P", str(eu)], capture_output=True)
    except Exception:  # noqa: BLE001
        pass


def _vigiar_cancelamento(parar: threading.Event) -> None:
    """A cada 3 s: se o vídeo que está gerando foi cancelado no painel, para as chamadas e mata os filhos."""
    import llm
    while not parar.is_set():
        try:
            atual = _ATUAL
            # série não tem o campo cancelar: o painel a marca como falhou enquanto ela ainda roda aqui
            serie_cancelada = isinstance(atual, Serie) and Serie.objects.filter(
                pk=atual.pk, status=Producao.Status.FALHOU).exists()
            if serie_cancelada or Producao.objects.filter(status=Producao.Status.GERANDO, cancelar=True).exists():
                if not llm.CANCELADO.is_set():
                    llm.CANCELADO.set()
                    _matar_filhos()
        except Exception:  # noqa: BLE001
            pass
        finally:
            close_old_connections()
        parar.wait(3)


def _batimento(parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            Produtor.objects.filter(pk=1).update(batimento=timezone.now())
        except Exception:  # noqa: BLE001 - banco ocupado: tenta no próximo batimento
            pass
        finally:
            close_old_connections()
        parar.wait(20)


def rodar(uma_vez: bool = False, log=print) -> None:
    os.environ["MILIONERE_COMFY_MANTER"] = "1"  # o ComfyUI fica no ar entre um vídeo e outro
    preparar()
    Produtor.get()
    for modelo in (Producao, Serie):  # o produtor anterior caiu no meio: essas não vão terminar sozinhas
        modelo.objects.filter(status=Producao.Status.GERANDO).update(
            status=Producao.Status.FALHOU, mensagem="o produtor foi reiniciado no meio", terminado=timezone.now())
    parar = threading.Event()
    threading.Thread(target=_batimento, args=(parar,), daemon=True).start()
    threading.Thread(target=_vigiar_cancelamento, args=(parar,), daemon=True).start()
    log("produtor no ar: um vídeo por vez, seguindo as metas do painel /canal (Ctrl+C para parar)")
    try:
        while True:
            prod = None if Produtor.get().pausado else proxima()
            if prod:
                import llm
                llm.CANCELADO.clear()
                log(f"{timezone.localtime():%H:%M} gerando: {prod.nicho} · {prod.tema}")
                executar_qualquer(prod)
                llm.CANCELADO.clear()
                prod.refresh_from_db()
                log(f"{timezone.localtime():%H:%M} {prod.status}: {prod.mensagem}")
                if uma_vez:
                    return
                continue
            if uma_vez:
                log("nada para gerar agora (metas cumpridas, pausado ou em descanso)")
                return
            for _ in range(10):  # espera 30 s, mas acorda em até 3 s se pedirem um vídeo no painel ("iniciar agora")
                time.sleep(3)
                if not Produtor.get().pausado and (Producao.objects.filter(status=Producao.Status.FILA, serie=None).exists()
                                                   or Serie.objects.filter(status=Producao.Status.FILA).exists()):
                    break
    finally:
        parar.set()
        try:
            _motor()
            import provedores
            provedores.encerrar()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ painel

def iniciar_agora(item_id) -> str:
    """Passa o pedido da fila para a frente de todos e liga o produtor se estiver parado. O produtor faz um vídeo por
    vez: se já tem um gerando, este é o próximo, sem descanso entre os dois."""
    item = (Producao.objects.filter(pk=item_id, status=Producao.Status.FILA).first()
            or Serie.objects.filter(pk=item_id, status=Producao.Status.FILA).first())
    if not item:
        return "Esse vídeo não está mais na fila."
    primeiros = [x for x in (Producao.objects.filter(status=Producao.Status.FILA).order_by("criado").first(),
                             Serie.objects.filter(status=Producao.Status.FILA).order_by("criado").first()) if x]
    frente = min(x.criado for x in primeiros)
    type(item).objects.filter(pk=item.pk).update(criado=frente - timedelta(seconds=1))
    if not vivo():
        ligar_produtor()
        return "Ligando o produtor: começa em alguns segundos"
    if Produtor.get().pausado:
        return "Está na frente da fila, mas o produtor está pausado: despause para começar"
    if Producao.objects.filter(status=Producao.Status.GERANDO).exists() or Serie.objects.filter(status=Producao.Status.GERANDO).exists():
        return "Já tem um vídeo gerando: este é o próximo, logo em seguida"
    return "Começando em alguns segundos"

def vivo() -> bool:
    p = Produtor.get()
    return bool(p.batimento and timezone.now() - p.batimento < timedelta(seconds=75))


def ligar_produtor() -> bool:
    """Sobe o `manage.py produtor` como processo separado (continua rodando mesmo se o site reiniciar).
    O que ele escreve vai para media/produtor.log."""
    import sys
    if vivo():
        return False
    log = open(Path(settings.MEDIA_ROOT) / "produtor.log", "a", encoding="utf-8")
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    subprocess.Popen([sys.executable, str(settings.BASE_DIR / "manage.py"), "produtor"], cwd=settings.BASE_DIR,
                     stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}, **extra)
    Produtor.objects.filter(pk=1).update(batimento=timezone.now())  # evita dois cliques subirem dois produtores
    return True


def sugerir(nicho: str, n: int = 10) -> int:
    """A IA propõe temas novos para a pauta, sem repetir o que já temos."""
    _motor()
    import llm

    formatos = formatos_do_nicho(nicho)
    existentes = list(Pauta.objects.filter(nicho=nicho).values_list("titulo", flat=True))
    prompt = (
        f"Você monta a pauta de um canal de Shorts/TikTok em português do Brasil, nicho **{nicho}**.\n"
        f"Sugira {n} temas NOVOS, distribuídos entre estes formatos (id: nome): "
        + "; ".join(f"{k}: {v}" for k, v in formatos.items()) + ".\n"
        "Regras: o fato central tem que ser verdadeiro e verificável; curiosidade forte que faz parar de rolar o feed; "
        "título curto (até 60 caracteres), no mesmo tom dos que já temos; nada repetido nem parecido com a lista abaixo.\n"
        + ("No gospel, só histórias e personagens que estão de fato na Bíblia, com a referência no título "
           "(ex.: 'O homem que subiu na árvore · Lucas 19:1-10').\n" if nicho == "gospel" else "")
        + "\n# Já temos\n" + "\n".join(f"- {t}" for t in existentes))
    schema = {"type": "object", "additionalProperties": False, "required": ["temas"], "properties": {"temas": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["formato", "titulo"],
                                   "properties": {"formato": {"type": "string", "enum": list(formatos)},
                                                  "titulo": {"type": "string"}}}}}}
    novos = 0
    with llm.usar_provedor(Produtor.get().llm):
        temas = llm.chamar(prompt, schema, papel="juiz")["temas"]
    for t in temas:
        _, criado = Pauta.objects.get_or_create(nicho=nicho, formato=t["formato"], titulo=t["titulo"].strip()[:200],
                                                defaults={"formato_nome": formatos.get(t["formato"], ""), "origem": "ia"})
        novos += criado
    return novos


def _prod(p: Producao, log: bool = False) -> dict:
    d = {"id": str(p.pk), "nicho": p.nicho, "formato": p.formato, "tema": p.tema, "status": p.status,
         "status_nome": p.get_status_display(), "etapa": p.etapa, "mensagem": p.mensagem, "titulo": p.titulo, "post": p.post,
         "videos": p.videos, "custo_brl": (p.custos or {}).get("brl"), "motivo": p.motivo, "avisos": p.avisos or [],
         "criado": p.criado.isoformat(), "iniciado": p.iniciado.isoformat() if p.iniciado else None,
         "terminado": p.terminado.isoformat() if p.terminado else None,
         "youtube": bool(p.postado_youtube), "tiktok": bool(p.postado_tiktok), "erro": p.mensagem if p.status == "falhou" else "",
         "cancelando": p.cancelar}
    if p.serie_id:
        d["serie"] = {"id": str(p.serie_id), "titulo": p.serie.titulo or p.serie.tema, "parte": p.parte,
                      "total": len(p.serie.plano.get("partes", [])) or None}
    if log:
        d["log"] = "\n".join(p.log.splitlines()[-60:])
    return d


STATUS_NOME = dict(Producao.Status.choices)


def _serie(s: Serie, log: bool = False) -> dict:
    d = {"id": str(s.pk), "tipo": "serie", "nicho": s.nicho, "formato": s.formato, "tema": s.tema, "titulo": s.titulo,
         "status": s.status, "status_nome": STATUS_NOME.get(s.status, s.status), "etapa": s.etapa, "mensagem": s.mensagem,
         "max_partes": s.max_partes, "avisos": s.avisos, "motivo": s.motivo, "custo_brl": (s.custos or {}).get("brl"),
         "arco": (s.plano or {}).get("arco", ""), "partes": [_prod(p) for p in s.partes.order_by("parte")],
         "criado": s.criado.isoformat(), "iniciado": s.iniciado.isoformat() if s.iniciado else None,
         "terminado": s.terminado.isoformat() if s.terminado else None,
         "erro": s.mensagem if s.status == "falhou" else ""}
    if log:
        d["log"] = "\n".join(s.log.splitlines()[-60:])
    return d


def estado() -> dict:
    if not Canal.objects.exists():
        preparar()
    sp, _, _ = _motor()
    cat = sp.catalogo()["nichos"]
    prod = Produtor.get()
    import caminhos
    import provedores
    sem_comfy = provedores.modo() == "comfy" and not caminhos.COMFY.exists()
    canais = []
    for c in Canal.objects.filter(nicho__in=NICHOS):
        feitos, falhas = hoje(c.nicho)
        livres = Pauta.objects.filter(nicho=c.nicho, usado=False, falhas__lt=2)
        canais.append({"nicho": c.nicho, "nome": cat[c.nicho]["nome"], "cor": cat[c.nicho]["cor"], "ativo": c.ativo,
                       "meta_dia": c.meta_dia, "musica": c.musica, "imagens": c.imagens, "legenda": c.legenda, "efeitos": c.efeitos, "volume": c.volume, "voz": c.voz,
                       "modo": c.modo, "serie_max": c.serie_max,
                       "serie_cada": c.serie_cada, "hoje": feitos, "falhas_hoje": falhas,
                       "restantes": livres.count(), "formatos": formatos_do_nicho(c.nicho),
                       "aviso": "Este PC não tem o ComfyUI: os temas do catálogo bíblico falham na etapa das imagens. "
                                "Rode o gospel na máquina com a GPU ou troque para Banco grátis."
                                if c.nicho == "gospel" and sem_comfy and c.imagens == "ia" else "",
                       "pauta": [{"id": p.pk, "titulo": p.titulo, "formato": p.formato, "origem": p.origem}
                                 for p in livres[:40]]})
    canais.sort(key=lambda c: NICHOS.index(c["nicho"]))
    q = Producao.objects.select_related("serie")
    unicos = q.filter(serie=None)
    series = Serie.objects.all()
    s_atual = series.filter(status=Producao.Status.GERANDO).first()
    atual = None if s_atual else unicos.filter(status=Producao.Status.GERANDO).first()
    fila = sorted([_prod(p) for p in unicos.filter(status=Producao.Status.FILA)]
                  + [_serie(s) for s in series.filter(status=Producao.Status.FILA)], key=lambda x: x["criado"])
    # série que falhou antes de criar as partes (no plano) só aparece no histórico como ela mesma
    hist = [_prod(p) for p in q.exclude(status__in=ATIVOS)[:40]] + [
        {**_serie(s), "tema": f"série: {s.titulo or s.tema}"} for s in series.filter(status=Producao.Status.FALHOU)[:20]
        if not s.partes.exists()]
    return {"produtor": {"vivo": vivo(), "pausado": prod.pausado, "intervalo_min": prod.intervalo_min,
                         "llm": prod.llm},
            "canais": canais,
            "atual": _serie(s_atual, log=True) if s_atual else _prod(atual, log=True) if atual else None,
            "fila": fila,
            "revisar": [_prod(p) for p in unicos.filter(status=Producao.Status.REVISAR)],
            "series_revisar": [_serie(s) for s in series.filter(status=Producao.Status.REVISAR)],
            "aprovados": [_prod(p) for p in q.filter(status=Producao.Status.APROVADO).order_by("serie_id", "parte", "-criado")],
            "historico": sorted(hist, key=lambda x: x["criado"], reverse=True)[:40]}
