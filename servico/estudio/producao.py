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
    return feitos, q.filter(status=Producao.Status.FALHOU).count()


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
        raise RuntimeError("o roteiro ou o render não passou nas validações (veja o log)")
    # as imagens aprovadas já entram no banco dentro do pipeline (pipeline.alimentar_banco)
    return videos


def _generico(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    sp, _, _ = _motor()
    import caminhos

    log = lambda etapa, msg: diario(msg or etapa, etapa)  # noqa: E731
    pauta = prod.pauta
    r = sp._roteiro_generico({"nicho": prod.nicho, "formato": prod.formato,
                              "formato_nome": pauta.formato_nome if pauta else prod.formato, "tema_livre": prod.tema}, log)
    if r.get("_avisos"):
        raise RuntimeError("o juiz reprovou o roteiro nas 3 tentativas: " + " | ".join(r["_avisos"][:3]))
    diario("roteiro aprovado:\n" + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]), "roteiro")
    return _video_generico(prod, r, musica, diario)


def _video_generico(prod: Producao, r: dict, musica: str, diario: _Diario) -> list[Path]:
    sp, _, _ = _motor()
    log = lambda etapa, msg: diario(msg or etapa, etapa)  # noqa: E731
    entrada = {"nicho": prod.nicho, "formato": prod.formato, "tema_livre": prod.tema, "dono": "canal",
               "cenas": [{"fala": c["fala"], "busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
               "post": {"titulo": r["titulo"], "desc": r["descricao"], "tags": " ".join(r["hashtags"]),
                        "comentario": r["comentario_fixado"], "tiktok_titulo": r.get("tiktok_titulo", ""),
                        "tiktok_legenda": r.get("tiktok_legenda", "")},
               "mus": musica}  # com | sem: um vídeo só
    pasta = Path(settings.MEDIA_ROOT) / "canal" / str(prod.id)
    saida = sp.gerar_video(entrada, pasta, log)
    videos = [Path(v) for v in saida.get("videos") or [saida["video"]]]
    return videos


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


def executar_qualquer(item: "Producao | Serie") -> None:
    (executar_serie if isinstance(item, Serie) else executar)(item)


def executar(prod: Producao) -> None:
    _motor()
    import medidor

    musica = _musica(prod.nicho)
    diario = _Diario(prod.pk)
    Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.GERANDO, etapa="roteiro", iniciado=timezone.now(),
                                               mensagem="começando")
    with medidor.medir() as m:
        try:
            biblico = prod.nicho == "gospel" and prod.pauta and prod.pauta.tema_id and prod.pauta.origem == "catalogo"
            videos = (_gospel if biblico else _generico)(prod, musica, diario)
            Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.REVISAR, etapa="post", mensagem="pronto para revisar",
                                                       terminado=timezone.now(), custos=m.resumo(), **_resultado(videos))
            if prod.pauta_id:
                Pauta.objects.filter(pk=prod.pauta_id).update(usado=True)
        except BaseException as e:  # noqa: BLE001 - SystemExit do pipeline também vira falha legível
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
            plano = ms.planejar(s.nicho, formato, tema, s.max_partes, log=lambda msg: diario(msg, "plano"))
            N = len(plano["partes"])
            Serie.objects.filter(pk=s.pk).update(plano=plano, titulo=plano["titulo_serie"][:200], etapa="roteiro")
            partes = [Producao.objects.create(serie=s, parte=k, pauta=pauta, nicho=s.nicho, formato=s.formato,
                                              tema=f"{plano['titulo_serie']} · parte {k}/{N}: {x['titulo']}"[:200],
                                              status=Producao.Status.GERANDO, iniciado=agora(), etapa="roteiro")
                      for k, x in enumerate(plano["partes"], 1)]
            slug_serie = f"serie-{s.formato}-{chave}"
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
                    if r.get("_avisos"):
                        raise RuntimeError(f"parte {k}: o juiz reprovou o roteiro nas 3 tentativas: " + " | ".join(r["_avisos"][:3]))
                    r["titulo"] = ms.titulo_parte(r["titulo"], k, N)
                    if r.get("tiktok_titulo"):
                        r["tiktok_titulo"] = ms.titulo_parte(r["tiktok_titulo"], k, N)
                    roteiros[k - 1] = r
                diario(f"parte {k}/{N} aprovada:\n" + "\n".join(f"  «{f}»" for f in falas(k)), "roteiro")

            for k in range(1, N + 1):
                escrever(k)
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
                if rodada == ms.RODADAS_SERIE:
                    raise RuntimeError("o juiz da série reprovou depois das reescritas: "
                                       + " | ".join(f"parte {k}: {p[0]}" for k, p in problemas.items()))
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
            avisos = []
            if visuais and any(r.get("personagens") for _, r, _ in visuais):
                diario("juiz visual da série: o mesmo personagem com a mesma cara em todas as partes", "montagem")
                avisos = ms.julgar_visual(visuais, pipeline.PROD / "midia" / "_serie_visual" / slug_serie)
                for a in avisos:
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
    log("produtor no ar: um vídeo por vez, seguindo as metas do painel /canal (Ctrl+C para parar)")
    try:
        while True:
            prod = None if Produtor.get().pausado else proxima()
            if prod:
                log(f"{timezone.localtime():%H:%M} gerando: {prod.nicho} · {prod.tema}")
                executar_qualquer(prod)
                prod.refresh_from_db()
                log(f"{timezone.localtime():%H:%M} {prod.status}: {prod.mensagem}")
                if uma_vez:
                    return
                continue
            if uma_vez:
                log("nada para gerar agora (metas cumpridas, pausado ou em descanso)")
                return
            time.sleep(30)
    finally:
        parar.set()
        try:
            _motor()
            import provedores
            provedores.encerrar()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ painel

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
    for t in llm.chamar(prompt, schema, papel="juiz")["temas"]:
        _, criado = Pauta.objects.get_or_create(nicho=nicho, formato=t["formato"], titulo=t["titulo"].strip()[:200],
                                                defaults={"formato_nome": formatos.get(t["formato"], ""), "origem": "ia"})
        novos += criado
    return novos


def _prod(p: Producao, log: bool = False) -> dict:
    d = {"id": str(p.pk), "nicho": p.nicho, "formato": p.formato, "tema": p.tema, "status": p.status,
         "status_nome": p.get_status_display(), "etapa": p.etapa, "mensagem": p.mensagem, "titulo": p.titulo, "post": p.post,
         "videos": p.videos, "custo_brl": (p.custos or {}).get("brl"), "motivo": p.motivo,
         "criado": p.criado.isoformat(), "iniciado": p.iniciado.isoformat() if p.iniciado else None,
         "terminado": p.terminado.isoformat() if p.terminado else None,
         "youtube": bool(p.postado_youtube), "tiktok": bool(p.postado_tiktok), "erro": p.mensagem if p.status == "falhou" else ""}
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
                       "meta_dia": c.meta_dia, "musica": c.musica, "modo": c.modo, "serie_max": c.serie_max,
                       "serie_cada": c.serie_cada, "hoje": feitos, "falhas_hoje": falhas,
                       "restantes": livres.count(), "formatos": formatos_do_nicho(c.nicho),
                       "aviso": "Este PC não tem o ComfyUI: os temas do catálogo bíblico falham na etapa das imagens. "
                                "Rode o gospel na máquina com a GPU." if c.nicho == "gospel" and sem_comfy else "",
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
    return {"produtor": {"vivo": vivo(), "pausado": prod.pausado, "intervalo_min": prod.intervalo_min},
            "canais": canais,
            "atual": _serie(s_atual, log=True) if s_atual else _prod(atual, log=True) if atual else None,
            "fila": fila,
            "revisar": [_prod(p) for p in unicos.filter(status=Producao.Status.REVISAR)],
            "series_revisar": [_serie(s) for s in series.filter(status=Producao.Status.REVISAR)],
            "aprovados": [_prod(p) for p in q.filter(status=Producao.Status.APROVADO).order_by("serie_id", "parte", "-criado")],
            "historico": sorted(hist, key=lambda x: x["criado"], reverse=True)[:40]}
