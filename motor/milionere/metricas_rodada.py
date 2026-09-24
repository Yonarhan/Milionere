"""Métricas de uma rodada do pipeline, a partir do log dela (e do comfy.log da mesma rodada).

Uso:
    python metricas_rodada.py producao/noite/rodada_03.log [--comfy producao/noite/rodada_03_comfy.log]
Imprime um JSON e acrescenta em producao/noite/rodadas.jsonl (base do relatório de tempo e computação).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from caminhos import PRODUCAO  # noqa: E402

LINHA = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\] (.*)$")


def _seg(h, m, s) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def medir(log: Path, comfy: Path | None = None) -> dict:
    ev = []
    base = None
    for bruta in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINHA.match(bruta)
        if not m:
            continue
        t = _seg(*m.groups()[:3])
        base = t if base is None else base
        ev.append((t - base + (86400 if t < base else 0), m.group(4).strip()))  # vira a meia-noite

    def quando(prefixo: str, depois: float = -1) -> float | None:
        return next((t for t, msg in ev if t > depois and msg.startswith(prefixo)), None)

    d: dict = {"log": log.name}
    cab = next((msg for _, msg in ev if msg.startswith("===")), "")
    partes = [p.strip() for p in cab.strip("= ").split("|")]
    d["tema"] = partes[1] if len(partes) > 1 else ""
    d["estilo"] = partes[-1].replace("estilo ", "") if partes else ""
    d["roteiro_tentativas"] = sum(msg.startswith("roteiro: tentativa") for _, msg in ev)
    t_ap, t_img, t_j = quando("roteiro aprovado"), quando("imagens: gerando"), quando("camada 3")
    t_fim_img = quando("todas as imagens aprovadas") or quando("AVISO: sobraram")
    t_render, t_fim = quando("render"), quando("FIM")
    m_img = next((re.search(r"gerando (\d+)", msg) for _, msg in ev if msg.startswith("imagens: gerando")), None)
    cenas = int(m_img.group(1)) if m_img else 0
    rep1 = 0
    if t_j is not None:
        prox = quando("refação", t_j) or t_fim_img or t_j
        rep1 = len({re.search(r"cena (\d+)", msg).group(1) for t, msg in ev
                    if t_j <= t <= prox and re.match(r"cena \d+ reprovada", msg)})
    refacoes = sum(msg.startswith("refação") for _, msg in ev)
    minutos = lambda a, b: round((b - a) / 60, 1) if a is not None and b is not None else None  # noqa: E731
    d.update({
        "desistiu": any(msg.startswith("DESISTI") for _, msg in ev),
        "min_total": minutos(0, t_fim),
        "min_roteiro": minutos(0, t_ap),
        "min_imagens_iniciais": minutos(t_img, t_j),
        "min_juiz_e_refacao": minutos(t_j, t_fim_img),
        "min_render": minutos(t_render, t_fim),
        "cenas": cenas,
        "reprovadas_1a_passada": rep1,
        "aprovacao_1a_passada": round((cenas - rep1) / cenas, 2) if cenas else None,
        "refacoes": refacoes,
        "imagens_geradas": cenas + refacoes,
        "imagens_por_cena": round((cenas + refacoes) / cenas, 2) if cenas else None,
        "sobrou_reprovada": any("AVISO: sobraram" in msg for _, msg in ev),
        "reusadas_banco": sum("veio do banco" in msg for _, msg in ev),
        "videos": [msg.split("(+")[0].strip() for _, msg in ev if "videos_prontos" in msg],
    })
    custo = next((msg for _, msg in ev if msg.startswith("custo:")), "")
    mc = re.search(r"US\$ ([\d.]+) \(R\$ ([\d.]+)\) \| (\d+) chamadas", custo)
    if mc:
        d.update(usd=float(mc.group(1)), brl=float(mc.group(2)), chamadas_ia=int(mc.group(3)))
    if comfy and comfy.exists():
        s = [float(x) for x in re.findall(r"Prompt executed in ([\d.]+) seconds", comfy.read_text(errors="replace"))]
        d.update(gpu_min=round(sum(s) / 60, 1), gpu_s_por_imagem=round(sum(s) / len(s), 1) if s else None)
    return d


def juntar_roteiro(d: dict, roteiro_log: Path) -> dict:
    """Esteira: o roteiro foi feito em paralelo com o vídeo anterior, num log próprio (pipeline --so-roteiro)."""
    r = medir(roteiro_log)
    ev = roteiro_log.read_text(encoding="utf-8", errors="replace")
    fim = re.findall(r"^\[(\d\d):(\d\d):(\d\d)\] roteiro pronto", ev, re.M)
    ini = re.findall(r"^\[(\d\d):(\d\d):(\d\d)\]", ev, re.M)
    d["tema"] = r["tema"] or d["tema"]
    d["roteiro_tentativas"] = r["roteiro_tentativas"]
    d["min_roteiro_paralelo"] = round((_seg(*fim[0]) - _seg(*ini[0])) / 60, 1) if fim and ini else None
    d["min_roteiro"] = 0.0  # não entra no tempo da rodada: correu enquanto a GPU fazia o vídeo anterior
    for k in ("usd", "brl", "chamadas_ia"):
        if k in r:
            d[k] = round(d.get(k, 0) + r[k], 2)
    d["esteira"] = True
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--comfy", type=Path)
    ap.add_argument("--roteiro-log", type=Path, help="log do pipeline --so-roteiro que preparou esta rodada")
    a = ap.parse_args()
    d = medir(a.log, a.comfy)
    if a.roteiro_log and a.roteiro_log.exists():
        d = juntar_roteiro(d, a.roteiro_log)
    print(json.dumps(d, ensure_ascii=False, indent=1))
    saida = PRODUCAO / "noite" / "rodadas.jsonl"
    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
