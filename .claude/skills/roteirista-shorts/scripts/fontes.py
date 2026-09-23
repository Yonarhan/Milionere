"""Fontes de imagem/vídeo para as cenas. Todas devolvem candidatos no mesmo formato:

    {"ref": "pexels:123", "tipo": "video"|"foto", "thumb": url, "link": url,
     "dur": segundos (vídeo), "desc": texto curto, "credito": texto para a descrição}

- pexels / pixabay: vídeos de banco (campo "busca" da cena)
- wikimedia / met: pinturas e fotos em DOMÍNIO PÚBLICO (campo "arte" da cena) — ótimo para histórias bíblicas
- nasa: imagens reais do espaço, domínio público (campo "arte" da cena) — astronomia
"""

import json
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "roteirista-shorts/1.0 (personal non-commercial video tool)"}


def _json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _chaves(config: Path) -> dict:
    with open(config, "rb") as f:
        app = tomllib.load(f)["app"]
    return {"pexels": (app.get("pexels_api_keys") or [""])[0], "pixabay": (app.get("pixabay_api_keys") or [""])[0]}


def pexels(termo: str, chaves: dict, n: int = 8) -> list[dict]:
    dados = _json("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": termo, "per_page": 20, "orientation": "portrait"}), {"Authorization": chaves["pexels"]})
    saida = []
    for v in dados.get("videos", []):
        verticais = [f for f in v.get("video_files", []) if f.get("height") and f["height"] >= f.get("width", 0)]
        hd = [f for f in verticais if f["height"] >= 1280]
        arq = min(hd, key=lambda f: f["height"]) if hd else (max(verticais, key=lambda f: f["height"]) if verticais else None)
        if arq:
            saida.append({"ref": f"pexels:{v['id']}", "tipo": "video", "thumb": v.get("image"), "link": arq["link"],
                          "dur": v.get("duration", 0), "desc": v.get("url", "").rstrip("/").split("/")[-1],
                          "credito": "Pexels"})
    return saida[:n]


def pixabay(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    dados = _json("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": chaves["pixabay"], "q": termo, "per_page": 20, "safesearch": "true"}))
    saida = []
    for v in dados.get("hits", []):
        tam = v.get("videos", {})
        arq = next((tam[k] for k in ("large", "medium", "small") if tam.get(k, {}).get("url")), None)
        if arq:
            saida.append({"ref": f"pixabay:{v['id']}", "tipo": "video", "thumb": arq.get("thumbnail") or tam.get("tiny", {}).get("thumbnail"),
                          "link": arq["url"], "dur": v.get("duration", 0), "desc": v.get("tags", ""), "credito": "Pixabay"})
    return saida[:n]


def wikimedia(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    dados = _json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{termo} filetype:bitmap",
        "gsrnamespace": 6, "gsrlimit": 25, "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400}))
    saida = []
    for pg in sorted(dados.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        info = (pg.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        licenca = meta.get("LicenseShortName", {}).get("value", "")
        if not any(x in licenca.lower() for x in ("public domain", "pd", "cc0")) or info.get("width", 0) < 800:
            continue
        artista = meta.get("Artist", {}).get("value", "")
        artista = artista.split(">")[-2].split("<")[0] if ">" in artista else artista
        saida.append({"ref": f"wikimedia:{pg['pageid']}", "tipo": "foto", "thumb": info.get("thumburl"),
                      "link": info.get("thumburl"), "desc": pg.get("title", "")[5:80],
                      "credito": f"{pg.get('title', '')[5:].rsplit('.', 1)[0]} ({artista.strip() or 'domínio público'}), Wikimedia Commons"})
    return saida[:n]


def met(termo: str, chaves: dict, n: int = 5) -> list[dict]:
    ids = _json("https://collectionapi.metmuseum.org/public/collection/v1/search?" + urllib.parse.urlencode(
        {"hasImages": "true", "q": termo})).get("objectIDs") or []
    saida = []
    for oid in ids[:20]:
        try:
            o = _json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}")
        except Exception:
            continue
        if o.get("isPublicDomain") and o.get("primaryImage"):
            saida.append({"ref": f"met:{oid}", "tipo": "foto", "thumb": o.get("primaryImageSmall") or o["primaryImage"],
                          "link": o["primaryImage"], "desc": o.get("title", "")[:80],
                          "credito": f"{o.get('title', '')} ({o.get('artistDisplayName') or 'autor desconhecido'}), The Met, domínio público"})
        if len(saida) >= n:
            break
    return saida


def nasa(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    dados = _json("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": termo, "media_type": "image"}))
    saida = []
    for it in dados.get("collection", {}).get("items", [])[:n * 2]:
        d = (it.get("data") or [{}])[0]
        thumb = next((l["href"] for l in it.get("links", []) if l.get("render") == "image"), None)
        if thumb:
            saida.append({"ref": f"nasa:{d.get('nasa_id')}", "tipo": "foto", "thumb": thumb,
                          "link": thumb.replace("~thumb", "~medium"), "desc": d.get("title", "")[:80],
                          "credito": "NASA"})
    return saida[:n]


def pixabay_foto(termo: str, chaves: dict, n: int = 8) -> list[dict]:
    """Fotos e ilustrações do Pixabay (muitas cenas bíblicas feitas por IA, licença livre)."""
    dados = _json("https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": chaves["pixabay"], "q": termo, "orientation": "vertical", "per_page": 30, "safesearch": "true"}))
    return [{"ref": f"pixabayfoto:{h['id']}", "tipo": "foto", "thumb": h["webformatURL"], "link": h["largeImageURL"],
             "desc": h.get("tags", ""), "credito": "Pixabay"} for h in dados.get("hits", [])][:n]


def pexels_foto(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    dados = _json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": termo, "orientation": "portrait", "per_page": 20}), {"Authorization": chaves["pexels"]})
    return [{"ref": f"pexelsfoto:{p['id']}", "tipo": "foto", "thumb": p["src"]["medium"], "link": p["src"]["large2x"],
             "desc": p.get("alt", ""), "credito": "Pexels"} for p in dados.get("photos", [])][:n]


def nasa_video(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    """Vídeos e animações da NASA (domínio público): buracos negros, supernovas, sondas, simulações."""
    dados = _json("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": termo, "media_type": "video"}))
    saida = []
    for it in dados.get("collection", {}).get("items", [])[: n * 2]:
        d = (it.get("data") or [{}])[0]
        thumb = next((l["href"] for l in it.get("links", []) if l.get("render") == "image"), None)
        try:
            arquivos = [a["href"] for a in _json(f"https://images-api.nasa.gov/asset/{urllib.parse.quote(d['nasa_id'])}")["collection"]["items"]]
        except Exception:
            continue
        mp4 = next((a for tam in ("~mobile.mp4", "~small.mp4", "~medium.mp4", "~orig.mp4") for a in arquivos if a.endswith(tam)), None)
        if thumb and mp4:
            saida.append({"ref": f"nasavideo:{d['nasa_id']}", "tipo": "video", "thumb": thumb, "link": mp4.replace("http://", "https://"),
                          "dur": 20, "desc": d.get("title", "")[:80], "credito": "NASA"})
        if len(saida) >= n:
            break
    return saida


FONTES = {"pexels": pexels, "pixabay": pixabay, "wikimedia": wikimedia, "met": met, "nasa": nasa,
          "pixabay_foto": pixabay_foto, "pexels_foto": pexels_foto, "nasa_video": nasa_video}


def buscar_candidatos(cena: dict, fontes_video: list[str], fontes_arte: list[str], config: Path,
                      evitar: list[str] | None = None, fontes_foto: list[str] | None = None) -> list[dict]:
    chaves = _chaves(config)
    pedidos = []
    if cena.get("foto"):  # ilustração/foto específica (ex.: "jesus crying") — vem primeiro na folha
        pedidos += [(f, t) for f in (fontes_foto or []) for t in cena["foto"].split("|")[:2]]
    pedidos += [(f, t) for f in fontes_video for t in cena["busca"].split("|")[:2]]
    if cena.get("arte"):
        pedidos += [(f, t) for f in fontes_arte for t in cena["arte"].split("|")[:2]]
    vistos, saida = set(), []
    for fonte, termo in pedidos:
        try:
            achados = FONTES[fonte](termo.strip(), chaves)
        except Exception as e:  # uma fonte fora do ar não derruba as outras
            print(f"  aviso: {fonte} '{termo}' falhou: {e}")
            continue
        for c in achados:
            texto = f"{c['desc']} {c['link']}".lower()
            if c["ref"] in vistos or any(e in texto for e in (evitar or [])):
                continue
            vistos.add(c["ref"])
            saida.append(c)
    return saida
