# Routing API (FastAPI) — Maroc

Cette API calcule un itinéraire « optimal » au Maroc en fournissant **3 à 5 points** :

- 1 point de départ (`start`)  
- 1 à 3 étapes intermédiaires (`via`)  
- 1 point d’arrivée (`end`)

L’API :
- optimise l’ordre des étapes intermédiaires (**bruteforce TSP**, métrique = distance),
- utilise **OSRM public** (`https://router.project-osrm.org`) pour calculer le trajet,
- retourne la **distance totale**, la **durée estimée** et la **géométrie de la route**.

> ⚠️ Remarque : le profil accepté est `"truck"`, mais il est mappé sur le profil **driving** du serveur OSRM public (pas de contraintes poids-lourds réelles).

---

## ⚙️ Prérequis

- **Windows 10 / 11**
- **Python 3.10+** (vérifier avec `python --version`)
- **Git** (vérifier avec `git --version`)
- Accès Internet (l’API appelle `https://router.project-osrm.org`)

---

## 🚀 Installation et lancement (Windows)

### 1) Cloner le projet
Ouvrez **PowerShell** et exécutez :
```powershell
git clone https://github.com/<votre-utilisateur>/routing_api.git
cd routing_api
2) Créer et activer un environnement virtuel
powershell
Copier le code
python -m venv .venv
.venv\Scripts\Activate.ps1
Vous devriez voir (.venv) au début de votre invite.

3) Installer les dépendances
powershell
Copier le code
pip install --upgrade pip
pip install -r requirements.txt
4) Lancer l’API
powershell
Copier le code
uvicorn main:app --reload --port 8080
Le serveur démarre sur :
👉 http://127.0.0.1:8080

📖 Endpoints utiles
GET /health — vérifie que l’API tourne

POST /route — calcul d’itinéraire (payload JSON, voir exemple ci-dessous)

Documentation interactive (Swagger UI) : http://127.0.0.1:8080/docs

📨 Exemple d’utilisation
Exemple JSON (3 points)
json
Copier le code
{
  "points": [
    {"lat": 33.5731, "lon": -7.5898, "role": "start"},
    {"lat": 34.0209, "lon": -6.8416, "role": "via"},
    {"lat": 31.6295, "lon": -7.9811, "role": "end"}
  ],
  "metric": "distance",
  "optimize": true,
  "profile": "truck"
}
A) Tester via Swagger
Laissez Uvicorn tourner.

Allez sur http://127.0.0.1:8080/docs

Ouvrez POST /route → Try it out → collez le JSON → Execute
