"""
Genere data/europe_paths.json : les tracés SVG (attribut `d`) de chaque pays
d'Europe, indexes par code ISO-2, prets a etre inlines dans guide_finder.html
(un seul <path> par pays, cliquable, sans dependance JS a l'execution).

A relancer seulement si la carte doit changer (nouveau pays, cadrage
different). N'a rien a voir avec le registre : aucune dependance a Claude,
stdlib Python uniquement (urllib), pas de requests/numpy/shapely.

Usage :
    python make_europe_map.py --out data/europe_paths.json

Source des donnees : Natural Earth 1:50m (domaine public) via le paquet npm
world-atlas, qui encode les geometries en TopoJSON avec un identifiant ISO
3166-1 NUMERIQUE par pays (ce qui evite le piege connu des codes alpha "-99"
de Natural Earth pour la France et la Norvege). Ecarte : les SVG Wikimedia
(CC BY-SA, partage a l'identique contagieux pour un fichier redistribue),
leakyMirror/map-of-europe (aucune licence publiee), Eurostat GISCO
(attribution EuroGeographics obligatoire), geo-countries (14 Mo, et
France/Norvege a "-99" justement).

Etapes : telechargement (une fois) -> decodage TopoJSON (arcs delta-encodes)
-> fusion de N. Cyprus (geometrie sans id) dans CY -> recadrage sur la
fenetre lon -26..45 / lat 33..72 (ecarte Guyane, Canaries, Svalbard,
Kamtchatka qui feraient exploser le cadrage) -> projection azimutale
equivalente de Lambert centree sur l'Europe -> simplification
(Douglas-Peucker) -> ecriture JSON {"AT": "M... Z", ...}.
"""

import argparse
import json
import math
import urllib.request

WORLD_ATLAS_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json"

# numerique ISO 3166-1 -> alpha-2. Les 27 pays presents dans le registre,
# plus un anneau de pays voisins affiches en gris pour le contexte visuel
# (jamais cliquables, pas de donnees).
TARGET_COUNTRIES = {
    "040": "AT", "056": "BE", "100": "BG", "756": "CH", "196": "CY",
    "203": "CZ", "276": "DE", "208": "DK", "233": "EE", "724": "ES",
    "246": "FI", "250": "FR", "300": "GR", "348": "HU", "372": "IE",
    "380": "IT", "440": "LT", "442": "LU", "428": "LV", "528": "NL",
    "578": "NO", "616": "PL", "620": "PT", "642": "RO", "752": "SE",
    "705": "SI", "703": "SK",
    # dans le perimetre du registre (menu pays de la Commission) mais sans
    # aucun guide enregistre a ce jour : on les veut cliquables sur la carte,
    # distincts des pays hors perimetre (Royaume-Uni, Russie...) en gris.
    "191": "HR", "470": "MT",
}
CONTEXT_COUNTRIES = {
    # uniquement des voisins sans ambiguite europeens (jamais cliquables,
    # juste du gris de repere) : pas de Russie/Turquie/Bielorussie/Ukraine,
    # dont l'essentiel du territoire deborde hors d'Europe et qui n'ont
    # jamais figure au registre.
    "826": "GB", "352": "IS", "688": "RS", "070": "BA",
    "008": "AL", "807": "MK", "499": "ME", "020": "AD", "674": "SM",
    "438": "LI", "492": "MC", "336": "VA",
}
ALL_IDS = dict(TARGET_COUNTRIES, **CONTEXT_COUNTRIES)

# fenetre geographique de recadrage (voir docstring)
LON_MIN, LON_MAX = -26, 45
LAT_MIN, LAT_MAX = 33, 72

# projection : Lambert azimutal equivalent, centre approximatif de l'Europe
PROJ_LON0 = math.radians(10)
PROJ_LAT0 = math.radians(52)

VIEWBOX_W, VIEWBOX_H = 500, 600
PADDING = 8
SIMPLIFY_EPSILON_PX = 0.6


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "make_europe_map.py"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def decode_arcs(topology):
    """Decode chaque arc TopoJSON (deltas quantifies) en liste de (lon, lat)."""
    scale = topology["transform"]["scale"]
    translate = topology["transform"]["translate"]
    decoded = []
    for arc in topology["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x += dx
            y += dy
            points.append((x * scale[0] + translate[0], y * scale[1] + translate[1]))
        decoded.append(points)
    return decoded


def resolve_arc(idx, arcs):
    if idx >= 0:
        return arcs[idx]
    i = ~idx
    return list(reversed(arcs[i]))


def ring_from_arc_indices(indices, arcs):
    points = []
    for idx in indices:
        pts = resolve_arc(idx, arcs)
        if points and points[-1] == pts[0]:
            pts = pts[1:]
        points.extend(pts)
    return points


def geometry_rings(geometry, arcs):
    """Retourne une liste d'anneaux (chacun = liste de (lon,lat)) pour une
    geometrie Polygon ou MultiPolygon. Ignore les trous (anneaux interieurs)
    : a l'echelle d'une carte de filtrage par pays, aucun pays de la liste
    n'a d'enclave interieure visible."""
    rings = []
    gtype = geometry["type"]
    garcs = geometry["arcs"]
    if gtype == "Polygon":
        polygons = [garcs]
    elif gtype == "MultiPolygon":
        polygons = garcs
    else:
        return rings
    for polygon in polygons:
        outer = polygon[0] if polygon else []
        if outer:
            rings.append(ring_from_arc_indices(outer, arcs))
    return rings


def ring_centroid(ring):
    n = len(ring) or 1
    return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n


def in_window(lon, lat):
    return LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX


def project(lon, lat):
    """Lambert azimutal equivalent, sphere unitaire (avant mise a l'echelle)."""
    lam, phi = math.radians(lon), math.radians(lat)
    cosc_arg = math.sin(PROJ_LAT0) * math.sin(phi) + math.cos(PROJ_LAT0) * math.cos(phi) * math.cos(lam - PROJ_LON0)
    cosc_arg = max(-1.0, min(1.0, cosc_arg))
    k = math.sqrt(2.0 / (1.0 + cosc_arg)) if (1.0 + cosc_arg) > 1e-9 else 0.0
    x = k * math.cos(phi) * math.sin(lam - PROJ_LON0)
    y = k * (math.cos(PROJ_LAT0) * math.sin(phi) - math.sin(PROJ_LAT0) * math.cos(phi) * math.cos(lam - PROJ_LON0))
    return x, y


def douglas_peucker(points, epsilon):
    if len(points) < 3:
        return points

    def perp_dist(pt, a, b):
        (x, y), (ax, ay), (bx, by) = pt, a, b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(x - ax, y - ay)
        t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
        px, py = ax + t * dx, ay + t * dy
        return math.hypot(x - px, y - py)

    dmax, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perp_dist(points[i], points[0], points[-1])
        if d > dmax:
            dmax, index = d, i

    if dmax > epsilon:
        left = douglas_peucker(points[: index + 1], epsilon)
        right = douglas_peucker(points[index:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def path_d(rings):
    parts = []
    for ring in rings:
        if len(ring) < 3:
            continue
        pts = ["{:.2f},{:.2f}".format(x, y) for x, y in ring]
        parts.append("M" + "L".join(pts) + "Z")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="data/europe_paths.json")
    parser.add_argument("--source", default=WORLD_ATLAS_URL)
    args = parser.parse_args()

    print(f"Telechargement de {args.source} ...")
    topology = fetch_json(args.source)
    arcs = decode_arcs(topology)

    geometries = topology["objects"]["countries"]["geometries"]
    print(f"{len(geometries)} geometries dans le fichier source.")

    by_id = {}       # numeric id -> list of rings (lon,lat)
    cyprus_extra = []  # anneaux de "N. Cyprus" (pas d'id), a fusionner dans CY

    for geom in geometries:
        gid = geom.get("id")
        name = (geom.get("properties") or {}).get("name", "")
        rings = geometry_rings(geom, arcs)
        if not rings:
            continue
        if not gid and "cyprus" in name.lower():
            cyprus_extra.extend(rings)
            continue
        if gid in ALL_IDS:
            by_id.setdefault(gid, []).extend(rings)

    if "196" in by_id and cyprus_extra:
        by_id["196"].extend(cyprus_extra)
        print("N. Cyprus fusionne dans CY.")

    missing = [code for code in TARGET_COUNTRIES if code not in by_id]
    if missing:
        print("ATTENTION, pays cibles absents de la source :", [TARGET_COUNTRIES[m] for m in missing])

    # recadrage : on jette les anneaux hors fenetre (territoires d'outre-mer,
    # Svalbard, etc.) mais on garde le pays s'il lui reste au moins un anneau
    cropped = {}
    for gid, rings in by_id.items():
        kept = [r for r in rings if in_window(*ring_centroid(r))]
        if kept:
            cropped[gid] = kept

    # projection (sphere unitaire) de tous les points retenus, pour calculer
    # une seule bbox commune -> un seul facteur d'echelle pour toute la carte
    projected = {}
    all_x, all_y = [], []
    for gid, rings in cropped.items():
        proj_rings = []
        for ring in rings:
            pr = [project(lon, lat) for lon, lat in ring]
            proj_rings.append(pr)
            all_x.extend(p[0] for p in pr)
            all_y.extend(p[1] for p in pr)
        projected[gid] = proj_rings

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    span_x, span_y = max_x - min_x, max_y - min_y
    avail_w, avail_h = VIEWBOX_W - 2 * PADDING, VIEWBOX_H - 2 * PADDING
    scale = min(avail_w / span_x, avail_h / span_y)
    off_x = PADDING + (avail_w - span_x * scale) / 2 - min_x * scale
    off_y = PADDING + (avail_h - span_y * scale) / 2

    def to_svg(x, y):
        # y ecran croit vers le bas ; y projete croit vers le nord -> on inverse
        return x * scale + off_x, off_y + (max_y - y) * scale

    paths = {}
    context_paths = {}
    for gid, proj_rings in projected.items():
        svg_rings = []
        for pr in proj_rings:
            svg_pts = [to_svg(x, y) for x, y in pr]
            simplified = douglas_peucker(svg_pts, SIMPLIFY_EPSILON_PX)
            svg_rings.append(simplified)
        d = path_d(svg_rings)
        if gid in TARGET_COUNTRIES:
            paths[TARGET_COUNTRIES[gid]] = d
        else:
            context_paths[CONTEXT_COUNTRIES[gid]] = d

    out = {"viewBox": f"0 0 {VIEWBOX_W} {VIEWBOX_H}", "countries": paths, "context": context_paths}

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    size_kb = os.path.getsize(args.out) / 1024
    print(f"{len(paths)} pays + {len(context_paths)} pays de contexte -> {args.out} ({size_kb:.0f} Ko)")


if __name__ == "__main__":
    main()
