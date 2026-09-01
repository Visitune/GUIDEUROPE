# Registre des guides d'hygiène UE — outil VisiPilot

Web app autonome (un seul fichier HTML, pas de serveur ni d'installation)
pour filtrer, comparer entre pays et repérer les guides nationaux de bonnes
pratiques d'hygiène les plus pertinents. Pensé pour un usage professionnel
(auditeurs, consultants, responsables qualité) : benchmark multi-pays,
recherche ponctuelle, veille sur les guides récents.

**Distinction importante** : l'outil (interface, filtres, recherche,
comparaison) est un produit VisiPilot — design system VisiPilot (Inter +
JetBrains Mono, orange `#F97316`, dark/light). **Les données ne sont pas de
VisiPilot** : ce sont les guides nationaux tels qu'enregistrés par le
registre public de la Commission européenne
(https://webgate.ec.europa.eu/dyna2/hygienelegislation/), rappelé dans
l'en-tête, dans la modale d'aide et dans chaque export. VisiPilot ne rédige
ni ne valide le contenu des guides.

## Utiliser l'outil

Ouvre **`guide_finder.html`** directement dans un navigateur (double-clic).
Aucune installation, aucun serveur, aucune requête réseau au chargement :
les 697 guides, la carte, le logo et les polices (Inter + JetBrains Mono,
sous-ensembles latin/latin-ext) sont tous embarqués dans le fichier —
utilisable sans connexion. ~1,8 Mo au total.

- **Recherche multilingue** : le corpus est très majoritairement italien/
  allemand/français/néerlandais (20 guides sur 697 seulement sont en
  anglais). Un glossaire embarqué fait le pont — taper « traçabilité »,
  « fromage » ou « nettoyage » trouve aussi les guides italiens/allemands
  correspondants. Insensible aux accents, plusieurs mots = ET logique,
  termes trouvés surlignés. Raccourci `/` pour y accéder, `Échap` pour
  effacer.
- **Filtres** : année d'édition (histogramme cliquable par période de 5 ans,
  y compris « année non connue »), pays (liste avec recherche + tout
  sélectionner/désélectionner, ou carte), type, thème, produit. Chaque
  option affiche le nombre de résultats qu'elle donnerait compte tenu des
  autres filtres actifs. Chaque panneau de filtre est repliable
  (`<details>` natif).
- **Carte d'Europe** cliquable (bouton « Afficher la carte »), synchronisée
  avec la liste de pays. Intensité = nombre de guides. La Croatie et Malte
  sont dans le périmètre du registre mais n'ont aucun guide : elles
  apparaissent dans un style distinct plutôt que d'être simplement absentes.
- **Classification déduite** : 429 guides sur 697 n'ont aucun thème dans le
  registre officiel. Des règles multilingues déduisent un thème plausible
  depuis le titre (marqué visuellement « déduit », jamais confondu avec la
  donnée officielle) — désactivable via l'interrupteur « Inclure les thèmes
  déduits ». Un chip « Non classé » rend visible ce qui reste réellement
  sans thème, au lieu de le masquer.
- **Sélection temporaire** : une étoile sur chaque guide (carte ou tableau)
  l'ajoute à une sélection ; le bouton étoile de l'en-tête n'affiche que la
  sélection — pratique pour l'exporter ou la comparer isolément.
- **Fiche détaillée** par guide (bouton « Détails » ou clic sur le titre en
  mode Tableau) : tous les champs (thème officiel/déduit, étape, résumé,
  contact, statut et date de vérification du lien...) sur une seule fiche,
  avec URL directement partageable (`#detail=...`).
- **3 modes d'affichage** : Liste (cartes détaillées), Tableau (dense,
  colonnes triables, accessible clavier avec `aria-sort`), Comparer (matrice
  Thème/Étape/Produit × pays au choix, avec code couleur — bascule Nombre de
  guides / Année la plus récente — clic sur une cellule pour voir le détail ;
  vue côte-à-côte en complément).
- **Fiabilité des liens** : 256 guides sur 697 ont un lien externe (le
  registre n'en fournit pas pour les 441 autres) — chacun de ces 256 liens a
  été testé (154 valides, 102 signalés morts). Un lien mort affiche un
  avertissement et, quand une copie existe, un bouton « Version archivée »
  (Wayback Machine, 70 cas). La fiche du registre européen est toujours
  proposée en repli, elle est fiable à 100%.
- **Export CSV** (UTF-8 + BOM, séparateur `;`, colonnes enrichies : étape,
  résumé, contact, source de classification, lien archivé, statut HTTP, date
  de vérification) et **export JSON**, de la liste filtrée, de la sélection
  ou de la matrice de comparaison.
- **État partageable** : les filtres actifs (et la fiche ouverte) vivent
  dans l'URL (`#pays=...`) et sont mémorisés localement — recharger la page
  restaure la même vue. Bouton dédié pour copier le lien.
- **Aide contextuelle** : bouton « ? » en haut à droite (modale affichée
  automatiquement au premier chargement), avec le lien direct vers le
  registre officiel et un résumé de la qualité des données.
- **Responsive** : sous 900px de large, le panneau de filtres devient une
  feuille plein écran ouverte via un bouton flottant « Filtres », avec un
  bouton « Voir les résultats » toujours visible en bas — pas besoin de
  faire défiler tous les filtres avant d'atteindre les résultats.

## Rafraîchir les données

Le registre de la Commission bouge de temps en temps. Pour repartir sur des
données à jour, sans repasser par Claude :

```bash
pip install requests beautifulsoup4 lxml   # une seule fois

python scrape_hygiene_register.py --out data/guides.json --check-links
python build_tool.py
```

`scrape_hygiene_register.py` télécharge la liste complète du registre
(https://webgate.ec.europa.eu/dyna2/hygienelegislation/, ~700 guides, ~27
pays), va chercher sur chaque fiche détail l'année d'édition, l'éditeur, le
résumé et le lien direct (3-5 minutes), déduit un thème pour les guides non
classés, puis (avec `--check-links`) teste chaque lien externe et cherche
une copie archive.org pour ceux qui sont morts (+3-4 minutes). Écrit aussi
`data/meta.json` (date du scrape, compteurs, taux de liens valides).

`build_tool.py` réinjecte `data/guides.json`, `data/europe_paths.json` et
`data/meta.json` dans `guide_finder_template.html` pour régénérer
`guide_finder.html`.

Options utiles :

```bash
python scrape_hygiene_register.py --out data/guides.json --limit 20   # test rapide
python scrape_hygiene_register.py --out data/guides.json --skip-details  # sans année/PDF, plus rapide
```

Le registre contient de très rares titres saisis sans espace entre deux mots
(ex. « ofDoner » au lieu de « of Doner »). Corrigés au cas par cas dans
`GLUED_WORD_FIXES` (`scrape_hygiene_register.py`) — volontairement pas une
règle générique automatique : testée sur les 697 titres réels, elle aurait
aussi cassé le nom de certification légitime « EurepGap » en « Eurep Gap ».
Si un nouveau cas apparaît à un futur scrape, l'ajouter à la main dans ce
dictionnaire après vérification, plutôt que de réintroduire une heuristique
automatique.

La carte (`data/europe_paths.json`) n'a besoin d'être régénérée que si son
cadrage ou sa liste de pays doit changer — ce n'est pas lié au registre :

```bash
python make_europe_map.py --out data/europe_paths.json
python build_tool.py
```

## Mémorisation locale (localStorage) et `file://`

Les filtres, la sélection favorite et « avoir déjà vu l'aide » sont mémorisés
via `localStorage`. Certains navigateurs (Chrome en configuration stricte,
notamment) bloquent `localStorage` pour les pages ouvertes en `file://`
(double-clic). Dans ce cas précis, testé explicitement : l'outil fonctionne
normalement, il ne mémorise simplement rien d'une ouverture à l'autre (la
modale d'aide se réaffiche à chaque fois, par exemple). Aucune erreur, aucune
fonctionnalité perdue par ailleurs.

## Ce que couvrent les données

Chaque guide a : pays, type (Food/Feed/Food-Feed), titre original + titre
anglais, thème(s) officiel(s) et déduit(s), produit(s), étape, résumé,
langue, année d'édition (brute et normalisée), éditeur, contact, lien direct
(quand le registre en fournit un, avec repli sur la fiche registre et, pour
les liens morts, une copie archive.org), état de vérification du lien.

Ce ne sont que des **métadonnées** — pas le contenu des PDF eux-mêmes. Une
recherche/comparaison sur le contenu réel des guides (texte des PDF, souvent
non-anglais) resterait un projet à part : téléchargement, OCR/traduction,
indexation et RAG. Volontairement pas fait ici — à lancer si besoin, pays ou
thème prioritaire plutôt que sur tout le registre d'un coup.

Le registre de la Commission contient lui-même des liens cassés (texte libre
mal formaté côté Commission, ou site national qui a bougé). Le scraper
répare automatiquement les liens reconstructibles et cherche une archive
pour le reste.

## Simplifications assumées (par rapport à une version idéale)

- La dimension **Produit** de la matrice de comparaison se limite aux 10
  produits les plus fréquents + « Autres produits » + « Non renseigné » (58
  valeurs distinctes existent dans le registre — les afficher toutes en
  lignes de matrice serait illisible).
- La traduction FR des valeurs de facettes couvre le type, les 6 thèmes et
  les étapes les plus fréquentes ; les valeurs plus rares restent affichées
  telles quelles (repli, pas d'erreur).
- Le fichier reste un template HTML unique (pas de découpage en plusieurs
  fichiers sources) : plus simple à faire évoluer soi-même sans étape de
  build supplémentaire, au prix d'un seul gros fichier (~100 Ko de code, hors
  polices, logo et données embarqués).
- Le logo VisiPilot est embarqué en PNG (seul format disponible actuellement,
  `logo-horizontal.png` du skill `visipilot-design`), pas en SVG — suffisant
  à la taille d'affichage (~26px de haut) mais à remplacer par un SVG si une
  version imprimée/agrandie est nécessaire un jour.
- Pas d'export XLSX natif (nécessiterait une librairie chargée depuis un
  CDN, contraire au principe « zéro dépendance réseau ») — le CSV/JSON
  couvrent l'usage, et le CSV s'ouvre nativement dans Excel.
- La sélection favorite et les filtres mémorisés utilisent `localStorage`,
  indisponible pour certains navigateurs en `file://` (voir plus bas) :
  l'outil reste pleinement fonctionnel, juste sans mémoire d'une session à
  l'autre dans ce cas précis.

## Fichiers

- `guide_finder.html` — l'outil, à ouvrir directement.
- `guide_finder_template.html` — le template source (HTML/CSS/JS), avec les
  marqueurs `__GUIDES_JSON__`, `__EUROPE_PATHS_JSON__`, `__META_JSON__`.
- `build_tool.py` — génère `guide_finder.html` à partir du template + des
  données.
- `scrape_hygiene_register.py` — scrape le registre UE, classification
  déduite, vérification des liens, repli archive.org.
- `make_europe_map.py` — génère la géométrie de la carte (Natural Earth,
  domaine public) en tracés SVG prêts à l'emploi, sans dépendance JS.
- `data/guides.json`, `data/europe_paths.json`, `data/meta.json` — données
  actuelles.
- `extracted/` — ancienne maquette React/Vite d'une session précédente,
  conservée mais remplacée par l'outil autonome ci-dessus.
