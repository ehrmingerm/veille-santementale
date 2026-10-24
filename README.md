# veille-sante-mentale

Collecte quotidienne des sources de la veille « santé mentale et psychiatrie ».
Le résultat alimente la tâche planifiée qui rédige la note du jour.

## Pourquoi ce dépôt

La tâche planifiée ne peut lire ni Le Monde, ni Libération, ni Radio France, ni
The Guardian, ni la BBC : ces sites refusent ses outils de lecture, flux RSS
compris. Elle dépend donc de ce qui transite par Readwise Reader, soit quatre
abonnements.

Un exécuteur GitHub Actions n'a pas ces restrictions. Il interroge chaque matin
Google Actualités, qui indexe l'ensemble de ces titres, et les flux RSS
d'éditeurs, puis dépose le résultat en JSON. La tâche n'a plus qu'à le lire.

```
Google Actualités + flux RSS  ──►  GitHub Actions  ──►  veille.json
     (8 requêtes, 6 axes)            chaque matin          jours.json
                                                               │
                                                               ▼
                                                     tâche planifiée 06:45
                                                     (tri, résumés, archive)
```

## Les fichiers

| Fichier | Rôle |
|---|---|
| `collecte.py` | interroge les sources, filtre, alimente l'archive |
| `.github/workflows/veille.yml` | lance la collecte chaque matin à 04:28 UTC |
| `veille.json` | les références **nouvelles** du jour : ce que la tâche lit |
| `jours.json` | l'archive jour par jour, pour la synthèse, la lettre et la page |
| `index.html` | la page de consultation, à la charte du site |

La distinction compte : `veille.json` ne contient que ce qui n'avait jamais été
vu, déjà dédoublonné contre toute l'archive. La tâche n'a donc aucun tri de
doublons à faire.

## Mise en place

1. Dépôt **public** : les minutes d'exécution y sont gratuites et sans limite.
2. **Settings → Actions → General → Workflow permissions** : cochez
   **Read and write permissions**, sans quoi le dépôt du fichier échoue.
3. **Settings → Pages → Source** : *Deploy from a branch*, branche `main`,
   dossier `/ (root)`. La page paraît à
   `https://<votre-compte>.github.io/veille-sante-mentale/` après une ou deux
   minutes. Pour un domaine à vous, ajoutez un fichier `CNAME` contenant le nom
   de domaine et faites pointer un enregistrement DNS vers GitHub Pages.
4. **Actions → veille-sante-mentale → Run workflow** pour une première collecte.
5. Lisez le journal de cette exécution : il indique, source par source, combien
   de références ont été vues, retenues, écartées hors du périmètre, et
   lesquelles ont échoué.

## La page

`index.html` lit `jours.json` à l'ouverture et affiche les références par
journée, la plus récente en haut. Elle suit la charte de *Communiquer en santé
mentale* : colonne de lecture sur surface blanche, fond blanc cassé, Bricolage
Grotesque et Instrument Sans, un seul accent indigo, mode clair uniquement.

Chaque référence porte une étiquette de couleur selon son axe, reprise de la
palette des rubriques et des types de ressources. Les filtres par axe ne
s'affichent que pour les axes effectivement présents dans l'archive.

La page ne propose aucun tri ni marquage : le jugement éditorial appartient à la
note quotidienne, et un marquage posé dans un navigateur n'irait nulle part. Elle
est une fenêtre sur ce que le collecteur a trouvé, rien de plus. L'encadré 3114
y figure en permanence, les titres collectés touchant régulièrement au suicide.

## Les huit requêtes

Elles suivent les axes de la veille, et chacune laisse sa trace dans le champ
`feed` de chaque référence.

| Clé | Ce qu'elle cherche |
|---|---|
| `politiques-soins` | réformes, financement, démographie des professions, organisation |
| `stigmatisation` | représentations, idées reçues, regard social |
| `droits-contrainte` | contention, isolement, soins sans consentement, droits |
| `pair-aidance` | pair-aidance, savoir expérientiel, rétablissement |
| `societe` | jeunes, travail, écrans, intelligence artificielle |
| `communication` | campagnes, sensibilisation, prises de parole de personnalités |
| `culture` | livres, documentaires, séries, films, podcasts |
| `international` | presse anglophone, mêmes angles |

Tout se règle en tête de `collecte.py` :

- `REQUETES` : les huit requêtes. La syntaxe Google Actualités accepte les
  guillemets pour une expression exacte, `OR` en majuscules, les parenthèses,
  et `-terme` pour exclure.
- `FLUX_DIRECTS` : les flux RSS d'éditeurs interrogés directement.
- `MOTS_DU_CHAMP` : une référence n'est retenue que si son titre ou son résumé
  contient l'un de ces termes. C'est ce qui écarte le bruit des requêtes larges.
- `EXCLUSIONS` : horoscopes, promotions, pronostics sportifs et autres faux amis.
- `FENETRE_JOURS` : au-delà de cet âge, une référence est ignorée.

Après modification, **Run workflow** pour voir le résultat tout de suite.

## Les flux directs restent à vérifier

Les adresses de `FLUX_DIRECTS` n'ont pas pu être vérifiées lors de l'écriture du
script. Le premier passage le dira : le journal d'exécution affiche l'état de
chaque source, et le champ `sources` de `veille.json` le conserve. Retirez celles
qui échouent, ajoutez les vôtres.

Ajouter un flux ne demande qu'une ligne :

```python
FLUX_DIRECTS = [
    ("hospimedia", "https://www.hospimedia.fr/rss"),
]
```

La clé sert d'étiquette dans le champ `feed`. Les formats RSS et Atom sont
reconnus l'un comme l'autre.

## Format de `veille.json`

```json
{
  "genere": "2026-10-25T04:28:40+00:00",
  "fenetre_jours": 3,
  "sources": [
    { "cle": "politiques-soins", "type": "google", "requete": "…",
      "etat": "ok", "bruts": 64, "retenus": 11,
      "hors_champ": 9, "hors_fenetre": 44 }
  ],
  "nouveaux": 23,
  "items": [
    {
      "id": "ufe170bb9",
      "title": "…",
      "url": "https://www.lemonde.fr/…",
      "gnews": "https://news.google.com/rss/articles/…",
      "resolu": true,
      "source": "Le Monde",
      "published": "2026-10-24",
      "summary": "",
      "feed": "politiques-soins"
    }
  ]
}
```

`summary` porte le chapô quand le flux en fournit un, ce qui est le cas des flux
directs mais pas de Google Actualités.

## Résolution des liens

Google Actualités ne donne pas l'adresse de l'article : son lien passe par une
redirection `news.google.com/rss/articles/…`. Le script tente de remonter à
l'adresse réelle par deux voies successives, et conserve le lien d'origine si
les deux échouent.

1. **Décodage de l'identifiant.** Il encode souvent l'adresse, en base64 et au
   format protobuf. La longueur déclarée de chaque chaîne est lue plutôt que
   devinée, faute de quoi un octet de structure se colle à la fin de l'URL.
2. **Lecture de la page de redirection.** Son HTML porte généralement l'adresse
   d'origine dans un attribut `data-n-au`.

Le champ `resolu` dit si l'une des deux a abouti. Quand c'est le cas, `url`
porte l'adresse de l'article et `gnews` conserve le lien Google. Sinon `url`
reste le lien Google, qui redirige correctement dans un navigateur.

Les liens restés opaques sont retentés à chaque collecte, dix au maximum par
passage. Le total figure dans `liens_non_resolus`, à la racine de `jours.json` :
s'il grimpe, c'est que Google a changé son encodage.

## Ce que le dépôt ne fait pas

Il ne rédige rien. Il ne trie pas selon le périmètre fin de la veille, ne vérifie
pas les dates à la source, n'écarte pas les résultats cliniques maladie par
maladie, et ne rédige aucun résumé. Tout cela reste le travail de la tâche
planifiée, qui garde la main sur le jugement éditorial.


