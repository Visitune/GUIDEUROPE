"""
Assemble l'outil autonome guide_finder.html a partir du template
(guide_finder_template.html) et des donnees generees (data/guides.json,
data/europe_paths.json, data/meta.json).

A relancer a chaque fois que les donnees sont mises a jour :

    python scrape_hygiene_register.py --out data/guides.json --check-links
    python build_tool.py

Et seulement si la carte doit changer (rare) :

    python make_europe_map.py --out data/europe_paths.json
    python build_tool.py

Ne necessite aucune dependance externe (juste la stdlib).
"""

import json
import os

TEMPLATE = "guide_finder_template.html"
OUT = "guide_finder.html"

SOURCES = {
    "__GUIDES_JSON__": "data/guides.json",
    "__EUROPE_PATHS_JSON__": "data/europe_paths.json",
    "__META_JSON__": "data/meta.json",
}


def load_payload(path):
    if not os.path.exists(path):
        return "null"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # JSON compact, et on echappe tout '<' pour qu'aucune sequence
    # "</script>" (ou autre balise) ne puisse jamais apparaitre a l'interieur
    # d'un <script type="application/json"> qui embarque les donnees.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return payload.replace("<", "\\u003c")


def main():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()

    guides_count = None
    for placeholder, path in SOURCES.items():
        if placeholder not in html:
            raise SystemExit(f"Placeholder {placeholder} introuvable dans {TEMPLATE}")
        payload = load_payload(path)
        if placeholder == "__GUIDES_JSON__" and payload != "null":
            guides_count = len(json.loads(payload.replace("\\u003c", "<")))
        html = html.replace(placeholder, payload)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    n = f"{guides_count} guides" if guides_count is not None else "aucune donnee (data/guides.json absent)"
    print(f"{OUT} genere avec {n} ({len(html) / 1024:.0f} Ko).")


if __name__ == "__main__":
    main()
