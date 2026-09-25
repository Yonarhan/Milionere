"""Montagem cena a cena: cada trecho da fala ganha um vídeo cortado no tempo exato.

O motor sozinho troca de imagem num ritmo fixo (video_clip_duration) sem saber
quando cada frase é falada. Aqui:
  1. lemos o subtitle.srt da narração (tempo de cada palavra/frase);
  2. achamos o início de cada cena pela contagem de palavras;
  3. baixamos do Pexels um vídeo vertical por tomada e cortamos no tamanho exato;
  4. devolvemos os arquivos na ordem, para o motor montar em modo sequencial.
"""

import json
import math
import re
import subprocess
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30
ANTECIPA = 0.15  # a imagem entra um pouco antes da palavra, como numa edição de verdade
FOLGA_FINAL = 1.0  # o último clipe passa um pouco do fim da narração
UA = {"User-Agent": "Mozilla/5.0 roteirista-shorts"}


def tokens(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.lower())


def ler_srt(caminho: Path) -> list[tuple[float, float, str]]:
    def seg(t: str) -> float:
        h, m, s = t.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    blocos = []
    for bloco in re.split(r"\n\s*\n", caminho.read_text(encoding="utf-8").strip()):
        linhas = bloco.strip().splitlines()
        if len(linhas) >= 3 and "-->" in linhas[1]:
            ini, fim = (seg(x.strip()) for x in linhas[1].split("-->"))
            blocos.append((ini, fim, " ".join(linhas[2:])))
    return blocos


def duracao_audio(caminho: Path) -> float:
    saida = subprocess.run([FFMPEG, "-i", str(caminho)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", saida).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


PAUSA_MIN = 0.35  # entre duas falas, menos que isso soa como frase colada / pedaço perdido
PAUSA_ALVO = 0.8  # pausa normal do Edge TTS depois de ponto final
PAUSA_MAX = 0.45  # compactar_pausas(): 0.8s entre frases derruba o ritmo (60% pulavam o vídeo no começo)


def _tempo_srt(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def respirar(cenas: list[dict], audio: Path, srt_arq: Path) -> list[str]:
    """O Edge TTS às vezes cola duas frases sem pausa ('manda eu ir Jesus respondeu'). Acha as trocas de fala
    com pausa < PAUSA_MIN e insere silêncio ali, no áudio e na legenda. Devolve o que corrigiu."""
    srt = ler_srt(srt_arq)
    fins_de_fala, acc = set(), 0
    for c in cenas[:-1]:
        acc += len(tokens(c["fala"]))
        fins_de_fala.add(acc)
    cortes, acc = [], 0  # (índice do bloco que termina a fala, silêncio a inserir)
    for k, (ini, fim, txt) in enumerate(srt[:-1]):
        acc += len(tokens(txt))
        gap = srt[k + 1][0] - fim
        if acc in fins_de_fala and gap < PAUSA_MIN:
            cortes.append((k, PAUSA_ALVO - gap))
    if not cortes:
        return []
    # o fim do bloco no srt às vezes cai no meio da última sílaba: corta no ponto mais silencioso logo depois
    import numpy as np
    bruto = subprocess.run([FFMPEG, "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True, check=True).stdout
    amostras = np.frombuffer(bruto, np.int16).astype(float)

    def rms(x: float) -> float:
        trecho = amostras[int(x * 16000):int(x * 16000) + 320]
        return float(np.sqrt(np.mean(trecho ** 2))) if len(trecho) else 0.0

    def vale(t: float) -> float:
        # o PRIMEIRO ponto quieto depois do fim da frase: quando o TTS emenda, a palavra seguinte já começa
        # logo depois, e o ponto mais quieto da janela pode cair no meio dela ("Je... sus")
        voz = max(rms(t - 0.3 + j * 0.01) for j in range(30))
        janelas = [t + j * 0.01 for j in range(-3, 31)]
        quieto = next((x for x in janelas if rms(x) < 0.15 * voz), None)
        return (quieto if quieto is not None else min(janelas, key=rms)) + 0.01

    pontos = {k: vale(srt[k][1]) for k, _ in cortes}
    info = subprocess.run([FFMPEG, "-i", str(audio)], capture_output=True, text=True).stderr
    taxa = re.search(r"(\d+) Hz", info).group(1)
    canais = 2 if "stereo" in info else 1
    filtros, rotulos, ant = [], [], 0.0
    for j, (k, sil) in enumerate(cortes):
        t = pontos[k]
        filtros.append(f"[0:a]atrim={ant:.3f}:{t:.3f},asetpts=PTS-STARTPTS[p{j}]")
        filtros.append(f"aevalsrc={'|'.join(['0'] * canais)}:d={sil:.3f}:s={taxa}[s{j}]")
        rotulos += [f"[p{j}]", f"[s{j}]"]
        ant = t
    filtros.append(f"[0:a]atrim=start={ant:.3f},asetpts=PTS-STARTPTS[fim]")
    rotulos.append("[fim]")
    filtros.append(f"{''.join(rotulos)}concat=n={len(rotulos)}:v=0:a=1[a]")
    original = audio.with_name(audio.stem + "_original" + audio.suffix)
    if not original.exists():
        audio.rename(original)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(original), "-filter_complex", ";".join(filtros),
                    "-map", "[a]", str(audio)], check=True)
    novos, desloc, corte = [], 0.0, dict(cortes)
    for k, (ini, fim, txt) in enumerate(srt):
        novos.append((ini + desloc, fim + desloc, txt))
        desloc += corte.get(k, 0.0)
    srt_arq.write_text("\n".join(f"{n}\n{_tempo_srt(a)} --> {_tempo_srt(b)}\n{t}\n" for n, (a, b, t) in enumerate(novos, 1)),
                       encoding="utf-8")
    return [f"pausa inserida depois de «{srt[k][2]}» (era {PAUSA_ALVO - s:.2f}s)" for k, s in cortes]


def compactar_pausas(audio: Path, srt_arq: Path) -> float:
    """Encurta o silêncio entre frases para PAUSA_MAX (fica acima de PAUSA_MIN: não soa colado), no áudio e na
    legenda. Mantém 0.25s depois do fim da frase (o srt às vezes corta no meio da última sílaba) e 0.2s antes da
    próxima. Devolve quantos segundos tirou."""
    srt = ler_srt(srt_arq)
    cortes = []  # (início, fim) do trecho de silêncio removido
    if srt and srt[0][0] > 0.2:
        cortes.append((0.0, srt[0][0] - 0.1))
    for (_, fim, _), (ini_prox, _, _) in zip(srt, srt[1:]):
        if ini_prox - fim > PAUSA_MAX:
            a, b = fim + 0.25, ini_prox - 0.2
            if b - a > 0.05:
                cortes.append((a, b))
    if not cortes:
        return 0.0
    filtros, rotulos, ant = [], [], 0.0
    for j, (a, b) in enumerate(cortes):
        if a > ant:
            filtros.append(f"[0:a]atrim={ant:.3f}:{a:.3f},asetpts=PTS-STARTPTS[p{j}]")
            rotulos.append(f"[p{j}]")
        ant = b
    filtros.append(f"[0:a]atrim=start={ant:.3f},asetpts=PTS-STARTPTS[fim]")
    rotulos.append("[fim]")
    filtros.append(f"{''.join(rotulos)}concat=n={len(rotulos)}:v=0:a=1[a]")
    antes = audio.with_name(audio.stem + "_pausas" + audio.suffix)
    audio.replace(antes)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(antes), "-filter_complex", ";".join(filtros),
                    "-map", "[a]", str(audio)], check=True)

    def novo(t: float) -> float:
        return t - sum(min(b, t) - a for a, b in cortes if t > a)

    srt_arq.write_text("\n".join(f"{n}\n{_tempo_srt(novo(a))} --> {_tempo_srt(novo(b))}\n{t}\n"
                                 for n, (a, b, t) in enumerate(srt, 1)), encoding="utf-8")
    return sum(b - a for a, b in cortes)


def tempos_das_cenas(cenas: list[dict], srt: list, dur_audio: float) -> tuple[list[tuple[float, float]], list[str]]:
    """Início/fim de cada cena. Cada palavra do srt ganha um horário (interpolado dentro do bloco)."""
    linha_do_tempo = []
    for ini, fim, txt in srt:
        tk = tokens(txt)
        linha_do_tempo += [ini + (fim - ini) * j / len(tk) for j in range(len(tk))]

    avisos, inicios, pos = [], [], 0
    for c in cenas:
        t = linha_do_tempo[min(pos, len(linha_do_tempo) - 1)]
        inicios.append(max(0.0, t - ANTECIPA))
        pos += len(tokens(c["fala"]))
    if pos != len(linha_do_tempo):
        avisos.append(f"roteiro tem {pos} palavras e a legenda {len(linha_do_tempo)}; cortes podem ficar levemente fora")

    inicios[0] = 0.0
    fins = inicios[1:] + [dur_audio + FOLGA_FINAL]
    return list(zip(inicios, fins)), avisos


class Pexels:
    def __init__(self, config: Path, cache: Path):
        with open(config, "rb") as f:
            self.chave = tomllib.load(f)["app"]["pexels_api_keys"][0]
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self._buscas: dict[str, list] = {}

    def buscar(self, termo: str) -> list[dict]:
        if termo not in self._buscas:
            params = {"query": termo, "per_page": 30, "orientation": "portrait"}
            if termo.startswith("pt:"):  # termo em português (fala do usuário sem busca em inglês)
                params.update(query=termo[3:], locale="pt-BR")
            url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"Authorization": self.chave, **UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                self._buscas[termo] = json.load(r).get("videos", [])
        return self._buscas[termo]

    @staticmethod
    def melhor_arquivo(video: dict) -> dict | None:
        verticais = [f for f in video.get("video_files", []) if f.get("height") and f["height"] >= f.get("width", 0)]
        if not verticais:
            return None
        hd = [f for f in verticais if f["height"] >= 1280]
        return min(hd, key=lambda f: f["height"]) if hd else max(verticais, key=lambda f: f["height"])

    def baixar(self, video: dict) -> Path:
        destino = self.cache / f"pexels_{video['id']}.mp4"
        if not destino.exists():
            arq = self.melhor_arquivo(video)
            req = urllib.request.Request(arq["link"], headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                destino.write_bytes(r.read())
        return destino


def cortar(origem: Path, destino: Path, inicio_origem: float, frames: int) -> None:
    base = [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", f"{inicio_origem:.2f}", "-i", str(origem),
        "-frames:v", str(frames),
        # tpad: clipe mais curto que a fala congela no último quadro em vez de encurtar a tomada (desincroniza)
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,fps={FPS},setsar=1,"
               "tpad=stop_mode=clone:stop_duration=30",
        "-an", "-pix_fmt", "yuv420p",
    ]
    # placa de vídeo primeiro (bem mais rápido no i3); processador se a placa falhar
    if subprocess.run([*base, "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", str(destino)]).returncode != 0:
        subprocess.run([*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(destino)], check=True)



def baixar_candidato(c: dict, cache: Path) -> Path:
    ext = ".mp4" if c["tipo"] == "video" else ".jpg"
    destino = cache / (c["ref"].replace(":", "_").replace("/", "_") + ext)
    if not destino.exists():
        req = urllib.request.Request(c["link"], headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            destino.write_bytes(r.read())
    return destino


def baixar_ou_proximo(c: dict, alternativas: list[dict], cache: Path) -> tuple[dict, Path]:
    """Baixa o candidato escolhido; se a fonte recusar (403, fora do ar...), tenta os outros da mesma cena,
    primeiro os do mesmo tipo (vídeo/foto). Só falha se nenhum baixar."""
    ordem = [c] + [a for a in alternativas if a["ref"] != c["ref"] and a["tipo"] == c["tipo"]] \
                + [a for a in alternativas if a["ref"] != c["ref"] and a["tipo"] != c["tipo"]]
    ultimo = None
    for cand in ordem:
        try:
            return cand, baixar_candidato(cand, cache)
        except Exception as e:  # noqa: BLE001
            ultimo = e
            print(f"AVISO  não baixou {cand['ref']} ({e}); tentando outro candidato da cena")
    raise RuntimeError(f"nenhum candidato da cena baixou (último erro: {ultimo})")
# (z, x, y) do zoompan; P = progresso 0->1 da tomada. Um movimento diferente a cada tomada: o mesmo zoom central em
# todas as imagens é o "slideshow" que a política de conteúdo não original do YouTube cita como produzido em massa.
_CX, _CY = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
MOVIMENTOS = [
    ("1+0.08*P", _CX, _CY),                          # aproxima no centro
    ("1.1", "(iw-iw/zoom)*P", _CY),                  # desliza pra direita
    ("1.08-0.08*P", _CX, _CY),                       # afasta
    ("1+0.08*P", _CX, "(ih/2-(ih/zoom/2))*0.55"),    # aproxima no terço de cima (rostos)
    ("1.1", "(iw-iw/zoom)*(1-P)", _CY),              # desliza pra esquerda
    ("1.1", _CX, "(ih-ih/zoom)*(1-P)"),              # sobe
]


def animar_foto(origem: Path, destino: Path, frames: int, parte: int = 0) -> None:
    """Foto/pintura -> clipe vertical com movimento lento (MOVIMENTOS[parte], em rodízio). Retrato preenche a tela;
    paisagem fica grande no meio com o fundo desfocado da própria imagem."""
    from PIL import Image

    with Image.open(origem) as im:
        proporcao = im.width / im.height
    z, x, y = (e.replace("P", f"(on/{frames})") for e in MOVIMENTOS[parte % len(MOVIMENTOS)])
    zoom = f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s=1080x1920:fps={FPS}"
    if proporcao < 0.75:
        filtro = f"[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,{zoom},setsar=1[v]"
    else:
        filtro = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:3,eq=brightness=-0.12[bg];"
            "[0:v]scale=-2:1250,crop='min(iw,1080)':ih[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale=2160:3840,{zoom},setsar=1[v]"
        )
    base = [FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(origem),
            "-filter_complex", filtro, "-map", "[v]", "-frames:v", str(frames), "-pix_fmt", "yuv420p"]
    if subprocess.run([*base, "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", str(destino)]).returncode != 0:
        subprocess.run([*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(destino)], check=True)


def montar_tomadas(cenas, tempos, corte_max: float, pexels: Pexels, pasta: Path,
                   evitar: list[str] | None = None, curadoria: dict | None = None,
                   pasta_midia: Path | None = None) -> tuple[list[dict], list[str]]:
    """Baixa e corta um clipe por tomada. Cenas longas viram várias tomadas.
    Se a cena tem "escolha" (refs escolhidos na curadoria), usa exatamente esses; senão, busca automática no Pexels."""
    por_ref = {c["ref"]: c for lista in (curadoria or {}).values() for c in lista}
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("tomada_*.mp4"):
        velho.unlink()

    usados: set[int] = set()
    tomadas, relatorio = [], []
    n = 0
    for i, (cena, (ini, fim)) in enumerate(zip(cenas, tempos), 1):
        partes = max(1, math.ceil((fim - ini) / corte_max - 0.15))
        f_ini_cena, f_fim_cena = round(ini * FPS), round(fim * FPS)
        limites = [f_ini_cena + round((f_fim_cena - f_ini_cena) * k / partes) for k in range(partes + 1)]

        # 1º: arquivos do usuário em producao/midia/<slug>/cena_05.jpg, cena_05b.mp4... (prioridade total)
        manuais = sorted(p for p in (pasta_midia.glob(f"cena_{i:02d}*") if pasta_midia and pasta_midia.exists() else [])
                         if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"})
        videos = [p for p in manuais if p.suffix.lower() in {".mp4", ".mov"}]
        if videos and any(p.stem == f"cena_{i:02d}" for p in videos):
            manuais = videos  # cena animada (animar.py) substitui a imagem de onde saiu
        if manuais:
            if len(manuais) < partes:  # 1 imagem para cena longa = 1 tomada contínua (o zoom não "reinicia")
                partes = len(manuais)
                limites = [f_ini_cena + round((f_fim_cena - f_ini_cena) * k / partes) for k in range(partes + 1)]
            for k in range(partes):
                frames = limites[k + 1] - limites[k]
                origem = manuais[min(k, len(manuais) - 1)]
                n += 1
                destino = pasta / f"tomada_{n:02d}.mp4"
                if origem.suffix.lower() in {".mp4", ".mov"}:
                    cortar(origem, destino, 0.0, frames)
                else:
                    animar_foto(origem, destino, frames, n)
                tomadas.append({"provider": "local", "url": str(destino), "duration": max(1, math.ceil(frames / FPS)), "frames": frames})
                relatorio.append(f"  {ini:5.1f}s–{fim:5.1f}s  cena {i:>2}.{k + 1}  {frames / FPS:4.1f}s  SUA PASTA: {origem.name}  «{cena['fala'][:50]}»")
            continue

        escolha = [e for e in (cena.get("escolha") or []) if e in por_ref]  # escolhas órfãs viram busca automática
        if escolha:
            for k in range(partes):
                frames = limites[k + 1] - limites[k]
                ref = escolha[min(k, len(escolha) - 1)]
                repeticao = k - escolha.index(ref)  # mesma escolha em 2 tomadas -> pega outro trecho do vídeo
                c, origem = baixar_ou_proximo(por_ref[ref], (curadoria or {}).get(str(i), []), pexels.cache)
                if c["ref"] != ref:  # o crédito do post tem que ser o da imagem que entrou de verdade
                    cena["escolha"] = [c["ref"] if e == ref else e for e in cena["escolha"]]
                    por_ref[c["ref"]] = c
                n += 1
                destino = pasta / f"tomada_{n:02d}.mp4"
                if c["tipo"] == "video":
                    dur = frames / FPS
                    inicio_origem = min(max(0.0, c.get("dur", 0) - dur - 0.2), 0.5 + repeticao * (dur + 0.5))
                    cortar(origem, destino, inicio_origem, frames)
                else:
                    animar_foto(origem, destino, frames, n)
                tomadas.append({"provider": "local", "url": str(destino), "duration": max(1, math.ceil(frames / FPS)), "frames": frames})
                relatorio.append(f"  {ini:5.1f}s–{fim:5.1f}s  cena {i:>2}.{k + 1}  {frames / FPS:4.1f}s  {ref}  «{cena['fala'][:50]}»")
            continue

        termos = [t.strip() for t in cena["busca"].split("|") if t.strip()]
        candidatos = [v for t in termos for v in pexels.buscar(t) if pexels.melhor_arquivo(v)
                      and not any(e in v.get("url", "").lower() for e in (evitar or []))]
        if not candidatos:
            raise RuntimeError(f"cena {i} ('{cena['busca']}') não achou nenhum vídeo vertical no Pexels")

        for k in range(partes):
            frames = limites[k + 1] - limites[k]
            dur = frames / FPS
            livres = [v for v in candidatos if v["id"] not in usados] or candidatos
            longos = [v for v in livres if v.get("duration", 0) >= dur + 0.6]
            video = (longos or sorted(livres, key=lambda v: -v.get("duration", 0)))[0]
            usados.add(video["id"])

            origem = pexels.baixar(video)
            sobra = video.get("duration", 0) - dur
            inicio_origem = min(1.0, max(0.0, sobra / 2))
            n += 1
            destino = pasta / f"tomada_{n:02d}.mp4"
            cortar(origem, destino, inicio_origem, frames)
            tomadas.append({"provider": "local", "url": str(destino), "duration": max(1, math.ceil(dur)), "frames": frames})
            relatorio.append(f"  {ini:5.1f}s–{fim:5.1f}s  cena {i:>2}.{k + 1}  {dur:4.1f}s  [{cena['busca']}] pexels {video['id']}  «{cena['fala'][:50]}»")
    return tomadas, relatorio


def painel(tomadas: list[Path], destino: Path) -> None:
    """Uma miniatura de cada tomada lado a lado (10 por linha), para revisar as imagens antes de entregar."""
    quadros = []
    for i, t in enumerate(tomadas):
        q = destino.with_name(f"_q{i:02d}.png")
        subprocess.run([FFMPEG, "-y", "-loglevel", "quiet", "-ss", "0.4", "-i", str(t), "-frames:v", "1",
                        "-vf", "scale=180:320", str(q)])
        quadros.append(q)
    linhas = math.ceil(len(quadros) / 10)
    subprocess.run([FFMPEG, "-y", "-loglevel", "quiet", "-i", str(destino.with_name("_q%02d.png")),
                    "-vf", f"tile=10x{linhas}", "-frames:v", "1", str(destino)])
    for q in quadros:
        q.unlink(missing_ok=True)
