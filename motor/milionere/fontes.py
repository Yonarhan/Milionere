"""Fontes de imagem/vídeo para as cenas. Todas devolvem candidatos no mesmo formato:

    {"ref": "pexels:123", "tipo": "video"|"foto", "thumb": url, "link": url,
     "dur": segundos (vídeo), "desc": texto curto, "credito": texto para a descrição}

- pexels / pixabay: vídeos de banco (campo "busca" da cena)
- wikimedia / met: pinturas e fotos em DOMÍNIO PÚBLICO (campo "arte" da cena) — ótimo para histórias bíblicas
- nasa: imagens reais do espaço, domínio público (campo "arte" da cena) — astronomia
- aic / cleveland: pinturas de museu em domínio público (CC0), sem chave — gospel (campo "arte")
- openverse: fotos CC0 / domínio público / CC-BY de vários acervos (Flickr, museus), sem chave (campo "foto")
- inaturalist: fotos de animais CC0 / CC-BY, sem chave (campo "foto") — animais
Todas liberam uso comercial; as CC-BY exigem crédito, que vai no campo "credito" (entra na descrição do post).
"""

import json
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "roteirista-shorts/1.0 (personal non-commercial video tool)"}


def _json(url: str, headers: dict | None = None) -> dict:
    """GET com JSON. Resposta 429 (muitos pedidos, comum no Wikimedia em paralelo): espera e tenta de novo."""
    import time
    import urllib.error
    for tentativa in range(3):
        req = urllib.request.Request(url, headers={**UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == 2:
                raise
            time.sleep(3 * (tentativa + 1))


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


def aic(termo: str, chaves: dict, n: int = 5) -> list[dict]:
    """Art Institute of Chicago: só obras em domínio público (imagens CC0), servidas por IIIF."""
    dados = _json("https://api.artic.edu/api/v1/artworks/search?" + urllib.parse.urlencode({
        "q": termo, "query[term][is_public_domain]": "true", "limit": 15,
        "fields": "id,title,image_id,artist_title,is_public_domain"}))
    saida = []
    for o in dados.get("data", []):
        if not o.get("image_id") or not o.get("is_public_domain"):
            continue
        base = f"https://www.artic.edu/iiif/2/{o['image_id']}/full"
        saida.append({"ref": f"aic:{o['id']}", "tipo": "foto", "thumb": f"{base}/200,/0/default.jpg",
                      "link": f"{base}/1686,/0/default.jpg", "desc": (o.get("title") or "")[:80],
                      "credito": f"{o.get('title', '')} ({o.get('artist_title') or 'autor desconhecido'}), "
                                 "Art Institute of Chicago, domínio público"})
    return saida[:n]


def cleveland(termo: str, chaves: dict, n: int = 5) -> list[dict]:
    """Cleveland Museum of Art Open Access: só obras CC0 com imagem."""
    dados = _json("https://openaccess-api.clevelandart.org/api/artworks/?" + urllib.parse.urlencode(
        {"q": termo, "cc0": 1, "has_image": 1, "limit": 12}))
    saida = []
    for o in dados.get("data", []):
        web = ((o.get("images") or {}).get("web") or {}).get("url")
        if not web:
            continue
        autor = ((o.get("creators") or [{}])[0].get("description") or "autor desconhecido").split("(")[0].strip()
        saida.append({"ref": f"cleveland:{o['id']}", "tipo": "foto", "thumb": web, "link": web,
                      "desc": (o.get("title") or "")[:80],
                      "credito": f"{o.get('title', '')} ({autor}), Cleveland Museum of Art, CC0"})
    return saida[:n]


LICENCAS_LIVRES = {"cc0", "pdm", "by"}  # sem NC (não comercial), ND (sem derivação) nem SA (obriga a mesma licença)


def openverse(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    """Openverse (WordPress): milhões de fotos abertas. Só CC0, domínio público e CC-BY (com crédito)."""
    dados = _json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": termo, "license": ",".join(sorted(LICENCAS_LIVRES)), "page_size": 15, "mature": "false"}))
    saida = []
    for o in dados.get("results", []):
        if o.get("license") not in LICENCAS_LIVRES or not o.get("url"):
            continue
        lic = "domínio público" if o["license"] in ("cc0", "pdm") else f"CC BY {o.get('license_version', '')}".strip()
        saida.append({"ref": f"openverse:{o['id']}", "tipo": "foto", "thumb": o.get("thumbnail") or o["url"],
                      "link": o["url"], "desc": (o.get("title") or "")[:80],
                      "credito": f"\"{o.get('title', '')}\" por {o.get('creator') or 'autor desconhecido'} ({lic}), via Openverse"})
    return saida[:n]


def inaturalist(termo: str, chaves: dict, n: int = 6) -> list[dict]:
    """iNaturalist: fotos de observações verificadas (research grade), só CC0 e CC-BY."""
    dados = _json("https://api.inaturalist.org/v1/observations?" + urllib.parse.urlencode({
        "q": termo, "photo_license": "cc0,cc-by", "quality_grade": "research", "photos": "true",
        "per_page": 15, "order_by": "votes"}))
    saida = []
    for o in dados.get("results", []):
        for foto in o.get("photos", [])[:1]:
            if (foto.get("license_code") or "") not in ("cc0", "cc-by") or not foto.get("url"):
                continue
            nome = ((o.get("taxon") or {}).get("preferred_common_name") or (o.get("taxon") or {}).get("name") or "")
            saida.append({"ref": f"inaturalist:{foto['id']}", "tipo": "foto", "thumb": foto["url"].replace("square", "small"),
                          "link": foto["url"].replace("square", "large"), "desc": nome[:80],
                          "credito": f"{nome}: {foto.get('attribution') or 'iNaturalist'}"})
    return saida[:n]


FONTES = {"pexels": pexels, "pixabay": pixabay, "wikimedia": wikimedia, "met": met, "nasa": nasa,
          "pixabay_foto": pixabay_foto, "pexels_foto": pexels_foto, "nasa_video": nasa_video,
          "aic": aic, "cleveland": cleveland, "openverse": openverse, "inaturalist": inaturalist}


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
