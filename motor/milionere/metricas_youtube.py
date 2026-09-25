"""Métricas dos vídeos postados: título pergunta x afirmação (e o que mais quiser comparar), com números reais.

    python metricas_youtube.py                    # tabela + resumo por tipo de título, salva em producao/metricas/
    python metricas_youtube.py --min-horas 72     # só vídeos públicos há 72 h ou mais (padrão 48)
    python metricas_youtube.py --autorizar        # 1 vez: libera a retenção (YouTube Analytics API)

Views, likes e comentários vêm da Data API com o token da postagem (postar.py). A retenção (% médio assistido e
duração média, com 24-48 h de atraso em relação às views) precisa do escopo do YouTube Analytics, num token SEPARADO (segredos/youtube_token_analytics.json)
para não mexer no token que o cron de postagem usa. Antes de --autorizar: ative a "YouTube Analytics API" no mesmo
projeto do Google Cloud do youtube_cliente.json (grátis). Sem esse token, o relatório sai sem a retenção.
"""

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import cta  # noqa: E402
import postar  # noqa: E402

TOKEN_ANALYTICS = postar.SEGREDOS / "youtube_token_analytics.json"
ESCOPOS_ANALYTICS = ["https://www.googleapis.com/auth/yt-analytics.readonly",
                     "https://www.googleapis.com/auth/youtube.readonly"]
SAIDA = caminhos.PRODUCAO / "metricas"


def _cred_analytics(autorizar: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred = Credentials.from_authorized_user_file(str(TOKEN_ANALYTICS), ESCOPOS_ANALYTICS) if TOKEN_ANALYTICS.exists() else None
    if cred and cred.valid:
        return cred
    if cred and cred.expired and cred.refresh_token and not autorizar:
        try:
            cred.refresh(Request())
            TOKEN_ANALYTICS.write_text(cred.to_json(), encoding="utf-8")
            return cred
        except Exception as e:  # noqa: BLE001
            print(f"(token do Analytics não renovou: {e}; rode --autorizar)")
            return None
    if not autorizar:
        return None
    fluxo = InstalledAppFlow.from_client_secrets_file(str(postar.CLIENTE), ESCOPOS_ANALYTICS)
    cred = fluxo.run_local_server(port=8766, open_browser=False, prompt="consent",
                                  authorization_prompt_message="Abra no navegador e autorize:\n{url}\n")
    TOKEN_ANALYTICS.write_text(cred.to_json(), encoding="utf-8")
    TOKEN_ANALYTICS.chmod(0o600)
    return cred


def coletar() -> list[dict]:
    from googleapiclient.discovery import build

    ja = postar.postados()
    por_id = {v["id"]: k for k, v in ja.items() if v.get("id")}
    if not por_id:
        return []
    yt = build("youtube", "v3", credentials=postar.credenciais())
    videos = []
    ids = list(por_id)
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet,statistics,status", id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            st, sn = it.get("statistics", {}), it["snippet"]
            titulo = sn["title"]
            videos.append({
                "arquivo": por_id[it["id"]], "id": it["id"], "titulo": titulo,
                "tipo_titulo": ja[por_id[it["id"]]].get("tipo_titulo") or cta.tipo_titulo(titulo),
                "status": it["status"]["privacyStatus"], "publicado": sn.get("publishedAt"),
                "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                "comentarios": int(st.get("commentCount", 0)),
            })
    cred = _cred_analytics()
    if cred and videos:
        from googleapiclient.discovery import build as build2
        ya = build2("youtubeAnalytics", "v2", credentials=cred)
        inicio = min(v["publicado"][:10] for v in videos if v["publicado"])
        try:
            rep = ya.reports().query(ids="channel==MINE", startDate=inicio, endDate=date.today().isoformat(),
                                     metrics="views,averageViewPercentage,averageViewDuration", dimensions="video",
                                     filters="video==" + ",".join(v["id"] for v in videos), sort="-views", maxResults=200).execute()
            ret = {r[0]: r for r in rep.get("rows", [])}
            for v in videos:
                if v["id"] in ret:
                    v["retencao_pct"], v["duracao_media_s"] = round(ret[v["id"]][2], 1), round(ret[v["id"]][3], 1)
        except Exception as e:  # noqa: BLE001 - API desativada no projeto, cota etc.: relatório sai sem retenção
            print(f"(retenção indisponível: {str(e)[:200]})")
    return videos


def _idade_h(v: dict) -> float:
    if not v.get("publicado"):
        return 0
    pub = datetime.fromisoformat(v["publicado"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - pub) / timedelta(hours=1)


def resumo(videos: list[dict], min_horas: float) -> dict:
    """Só públicos há min_horas ou mais: vídeo de 3 h contra vídeo de 3 dias não é comparação."""
    base = [v for v in videos if v["status"] == "public" and _idade_h(v) >= min_horas]
    out = {}
    for tipo in ("pergunta", "afirmacao"):
        g = [v for v in base if v["tipo_titulo"] == tipo]
        if not g:
            continue
        ret = [v["retencao_pct"] for v in g if "retencao_pct" in v]
        out[tipo] = {"videos": len(g), "views_mediana": statistics.median(v["views"] for v in g),
                     "views_media": round(statistics.mean(v["views"] for v in g), 1),
                     "comentarios_media": round(statistics.mean(v["comentarios"] for v in g), 2),
                     "retencao_media_pct": round(statistics.mean(ret), 1) if ret else None}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-horas", type=float, default=48)
    ap.add_argument("--autorizar", action="store_true", help="libera a retenção (YouTube Analytics API)")
    a = ap.parse_args()
    if a.autorizar:
        _cred_analytics(autorizar=True)
        print(f"ok: {TOKEN_ANALYTICS}")
        return
    videos = coletar()
    if not videos:
        sys.exit("nenhum vídeo com id no postados.json")
    print(f"{'tipo':9} {'status':8} {'idade':>6} {'views':>6} {'likes':>5} {'coment':>6} {'ret%':>5}  título")
    for v in sorted(videos, key=lambda v: -v["views"]):
        print(f"{v['tipo_titulo']:9} {v['status']:8} {_idade_h(v):5.0f}h {v['views']:6} {v['likes']:5} "
              f"{v['comentarios']:6} {v.get('retencao_pct', '-'):>5}  {v['titulo'][:60]}")
    r = resumo(videos, a.min_horas)
    print(f"\nresumo (públicos há {a.min_horas:.0f} h ou mais):")
    for tipo, d in r.items():
        print(f"  {tipo:9} {d}")
    if len(r) < 2 or min(d["videos"] for d in r.values()) < 5:
        print("  (ainda pouco vídeo para concluir: espere pelo menos 5 de cada tipo)")
    SAIDA.mkdir(parents=True, exist_ok=True)
    arq = SAIDA / f"{date.today():%Y-%m-%d}.json"
    arq.write_text(json.dumps({"videos": videos, "resumo": r}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsalvo em {arq}")


if __name__ == "__main__":
    main()
