"""Narração com o OmniVoice (motor do VoiceStudio), clonada de uma voz de referência do canal.

Roda no Python do OmniVoice (MILIONERE_OMNIVOICE_PYTHON), separado do motor, porque puxa torch com CUDA:
    python voz_omnivoice.py pedido.json

O pedido traz o texto, a lista de palavras (os tokens do sincronizar.py), a referência e a pasta de saída. Sai o
mesmo par do Edge TTS: audio.wav e tempos.json com [início, fim] de cada palavra, na ordem da lista. O tempo vem
do alinhamento forçado (MMS do torchaudio) com o texto que já sabemos, então a contagem de palavras sempre bate.
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

SR = 24000


def _romano(palavra: str) -> str:
    """'coração' -> 'coracao': o alinhador só conhece letras sem acento."""
    sem = unicodedata.normalize("NFKD", palavra.lower())
    return "".join(ch for ch in sem if "a" <= ch <= "z" or ch == "'")


def narrar(texto: str, ref: str, ref_texto: str, velocidade: float) -> torch.Tensor:
    from omnivoice import OmniVoice

    disp = "cuda:0" if torch.cuda.is_available() else "cpu"
    # placa Pascal (GTX 10xx) faz fp16 a 1/64 da velocidade: fp32 em qualquer GPU antiga
    fp16 = disp != "cpu" and torch.cuda.get_device_capability()[0] >= 7
    model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=disp,
                                      dtype=torch.float16 if fp16 else torch.float32)
    torch.manual_seed(7)
    audio = model.generate(text=texto, language="pt", ref_audio=ref, ref_text=ref_texto, speed=velocidade)[0]
    audio = torch.as_tensor(audio).float().reshape(-1).cpu()
    del model
    if disp != "cpu":
        torch.cuda.empty_cache()
    return audio


def alinhar(audio: torch.Tensor, palavras: list[str]) -> list[list[float]]:
    """[início, fim] em segundos de cada palavra. Palavra sem letra (ex.: '2023') ganha o espaço entre as vizinhas."""
    bundle = torchaudio.pipelines.MMS_FA
    disp = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = bundle.get_model(with_star=False).to(disp)
    onda = torchaudio.functional.resample(audio.unsqueeze(0), SR, bundle.sample_rate).to(disp)
    with torch.inference_mode():
        emissao, _ = model(onda)
    dicio = bundle.get_dict(star=None)
    romanas = [_romano(p) for p in palavras]
    com_letra = [i for i, r in enumerate(romanas) if r]
    alvo = [dicio[c] for i in com_letra for c in romanas[i] if c in dicio]
    alinh, _ = torchaudio.functional.forced_align(emissao, torch.tensor([alvo], device=disp))
    spans = torchaudio.functional.merge_tokens(alinh[0], torch.zeros(len(alinh[0]), device=disp))
    seg_por_quadro = onda.size(1) / emissao.size(1) / bundle.sample_rate

    tempos: list[list[float] | None] = [None] * len(palavras)
    k = 0
    for i in com_letra:
        n = sum(1 for c in romanas[i] if c in dicio)
        if n:
            parte = spans[k:k + n]
            tempos[i] = [parte[0].start * seg_por_quadro, parte[-1].end * seg_por_quadro]
            k += n
    total = audio.numel() / SR
    for i, t in enumerate(tempos):  # sem letra: entre o fim da anterior e o começo da próxima
        if t is None:
            ini = tempos[i - 1][1] if i and tempos[i - 1] else 0.0
            prox = next((x[0] for x in tempos[i + 1:] if x), total)
            tempos[i] = [ini, max(ini + 0.05, prox)]
    return tempos


def main() -> None:
    pedido = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    saida = Path(pedido["saida"])
    saida.mkdir(parents=True, exist_ok=True)
    t = time.time()
    audio = narrar(pedido["texto"], pedido["ref"], pedido["ref_texto"], float(pedido.get("velocidade", 1.0)))
    sf.write(saida / "audio.wav", audio.numpy(), SR)
    print(f"narração: {audio.numel() / SR:.1f} s de áudio em {time.time() - t:.0f} s", flush=True)
    t = time.time()
    tempos = alinhar(audio, pedido["palavras"])
    (saida / "tempos.json").write_text(json.dumps(tempos), encoding="utf-8")
    print(f"alinhamento: {len(tempos)} palavras em {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    main()
