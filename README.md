# 📊 Moniteur de Processus Python

Un outil de surveillance système multiplateforme (Windows/Linux) construit avec Python, PSUtil et Tkinter. Inclut des graphiques en temps réel, des alertes et un widget de bureau.

![Aperçu de l'application](https://private-user-images.githubusercontent.com/190843055/508230348-b5a209fa-1f23-4035-892a-52ff504e2027.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NjE5MTk0ODksIm5iZiI6MTc2MTkxOTE4OSwicGF0aCI6Ii8xOTA4NDMwNTUvNTA4MjMwMzQ4LWI1YTIwOWZhLTFmMjMtNDAzNS04OTJhLTUyZmY1MDRlMjAyNy5wbmc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjUxMDMxJTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI1MTAzMVQxMzU5NDlaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT1iYWQ5ZTIwYzdhZjRjOTk5NWY1M2ZmYTM3NjY2NzBlNDFkYmM1MTRlZjdiY2E2MTUxNjFjNzFlZmI1MjJiYTBlJlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCJ9.yNKpDg588ixg1fVxKgEKE_kQH4iMFhUmob8QYxf2Dxs)

## 🚀 Fonctionnalités

* **Tableau de bord principal :**
    * Graphiques en temps réel pour CPU, RAM, GPU (NVIDIA) et Ventilateurs (Linux uniquement).
    * Liste des processus les plus consommateurs.
* **Historique :**
    * Les données sont sauvegardées dans une base de données `sqlite` locale.
    * Nettoyage automatique configurable.
* **Alertes :**
    * Notifications pop-up si le CPU, la RAM, ou le GPU dépassent un seuil défini par l'utilisateur.
    * Alertes si un processus unique devient trop gourmand.
* **Personnalisation :**
    * Plusieurs thèmes (`ttkthemes`).
    * Sauvegarde des préférences (thème, transparence du widget) dans un `config.json`.
* **Widget de Bureau :**
    * Minimisation en un widget flottant "toujours visible".
    * Widget déplaçable avec transparence ajustable.
    * Deux formes au choix : cercle (transparent) ou carré.
* **Multiplateforme :**
    * Code source compatible Windows et Linux.
    * Icône dans la barre système (tray icon) pour un accès rapide.

---

## 📥 Téléchargements (Versions Compilées)

Vous n'avez pas besoin d'installer Python. Vous pouvez télécharger la dernière version exécutable pour votre système.

Rendez-vous dans l'onglet **[Releases](https://github.com/xjapan007/Process_monitor/releases)** (remplacez par l'URL de votre repo) pour télécharger :
* `main.exe` (pour Windows)
* `main` (pour Linux)

---

## 🛠️ Installation (depuis le code source)

Si vous êtes un développeur et que vous souhaitez l'exécuter depuis le code :

1.  Clonez ce dépôt :
    ```bash
    git clone [https://github.com/VotreNom/NOM-DU-REPO.git](https://github.com/xjapan007/Process_Monitor.git)
    cd Process_Monitor
    ```

2.  Créez un environnement virtuel :
    ```bash
    # Windows
    python -m venv venv
    venv\Scripts\activate
    
    # Linux/macOS
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  Installez les dépendances :
    ```bash
    pip install -r requirements.txt
    ```
    *(Sur Linux, vous devrez peut-être installer Tkinter : `sudo apt-get install python3-tk`)*

4.  Exécutez l'application :
    ```bash
    python main.py
    ```

---

## ⚙️ Bibliothèques utilisées

* `psutil`
* `matplotlib`
* `ttkthemes`
* `pystray`
* `pillow`
* `pynvml` (pour la surveillance GPU NVIDIA)