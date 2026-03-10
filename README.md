# Docker Control Room

Interface web locale en HTML/CSS/JS avec page d'authentification et tableau de bord pour demarrer, arreter ou redemarrer toutes les machines, ou une machine specifique.

## Lancer

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

Puis ouvrir `http://127.0.0.1:8000`.

## Environnement Python

Le projet n'a pas de dependance Python externe: `requirements.txt` est volontairement minimal car `server.py` utilise uniquement la bibliotheque standard.

L'usage recommande est de creer un environnement virtuel par machine pour isoler l'installation locale, meme si aucune librairie supplementaire n'est necessaire aujourd'hui.

## Identifiants par defaut

- utilisateur: `admin`
- mot de passe: `docker123`

Les comptes locaux sont ensuite stockes dans `users.json`. Depuis le bouton d'administration de l'interface, les comptes de gestion peuvent creer d'autres utilisateurs selon leur niveau de role.

Chaque utilisateur peut aussi activer une A2F TOTP via QR code depuis l'administration.

Hierarchie des roles:
- `admin`: gere tous les comptes
- `operator`: gere uniquement les comptes `user`
- `user`: acces standard sans gestion des autres comptes

## Mode Docker reel

Si `docker` est disponible dans votre environnement, le tableau de bord pilote les conteneurs reels avec:

- `Demarrer tout`
- `Arreter tout`
- `Redemarrer tout`
- `Demarrer`, `arreter` ou `redemarrer` une machine specifique depuis le panneau ou l'onglet `Conteneurs`
- `Deployer la stack` si un fichier `compose.yml` ou `docker-compose.yml` existe dans ce dossier

Sinon, l'application fonctionne en mode demo pour garder une interface testable immediatement.
