# Portefeuille Pokémon

Suivi perso de collection Pokémon TCG : scellé, cartes loose et gradées, estimation du prix de revente à partir de tes propres relevés, progression du portefeuille.

Accessible depuis n'importe quel appareil, protégé par mot de passe.

---

## Deux onglets

**Portefeuille** — ce que tu possèdes. Valeur estimée, plus-value, net de frais, courbe de progression.

**Veille** — ce que tu n'as pas encore acheté. Même moteur d'estimation, mais l'item ne pèse pas dans le bilan. Tu y suis :

| Indicateur | Ce qu'il dit |
|---|---|
| **Tendance 30j** | médiane des 30 derniers jours contre celle des 60 jours précédents |
| **Rythme** | pente de régression sur 180 jours, en % par mois — la direction de fond |
| **Ça part ?** | ventes constatées par mois, à partir des relevés issus d'une vraie transaction (eBay vendu, vente Cardmarket, GCC) |
| **Dispersion** | écart entre le plus bas et le plus haut sur 90 jours — un marché large est un marché où le prix se négocie |
| **Objectif** | le prix auquel tu serais acheteur, et l'écart du marché à cet objectif |

Le graphique de la fiche montre tous tes relevés dans le temps, la droite de tendance, et ton objectif en pointillés dorés.

### Le champ « nb de ventes »

Un relevé peut résumer plusieurs transactions : « 9 ventes eBay autour de 104 € cette semaine » → prix `104`, nb de ventes `9`. C'est ce qui alimente le rythme de vente. Un relevé de prix affiché (annonce Cardmarket, tendance) ne compte pas comme une vente.

Quand tu achètes : bouton **Je l'ai acheté**, prix payé et quantité, l'item bascule au portefeuille en gardant tout son historique de prix.

Ces indicateurs décrivent ce que tes relevés contiennent, rien de plus. Une tendance calculée sur trois relevés d'un même vendeur ne vaut pas grand-chose — la colonne « historique » et le nombre de relevés sont là pour te le rappeler.

---

## Mettre en ligne sur ton nom de domaine (Railway)

### 1. Le code sur GitHub

```
git init && git add . && git commit -m "portefeuille pokemon"
gh repo create portefeuille-pokemon --private --source=. --push
```

Dépôt **privé** : inutile d'exposer la config.

### 2. Le service Railway

New Project → Deploy from GitHub repo → ce dépôt. Le `Dockerfile` est détecté automatiquement.

### 3. Le volume (l'étape à ne pas rater)

Sur le service : **Variables → Volumes → New Volume**, point de montage `/data`.

Sans volume, la base est effacée à chaque redéploiement. Avec, elle survit à tout.

### 4. Les variables d'environnement

| Variable | Valeur |
|---|---|
| `PORTFOLIO_PASSWORD` | ton mot de passe (obligatoire, le site est public) |
| `DB_PATH` | `/data/portfolio.db` |
| `PORT` | `8000` |
| `SESSION_DAYS` | `90` (optionnel — durée avant de redemander le mot de passe) |

### 5. Le domaine

Service → Settings → Networking → **+ Custom Domain** → `pokemon.tondomaine.fr`.

Railway affiche **deux** enregistrements à créer chez ton registrar : un `CNAME` et un `TXT`. Les deux sont obligatoires — sans le TXT, le domaine renvoie 404 même quand le CNAME résout. HTTPS automatique ensuite.

Détail du pas à pas : `TUTO-RAILWAY.md`.

### 6. Tes données

Ouvre le site, connecte-toi, bouton **Importer**, choisis l'export JSON de la version locale. Tout est repris : items, relevés, historique, réglages.

Sur le téléphone : Partager → **Sur l'écran d'accueil**. L'app s'ouvre en plein écran et la session tient 90 jours — mot de passe une fois, plus jamais ensuite.

---

## La protection

- Page de connexion sur **toute** l'application : sans session valide, aucune page ni aucune route API ne répond.
- Session = cookie signé HMAC-SHA256, `HttpOnly` + `Secure` en HTTPS. La clé de signature est générée une fois et stockée dans la base, donc un redéploiement ne te déconnecte pas.
- 5 essais ratés par IP et par quart d'heure, ensuite `429`.
- Mot de passe comparé en temps constant, jamais stocké en base : il ne vit que dans la variable d'environnement.

Prends un mot de passe long et unique. C'est la seule chose entre l'inventaire de ta collection et le premier venu.

---

## En local

```
./start.sh          # macOS / Linux
start.bat           # Windows
```

Sans `PORTFOLIO_PASSWORD`, l'accès est libre — acceptable sur ton réseau, jamais en ligne. La base est `portfolio.db` à côté de `app.py`.

Pour tester la version protégée en local :

```
PORTFOLIO_PASSWORD=test uvicorn app:app --port 8000
```

---

## Sauvegarde

Le bouton **Exporter** produit un JSON complet. Sur Railway, prends l'habitude de l'enregistrer de temps en temps : un volume, ça reste un seul endroit.

---

## API

Doc interactive sur `/docs` (protégée elle aussi).

| Endpoint | Rôle |
|---|---|
| `POST /api/login` · `POST /api/logout` | session |
| `GET /api/state` | items + estimations + totaux + historique |
| `POST/PUT/DELETE /api/items` | gestion des items |
| `POST /api/items/{id}/comps` | ajouter un relevé de prix |
| `PATCH /api/comps/{id}` | ignorer / réintégrer un relevé |
| `PUT /api/settings` | demi-vie, frais, poids des sources |
| `GET /api/export` · `POST /api/import` | sauvegarde JSON |

Utile si tu veux plus tard alimenter les relevés depuis un script Python plutôt qu'à la main.
