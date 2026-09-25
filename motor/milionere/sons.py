"""Efeitos sonoros gerados por código (sem arquivo de terceiros, sem licença): whoosh nas trocas de cena e um impacto
grave no primeiro quadro. Tudo vira UMA trilha .wav do tamanho do vídeo, que o render mistura baixinho sob a voz.

    python sons.py            # gera storage/sfx/whoosh.wav e impacto.wav e uma trilha de teste
"""

import wave
from pathlib import Path

import numpy as np

TAXA = 44100
PASTA = Path(__file__).resolve().parents[1] / "storage" / "sfx"


def _salvar(sinal: np.ndarray, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(sinal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(pcm.tobytes())
    return destino


def whoosh(dur: float = 0.42, seed: int = 3) -> np.ndarray:
    """Ar passando: ruído com filtro que abre e fecha (grave -> agudo -> grave) e volume em arco."""
    n = int(dur * TAXA)
    ruido = np.random.default_rng(seed).standard_normal(n)
    t = np.linspace(0, 1, n)
    corte = 0.02 + 0.28 * np.sin(np.pi * t) ** 2          # coeficiente do passa-baixa de um polo: abre no meio
    saida, y = np.empty(n), 0.0
    for i in range(n):
        y += corte[i] * (ruido[i] - y)
        saida[i] = y
    env = np.sin(np.pi * t ** 0.8) ** 1.5
    s = saida * env
    return s / (np.abs(s).max() + 1e-9) * 0.9


def impacto(dur: float = 0.9) -> np.ndarray:
    """Batida grave de trailer: seno que cai de 70 para 38 Hz + um estalo curto de ruído no ataque."""
    n = int(dur * TAXA)
    t = np.arange(n) / TAXA
    freq = 38 + 32 * np.exp(-t * 6)
    fase = 2 * np.pi * np.cumsum(freq) / TAXA
    corpo = np.sin(fase) * np.exp(-t * 4.2)
    estalo = np.random.default_rng(5).standard_normal(n) * np.exp(-t * 60) * 0.35
    s = corpo + estalo
    return s / (np.abs(s).max() + 1e-9) * 0.95


def garantir() -> dict[str, Path]:
    """Os sons básicos em storage/sfx (gerados uma vez)."""
    sons = {"whoosh": whoosh, "impacto": impacto}
    feitos = {}
    for nome, gerar in sons.items():
        arq = PASTA / f"{nome}.wav"
        if not arq.exists():
            _salvar(gerar(), arq)
        feitos[nome] = arq
    return feitos


def trilha(cortes: list[float], total: float, destino: Path, impacto_inicio: bool = True) -> Path:
    """Uma trilha só, do tamanho do vídeo: whoosh centrado em cada troca de cena (o pico cai no corte) e o impacto
    no quadro 0. Trocas muito próximas (< 0,6 s) ganham um só whoosh, para não virar chiado."""
    n = int(total * TAXA) + TAXA
    faixa = np.zeros(n)
    w = whoosh()
    ultimo = -9.0
    for c in sorted(cortes):
        if c - ultimo < 0.6 or c <= 0.3:
            continue
        ini = max(0, int((c - len(w) / TAXA * 0.55) * TAXA))  # o ponto alto do whoosh encosta no corte
        faixa[ini:ini + len(w)] += w[: max(0, min(len(w), n - ini))]
        ultimo = c
    if impacto_inicio:
        b = impacto()
        faixa[: len(b)] += b[: n]
    return _salvar(faixa / max(1.0, np.abs(faixa).max()), destino)


if __name__ == "__main__":
    print(garantir())
    print(trilha([2.3, 5.6, 8.0, 10.7], 12.0, PASTA / "_teste_trilha.wav"))
