"""
Scraper pour le Registre UE des guides nationaux de bonnes pratiques d'hygiene
https://webgate.ec.europa.eu/dyna2/hygienelegislation/

A relancer quand tu veux pour rafraichir les donnees (le registre est mis a jour
par la Commission de temps en temps). Aucune dependance a Claude : c'est un
script Python autonome.

Installation (une seule fois) :
    pip install requests beautifulsoup4 lxml

Usage :
    # Scrape complet (liste + fiche detail de chaque guide : annee, editeur, PDF)
    python scrape_hygiene_register.py --out data/guides.json

    # + verification des liens externes (ok/bloque/mort) et repli archive.org
    python scrape_hygiene_register.py --out data/guides.json --check-links

    # Rapide : juste la liste (pays/titre/theme), sans annee ni lien PDF direct
    python scrape_hygiene_register.py --out data/guides.json --skip-details

    # Test sur un petit echantillon avant de lancer le scrape complet
    python scrape_hygiene_register.py --out data/guides_sample.json --limit 20

Le scrape complet (~700 guides) fait ~700 requetes vers webgate.ec.europa.eu
(une par fiche detail), avec 4 requetes en parallele et une petite pause entre
chaque lot pour rester correct vis-a-vis du serveur. Ca prend 3-5 minutes.
Avec --check-links, ~3-4 minutes de plus pour tester les ~250 liens externes.

Ecrit aussi data/meta.json (date du scrape, compteurs, taux de liens valides).
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://webgate.ec.europa.eu/dyna2/hygienelegislation/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; food-safety-research-bot/1.0; +personal use)"
}


def fetch(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    # Le serveur declare correctement charset=UTF-8 dans Content-Type ;
    # requests s'en sert deja pour resp.text. On force juste un fallback
    # au cas ou l'en-tete manquerait sur certaines pages.
    if not resp.encoding:
        resp.encoding = "utf-8"
    return resp.text


# Correctifs cibles, un par un, pour de rares titres saisis cote Commission
# sans espace entre deux mots (ex. 'preparation ofDoner kebab'). Volontairement
# PAS une regle generique de type "minuscule suivie d'une majuscule" : verifie
# sur les 697 titres reels, ce motif ne matche que 2 cas, et l'un des deux
# ('EurepGap', un nom de certification legitime) serait casse a tort en
# 'Eurep Gap'. Mieux vaut une liste courte et sure qu'une heuristique qui
# peut corrompre un futur titre legitime. A completer si un nouveau cas
# apparait lors d'un prochain scrape (verifier a la main avant d'ajouter).
GLUED_WORD_FIXES = {
    "ofDoner": "of Doner",
}


def fix_glued_words(text):
    if not text:
        return text
    for bad, good in GLUED_WORD_FIXES.items():
        text = text.replace(bad, good)
    return text


def parse_list(html: str):
    """Parse la table principale (une ligne = un guide, tous pays confondus)."""
    soup = BeautifulSoup(html, "lxml")

    table = soup.find("table", id="datatable-example")
    if table is None:
        for t in soup.find_all("table"):
            header_text = t.get_text(" ", strip=True).lower()
            if "country" in header_text and "original title" in header_text:
                table = t
                break

    if table is None:
        print(
            "Impossible de trouver la table de resultats. Le site a peut-etre "
            "change de structure. Verifie 'page.html' telecharge a la main.",
            file=sys.stderr,
        )
        return []

    tbody = table.find("tbody") or table
    guides = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 8:
            continue  # ligne d'en-tete ou incomplete

        def cell_text(i):
            return cells[i].get_text(" ", strip=True)

        country = cell_text(0)
        guide_type = cell_text(1)

        original_link = cells[2].find("a")
        english_link = cells[3].find("a")

        title_original = fix_glued_words(original_link.get_text(strip=True) if original_link else cell_text(2))
        title_en = fix_glued_words(english_link.get_text(strip=True) if english_link else cell_text(3))

        detail_url = None
        if english_link and english_link.get("href"):
            detail_url = english_link["href"].strip()
        elif original_link and original_link.get("href"):
            detail_url = original_link["href"].strip()
        if detail_url and detail_url.startswith("/"):
            detail_url = "https://webgate.ec.europa.eu" + detail_url

        if not country or not title_en:
            continue

        guides.append(
            {
                "country": country,
                "type": guide_type,
                "title_original": title_original,
                "title_en": title_en,
                "stage": cell_text(4),
                "issue": [s.strip() for s in cell_text(5).split(",") if s.strip()],
                "product": [s.strip() for s in cell_text(6).split(",") if s.strip()],
                "focus": [s.strip() for s in cell_text(7).split(",") if s.strip()],
                "detail_url": detail_url,
            }
        )

    return guides


DETAIL_FIELDS = {
    "Language": "language",
    "Summary": "summary",
    "Year/Edition": "year",
    "Publisher/Author": "publisher",
    "Contact point": "contact",
    "ISBN, ISSN": "isbn",
    "Direct link to guide": "pdf_url",
    # Stage/Issue/Product existent deja (categories fixes du tableau liste,
    # utilisees par les filtres). La fiche detail donne une sous-categorie
    # plus fine ("Other : Hygiene and HACCP" au lieu de juste "Other") : on
    # la garde a part, en texte libre, pour la recherche et l'affichage —
    # sans toucher aux categories fixes dont dependent les filtres.
    "Stage": "stage_detail",
    "Issue": "issue_detail",
    "Product": "product_detail",
}


BROKEN_SELF_LINK_RE = re.compile(
    r"^https://webgate\.ec\.europa\.eu/dyna2/hygienelegislation/show/\d+/(.+)$"
)
DOMAIN_RE = re.compile(r"\.[a-zA-Z]{2,}")


def repair_pdf_url(url):
    """Le champ 'Direct link to guide' du registre est parfois du texte libre
    sans schema ('www.afsca.be', 'info@x.com', 'no published', '-'...). Le
    CMS de la Commission le transforme alors, a tort, en lien absolu casse
    qui pointe vers sa propre page (ex.
    '.../show/1490/www.afsca.be' au lieu de 'https://www.afsca.be'). On
    detecte ce motif et on reconstruit l'URL externe qu'il etait cense etre ;
    quand le texte n'est manifestement pas une URL (email, tiret, plusieurs
    domaines separes par une virgule, pas de TLD...), on renonce (None) pour
    laisser l'app retomber sur la fiche du registre, qui elle marche
    toujours."""
    if not url:
        return None

    m = BROKEN_SELF_LINK_RE.match(url)
    if m:
        tail = m.group(1).strip()
        tail = re.split(r"[,\s]+", tail)[0] if tail else ""
        if not tail or "@" in tail or not DOMAIN_RE.search(tail):
            return None
        return "https://" + tail

    if not url.startswith("http"):
        return None

    return url


def parse_detail(html: str) -> dict:
    """Parse une fiche detail. La page rend chaque champ comme une ligne
    bootstrap : `<div class="row"><div class="col-sm-2"><label>Label</label>
    </div><div class="col-sm-4">Valeur</div></div>`. On cherche le label
    connu, remonte a la ligne, et prend le premier `col-sm-*` suivant qui
    n'est pas la colonne du label."""
    soup = BeautifulSoup(html, "lxml")
    result = {}

    for label, key in DETAIL_FIELDS.items():
        label_tag = soup.find("label", string=lambda s: s and s.strip() == label)
        if not label_tag:
            continue
        label_col = label_tag.find_parent("div")
        row = label_col.find_parent("div", class_="row") if label_col else None
        if not row:
            continue
        value_col = label_col.find_next_sibling("div")
        if value_col is None:
            continue
        link = value_col.find("a")
        if link and link.get("href"):
            result[key] = link["href"].strip()
        else:
            text = value_col.get_text(" ", strip=True)
            result[key] = text or None

    if "pdf_url" in result:
        result["pdf_url"] = repair_pdf_url(result["pdf_url"])

    return result


def enrich_with_details(guides, workers: int, delay: float):
    total = len(guides)
    done = 0

    def worker(guide):
        if not guide.get("detail_url"):
            return guide, {}
        try:
            html = fetch(guide["detail_url"])
            return guide, parse_detail(html)
        except Exception as exc:  # noqa: BLE001 - on veut juste logguer et continuer
            print(f"  [!] echec sur {guide['detail_url']}: {exc}", file=sys.stderr)
            return guide, {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, g): g for g in guides}
        for fut in as_completed(futures):
            guide, details = fut.result()
            guide.update(details)
            done += 1
            if done % 25 == 0 or done == total:
                print(f"  fiches detail : {done}/{total}")
            time.sleep(delay)

    return guides


YEAR_RE = None  # compiled lazily, see normalize_year


def normalize_year(raw):
    """Le champ 'Year/Edition' est du texte libre ('2018', 'Validated 30/9/15',
    '1 dd 29/05/2013', 'weekly update', '?', ...). On en extrait un entier
    utilisable pour trier/filtrer par recence : le plus grand nombre a 4
    chiffres plausible (1990-annee courante+1) trouve dans le texte."""
    global YEAR_RE
    if not raw:
        return None
    if YEAR_RE is None:
        YEAR_RE = re.compile(r"(19[9]\d|20[0-4]\d)")
    matches = [int(m) for m in YEAR_RE.findall(raw)]
    return max(matches) if matches else None


# ---------------------------------------------------------------------------
# Classification deduite : 429 guides sur 697 n'ont AUCUN theme dans le
# registre officiel (le champ "issue" de la liste est vide, et la fiche
# detail n'en ajoute pas). Plutot que de laisser le filtre Theme masquer 62%
# du corpus, on deduit un theme plausible depuis le titre par des regles
# multilingues transparentes (le corpus est majoritairement IT/DE/FR/NL, pas
# anglais). Marque a part (issue_derived) : jamais confondu avec la donnee
# officielle du registre (issue).
# ---------------------------------------------------------------------------

ISSUE_RULES = [
    ("HACCP", re.compile(r"\bhaccp\b", re.IGNORECASE)),
    (
        "GHP/GMP",
        re.compile(
            r"\bghp\b|\bgmp\b|good hygien|good manufactur|"
            r"bonnes? pratiques? d.hygi|bpf\b|bph\b|"
            r"buona prassi igien|buone prassi igien|corretta prassi igien|"
            r"gute hygienepraxis|hygienepraxis|hygieneleitlinie|"
            r"hygi.necode|goede hygi.nepraktijk|god hygienepraksis|"
            r"buenas pr.cticas de higiene|boas pr.ticas de higiene",
            re.IGNORECASE,
        ),
    ),
    (
        "Recall",
        re.compile(
            r"\brecall\b|\bretrait\b|\brappel\b|\brichiamo\b|\br.ckruf\b|"
            r"terugroep|tilbagekald|tillbakakallelse",
            re.IGNORECASE,
        ),
    ),
]


def derive_issues(guide):
    """Retourne la liste des themes deduits du titre (voir ISSUE_RULES),
    sans jamais modifier `issue` (verite du registre)."""
    hay = " ".join(filter(None, [guide.get("title_en"), guide.get("title_original"), guide.get("summary")]))
    found = []
    for label, pattern in ISSUE_RULES:
        if pattern.search(hay):
            found.append(label)
    return found


def apply_classification(guides):
    for g in guides:
        official = g.get("issue") or []
        derived = [i for i in derive_issues(g) if i not in official]
        g["issue_derived"] = derived
        if official and derived:
            g["classification_source"] = "mixte"
        elif official:
            g["classification_source"] = "registre"
        elif derived:
            g["classification_source"] = "deduit"
        else:
            g["classification_source"] = "aucune"
    return guides


# ---------------------------------------------------------------------------
# Verification des liens : ~37% des guides ont un lien externe (pdf_url ou
# contact) qui pointe vers un site national jamais revalide par la
# Commission depuis son enregistrement. On teste chaque lien (HEAD puis GET
# en repli) et on distingue un blocage anti-robot (403/406/429 : le lien
# fonctionne dans un vrai navigateur) d'un lien vraiment mort (404/410/5xx),
# sans quoi on produirait de faux "liens morts". Pour les liens vraiment
# morts, on cherche une copie archivee sur archive.org.
# ---------------------------------------------------------------------------

LINK_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BLOCKED_CODES = {401, 403, 406, 429}
DEAD_CODES = {404, 410}


def check_one_link(url, timeout=8):
    """Renvoie (status, http_code) avec status in {ok, blocked, dead, unchecked}."""
    try:
        r = requests.head(url, headers=LINK_HEADERS, timeout=timeout, allow_redirects=True)
        code = r.status_code
        if code == 405 or code >= 500:
            r = requests.get(url, headers=LINK_HEADERS, timeout=timeout, stream=True)
            code = r.status_code
    except requests.RequestException:
        return "dead", None

    if code < 400:
        return "ok", code
    if code in BLOCKED_CODES:
        return "blocked", code
    if code in DEAD_CODES or code >= 500:
        return "dead", code
    return "dead", code


def archive_lookup(url, timeout=10, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                "https://archive.org/wayback/available",
                params={"url": url},
                timeout=timeout,
            )
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            snap = (data.get("archived_snapshots") or {}).get("closest") or {}
            if snap.get("available") and snap.get("url"):
                return snap["url"].replace("http://", "https://", 1)
            return None
        except (requests.RequestException, ValueError):
            return None
    return None


def link_to_check(guide):
    if guide.get("pdf_url"):
        return guide["pdf_url"]
    contact = guide.get("contact") or ""
    if contact.startswith("http"):
        return contact
    return None


def check_links(guides, workers: int, delay: float):
    targets = [g for g in guides if link_to_check(g)]
    total = len(targets)
    print(f"Verification de {total} liens externes...")
    done = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def worker(guide):
        url = link_to_check(guide)
        status, code = check_one_link(url)
        return guide, status, code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, g): g for g in targets}
        for fut in as_completed(futures):
            guide, status, code = fut.result()
            guide["link_status"] = status
            guide["link_http"] = code
            guide["link_checked_at"] = now
            done += 1
            if done % 25 == 0 or done == total:
                print(f"  liens verifies : {done}/{total}")
            time.sleep(delay)

    # archive.org limite le debit (429 rapidement) : on interroge les liens
    # morts en sequence, avec une pause large, plutot qu'en parallele avec
    # les verifications de liens ci-dessus.
    dead = [g for g in guides if g.get("link_status") == "dead"]
    if dead:
        print(f"Recherche d'archives pour {len(dead)} liens morts...")
        found = 0
        for i, g in enumerate(dead, 1):
            url = link_to_check(g)
            archive_url = archive_lookup(url)
            if archive_url:
                g["archive_url"] = archive_url
                found += 1
            if i % 20 == 0 or i == len(dead):
                print(f"  archives verifiees : {i}/{len(dead)} ({found} trouvees)")
            time.sleep(1.2)

    for g in guides:
        if "link_status" not in g:
            g["link_status"] = "unchecked" if link_to_check(g) else "aucun"

    return guides


def write_meta(guides, out_path):
    import os

    n = len(guides)
    checked = [g for g in guides if g.get("link_status") in ("ok", "blocked", "dead")]
    ok = sum(1 for g in checked if g["link_status"] in ("ok", "blocked"))
    meta = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_guides": n,
        "total_countries": len({g["country"] for g in guides}),
        "links_checked": len(checked),
        "links_valid": ok,
        "link_validity_rate": round(ok / len(checked), 3) if checked else None,
        "classified_official": sum(1 for g in guides if g.get("classification_source") == "registre"),
        "classified_derived": sum(1 for g in guides if g.get("classification_source") in ("deduit", "mixte")),
        "unclassified": sum(1 for g in guides if g.get("classification_source") == "aucune"),
    }
    meta_path = os.path.join(os.path.dirname(out_path) or ".", "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Ecrit {meta_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="data/guides.json", help="Fichier JSON de sortie")
    parser.add_argument("--skip-details", action="store_true", help="Ne pas aller chercher annee/editeur/PDF sur chaque fiche (plus rapide)")
    parser.add_argument("--limit", type=int, default=None, help="Ne traiter que les N premiers guides (pour tester)")
    parser.add_argument("--workers", type=int, default=4, help="Requetes en parallele pour les fiches detail (defaut: 4)")
    parser.add_argument("--delay", type=float, default=0.15, help="Pause en secondes apres chaque fiche detail (defaut: 0.15)")
    parser.add_argument("--check-links", action="store_true", help="Teste chaque lien externe (HEAD/GET) et cherche une copie archive.org pour les liens morts (+3-4 min)")
    parser.add_argument("--debug", action="store_true", help="Affiche un apercu du HTML brut de la liste et s'arrete")
    args = parser.parse_args()

    print(f"Telechargement de {BASE_URL} ...")
    html = fetch(BASE_URL)

    if args.debug:
        print(html[:5000])
        return

    guides = parse_list(html)
    print(f"{len(guides)} guides trouves dans le registre.")

    if args.limit:
        guides = guides[: args.limit]
        print(f"(limite a {len(guides)} pour ce run)")

    if not args.skip_details:
        print("Recuperation des fiches detail (annee, editeur, lien PDF direct)...")
        guides = enrich_with_details(guides, workers=args.workers, delay=args.delay)
        for g in guides:
            g["year_normalized"] = normalize_year(g.get("year"))

    guides = apply_classification(guides)

    if args.check_links:
        guides = check_links(guides, workers=args.workers, delay=args.delay)

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(guides, f, ensure_ascii=False, indent=2)

    print(f"Ecrit {len(guides)} guides dans {args.out}")
    write_meta(guides, args.out)


if __name__ == "__main__":
    main()
