"""Render final rápido: uma única passada no ffmpeg (clipes + legenda ASS + voz + música).

Substitui a montagem do motor (moviepy, que recodifica 3 vezes e desenha a legenda
quadro a quadro em Python). Aqui a legenda é desenhada pela libass e o vídeo é codificado na
placa de vídeo (h264_nvenc); se a placa falhar, cai para libx264 no processador.
"""

import subprocess
from pathlib import Path

from sincronizar import FFMPEG, FPS, ler_srt

LARGURA, ALTURA = 1080, 1920
FONTES = {
    # arquivo em motor/resource/fonts -> (família, negrito)
    "BeVietnamPro-Bold.ttf": ("Be Vietnam Pro", True),
    "BeVietnamPro-Medium.ttf": ("Be Vietnam Pro", False),
    "Charm-Bold.ttf": ("Charm", True),
    "UTM Kabel KT.ttf": ("UTM Kabel KT", False),
}
EMENDA_MAX = {"word_by_word": 0.35, "sentence": 1.5}  # buracos menores que isso são fechados (evita piscar/sumir)
ESCALA_FONTE = 1.45  # font_size do preset (px do motor) -> tamanho ASS equivalente


def cor_ass(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def tempo_ass(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def gerar_ass(srt: Path, destino: Path, p: dict, total: float | None = None) -> None:
    familia, negrito = FONTES.get(p.get("font_name", ""), ("Arial", True))
    tamanho = round(float(p.get("font_size", 60)) * ESCALA_FONTE)
    emenda = EMENDA_MAX.get(p.get("subtitle_display_mode", "sentence"), 0.35)
    contorno = float(p.get("stroke_width", 1.5)) + 1
    y = round(ALTURA * float(p.get("custom_position", 66)) / 100) if p.get("subtitle_position") == "custom" else {
        "top": round(ALTURA * 0.15), "bottom": round(ALTURA * 0.80), "two_thirds_bottom": round(ALTURA * 0.67)
    }.get(p.get("subtitle_position"), ALTURA // 2)

    if p.get("subtitle_animation") == "pop_spring":
        efeito = r"\fscx60\fscy60\t(0,90,\fscx112\fscy112)\t(90,170,\fscx100\fscy100)"
    else:
        efeito = r"\fad(120,0)"

    blocos = ler_srt(srt)
    linhas = []
    for i, (ini, fim, txt) in enumerate(blocos):
        if i + 1 < len(blocos) and 0 < blocos[i + 1][0] - fim < emenda:
            fim = blocos[i + 1][0]
        texto = txt.replace("{", "(").replace("}", ")")
        linhas.append(f"Dialogue: 0,{tempo_ass(ini)},{tempo_ass(fim)},Legenda,,0,0,0,,{{\\an5\\pos({LARGURA // 2},{y}){efeito}}}{texto}")

    destino.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {LARGURA}",
                f"PlayResY: {ALTURA}",
                "WrapStyle: 0",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                f"Style: Legenda,{familia},{tamanho},{cor_ass(p.get('text_fore_color', '#FFFFFF'))},&H000000FF,"
                f"{cor_ass(p.get('stroke_color', '#000000'))},&H80000000,{-1 if negrito else 0},0,0,0,100,100,0,0,1,"
                f"{contorno:.1f},1,5,90,90,0,1",
                # cartão do fim: caixa vermelha (BorderStyle 3) com INSCREVA-SE e o nome do canal
                f"Style: Inscreva,{familia},{round(tamanho * 0.95)},&H00FFFFFF,&H000000FF,&H001C1CE0,&H001C1CE0,-1,0,0,0,"
                "100,100,2,0,3,18,0,5,90,90,0,1",
                f"Style: Canal,{familia},{round(tamanho * 0.6)},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,"
                "100,100,1,0,1,3,1,5,90,90,0,1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                *linhas,
                *_cartao_inscreva(p, total or (blocos[-1][1] if blocos else 0)),
                "",
            ]
        ),
        encoding="utf-8",
    )


def com_musica(video: Path, musica: Path, p: dict, saida: Path) -> None:
    """Versão com música a partir do vídeo já montado sem música: só mistura o áudio e copia o vídeo
    (segundos, em vez de montar tudo de novo)."""
    total = _duracao(video)
    vol = float(p.get("bgm_volume", 0.2))
    filtro = (f"[1:a]volume={vol},afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[bg];"
              "[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]")
    proc = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(musica),
                           "-filter_complex", filtro, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-t", f"{total:.3f}",
                           "-movflags", "+faststart", str(saida)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg (música) falhou:\n{proc.stderr[-800:]}")


def _duracao(video: Path) -> float:
    """Duração pelo próprio ffmpeg (não depende de ffprobe estar instalado)."""
    import re
    err = subprocess.run([FFMPEG, "-i", str(video)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def _cartao_inscreva(p: dict, total: float) -> list[str]:
    """Os últimos segundos ganham o cartão "INSCREVA-SE" + o nome do canal (preset: inscreva_canal, inscreva_segundos)."""
    canal = p.get("inscreva_canal")
    if not canal or total <= 0:
        return []
    ini = max(0.0, total - float(p.get("inscreva_segundos", 3.0)))
    y = round(ALTURA * 0.80)
    pop = r"\fscx70\fscy70\t(0,160,\fscx108\fscy108)\t(160,260,\fscx100\fscy100)"
    return [f"Dialogue: 1,{tempo_ass(ini)},{tempo_ass(total)},Inscreva,,0,0,0,,{{\\an5\\pos({LARGURA // 2},{y}){pop}}}INSCREVA-SE",
            f"Dialogue: 1,{tempo_ass(ini + 0.15)},{tempo_ass(total)},Canal,,0,0,0,,{{\\an5\\pos({LARGURA // 2},{y + 105})\\fad(150,0)}}{canal}"]


def renderizar(tomadas: list[Path], frames_total: int, audio: Path, srt: Path, musica: Path | None,
               p: dict, pasta: Path, fontes: Path, saida: Path) -> str:
    """Devolve o encoder usado. Roda com cwd=pasta para os caminhos do filtro ass não terem 'C:'."""
    (pasta / "lista.txt").write_text("".join(f"file '{t.name}'\n" for t in tomadas), encoding="utf-8")
    total = frames_total / FPS
    gerar_ass(srt, pasta / "legenda.ass", p, total)
    fontes_rel = Path(*[".."] * len(pasta.relative_to(fontes.parents[1]).parts), fontes.relative_to(fontes.parents[1])).as_posix()

    entradas = ["-f", "concat", "-safe", "0", "-i", "lista.txt", "-i", str(audio)]
    voz = f"[1:a]volume={float(p.get('voice_volume', 1.0))},apad[voz]"
    if musica:
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
        vol = float(p.get("bgm_volume", 0.2))
        audio_f = f"{voz};[2:a]volume={vol},afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[bg];[voz][bg]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        audio_f = voz.replace("[voz]", "[a]")
    filtro = f"[0:v]ass=legenda.ass:fontsdir={fontes_rel}[v];{audio_f}"

    base = [FFMPEG, "-y", "-loglevel", "error", *entradas, "-filter_complex", filtro,
            "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart"]
    for nome, video in (("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-pix_fmt", "yuv420p"]),
                        ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])):
        proc = subprocess.run([*base, *video, str(saida)], cwd=pasta, capture_output=True, text=True)
        if proc.returncode == 0:
            return nome
        erro = proc.stderr[-800:]
    raise RuntimeError(f"ffmpeg falhou:\n{erro}")
