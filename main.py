import tkinter as tk
from tkinter import ttk
import threading
import psutil
import queue
import time
import sqlite3
import datetime
from ttkthemes import ThemedTk
from collections import deque
import pystray
from PIL import Image

try:
    import pynvml
    NVIDIA_AVAILABLE = True  
except ImportError:
    NVIDIA_AVAILABLE = False 
import json

# --- Matplotlib dans Tkinter ---
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- Paramètres ---
UPDATE_INTERVAL_MS = 1000  # Intervalle de collecte (en ms)
GRAPH_HISTORY_SIZE = 60    # Garder 60 points pour le graphique (ex: 60 secondes)
TOP_PROCESS_COUNT = 10     # Afficher les 10 processus les plus gourmands

class ProcessMonitorApp(ThemedTk):
    def __init__(self):
        # --- Fichier de config et valeurs par défaut ---
        self.config_file = 'config.json'
        self.widget_alpha = 0.8
        self.widget_shape = "circle"
        
        super().__init__(theme="arc") 
        
        self.title("Process Monitor by xjapan ")
        self.geometry("800x600")

        # --- Variables pour les seuils d'alerte ---
        self.cpu_threshold_var = tk.IntVar(value=90)
        self.ram_threshold_var = tk.IntVar(value=90)
        self.gpu_threshold_var = tk.IntVar(value=90)
        self.process_cpu_threshold_var = tk.IntVar(value=50) # Alerte si un seul processus dépasse

        # --- Verrous d'alerte (pour éviter le spam) ---
        self.system_alert_triggered = {
            "cpu": False,
            "ram": False,
            "gpu": False
        }
        # Dictionnaire pour les processus déjà signalés {pid: "nom"}
        self.process_alert_triggered = {}

        # --- Données pour le graphique ---
        self.cpu_history = deque(maxlen=GRAPH_HISTORY_SIZE)
        self.ram_history = deque(maxlen=GRAPH_HISTORY_SIZE)
        self.fan_history = deque(maxlen=GRAPH_HISTORY_SIZE) 
        self.gpu_history = deque(maxlen=GRAPH_HISTORY_SIZE) 

        # --- Configuration de la base de données ---
        self.db_name = 'system_monitor.db'
        self.db_conn = None  

        # --- File d'attente pour la communication ---
        self.data_queue = queue.Queue()

        # --- Configuration de l'interface ---
        self.setup_ui()

        # --- Charger l'historique initial de la DB pour le graphique ---
        self.load_initial_graph_data()

        # --- Démarrer le thread de travail (collecte + DB) ---
        self.start_worker_thread() # <--- Sera modifié

        # --- Lancer la boucle de rafraîchissement de l'interface ---
        self.process_gui_queue()

        # --- Logique de fermeture et de widget ---
        self.protocol("WM_DELETE_WINDOW", self.on_close_request)
        
        self.widget_window = None
        self.widget_text_id = None 
        self.widget_canvas = None 
        self.widget_label = None 
        self.widget_frame = None 
        
        # --- Ajouts pour pystray ---
        self.tray_icon = None 
        tray_thread = threading.Thread(target=self.setup_system_tray, daemon=True)
        tray_thread.start()
        
        # --- Initialisation GPU NVIDIA ---
        self.gpu_handle = None
        global NVIDIA_AVAILABLE 
        if NVIDIA_AVAILABLE: 
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0) 
                print("Surveillance NVIDIA initialisée.")
            except Exception as e:
                print(f"Erreur init pynvml (NVIDIA) : {e}. (Pilote à jour ?)")
                NVIDIA_AVAILABLE = False 
        else:
            print("Bibliothèque pynvml non trouvée. Surveillance GPU NVIDIA désactivée.")
            
        # --- Charger les préférences utilisateur ---
        self.load_settings()
        
    def setup_ui(self):
        """Crée les éléments de l'interface utilisateur."""
        
        # --- Panneau de configuration (en haut) ---
        config_frame = ttk.Frame(self)
        config_frame.pack(fill='x', pady=5, padx=5)

        # --- Ligne 1: Thème et Nettoyage DB ---
        config_frame_line1 = ttk.Frame(config_frame)
        config_frame_line1.pack(fill='x')
        
        ttk.Label(config_frame_line1, text="Thème :").pack(side=tk.LEFT, padx=5)
        self.theme_combo = ttk.Combobox(config_frame_line1, state="readonly", width=15)
        self.theme_combo['values'] = sorted(self.get_themes())
        self.theme_combo.pack(side=tk.LEFT, padx=5)
        self.theme_combo.bind("<<ComboboxSelected>>", self.on_theme_change)

        ttk.Label(config_frame_line1, text="Nettoyer l'historique après (jours):").pack(side=tk.LEFT, padx=20)
        self.days_to_keep = tk.IntVar(value=7)
        ttk.Spinbox(config_frame_line1, from_=1, to_=365, textvariable=self.days_to_keep, width=5).pack(side=tk.LEFT)

        # --- Ligne 2: Seuils d'alerte ---
        config_frame_line2 = ttk.Frame(config_frame)
        config_frame_line2.pack(fill='x', pady=5)
        
        ttk.Label(config_frame_line2, text="Alertes Système (%): CPU:").pack(side=tk.LEFT, padx=(5,0))
        ttk.Spinbox(config_frame_line2, from_=1, to_=100, textvariable=self.cpu_threshold_var, width=4).pack(side=tk.LEFT)
        
        ttk.Label(config_frame_line2, text="RAM:").pack(side=tk.LEFT, padx=(10,0))
        ttk.Spinbox(config_frame_line2, from_=1, to_=100, textvariable=self.ram_threshold_var, width=4).pack(side=tk.LEFT)
        
        ttk.Label(config_frame_line2, text="GPU:").pack(side=tk.LEFT, padx=(10,0))
        ttk.Spinbox(config_frame_line2, from_=1, to_=100, textvariable=self.gpu_threshold_var, width=4).pack(side=tk.LEFT)
        
        ttk.Label(config_frame_line2, text="Alerte Processus (%):").pack(side=tk.LEFT, padx=(20,0))
        ttk.Spinbox(config_frame_line2, from_=1, to_=100, textvariable=self.process_cpu_threshold_var, width=4).pack(side=tk.LEFT)
        
        # --- Panneau principal (divisé) ---
        main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        graph_frame = ttk.Frame(main_pane, height=250)
        self.setup_graph(graph_frame)
        main_pane.add(graph_frame, weight=1)
        process_frame = ttk.Frame(main_pane, height=350)
        self.setup_process_list(process_frame)
        main_pane.add(process_frame, weight=2)
        
    def on_theme_change(self, event):
        """Applique le nouveau thème sélectionné."""
        selected_theme = self.theme_combo.get()
        try:
            self.set_theme(selected_theme)
            
            # Re-configurer la couleur du graphique pour correspondre
            if "dark" in selected_theme or selected_theme in ["arc", "equilux", "black"]:
                bg_color = '#383838'
                fg_color = '#f0f0f0'
            else:
                bg_color = '#f0f0f0'
                fg_color = '#000000'
                
            self.ax.set_facecolor(bg_color)
            self.ax.xaxis.label.set_color(fg_color)
            self.ax.yaxis.label.set_color(fg_color)
            self.ax.title.set_color(fg_color)
            self.ax.tick_params(axis='x', colors=fg_color)
            self.ax.tick_params(axis='y', colors=fg_color)
            self.fig.set_facecolor(bg_color)
            self.update_graph_display() 
            
            # --- Sauvegarder le choix ---
            self.save_settings()
            
        except Exception as e:
            print(f"Erreur lors du changement de thème : {e}")

    def on_theme_change(self, event):
        """Applique le nouveau thème sélectionné."""
        selected_theme = self.theme_combo.get()
        self.set_theme(selected_theme)
        
    def setup_graph(self, parent_frame):
        """Initialise le graphique Matplotlib."""
        
        current_theme = self.current_theme
               
        if "dark" in current_theme or current_theme in ["arc", "equilux", "black"]:
            bg_color = '#383838'
            fg_color = '#f0f0f0'
        else:
            bg_color = '#f0f0f0'
            fg_color = '#000000'
        
        # 'figsize' est en pouces, 'dpi' (dots-per-inch) ajuste la taille
        
        self.fig = Figure(figsize=(5, 2.5), dpi=100, facecolor=bg_color)
        self.ax = self.fig.add_subplot(111) # 'ax' (axes) est notre zone de dessin
        self.ax.set_facecolor(bg_color) # Fond du graphique

        # Style du graphique (avec les bonnes couleurs)
        self.ax.set_title("Utilisation CPU & RAM", color=fg_color)
        self.ax.set_ylabel("% Utilisation", color=fg_color)
        self.ax.set_ylim(0, 100)
        self.ax.set_xticklabels([])
        
        # Couleur des axes
        self.ax.tick_params(axis='x', colors=fg_color)
        self.ax.tick_params(axis='y', colors=fg_color)
        
        # Couleur des bordures
        for spine in self.ax.spines.values():
            spine.set_edgecolor(fg_color)
        
        # Créer le canevas Tkinter pour le graphique
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def setup_process_list(self, parent_frame):
        """Initialise le TreeView pour les processus."""
        
        ttk.Label(parent_frame, text="Processus les plus consommateurs (CPU)", font=("Helvetica", 10, "bold")).pack(pady=5)

        cols = ('pid', 'name', 'cpu', 'ram')
        self.tree = ttk.Treeview(parent_frame, columns=cols, show='headings')

        # Définir les en-têtes
        self.tree.heading('pid', text='PID')
        self.tree.heading('name', text='Nom')
        self.tree.heading('cpu', text='CPU %')
        self.tree.heading('ram', text='RAM %')

        # Ajuster les colonnes
        self.tree.column('pid', width=60, anchor=tk.E)
        self.tree.column('name', width=250)
        self.tree.column('cpu', width=80, anchor=tk.E)
        self.tree.column('ram', width=80, anchor=tk.E)

        # Ajouter une barre de défilement
        scrollbar = ttk.Scrollbar(parent_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def load_initial_graph_data(self):
        """Charge les N derniers points de la DB pour pré-remplir le graphique."""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            # Créer la table au cas où elle n'existerait pas
            # AJOUT de fan_rpm INTEGER
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_stats (
                    timestamp DATETIME PRIMARY KEY,
                    cpu_percent REAL,
                    ram_percent REAL,
                    fan_rpm INTEGER
                )
            """)
            
            # Tenter de mettre à jour l'ancienne table si 'fan_rpm' manque
            try:
                cursor.execute("ALTER TABLE system_stats ADD COLUMN fan_rpm INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass # La colonne existe déjà, c'est normal

            # Récupérer les N dernières entrées
            cursor.execute("SELECT cpu_percent, ram_percent, fan_rpm FROM system_stats ORDER BY timestamp DESC LIMIT ?", (GRAPH_HISTORY_SIZE,))
            rows = cursor.fetchall()
            conn.close()

            # Remplir les 'deque' (dans le bon ordre)
            if rows:
                for row in reversed(rows):
                    self.cpu_history.append(row[0])
                    self.ram_history.append(row[1])
                    self.fan_history.append(row[2] or 0) # 'or 0' au cas où c'est None
                self.update_graph_display() # Afficher le graphique initial
        except Exception as e:
            print(f"Erreur lors du chargement de l'historique : {e}")

    def start_worker_thread(self):
        """Démarre le thread qui collecte les données ET gère la DB."""
        worker = threading.Thread(
            target=self.data_collection_worker,
            args=( # Passer les variables Tkinter au thread
                self.days_to_keep,
                self.cpu_threshold_var,
                self.ram_threshold_var,
                self.gpu_threshold_var,
                self.process_cpu_threshold_var
            ), 
            daemon=True
        )
        worker.start()

    def data_collection_worker(self, days_to_keep_var, cpu_thresh_var, ram_thresh_var, 
                               gpu_thresh_var, proc_thresh_var):
        """
        Le "worker" : collecte, gère la DB, ET vérifie les alertes.
        S'exécute dans un thread séparé.
        """
        try:
            self.db_conn = sqlite3.connect(self.db_name, check_same_thread=False)
            cursor = self.db_conn.cursor()
            # (Le code de création de table/DB est dans load_initial_graph_data)
        except Exception as e:
            print(f"Erreur de connexion DB dans le worker : {e}")
            return 

        last_cleanup_time = 0
        current_pids = set() # Pour suivre les processus en vie

        while True:
            try:
                # --- 1. Collecte des données Système ---
                cpu = psutil.cpu_percent(interval=None) 
                ram = psutil.virtual_memory().percent
                timestamp = datetime.datetime.now()

                # --- 2. Collecte des données GPU (si possible) ---
                gpu_text = "N/A"
                gpu_util = 0 
                if self.gpu_handle: 
                    try:
                        util_rates = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                        gpu_util = util_rates.gpu 
                        gpu_text = f"{gpu_util} %"
                    except Exception as e:
                        gpu_text = "Err"
                        
                # --- 3. Collecte des données Ventilateur (si possible) ---
                fan_text = "N/A"
                fan_rpm = 0 
                try:
                    fans = psutil.sensors_fans()
                    if fans:
                        first_fan_key = list(fans.keys())[0]
                        fan_rpm = fans[first_fan_key][0].current
                        fan_text = f"{fan_rpm} RPM"
                except Exception as e:
                    pass 

                # --- 4. Vérification des Alertes Système ---
                # Lire les seuils depuis les variables Tkinter
                cpu_alert_level = cpu_thresh_var.get()
                ram_alert_level = ram_thresh_var.get()
                gpu_alert_level = gpu_thresh_var.get()
                
                # Définir des seuils de "retour à la normale" (pour réinitialiser l'alerte)
                cpu_reset_level = cpu_alert_level - 10
                ram_reset_level = ram_alert_level - 10
                gpu_reset_level = gpu_alert_level - 10
                
                # Logique de "verrou" (latching)
                if cpu > cpu_alert_level and not self.system_alert_triggered["cpu"]:
                    self.system_alert_triggered["cpu"] = True
                    self.data_queue.put({"alert": "system", "type": "CPU", "value": cpu})
                elif cpu < cpu_reset_level and self.system_alert_triggered["cpu"]:
                    self.system_alert_triggered["cpu"] = False # Réinitialiser le verrou

                if ram > ram_alert_level and not self.system_alert_triggered["ram"]:
                    self.system_alert_triggered["ram"] = True
                    self.data_queue.put({"alert": "system", "type": "RAM", "value": ram})
                elif ram < ram_reset_level and self.system_alert_triggered["ram"]:
                    self.system_alert_triggered["ram"] = False

                if gpu_util > gpu_alert_level and not self.system_alert_triggered["gpu"]:
                    self.system_alert_triggered["gpu"] = True
                    self.data_queue.put({"alert": "system", "type": "GPU", "value": gpu_util})
                elif gpu_util < gpu_reset_level and self.system_alert_triggered["gpu"]:
                    self.system_alert_triggered["gpu"] = False
                    
                # --- 5. Collecte des Processus ET Vérification Alertes Processus ---
                processes = []
                current_pids.clear()
                proc_alert_level = proc_thresh_var.get()
                
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        pinfo = proc.info
                        current_pids.add(pinfo['pid']) # Garder une trace des PID en vie

                        # 'cpu_percent' peut être None au premier appel
                        if pinfo['cpu_percent'] is not None:
                            processes.append(pinfo)
                            
                            # NOUVEAU : Vérification Alerte Processus
                            if pinfo['cpu_percent'] > proc_alert_level:
                                pid = pinfo['pid']
                                # Si le PID n'est pas déjà dans notre liste d'alerte...
                                if pid not in self.process_alert_triggered:
                                    self.process_alert_triggered[pid] = pinfo['name'] # ...on l'ajoute...
                                    # ...et on envoie une alerte
                                    self.data_queue.put({
                                        "alert": "process", 
                                        "name": pinfo['name'], 
                                        "pid": pid, 
                                        "value": pinfo['cpu_percent']
                                    })
                                    
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass # Le processus est mort pendant l'itération
                
                # Nettoyer la liste des alertes (retirer les processus morts)
                triggered_pids = list(self.process_alert_triggered.keys())
                for pid in triggered_pids:
                    if pid not in current_pids:
                        del self.process_alert_triggered[pid]

                # Trier et prendre le TOP N pour affichage
                top_processes = sorted(processes, key=lambda p: p['cpu_percent'], reverse=True)[:TOP_PROCESS_COUNT]

                # --- 6. Mettre les données STATS dans la file ---
                self.data_queue.put({
                    "cpu": cpu, "ram": ram, "processes": top_processes,
                    "fan_text": fan_text, "fan_rpm": fan_rpm,
                    "gpu_text": gpu_text, "gpu_util": gpu_util
                })

                # --- 7. Insérer dans la DB ---
                try:
                    cursor.execute("INSERT INTO system_stats (timestamp, cpu_percent, ram_percent, fan_rpm, gpu_percent) VALUES (?, ?, ?, ?, ?)",
                                   (timestamp, cpu, ram, fan_rpm, gpu_util))
                    self.db_conn.commit()
                except Exception as e:
                    print(f"Erreur d'insertion DB : {e}")

                # --- 8. Gérer le nettoyage DB ---
                current_time = time.time()
                if current_time - last_cleanup_time > 3600: # 1 fois par heure
                    try:
                        days = days_to_keep_var.get()
                        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
                        cursor.execute("DELETE FROM system_stats WHERE timestamp < ?", (cutoff_date,))
                        self.db_conn.commit()
                        print(f"Nettoyage DB effectué : suppression des entrées avant {cutoff_date}")
                    except Exception as e:
                        print(f"Erreur lors du nettoyage DB : {e}")
                    finally:
                        last_cleanup_time = current_time

                # Attendre avant la prochaine boucle
                time.sleep(UPDATE_INTERVAL_MS / 1000.0)

            except Exception as e:
                print(f"Erreur dans le worker : {e}")
                time.sleep(UPDATE_INTERVAL_MS / 1000.0)

    def process_gui_queue(self):
        """
        Vérifie la file d'attente pour les données OU les alertes.
        S'exécute dans le thread principal (GUI).
        """
        try:
            # Récupérer un item (stats OU alerte)
            data = self.data_queue.get(block=False)
            
            if data:
                if "alert" in data:
                    self.show_alert(data) # Appeler la fonction de popup
                                
                else:
                    # C'est un message de stats normal, mettre à jour la GUI
                    self.cpu_history.append(data['cpu'])
                    self.ram_history.append(data['ram'])
                    self.fan_history.append(data.get('fan_rpm', 0)) 
                    self.gpu_history.append(data.get('gpu_util', 0)) 
                    
                    if self.winfo_viewable(): 
                        self.update_graph_display()
                    
                    self.update_process_list_display(data['processes'])
                    
                    # Mettre à jour le widget
                    if self.widget_window and self.widget_window.winfo_exists():
                        fan_text = data.get("fan_text", "N/A") 
                        gpu_text = data.get("gpu_text", "N/A") 
                        
                        widget_text = (
                            f"CPU: {data['cpu']:.1f} %\n"
                            f"RAM: {data['ram']:.1f} %\n"
                            f"GPU: {gpu_text}\n"        
                            f"Fan: {fan_text}"
                        )
                        
                        if self.widget_shape == "circle" and self.widget_canvas and self.widget_text_id:
                            self.widget_canvas.itemconfig(self.widget_text_id, text=widget_text)
                        elif self.widget_shape == "square" and self.widget_label:
                            self.widget_label.config(text=widget_text)

        except queue.Empty:
            # C'est normal s'il n'y a pas de données
            pass
        
        # Redemander à Tkinter d'appeler cette fonction
        self.after(250, self.process_gui_queue)
        
    def show_alert(self, alert_data):
        """
        Affiche une boîte de dialogue d'alerte. 
        Cette fonction s'exécute TOUJOURS dans le thread GUI.
        """
        # Importer messagebox ici pour ne pas encombrer les imports globaux
        from tkinter import messagebox
        
        try:
            if alert_data["alert"] == "system":
                title = "Alerte de Performance Système"
                msg = (
                    f"Niveau critique atteint pour le {alert_data['type']} !\n\n"
                    f"Utilisation actuelle : {alert_data['value']:.1f} %"
                )
                messagebox.showwarning(title, msg, parent=self) # 'parent=self' la met au-dessus
            
            elif alert_data["alert"] == "process":
                title = "Alerte de Processus"
                msg = (
                    f"Le processus suivant consomme trop de CPU :\n\n"
                    f"Nom: {alert_data['name']} (PID: {alert_data['pid']})\n"
                    f"Utilisation: {alert_data['value']:.1f} %"
                )
                messagebox.showwarning(title, msg, parent=self)
        except Exception as e:
            print(f"Erreur lors de l'affichage de l'alerte : {e}")

    def update_graph_display(self):
        """Redessine le graphique Matplotlib (coûteux)."""
        
        # Nettoyer l'ancien graphique
        self.ax.clear()
        
        # Axe Y secondaire pour les RPM
        if hasattr(self, 'ax_fan'): 
             self.ax_fan.clear()
        else:
            self.ax_fan = self.ax.twinx() 
        
        # Dessiner CPU/RAM/GPU sur l'axe principal
        self.ax.plot(list(self.cpu_history), label="CPU %", color='blue', linewidth=1.5)
        self.ax.plot(list(self.ram_history), label="RAM %", color='orange', linewidth=1.5)
        self.ax.plot(list(self.gpu_history), label="GPU %", color='purple', linewidth=1.5) 
        
        # Dessiner Ventilateur sur l'axe secondaire
        fan_history_list = list(self.fan_history)
        self.ax_fan.plot(fan_history_list, label="Fan (RPM)", color='green', linewidth=1.5, linestyle=':')
        
        # --- Stylisation des deux axes ---
        
        # Axe principal (CPU/RAM/GPU)
        self.ax.set_title("Utilisation Système (Dernières 60 sec)", color=self.ax.title.get_color())
        self.ax.set_ylabel("% Utilisation", color='blue')
        self.ax.set_ylim(0, 100)
        self.ax.set_xticklabels([])
        
        # Axe secondaire (Fan)
        self.ax_fan.set_ylabel("RPM", color='green') 
        
        # Trouver le max, ou 0 si l'historique est vide ou plein de zéros
        max_rpm = max(fan_history_list or [0]) 
        
        if max_rpm == 0:
            display_max_rpm = 1000 # Si 0 RPM, fixer l'axe à 1000
        else:
            display_max_rpm = max_rpm * 1.5 # Sinon, marge de 50%
            
        self.ax_fan.set_ylim(0, display_max_rpm) 
                
        # Légendes combinées
        lines, labels = self.ax.get_legend_handles_labels()
        lines2, labels2 = self.ax_fan.get_legend_handles_labels()
        self.ax_fan.legend(lines + lines2, labels + labels2, loc='upper left', fontsize='small')
        
        self.ax.grid(True, linestyle=':', alpha=0.6)
        
        # Appliquer les changements au canevas
        self.canvas.draw()

    def update_process_list_display(self, processes):
        """Rafraîchit le TreeView avec la nouvelle liste de processus."""
        
        # Effacer l'ancienne liste
        self.tree.delete(*self.tree.get_children())
        
        # Insérer les nouvelles données
        for proc in processes:
            pid = proc.get('pid', 'N/A')
            name = proc.get('name', 'N/A')
            cpu = proc.get('cpu_percent', 0.0)
            mem = proc.get('memory_percent', 0.0)
            
            # Insérer la ligne dans le TreeView
            self.tree.insert('', 'end', values=(pid, name, f"{cpu:.1f}", f"{mem:.1f}"))
            
    def on_close_request(self):
        """
        Appelée quand l'utilisateur clique sur le 'X'.
        Demande s'il faut quitter ou minimiser en widget.
        """
        # On importe 'messagebox' seulement ici pour ne pas encombrer le début
        from tkinter import messagebox
        
        # 'askyesnocancel' renvoie: True (Oui), False (Non), None (Annuler)
        reponse = messagebox.askyesnocancel(
            "Quitter ?",
            "Voulez-vous réduire l'application en widget ?\n\n"
            "[Oui] = Réduire en widget\n"
            "[Non] = Quitter l'application\n"
            "[Annuler] = Rester sur l'application",
            icon='warning' # icône de question/avertissement
        )

        if reponse is True:  # Bouton [Oui]
            self.minimize_to_widget()
        elif reponse is False: # Bouton [Non]
            self.quit_application()
        else: # Bouton [Annuler] (reponse is None)
            pass # Ne rien faire

    def quit_application(self):
        """Ferme proprement l'application (Tkinter, Pystray et Pynvml)."""
        
        # --- Sauvegarder l'état final ---
        self.save_settings()
        
        # Arrêter Pynvml
        if NVIDIA_AVAILABLE and self.gpu_handle:
            try:
                pynvml.nvmlShutdown()
                print("Surveillance NVIDIA arrêtée.")
            except Exception as e:
                print(f"Erreur lors de nvmlShutdown: {e}")
        
        # Arrêter Pystray
        if self.tray_icon:
            self.tray_icon.stop()
            
        # Arrêter Tkinter
        self.destroy()

    def minimize_to_widget(self):
        """Cache la fenêtre principale et crée le widget (cercle OU carré)."""
        
        # 1. Cacher la fenêtre principale
        self.withdraw()
        
        # 2. Créer la fenêtre widget (si elle n'existe pas déjà)
        if self.widget_window is None or not self.widget_window.winfo_exists():
            self.widget_window = tk.Toplevel(self)
            
            # --- Configuration de base du widget ---
            self.widget_window.overrideredirect(True) 
            self.widget_window.attributes("-topmost", True) 
            
            # --- Créer le menu clic-droit (commun aux deux formes) ---
            menu = tk.Menu(self.widget_window, tearoff=0)
            menu.add_command(label="Changer de forme", command=self.toggle_widget_shape)
            menu.add_separator()
            menu.add_command(label="Afficher le moniteur", command=self.show_main_window)
            menu.add_separator()
            menu.add_command(label="Quitter", command=self.quit_application)

            # --- DÉBUT LOGIQUE DE FORME ---
            
            if self.widget_shape == "circle":
                # --- A. FORME CERCLE ---
                TRANSPARENT_COLOR = 'lime' 
                self.widget_window.config(bg=TRANSPARENT_COLOR)
                try:
                    self.widget_window.wm_attributes('-transparentcolor', TRANSPARENT_COLOR)
                except tk.TclError:
                    print("'-transparentcolor' n'est pas supporté sur cet OS.")

                screen_width = self.winfo_screenwidth()
                self.widget_window.geometry(f"120x120+{screen_width - 130}+30")

                self.widget_canvas = tk.Canvas(self.widget_window, width=120, height=120, bg=TRANSPARENT_COLOR, highlightthickness=0)
                self.widget_canvas.pack()
                self.widget_canvas.create_oval(5, 5, 115, 115, fill='dim gray', outline='cyan', width=2)
                
                self.widget_text_id = self.widget_canvas.create_text(
                    60, 55, 
                    text="CPU: ...\nRAM: ...\nGPU: ...\nFan: ...", 
                    fill="white", font=("Consolas", 10, "bold"), justify=tk.CENTER
                )
                
                # --- Slider Transparence ---
                alpha_slider = ttk.Scale(self.widget_window, 
                                         from_=0.2, to=1.0, 
                                         value=self.widget_alpha, # Utiliser valeur chargée
                                         orient=tk.HORIZONTAL, 
                                         command=self.on_alpha_change, # Utiliser nouvelle fonction
                                         length=100)
                self.widget_canvas.create_window(60, 100, window=alpha_slider, anchor=tk.S)
                
                # Liaisons (clics)
                self.widget_window.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
                self.widget_canvas.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
                alpha_slider.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

            else:
                # --- B. FORME CARRÉ ---
                self.widget_shape = "square" 
                self.widget_window.config(bg='dim gray') 
                
                screen_width = self.winfo_screenwidth()
                self.widget_window.geometry(f"160x100+{screen_width - 170}+30")

                self.widget_frame = ttk.Frame(self.widget_window, style="TFrame")
                self.widget_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                
                self.widget_label = ttk.Label(self.widget_frame, 
                                             text="CPU: ...\nRAM: ...\nGPU: ...\nFan: ...", 
                                             font=("Consolas", 10, "bold"),
                                             justify=tk.LEFT,
                                             style="TLabel")
                self.widget_label.pack(pady=5)

                # --- Slider Transparence ---
                alpha_slider = ttk.Scale(self.widget_frame, 
                                         from_=0.2, to=1.0, 
                                         value=self.widget_alpha, # Utiliser valeur chargée
                                         orient=tk.HORIZONTAL, 
                                         command=self.on_alpha_change, # Utiliser nouvelle fonction
                                         length=100)
                alpha_slider.pack(fill='x', padx=5, pady=5)
                
                # Liaisons (clics)
                self.widget_window.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
                self.widget_frame.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
                self.widget_label.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
                alpha_slider.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

            # --- FIN LOGIQUE DE FORME ---
            
            # Appliquer la transparence (lue depuis les settings)
            self.widget_window.attributes("-alpha", self.widget_alpha)
            # Rendre le widget déplaçable
            self.make_widget_draggable(self.widget_window)

    # --- Curseur de Transparence (facultatif mais sympa) ---
    def change_transparency(value_str):
        self.widget_window.attributes("-alpha", float(value_str))

        alpha_slider = ttk.Scale(self.widget_window, 
                                from_=0.2, to=1.0, value=0.8,
                                orient=tk.HORIZONTAL,
                                command=change_transparency,
                                length=100)
            
        # Placer le curseur en bas, DANS le cercle (via le canvas)
        self.widget_canvas.create_window(60, 100, window=alpha_slider, anchor=tk.S)
            
        # Appliquer la transparence par défaut
        self.widget_window.attributes("-alpha", 0.8)

        # --- Rendre le widget déplaçable ---
        self.make_widget_draggable(self.widget_window)
            
        # --- Ajouter un menu clic-droit ---
        menu = tk.Menu(self.widget_window, tearoff=0)
        menu.add_command(label="Afficher le moniteur", command=self.show_main_window)
        menu.add_separator()
        menu.add_command(label="Quitter", command=self.quit_application)
            
        self.widget_window.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
        self.widget_canvas.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
            
    def make_widget_draggable(self, widget):
        """Permet de déplacer un widget 'overrideredirect' avec la souris."""
        self._drag_start_x = 0
        self._drag_start_y = 0

        def on_drag_start(event):
            self._drag_start_x = event.x
            self._drag_start_y = event.y

        def on_drag_motion(event):
            x = widget.winfo_x() - self._drag_start_x + event.x
            y = widget.winfo_y() - self._drag_start_y + event.y
            widget.geometry(f"+{x}+{y}") # Déplace la fenêtre

        # Lier le widget lui-même
        widget.bind("<Button-1>", on_drag_start)
        widget.bind("<B1-Motion>", on_drag_motion)
        
        # Lier les composants internes
        if self.widget_shape == "circle" and self.widget_canvas:
            self.widget_canvas.bind("<Button-1>", on_drag_start)
            self.widget_canvas.bind("<B1-Motion>", on_drag_motion)
        elif self.widget_shape == "square":
            if self.widget_frame:
                self.widget_frame.bind("<Button-1>", on_drag_start)
                self.widget_frame.bind("<B1-Motion>", on_drag_motion)
            if self.widget_label:
                self.widget_label.bind("<Button-1>", on_drag_start)
                self.widget_label.bind("<B1-Motion>", on_drag_motion)
        
    def show_main_window(self):
        """Détruit le widget et ré-affiche la fenêtre principale."""
        
        # 1. Détruire le widget
        if self.widget_window and self.widget_window.winfo_exists():
            self.widget_window.destroy()
        
        # 2. Réinitialiser les variables
        self.widget_window = None
        self.widget_canvas = None
        self.widget_text_id = None
        self.widget_label = None
        self.widget_frame = None
        
        # 3. Afficher la fenêtre principale
        self.deiconify() # C'est l'inverse de self.withdraw()
        self.attributes('-topmost', True) # Remettre la fenêtre au premier plan
        self.after(100, lambda: self.attributes('-topmost', False))
        
    def toggle_widget_shape(self):
        """Bascule la forme du widget entre cercle et carré."""
        
        # Basculer la variable d'état
        if self.widget_shape == "circle":
            self.widget_shape = "square"
        else:
            self.widget_shape = "circle"
            
        # --- Sauvegarder le choix ---
        self.save_settings()
            
        # Détruire l'ancien widget (s'il existe)
        if self.widget_window and self.widget_window.winfo_exists():
            self.widget_window.destroy()

        # Réinitialiser les variables
        self.widget_window = None
        self.widget_canvas = None
        self.widget_text_id = None
        self.widget_label = None
        self.widget_frame = None
        
        # Recréer le widget (qui lira la nouvelle valeur de self.widget_shape)
        self.after(50, self.minimize_to_widget)
        
    def load_settings(self):
        """Charge les préférences depuis config.json au démarrage."""
        try:
            with open(self.config_file, 'r') as f:
                settings = json.load(f)
            
            # 1. Charger et appliquer le thème
            default_theme = "arc" # Thème par défaut si celui sauvé n'existe plus
            loaded_theme = settings.get("theme", default_theme)
            if loaded_theme not in self.get_themes():
                loaded_theme = default_theme
                
            self.set_theme(loaded_theme) 
            self.theme_combo.set(loaded_theme) # Mettre à jour le combobox
            
            # 2. Charger la forme du widget
            self.widget_shape = settings.get("shape", "circle")
            
            # 3. Charger la transparence
            self.widget_alpha = float(settings.get("alpha", 0.8))
            
            print(f"Préférences chargées : {settings}")

        except FileNotFoundError:
            print("Aucun fichier config.json trouvé. Utilisation des défauts.")
            # Les valeurs par défaut de __init__ seront utilisées
        except Exception as e:
            print(f"Erreur lors du chargement de config.json : {e}")

    def save_settings(self):
        """Sauvegarde les préférences actuelles dans config.json."""
        settings = {
            "theme": self.current_theme,
            "shape": self.widget_shape,
            "alpha": self.widget_alpha
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(settings, f, indent=4)
            print(f"Préférences sauvegardées : {settings}")
        except Exception as e:
            print(f"Erreur lors de la sauvegarde de config.json : {e}")

    def on_alpha_change(self, value_str):
        """Appelée par le slider de transparence."""
        self.widget_alpha = float(value_str)
        
        # Appliquer la transparence immédiatement
        if self.widget_window and self.widget_window.winfo_exists():
            self.widget_window.attributes("-alpha", self.widget_alpha)
            
        # Sauvegarder le choix
        self.save_settings()
        
    def setup_system_tray(self):
        """Crée et lance l'icône de la barre système (s'exécute dans un thread)."""
        try:
            image = Image.open("icon.png")
        except FileNotFoundError:
            # Créer une image par défaut si 'icon.png' n'existe pas
            image = Image.new('RGB', (64, 64), color='blue')
            print("Erreur: 'icon.png' non trouvé. Utilisation d'une image par défaut.")

        # Définir le menu de l'icône
        menu = (
            pystray.MenuItem('Afficher le moniteur', self.show_window_from_tray, default=True),
            pystray.MenuItem('Quitter', self.quit_from_tray)
        )

        # Créer l'icône
        self.tray_icon = pystray.Icon("ProcessMonitor", image, "Moniteur de Processus", menu)
        
        # Lancer la boucle de l'icône (cette ligne bloque ce thread)
        self.tray_icon.run()

    def show_window_from_tray(self):
        """
        Demande au thread Tkinter de ré-afficher la fenêtre.
        Appelé depuis le thread pystray.
        """
        self.after(0, self.deiconify) # 'deiconify' est l'inverse de 'withdraw'

    def quit_from_tray(self):
        """
        Arrête l'icône ET demande à Tkinter de se fermer.
        Appelé depuis le thread pystray.
        """
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self.quit_application) # Appelle la fermeture propre

# --- Point d'entrée principal ---
if __name__ == "__main__":
    app = ProcessMonitorApp()
    app.mainloop()