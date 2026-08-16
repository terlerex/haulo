# Déployer le portefeuille Pokémon sur Railway

> **Tu remplaces un site existant (haulo) ?** Saute directement à la section
> « Variante : reprendre un service existant » en bas. Les étapes 1 à 6 servent
> à créer un projet de zéro.

De zéro à `https://pokemon.tondomaine.fr` en une trentaine de minutes, dont l'essentiel en attente de propagation DNS.

**Avant de commencer**
- Un compte Railway avec un plan payant actif (le plan gratuit ne permet pas de faire tourner un service en continu, et les volumes sont réservés aux plans payants).
- Un compte GitHub.
- Le dossier `portefeuille-pokemon` décompressé sur ton ordinateur.
- Ton export JSON, si tu as déjà saisi des items en local.

---

## 1. Envoyer le code sur GitHub

Dans un terminal, place-toi dans le dossier décompressé :

```bash
cd portefeuille-pokemon
git init
git add .
git commit -m "Portefeuille Pokemon"
```

Puis crée le dépôt. Avec le CLI GitHub :

```bash
gh repo create portefeuille-pokemon --private --source=. --push
```

Sans le CLI : crée un dépôt **privé** vide sur github.com, puis

```bash
git remote add origin https://github.com/TON-PSEUDO/portefeuille-pokemon.git
git branch -M main
git push -u origin main
```

Privé, pas public : ça n'expose rien de critique (le mot de passe n'est pas dans le code), mais autant ne pas publier l'outil qui gère ton patrimoine.

Vérifie que `.gitignore` a bien fait son travail : aucun fichier `.db` ne doit apparaître dans le dépôt.

---

## 2. Créer le service Railway

1. railway.com → **New Project** → **Deploy from GitHub repo**.
2. Première fois : autorise l'application GitHub de Railway sur ce dépôt.
3. Sélectionne `portefeuille-pokemon`.

Railway détecte le `Dockerfile` et lance un premier build. **Il va probablement échouer ou démarrer sans base — c'est normal**, il manque le volume et les variables. On règle ça tout de suite.

---

## 3. Le volume (l'étape critique)

Sans volume, le système de fichiers est remis à zéro à chaque redéploiement : ta base disparaît.

1. Sur le canvas du projet : clic droit → **New Volume** (ou ⌘K / Ctrl+K → « volume »).
2. Attache-le au service `portefeuille-pokemon`.
3. Mount path : **`/data`** — exactement ça, c'est le chemin attendu par le `Dockerfile`.

Trois choses à savoir :
- Le volume est monté **au démarrage du conteneur**, pas au build. Rien de ce qui est écrit pendant le build n'est conservé.
- Un service avec volume a une **courte coupure à chaque redéploiement** : Railway empêche deux conteneurs d'écrire en même temps. Sur un usage perso, ça ne se voit pas.
- Le volume est monté en root. Notre image tourne en root, donc pas de souci de permissions.

---

## 4. Les variables d'environnement

Service → onglet **Variables** → **New Variable**, trois entrées :

| Nom | Valeur |
|---|---|
| `PORTFOLIO_PASSWORD` | ton mot de passe, long et unique |
| `DB_PATH` | `/data/portfolio.db` |
| `PORT` | `8000` |

`DB_PATH` place la base sur le volume. `PORT` évite toute ambiguïté sur le port écouté.

Optionnel : `SESSION_DAYS` (90 par défaut) — le nombre de jours avant que le mot de passe soit redemandé.

Railway redéploie automatiquement à chaque changement de variable.

---

## 5. Vérifier que ça tourne

1. Onglet **Deployments** → le dernier déploiement doit être vert.
2. Ouvre les **Logs** : tu dois voir `Uvicorn running on http://0.0.0.0:8000`.
3. Settings → **Networking** → **Generate Domain** (port cible `8000`).

Ouvre l'URL `*.up.railway.app` fournie : la page de connexion doit s'afficher. Entre ton mot de passe → tu arrives sur le portefeuille vide.

Si tu vois « Application failed to respond », c'est presque toujours le port : vérifie `PORT=8000` et le port cible du domaine.

---

## 6. Brancher ton nom de domaine

1. Service → Settings → Networking → **+ Custom Domain**.
2. Saisis `pokemon.tondomaine.fr` (un sous-domaine est plus simple qu'un domaine nu).
3. Railway affiche **deux enregistrements** : un `CNAME` et un `TXT`.

Chez ton registrar, crée **les deux, exactement tels qu'affichés**.

⚠️ C'est le piège classique : **sans l'enregistrement TXT, le domaine renvoie 404 même quand le CNAME résout correctement.** Le TXT sert à prouver que le domaine t'appartient, Railway ne route rien tant qu'il n'est pas vérifié.

Si tu tiens au domaine nu (`tondomaine.fr` sans sous-domaine) : Railway ne publie pas d'IP fixe, donc pas d'enregistrement A possible. Il te faut un registrar qui gère l'aplatissement de CNAME ou les enregistrements ALIAS/ANAME (Cloudflare, OVH le fait), et il faut supprimer les A/AAAA existants.

Compte quelques minutes en général, jusqu'à 72 h dans le pire des cas. Le certificat HTTPS est émis et renouvelé automatiquement.

---

## 7. Récupérer tes données

Sur le site en ligne, connecte-toi → bouton **Importer** → sélectionne ton export JSON.

Items, relevés de prix, historique, réglages et veille sont repris. L'import **remplace** le contenu de la base — c'est ce que tu veux ici, puisqu'elle est vide.

Vérifie ensuite que le total correspond à ce que tu avais en local.

---

## 8. Sur le téléphone

Ouvre `https://pokemon.tondomaine.fr` dans Safari ou Chrome, connecte-toi, puis **Partager → Sur l'écran d'accueil**.

L'app s'ouvre en plein écran, sans barre de navigateur. La session tient 90 jours : mot de passe une seule fois.

---

## 9. Au quotidien

**Mettre à jour le site** — un simple `git push` sur `main` déclenche un redéploiement. Tes données ne bougent pas, elles sont sur le volume.

**Sauvegarder** — le bouton *Exporter* télécharge tout en JSON. Prends l'habitude une fois par mois. Le volume est fiable, mais c'est un seul endroit, et une fausse manip d'import est vite arrivée.

**Surveiller la facture** — onglet Usage du projet. Cette app est minuscule : un process Python, une base SQLite, toi comme seul visiteur. Elle devrait rester loin du crédit inclus dans ton abonnement, mais jette un œil la première semaine pour confirmer plutôt que de le supposer.

---

## Dépannage

| Symptôme | Cause quasi certaine |
|---|---|
| 404 sur ton domaine alors que le CNAME est bon | l'enregistrement TXT manque |
| « Application failed to respond » | port : vérifie `PORT=8000` et le port cible du domaine |
| Les données disparaissent après un déploiement | pas de volume, ou `DB_PATH` ne pointe pas dans `/data` |
| Le site demande le mot de passe en boucle | cookie bloqué — vérifie que tu es bien en `https://` et pas en navigation privée stricte |
| « trop d'essais, réessaie dans 15 minutes » | protection anti-force brute, 5 échecs par quart d'heure |
| Mot de passe oublié | change `PORTFOLIO_PASSWORD` dans les variables, Railway redéploie, les données restent intactes |

---

## Si tu veux vérifier avant de déployer

En local, avec le mot de passe activé, exactement comme en ligne :

```bash
PORTFOLIO_PASSWORD=test DB_PATH=./test.db uvicorn app:app --port 8000
```

Puis `http://localhost:8000`. Supprime `test.db` ensuite.

---

# Variante : reprendre un service existant

Tu réutilises le dépôt, le service Railway et le domaine de l'ancien site. C'est plus rapide : le domaine est déjà branché et vérifié, donc aucun DNS à toucher.

## A. Archiver l'ancien site (2 minutes, ça vaut le coup)

Depuis ton dossier local `haulo` :

```bash
git switch main                       # ou master, selon le dépôt
git switch -c archive-haulo
git push -u origin archive-haulo
git switch main
```

L'ancien code reste accessible sur cette branche si tu le regrettes un jour.

Si l'ancienne base contenait des données à garder, récupère-les avant : `railway volume browse` ouvre le contenu du volume et permet de télécharger les fichiers.

## B. Remplacer le contenu du dépôt

Toujours dans le dossier `haulo`, on efface tout sauf l'historique git, puis on copie la nouvelle app :

```bash
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a /chemin/vers/portefeuille-pokemon/. .
git add -A
git commit -m "Remplacement par le portefeuille Pokemon"
git push
```

`cp -a … /.` copie aussi les fichiers cachés (`.gitignore`, `.dockerignore`). Vérifie avec `ls -a` avant de commiter.

Le push déclenche automatiquement un redéploiement sur Railway.

## C. Nettoyer la configuration du service

L'ancien projet était en React/Vite + Express : le service porte encore ses réglages, qui prendraient le pas sur le `Dockerfile`. Dans **Settings** :

| Réglage | À faire |
|---|---|
| **Root Directory** | vider s'il pointait vers un sous-dossier (`/server`, `/client`…) |
| **Custom Build Command** | vider (`npm run build` traînerait sinon) |
| **Custom Start Command** | vider (`npm start` empêcherait l'app Python de démarrer) |
| **Builder** | Dockerfile — normalement détecté seul une fois les commandes vidées |
| **Watch Paths** | vider s'il y en avait |

## D. Les variables

Onglet **Variables** : supprime celles de l'ancien site (clés d'API affiliés, `NODE_ENV`…), puis ajoute les trois nécessaires :

| Nom | Valeur |
|---|---|
| `PORTFOLIO_PASSWORD` | ton mot de passe |
| `DB_PATH` | `/data/portfolio.db` |
| `PORT` | `8000` |

## E. Le volume

Un service ne peut avoir **qu'un seul volume**. Deux cas :

- **Il en existe déjà un** (l'ancienne base SQLite y vivait). Regarde son mount path. S'il est différent de `/data`, tu as le choix : changer le mount path en `/data`, ou plus simple, laisser tel quel et adapter `DB_PATH` — par exemple mount path `/app/data` → `DB_PATH=/app/data/portfolio.db`. L'ancien fichier `.db` reste dans le volume sans gêner ; tu peux le supprimer plus tard avec `railway volume browse`.
- **Il n'y en a pas** : crée-le maintenant, mount path `/data`. Sans volume, tes données disparaissent au prochain déploiement.

## F. Le port du domaine — le piège

Le domaine est déjà attaché, mais son **port cible** pointe vers l'ancienne app (3000, 8080…). Le site répondrait « Application failed to respond ».

Settings → Networking → icône crayon à côté du domaine → port cible **8000**.

## G. Vérifier

1. Deployments : dernier déploiement vert.
2. Logs : `Uvicorn running on http://0.0.0.0:8000`.
3. Ouvre ton domaine : la page de connexion s'affiche.
4. Connecte-toi, bouton **Importer**, ton export JSON.

Rien à faire côté DNS : CNAME et TXT sont déjà en place et vérifiés depuis l'ancien site, le certificat HTTPS suit automatiquement.

## Si le déploiement échoue

Regarde les logs de build. Le cas le plus fréquent : Railway utilise encore Nixpacks et cherche un `package.json`. C'est qu'une commande de build ou de start personnalisée traîne encore dans Settings (étape C).
