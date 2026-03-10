# Docker Control Room

Interface web locale en HTML/CSS/JS avec page d'authentification et tableau de bord pour demarrer, arreter ou redemarrer toutes les machines.

## Lancer

```bash
python3 server.py
```

Puis ouvrir `http://127.0.0.1:8000`.

## Identifiants par defaut

- utilisateur: `admin`
- mot de passe: `docker123`

## Mode Docker reel

Si `docker` est disponible dans votre environnement, le tableau de bord pilote les conteneurs reels avec:

- `Demarrer tout`
- `Arreter tout`
- `Redemarrer tout`
- `Deployer la stack` si un fichier `compose.yml` ou `docker-compose.yml` existe dans ce dossier

Sinon, l'application fonctionne en mode demo pour garder une interface testable immediatement.
