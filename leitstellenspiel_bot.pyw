import time
import json
import os
import re
import sys
import threading
import tempfile
import queue
import tkinter as tk
from tkinter import messagebox
from collections import Counter
import traceback
from datetime import date
import requests
import math

# --- NEUE IMPORTS FÜR MODERNES UI ---
import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# --- SELENIUM IMPORTS ---
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# -----------------------------------------------------------------------------------
# KONFIGURATION & SETUP
# -----------------------------------------------------------------------------------

# UI Design Einstellungen
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Ermittelt den korrekten Pfad zu einer Ressource. """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Konfiguration laden ---
try:
    with open(resource_path('config.json'), 'r', encoding='utf-8') as f:
        config = json.load(f)
        LEITSTELLENSPIEL_USERNAME = config['username']
        LEITSTELLENSPIEL_PASSWORD = config['password']
        USE_TERMINAL = config.get('use_terminal', False)
except FileNotFoundError:
    print("FEHLER: Die Datei 'config.json' wurde nicht gefunden."); time.sleep(10); sys.exit()
except KeyError:
    print("FEHLER: In der 'config.json' fehlen Zugangsdaten."); time.sleep(10); sys.exit()

# --- Fahrzeug-Datenbank laden ---
def load_vehicle_database(file_path=resource_path("fahrzeug_datenbank.json")):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"FEHLER: Die Datenbank-Datei '{file_path}' wurde nicht gefunden!"); return None
    except json.JSONDecodeError:
        print(f"FEHLER: Die Datei '{file_path}' hat ein ungültiges JSON-Format."); return None

VEHICLE_DATABASE = load_vehicle_database()
if not VEHICLE_DATABASE:
    print("Bot wird beendet, da die Fahrzeug-Datenbank nicht geladen werden konnte."); time.sleep(10); sys.exit()

# --- Globale Konstanten ---
BOT_VERSION = "V1.2.1 - UI Fix"
PAUSE_IF_NO_VEHICLES_SECONDS = 300
MAX_START_DELAY_SECONDS = 3600
MINIMUM_CREDITS = 10000
ADDED_TO_DATABASE = []

# -----------------------------------------------------------------------------------
# MODERNES UI (CustomTkinter)
# -----------------------------------------------------------------------------------

class ModernApp(ctk.CTk):
    def __init__(self, pause_event, stop_event, gui_queue):
        super().__init__()
        self.gui_queue = gui_queue
        self.pause_event = pause_event
        self.stop_event = stop_event

        # Fenster Setup
        self.title(f"LSS Bot {BOT_VERSION} | {LEITSTELLENSPIEL_USERNAME}")
        self.geometry("1000x750") # Etwas höher
        self.minsize(800, 600)

        # Layout Grid Config
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar (Links) ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LSS COMMAND", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.status_label_sidebar = ctk.CTkLabel(self.sidebar_frame, text="Status: Startet...", font=ctk.CTkFont(size=12))
        self.status_label_sidebar.grid(row=1, column=0, padx=20, pady=10)

        self.pause_button = ctk.CTkButton(self.sidebar_frame, text="Pause", command=self.toggle_pause)
        self.pause_button.grid(row=2, column=0, padx=20, pady=10)

        self.stop_button = ctk.CTkButton(self.sidebar_frame, text="Beenden", fg_color="red", hover_color="darkred", command=self.stop_bot)
        self.stop_button.grid(row=3, column=0, padx=20, pady=10)

        # --- Hauptbereich (Tabs) ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        
        self.tab_dashboard = self.tabview.add("Live Log")
        self.tab_stats = self.tabview.add("Statistik & Ressourcen")

        # Tab 1: Dashboard (Text Informationen)
        self.tab_dashboard.grid_columnconfigure(0, weight=1)
        self.tab_dashboard.grid_rowconfigure(1, weight=1)
        
        # Info Boxen
        self.info_frame = ctk.CTkFrame(self.tab_dashboard)
        self.info_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        self.lbl_mission = ctk.CTkLabel(self.info_frame, text="Aktueller Einsatz:", font=ctk.CTkFont(weight="bold"))
        self.lbl_mission.pack(anchor="w", padx=10, pady=(10,0))
        self.val_mission = ctk.CTkLabel(self.info_frame, text="-", wraplength=600, justify="left")
        self.val_mission.pack(anchor="w", padx=10, pady=(0,10))

        self.lbl_req = ctk.CTkLabel(self.info_frame, text="Bedarf:", font=ctk.CTkFont(weight="bold"))
        self.lbl_req.pack(anchor="w", padx=10)
        self.val_req = ctk.CTkLabel(self.info_frame, text="-", wraplength=600, justify="left")
        self.val_req.pack(anchor="w", padx=10, pady=(0,10))
        
        self.lbl_alarm = ctk.CTkLabel(self.info_frame, text="Ergebnis:", font=ctk.CTkFont(weight="bold"))
        self.lbl_alarm.pack(anchor="w", padx=10)
        self.val_alarm = ctk.CTkLabel(self.info_frame, text="-", wraplength=600, justify="left")
        self.val_alarm.pack(anchor="w", padx=10, pady=(0,10))

        # Scrollbare Textbox für Logs
        self.log_box = ctk.CTkTextbox(self.tab_dashboard, height=200)
        self.log_box.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.log_box.insert("0.0", "Warte auf Fahrzeugdaten...\n")

        # --- Tab 2: Statistik (Matplotlib Grafik & Fahrzeugliste) ---
        # WICHTIG: Grid Konfiguration korrigiert!
        self.tab_stats.grid_columnconfigure(0, weight=1)
        
        # Row 0: Chart (Soll nicht wachsen, feste Größe behalten) -> weight=0
        self.tab_stats.grid_rowconfigure(0, weight=0) 
        # Row 1: Label (Soll nicht wachsen) -> weight=0
        self.tab_stats.grid_rowconfigure(1, weight=0)
        # Row 2: Liste (Soll den ganzen Restplatz bekommen) -> weight=1
        self.tab_stats.grid_rowconfigure(2, weight=1)

        self.setup_chart()
        
        # Label für die Liste
        self.list_label = ctk.CTkLabel(self.tab_stats, text="Detaillierte Fahrzeugliste (Verfügbar)", font=ctk.CTkFont(size=14, weight="bold"))
        self.list_label.grid(row=1, column=0, pady=(5,0), sticky="w", padx=10)

        # Scrollbarer Bereich
        self.vehicle_scroll_frame = ctk.CTkScrollableFrame(self.tab_stats, label_text="Fahrzeuge")
        self.vehicle_scroll_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        
        # Initialer Text in der Liste
        initial_label = ctk.CTkLabel(self.vehicle_scroll_frame, text="Warte auf ersten Scan...")
        initial_label.pack(anchor="w", padx=5, pady=5)

        # Update Loop starten
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self.process_queue)

    def setup_chart(self):
        # Erstelle eine Matplotlib Figur (Höhe reduziert von 5 auf 3.5)
        self.figure = Figure(figsize=(5, 3.5), dpi=100)
        self.figure.patch.set_facecolor('#2b2b2b') # Dunkelgrau
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor('#2b2b2b')
        self.ax.text(0.5, 0.5, 'Warte auf Daten...', 
                     horizontalalignment='center', verticalalignment='center', color='white')
        self.ax.axis('off')

        # Canvas für Tkinter
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.tab_stats)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="ew", padx=10, pady=10)

    def update_chart(self, data):
        """Aktualisiert das Diagramm mit neuen Personal-Daten"""
        self.ax.clear()
        
        labels = []
        sizes = []
        colors = []
        
        # Mapping für Farben
        color_map = {'FW': '#ff4d4d', 'RD': '#ffffff', 'POL': '#4dff4d', 'THW': '#4d4dff'}
        
        for org, count in data.items():
            if count > 0:
                labels.append(org)
                sizes.append(count)
                colors.append(color_map.get(org, '#cccccc'))

        if not sizes:
            self.ax.text(0.5, 0.5, 'Keine Einheiten verfügbar', color='white', ha='center')
        else:
            wedges, texts, autotexts = self.ax.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                                   colors=colors, startangle=90,
                                                   textprops={'color':"w"})
            self.ax.set_title("Verfügbares Personal (Live)", color='white', pad=10)
        
        self.figure.tight_layout()
        self.canvas.draw()

    def update_vehicle_list_ui(self, vehicle_counts):
        """Aktualisiert die scrollbare Liste mit Fahrzeugen"""
        # Alte Widgets entfernen
        for widget in self.vehicle_scroll_frame.winfo_children():
            widget.destroy()

        if not vehicle_counts:
            ctk.CTkLabel(self.vehicle_scroll_frame, text="Keine Fahrzeuge verfügbar").pack(anchor="w", padx=5)
            return

        # Sortieren nach Anzahl (absteigend) oder Name
        sorted_vehicles = sorted(vehicle_counts.items(), key=lambda x: x[0])
        
        for name, count in sorted_vehicles:
            # Container für eine Zeile
            row_frame = ctk.CTkFrame(self.vehicle_scroll_frame, fg_color="transparent", height=30)
            row_frame.pack(fill="x", padx=5, pady=2)
            
            lbl_name = ctk.CTkLabel(row_frame, text=f"{name}", anchor="w", font=ctk.CTkFont(weight="bold"))
            lbl_name.pack(side="left", padx=5)
            
            lbl_count = ctk.CTkLabel(row_frame, text=f"{count}x", anchor="e", text_color="#aaaaaa")
            lbl_count.pack(side="right", padx=5)

    def process_queue(self):
        try:
            while True:
                message = self.gui_queue.get_nowait()
                key, value = message

                if key == 'status':
                    self.status_label_sidebar.configure(text=f"Status: {value}")
                elif key == 'mission_name':
                    self.val_mission.configure(text=value)
                elif key == 'requirements':
                    self.val_req.configure(text=value)
                elif key == 'alarm_status':
                    self.val_alarm.configure(text=value)
                elif key == 'availability_text':
                    self.log_box.configure(state="normal")
                    self.log_box.delete("0.0", "end")
                    self.log_box.insert("0.0", value)
                    self.log_box.configure(state="disabled")
                elif key == 'stats_data':
                    self.update_chart(value)
                elif key == 'vehicle_list_data':
                    self.update_vehicle_list_ui(value)
                elif key == 'batch_update':
                    if 'status' in value: self.status_label_sidebar.configure(text=f"Status: {value['status']}")
                    if 'mission_name' in value: self.val_mission.configure(text=value['mission_name'])
                    if 'requirements' in value: self.val_req.configure(text=value['requirements'])
                    if 'alarm_status' in value: self.val_alarm.configure(text=value['alarm_status'])

        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.configure(text="Weiter", fg_color="green")
            self.status_label_sidebar.configure(text="Status: Pausiert")
        else:
            self.pause_event.set()
            self.pause_button.configure(text="Pause", fg_color="#1f6aa5")
            self.status_label_sidebar.configure(text="Status: Läuft")

    def stop_bot(self):
        self.status_label_sidebar.configure(text="Beende...")
        self.stop_event.set()
        self.after(1000, self.destroy)

    def on_closing(self):
        self.stop_bot()

# -----------------------------------------------------------------------------------
# TERMINAL MODE (HEADLESS)
# -----------------------------------------------------------------------------------

class TerminalHandler:
    def __init__(self, pause_event, stop_event, gui_queue):
        self.pause_event = pause_event
        self.stop_event = stop_event
        self.gui_queue = gui_queue
        self.running = True
        
        self.listener = threading.Thread(target=self.listen_to_queue)
        self.listener.start()
        
        print("--- HEADLESS MODE GESTARTET ---")
        print("Drücke STRG+C zum Beenden.")

    def listen_to_queue(self):
        while self.running:
            try:
                msg = self.gui_queue.get(timeout=1)
                key, value = msg
                
                if key == 'status':
                    print(f"[STATUS] {value}")
                elif key == 'mission_name':
                    print(f"\n>> EINSATZ: {value}")
                elif key == 'alarm_status':
                    print(f"[ALARM] {value}")
                
            except queue.Empty:
                continue
            except Exception:
                break
    
    def wait_for_exit(self):
        try:
            while True:
                time.sleep(1)
                if self.stop_event.is_set():
                    break
        except KeyboardInterrupt:
            print("\nBeende Bot...")
            self.stop_event.set()
            self.running = False

# -----------------------------------------------------------------------------------
# BOT-HILFSFUNKTIONEN
# -----------------------------------------------------------------------------------

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    # Stabilitäts-Flags
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")

    user_data_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    
    if sys.platform.startswith('linux'):
        user_agent = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    else:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    
    chrome_options.add_argument(f'user-agent={user_agent}')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        print("Info: Prüfe und aktualisiere ChromeDriver...")
        service = ChromeService(ChromeDriverManager().install())
        
        # --- HIER WIRD DAS TERMINAL FENSTER VOM DRIVER UNTERDRÜCKT (Windows) ---
        if sys.platform == "win32":
            service.creation_flags = 0x08000000  # CREATE_NO_WINDOW
            
    except Exception as e:
        print(f"WARNUNG: Automatisches Update fehlgeschlagen ({e}). Versuche lokalen Treiber...")
        if sys.platform.startswith('linux'):
            service = ChromeService(executable_path="/usr/bin/chromedriver")
        else:
            service = ChromeService(executable_path=resource_path("chromedriver.exe"))
            if sys.platform == "win32":
                service.creation_flags = 0x08000000
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver
    
def get_mission_requirements(driver, wait, player_inventory, given_patients, mission_name, mission_cache):
    # --- ANPASSBARE ÜBERSETZUNGS-LISTE ---
    translation_map = {
        "Feuerwehrkräne (FwK)": "FwK",
        "Drehleitern": "Drehleiter",
        "Rettungswagen": "RTW",
        "Löschfahrzeuge": "Löschfahrzeug",
        "Gerätewagen Öl": "GW-Öl",
        "Seenotrettungsboote": "Seenotrettungsboot",
        "Funkstreifenwagen (Dienstgruppenleitung)": "FuStW (DGL)"
    }

    iframe_locator = (By.TAG_NAME, "iframe")
    raw_requirements = {
        'fahrzeuge': [], 'fahrzeuge_optional': [], 'patienten': 0, 'credits': 0,
        'wasser': 0, 'schaummittel': 0,
        'personal_fw': 0, 'personal_thw': 0, 'personal_rd': 0, 'personal_pol': 0, 'betreuung_ratio': 0
    }
    try:
        wait.until(EC.frame_to_be_available_and_switch_to_it(iframe_locator))
        
        hilfe_button_xpath = "//*[@id='mission_help']" 
        hilfe_button = wait.until(EC.element_to_be_clickable((By.XPATH, hilfe_button_xpath)))
        driver.execute_script("arguments[0].click();", hilfe_button)

        credits, min_patients, max_patients = 0, 0, 0
        try:
            credits_text = driver.find_element(By.XPATH, "//td[normalize-space()='Credits im Durchschnitt']/following-sibling::td").text.strip().replace(".", "").replace(",", "")
            if credits_text.isdigit(): credits = int(credits_text)
        except NoSuchElementException: pass
        
        try:
            min_patients_text = driver.find_element(By.XPATH, "//td[normalize-space()='Mindest Patientenanzahl']/following-sibling::td").text.strip()
            if min_patients_text.isdigit(): min_patients = int(min_patients_text)
        except NoSuchElementException: pass

        try:
            max_patients_text = driver.find_element(By.XPATH, "//td[normalize-space()='Maximale Patientenanzahl']/following-sibling::td").text.strip()
            if max_patients_text.isdigit(): max_patients = int(max_patients_text)
        except NoSuchElementException: pass

        cache_key = f"{mission_name}_{credits}_{min_patients}_{max_patients}"

        if cache_key in mission_cache:
            print(f"Info: Anforderungen für '{cache_key}' aus dem Cache geladen.")
            cached_reqs = mission_cache[cache_key].copy()
            cached_reqs['patienten'] = given_patients if given_patients > 0 else min_patients
            return cached_reqs
        
        print(f"Info: Einsatz '{cache_key}' nicht im Cache. Lese Anforderungen neu ein.")

        try:
            vehicle_table = wait.until(EC.visibility_of_element_located((By.XPATH, "//table[.//th[contains(text(), 'Fahrzeuge')]]")))
            rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")

            def normalize_name(name):
                clean = name.replace("Benötigte ", "")
                return translation_map.get(clean, clean)

            def player_has_vehicle_of_type(required_type, inventory, database):
                for owned_vehicle_name in inventory:
                    if owned_vehicle_name in database and required_type in database[owned_vehicle_name].get("typ", []): return True
                return False

            ignored_optional_types = set()
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) < 2: continue
                requirement_text = cells[0].text.strip()
                is_optional = "anforderungswahrscheinlichkeit" in requirement_text.lower() or "nur angefordert, wenn vorhanden" in requirement_text.lower()
                if is_optional:
                    clean_name = requirement_text.replace("nur angefordert, wenn vorhanden", "").replace("Anforderungswahrscheinlichkeit", "").replace("Benötigte", "").strip()
                    normalized_name = normalize_name(clean_name)
                    if not player_has_vehicle_of_type(normalized_name, player_inventory, VEHICLE_DATABASE):
                        print(f"      -> Info: Anforderung '{normalized_name}' wird für diesen Einsatz ignoriert (nicht im Inventar).")
                        ignored_optional_types.add(normalized_name)
            
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) < 2: continue
                requirement_text, count_text = cells[0].text.strip(), cells[1].text.strip().replace(" L", "")
                clean_name = requirement_text.replace("nur angefordert, wenn vorhanden", "").replace("Anforderungswahrscheinlichkeit", "").replace("Benötigte", "").strip()
                normalized_name = normalize_name(clean_name)
                
                if normalized_name in ignored_optional_types: continue
                if "anforderungswahrscheinlichkeit" in requirement_text.lower() or "nur angefordert, wenn vorhanden" in requirement_text.lower(): continue

                req_lower = requirement_text.lower()
                numbers = re.findall(r'\d+', count_text)
                count = int(numbers[-1]) if numbers else 0

                if 'wasserwerfer' in clean_name.lower():
                    if count_text.isdigit():
                        for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Wasserwerfer"])
                    continue

                if 'polizisten' in req_lower:
                    raw_requirements['personal_pol'] += count; continue
                elif 'personalanzahl (thw)' in req_lower:
                    raw_requirements['personal_thw'] += count; continue
                elif 'rettungsdienst' in req_lower:
                    raw_requirements['personal_rd'] += count; continue
                elif 'feuerwehrleute' in req_lower:
                    raw_requirements['personal_fw'] += count; continue
                
                if 'betreuungs- und verpflegungsausstattung' in req_lower:
                    ratio_match = re.search(r'pro (\d+)', count_text)
                    if ratio_match:
                        ratio = int(ratio_match.group(1))
                        raw_requirements['betreuung_ratio'] = ratio
                    continue

                req_lower_clean = clean_name.lower()
                if any(keyword in req_lower_clean for keyword in ["schlauchwagen", "wasser", "sonderlöschmittelbedarf", "feuerlöschpumpe"]):
                    if "schlauchwagen" in req_lower_clean:
                        if count_text.isdigit():
                            for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Schlauchwagen"])
                    elif "wasser" in req_lower_clean:
                        if count_text.isdigit(): raw_requirements['wasser'] += int(count_text)
                    elif "sonderlöschmittelbedarf" in req_lower_clean:
                        if count_text.isdigit(): raw_requirements['schaummittel'] += int(count_text)
                    elif "feuerlöschpumpe" in req_lower_clean:
                        if count_text.isdigit():
                            for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Löschfahrzeug", "Tanklöschfahrzeug"])
                    continue

                options_text = [p.strip() for p in clean_name.replace(",", " oder ").split(" oder ")]
                final_options = [normalize_name(opt) for opt in options_text if opt]
                if count_text.isdigit() and final_options:
                    for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(final_options)
        except TimeoutException: print("Info: No vehicle requirement table found.")

        def process_probability_requirement(vehicle_name, probability_text_identifier):
            try:
                prob_text_cell = driver.find_element(By.XPATH, f"//td[contains(text(), '{probability_text_identifier}')]")
                prob_value_cell = prob_text_cell.find_element(By.XPATH, "./following-sibling::td")
                match = re.search(r'(\d+)', prob_value_cell.text)
                if not match: return
                probability = int(match.group(1))
                if player_has_vehicle_of_type(vehicle_name, player_inventory, VEHICLE_DATABASE):
                    if probability > 80: raw_requirements['fahrzeuge'].append([vehicle_name])
                    else: raw_requirements['fahrzeuge_optional'].append([vehicle_name])
            except NoSuchElementException: pass
        
        process_probability_requirement("NEF", "NEF Anforderungswahrscheinlichkeit")
        process_probability_requirement("RTH", "RTH Anforderungswahrscheinlichkeit")

        raw_requirements['credits'] = credits
        raw_requirements['patienten'] = given_patients if given_patients > 0 else min_patients
        
        final_reqs_for_cache = raw_requirements.copy()
        final_reqs_for_cache['patienten'] = min_patients
        mission_cache[cache_key] = final_reqs_for_cache
        print(f"      -> Anforderungen für '{cache_key}' zum Cache hinzugefügt.")

    except TimeoutException: 
        print(f"FEHLER: Der 'Hilfe'-Button mit XPath {hilfe_button_xpath} konnte auch im iFrame nicht gefunden werden.")
        return None
    finally:
        try: 
            wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Zurück' or @class='close' or contains(text(), 'Schließen')]"))).click()
        except: 
            driver.refresh()
    return raw_requirements

def get_available_vehicles(driver, wait):
    available_vehicles = []
    vehicle_table_selector = "#vehicle_show_table_all"
    
    try:
        try:
            load_more_button_selector = "//a[contains(@class, 'missing_vehicles_load')]"
            load_more_button = driver.find_element(By.XPATH, load_more_button_selector)
            vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
            initial_rows = len(vehicle_table.find_elements(By.XPATH, ".//tbody/tr"))
            driver.execute_script("arguments[0].click();", load_more_button)
            wait.until(lambda d: len(d.find_element(By.CSS_SELECTOR, vehicle_table_selector).find_elements(By.XPATH, ".//tbody/tr")) > initial_rows)
        except NoSuchElementException:
            pass

        vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
        vehicle_rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
        
        for row in vehicle_rows:
            try:
                checkbox = row.find_element(By.CSS_SELECTOR, "input.vehicle_checkbox")
                vehicle_type = row.get_attribute('vehicle_type')
                
                if vehicle_type and vehicle_type in VEHICLE_DATABASE:
                    full_vehicle_name = row.get_attribute('vehicle_caption') or "Unbekannter Name"
                    vehicle_properties = VEHICLE_DATABASE[vehicle_type]
                    available_vehicles.append({
                        'properties': vehicle_properties, 
                        'checkbox': checkbox, 
                        'name': full_vehicle_name,
                        'vehicle_type': vehicle_type
                    })
            except NoSuchElementException:
                continue
    except TimeoutException:
        print(f"FEHLER: Die Fahrzeug-Tabelle konnte nicht gefunden werden.")
    
    return available_vehicles

def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
    needed_vehicle_options_list = requirements.get('fahrzeuge', []).copy()
    optional_vehicle_options_list = requirements.get('fahrzeuge_optional', []).copy()
    needed_wasser = requirements.get('wasser', 0)
    needed_schaummittel = requirements.get('schaummittel', 0)
    patient_bedarf = requirements.get('patienten', 0)

    needed_fw = requirements.get('personal_fw', 0)
    needed_thw = requirements.get('personal_thw', 0)
    needed_rd = requirements.get('personal_rd', 0)
    needed_pol = requirements.get('personal_pol', 0)

    KTW_B_allowed = patient_bedarf > 5
    if patient_bedarf >= 5:
        needed_vehicle_options_list.extend([["KdoW-LNA"], ["GW-San"], ["ELW 1 (SEG)"]])
    if patient_bedarf >= 10:
        needed_vehicle_options_list.append(["KdoW-OrgL"])

    explicit_rtw_count = sum(1 for options in needed_vehicle_options_list if "RTW" in options)
    needed_vehicle_options_list = [options for options in needed_vehicle_options_list if "RTW" not in options]
    rtws_to_add = min(patient_bedarf, 15)
    final_rtw_bedarf = max(explicit_rtw_count, rtws_to_add)
    for _ in range(final_rtw_bedarf):
        needed_vehicle_options_list.append(["RTW", "KTW Typ B"] if KTW_B_allowed else ["RTW"])

    vehicles_to_send = []
    pool = list(available_vehicles)
    unfulfilled_slots = list(needed_vehicle_options_list)

    for slot in list(unfulfilled_slots):
        for vehicle in list(pool):
            vehicle_roles = set(vehicle['properties'].get('typ', []))
            if not vehicle_roles.isdisjoint(slot):
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                unfulfilled_slots.remove(slot)
                break 

    for optional_slot in list(optional_vehicle_options_list):
        for vehicle in list(pool):
            vehicle_roles = set(vehicle['properties'].get('typ', []))
            if not vehicle_roles.isdisjoint(optional_slot):
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                break

    provided_fw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'FW')
    provided_thw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'THW')
    provided_rd = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'RD')
    provided_pol = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'POL')

    def fill_personnel_deficit(needed, provided, fraktion):
        nonlocal pool, vehicles_to_send
        if provided < needed:
            faction_pool = sorted([v for v in pool if v['properties'].get('fraktion') == fraktion], key=lambda v: v['properties'].get('personal', 0), reverse=True)
            for vehicle in faction_pool:
                if provided >= needed: break
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                provided += vehicle['properties'].get('personal', 0)
        return provided
    
    provided_fw = fill_personnel_deficit(needed_fw, provided_fw, 'FW')
    provided_thw = fill_personnel_deficit(needed_thw, provided_thw, 'THW')
    provided_rd = fill_personnel_deficit(needed_rd, provided_rd, 'RD')
    provided_pol = fill_personnel_deficit(needed_pol, provided_pol, 'POL')

    provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    provided_patienten_kapazitaet = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)
    
    def fill_resource_deficit(needed, provided, resource_key):
        nonlocal pool, vehicles_to_send
        if provided < needed:
            resource_pool = sorted([v for v in pool if v['properties'].get(resource_key, 0) > 0], key=lambda v: v['properties'].get(resource_key, 0), reverse=True)
            for vehicle in resource_pool:
                if provided >= needed: break
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                provided += vehicle['properties'].get(resource_key, 0)
        return provided

    fill_resource_deficit(needed_wasser, provided_wasser, 'wasser')
    fill_resource_deficit(needed_schaummittel, provided_schaummittel, 'schaummittel')
    fill_resource_deficit(patient_bedarf, provided_patienten_kapazitaet, 'patienten_kapazitaet')
    
    betreuung_ratio = requirements.get('betreuung_ratio', 0)
    if betreuung_ratio > 0:
        total_personnel = sum(v['properties'].get('personal', 0) for v in vehicles_to_send)
        total_people = total_personnel + patient_bedarf
        units_needed = math.ceil(total_people / betreuung_ratio)
        units_provided = sum(1 for v in vehicles_to_send if "Betreuungsausstattung" in v['properties'].get('typ', []))
        
        deficit = units_needed - units_provided
        if deficit > 0:
            betreuungs_fahrzeuge = [v for v in pool if "Betreuungsausstattung" in v['properties'].get('typ', [])]
            betreuungs_personal_fahrzeuge = [v for v in pool if "Betreuungsausstattung_Personal" in v['properties'].get('typ', [])]
            for _ in range(deficit):
                if not betreuungs_fahrzeuge or not betreuungs_personal_fahrzeuge: break
                vehicle_to_add = betreuungs_fahrzeuge.pop(0)
                vehicle_to_add_2 = betreuungs_personal_fahrzeuge.pop(0)
                vehicles_to_send.append(vehicle_to_add)
                vehicles_to_send.append(vehicle_to_add_2)
                pool.remove(vehicle_to_add)
                pool.remove(vehicle_to_add_2)

    final_provided_fw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'FW')
    final_provided_thw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'THW')
    final_provided_rd = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'RD')
    final_provided_pol = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'POL')
    final_provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    final_provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    final_provided_patienten_kapazitaet = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)

    all_reqs_met = (
        not unfulfilled_slots and
        final_provided_fw >= needed_fw and
        final_provided_thw >= needed_thw and
        final_provided_rd >= needed_rd and
        final_provided_pol >= needed_pol and
        final_provided_wasser >= needed_wasser and
        final_provided_schaummittel >= needed_schaummittel and
        final_provided_patienten_kapazitaet >= patient_bedarf
    )

    if all_reqs_met:
        print(f"Erfolgreiche Zuteilung gefunden! Sende {len(vehicles_to_send)} Fahrzeuge.")
        return [v['checkbox'] for v in vehicles_to_send]
    else:
        print("Keine passende Fahrzeugkombination für die PFLICHT-Anforderungen gefunden.")
        return []

def get_on_scene_and_driving_vehicles(driver, wait, vehicle_id_map):
    fulfilled_roles = []
    if not vehicle_id_map: return []

    try:
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe.lightbox_iframe")))

        container_ids = ["mission_vehicle_driving", "mission_vehicle_at_mission"]
        short_wait = WebDriverWait(driver, 5)

        for container_id in container_ids:
            try:
                css_selector = f"table#{container_id} a[vehicle_type_id]"
                short_wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
                vehicle_links = driver.find_elements(By.CSS_SELECTOR, css_selector)
                
                for link in vehicle_links:
                    type_id = link.get_attribute('vehicle_type_id')
                    if type_id in vehicle_id_map:
                        vehicle_name = vehicle_id_map[type_id]
                        fulfilled_roles.append(vehicle_name)
                        if vehicle_name in VEHICLE_DATABASE:
                            generic_types = VEHICLE_DATABASE[vehicle_name].get("typ", [])
                            for t in generic_types:
                                if t != vehicle_name: fulfilled_roles.append(t)

            except TimeoutException: pass

    except TimeoutException:
        print("FEHLER: Konnte den Einsatz-iFrame nicht finden.")
    finally:
        driver.switch_to.default_content()

    print(f"Info: Alarmierte Fahrzeuge erfüllen folgende Rollen: {', '.join(sorted(list(set(fulfilled_roles))))}")
    return fulfilled_roles

def send_discord_notification(message, priority):
    highcommand_url = config.get("discord_highcommand_webhook_url", "")
    ROLE_ID_TO_PING = config.get("ROLE_ID_TO_PING", "")
    ping_text = f"<@&{ROLE_ID_TO_PING}> " if ROLE_ID_TO_PING else ""

    if "dev" in priority:
            data = {"content": f"{ping_text} | 🚨 **LSS Bot Alert - User: {LEITSTELLENSPIEL_USERNAME} | {BOT_VERSION} **\n>>> {message}", "allowed_mentions": {"parse": ["roles"]}}
            try: requests.post(highcommand_url, json=data)
            except requests.exceptions.RequestException: print("FEHLER: Discord-Benachrichtigung senden fehlgeschlagen.")

    if "discord_webhook_url" in config and config["discord_webhook_url"]:
        data = {"content": f"{ping_text} | ℹ️ **LSS Bot Message:**\n>>> {message}", "allowed_mentions": {"parse": ["roles"]}}
        try: requests.post(config["discord_webhook_url"], json=data)
        except requests.exceptions.RequestException: print("FEHLER: Discord-Benachrichtigung senden fehlgeschlagen.")

def check_and_claim_daily_bonus(driver, wait):
    try:
        bonus_icon = driver.find_element(By.XPATH, "//span[contains(@class, 'glyphicon-calendar') and contains(@class, 'bonus-active')]")
        bonus_icon.click(); time.sleep(2)
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
        claim_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.collect-possible-block button.collect-button")))
        claim_button.click(); time.sleep(3)
    except (NoSuchElementException, TimeoutException): pass
    finally:
        try: driver.switch_to.default_content()
        except: pass

def check_and_claim_tasks(driver, wait):
    """
    Navigiert direkt zur Aufgaben-URL, um UI-Probleme (wie Logout) zu vermeiden.
    """
    print("Info: Prüfe Aufgaben...")
    original_url = driver.current_url
    try:
        # Direktes Ansteuern der Aufgaben-Seite
        driver.get("https://www.leitstellenspiel.de/tasks/index")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Suche nach Buttons, die "Abholen" oder ähnlich heißen (CSS Klasse btn-success ist meist für fertige Aufgaben)
        # Suchen nach Buttons innerhalb der Aufgaben-Container
        claim_buttons = driver.find_elements(By.XPATH, "//a[contains(@class, 'btn-success') and contains(@href, '/tasks/collect/')]")
        
        if not claim_buttons:
             # Manchmal sind es Input-Buttons (Formulare)
            claim_buttons = driver.find_elements(By.XPATH, "//input[contains(@class, 'btn-success') and @value='Abholen']")

        clicked_count = 0
        for btn in claim_buttons:
            try:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    clicked_count += 1
                    time.sleep(1)
            except Exception: pass
        
        if clicked_count > 0:
            print(f"Info: {clicked_count} Aufgaben-Belohnungen eingesammelt.")
        
    except Exception as e:
        print(f"Warnung bei Aufgaben-Check: {e}")
    finally:
        # Immer sicherstellen, dass wir zur Hauptseite zurückkehren
        if driver.current_url != "https://www.leitstellenspiel.de/":
            driver.get("https://www.leitstellenspiel.de/")

def handle_sprechwunsche(driver, wait):
    navigated_away = False
    try:
        sprechwunsch_list = driver.find_element(By.ID, "radio_messages_important")
        messages = sprechwunsch_list.find_elements(By.XPATH, "./li")
        vehicle_urls_to_process = []
        for message in messages:
            if message.text.strip().endswith("Sprechwunsch"):
                try:
                    vehicle_link = message.find_element(By.XPATH, ".//a[contains(@href, '/vehicles/')]")
                    vehicle_urls_to_process.append({'url': vehicle_link.get_attribute('href'), 'name': vehicle_link.text.strip()})
                except NoSuchElementException: continue
        
        if not vehicle_urls_to_process: return

        navigated_away = True
        for vehicle_info in vehicle_urls_to_process:
            driver.get(vehicle_info['url'])
            try:
                transport_button_xpath = "//a[(contains(@href, '/patient/') or contains(@href, '/prisoner/') or contains(@href, '/gefangener/')) and contains(@class, 'btn-success')]"
                wait.until(EC.element_to_be_clickable((By.XPATH, transport_button_xpath))).click()
                time.sleep(2)
            except TimeoutException: pass

    except NoSuchElementException: pass
    except Exception as e: print(f"FEHLER bei der Sprechwunsch-Bearbeitung: {e}")
    finally:
        if navigated_away: driver.get("https://www.leitstellenspiel.de/")

def load_vehicle_id_map(file_path=resource_path("vehicle_id.json")):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError: return None
    except json.JSONDecodeError: return None

def save_vehicle_database(database, file_path=resource_path("fahrzeug_datenbank.json")):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=4, ensure_ascii=False)
        print("Info: Fahrzeug-Datenbank gespeichert.")
    except Exception as e: print(f"FEHLER: Datenbank speichern fehlgeschlagen: {e}")

def load_mission_cache(file_path=resource_path("mission_cache.json")):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_mission_cache(cache_data, file_path=resource_path("mission_cache.json")):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"FEHLER: Cache speichern fehlgeschlagen: {e}")

def get_player_vehicle_inventory(driver, wait):
    print("Info: Lese Fuhrpark ein...")
    vehicle_id_map = load_vehicle_id_map()
    if not vehicle_id_map: return set(), False

    inventory = set()
    database_updated = False
    try:
        driver.get("https://www.leitstellenspiel.de/vehicles")
        vehicle_rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tbody/tr")))

        for row in vehicle_rows:
            try:
                image_tag = row.find_element(By.XPATH, ".//img[@vehicle_type_id]")
                vehicle_id = image_tag.get_attribute('vehicle_type_id')
                
                if vehicle_id:
                    vehicle_name = vehicle_id_map.get(vehicle_id)
                    if vehicle_name:
                        inventory.add(vehicle_name)
                        if vehicle_name not in VEHICLE_DATABASE:
                            print(f"--> NEUES FAHRZEUG: '{vehicle_name}' wird hinzugefügt.")
                            VEHICLE_DATABASE[vehicle_name] = {
                                "fraktion": "",
                                "personal": 0,
                                "typ": [vehicle_name]
                            }
                            ADDED_TO_DATABASE.append(vehicle_name)
                            database_updated = True
            except NoSuchElementException: continue
        print(f"Info: Inventar mit {len(inventory)} Typen erstellt.")
    except Exception as e:
        print(f"FEHLER: Konnte den Fuhrpark nicht einlesen: {e}")
        traceback.print_exc()
            
    return inventory, database_updated

# -----------------------------------------------------------------------------------
# HAUPT-THREAD
# -----------------------------------------------------------------------------------

def main_bot_logic(gui_vars):
    driver = None
    last_check_date = None; bonus_checked_today = False
    try:
        mission_cache = load_mission_cache()
        gui_vars['gui_queue'].put(('status', "Initialisiere...")); driver = setup_driver(); wait = WebDriverWait(driver, 30)
        driver.set_page_load_timeout(45)

        vehicle_id_map = load_vehicle_id_map()

        gui_vars['gui_queue'].put(('status', "Logge ein...")); driver.get("https://www.leitstellenspiel.de/users/sign_in")
        wait.until(EC.visibility_of_element_located((By.ID, "user_email"))).send_keys(LEITSTELLENSPIEL_USERNAME)
        driver.find_element(By.ID, "user_password").send_keys(LEITSTELLENSPIEL_PASSWORD)
        time.sleep(1)
        try:
            login_button = wait.until(EC.element_to_be_clickable((By.NAME, "commit"))); login_button.click()
        except ElementClickInterceptedException:
            login_button = wait.until(EC.presence_of_element_located((By.NAME, "commit"))); driver.execute_script("arguments[0].click();", login_button)
        
        gui_vars['gui_queue'].put(('status', "Warte auf Hauptseite...")); wait.until(EC.presence_of_element_located((By.ID, "missions_outer"))); gui_vars['gui_queue'].put(('status', "Login erfolgreich!"))
        send_discord_notification(f"Bot gestartet: **{LEITSTELLENSPIEL_USERNAME}**", "user")
        
        player_inventory, gui_vars["db_updated_flag"] = get_player_vehicle_inventory(driver, wait)
        if gui_vars["db_updated_flag"]: save_vehicle_database(VEHICLE_DATABASE)
        
        while True:
            if gui_vars['stop_event'].is_set(): break
            if not gui_vars['pause_event'].is_set():
                gui_vars['gui_queue'].put(('status', "Bot pausiert...")); gui_vars['pause_event'].wait()

            gui_vars['gui_queue'].put(('status', "Prüfe Status...")); driver.get("https://www.leitstellenspiel.de/")
            wait.until(EC.presence_of_element_located((By.ID, "missions_outer")), 120)
            
            today = date.today()
            if last_check_date != today: bonus_checked_today = False; last_check_date = today
            if not bonus_checked_today:
                check_and_claim_daily_bonus(driver, wait)
                check_and_claim_tasks(driver, wait)
                bonus_checked_today = True

            try: 
                gui_vars['gui_queue'].put(('status', "Lade Einsatzliste..."))
                try:
                    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#missions_outer .missionSideBarEntry")))
                except TimeoutException:
                    gui_vars['gui_queue'].put(('status', f"Keine Einsätze. Warte {30}s...")); time.sleep(30); continue

                mission_list_container = wait.until(EC.presence_of_element_located((By.ID, "missions_outer")))
                mission_entries = mission_list_container.find_elements(By.XPATH, ".//div[contains(@class, 'missionSideBarEntry')]")

                mission_data = []
                for entry in mission_entries:
                    try:
                        mission_id = entry.get_attribute('mission_id') 
                        url_element = entry.find_element(By.XPATH, ".//a[contains(@id, 'mission_caption_')]")
                        full_name = url_element.text.strip()
                        name = full_name.split(',')[0].strip()

                        patient_count = 0; timeleft = 0
                        sort_data_str = entry.get_attribute('data-sortable-by')
                        if sort_data_str:
                            sort_data = json.loads(sort_data_str)
                            patient_count = sort_data.get('patients_count', [0, 0])[0]
                        try:
                            countdown_element = entry.find_element(By.XPATH, ".//div[contains(@id, 'mission_overview_countdown_')]")
                            timeleft_str = countdown_element.get_attribute('timeleft')
                            if timeleft_str and timeleft_str.isdigit(): timeleft = int(timeleft_str)
                        except NoSuchElementException: pass
                        
                        try:
                            panel_div = entry.find_element(By.XPATH, ".//div[contains(@id, 'mission_panel_')]")
                            panel_class = panel_div.get_attribute('class')
                            is_red = 'mission_panel_red' in panel_class
                        except NoSuchElementException: is_red = False

                        if name and mission_id and is_red:
                            mission_data.append({'id': mission_id, 'name': name, 'patienten': patient_count, 'timeleft': timeleft})
                    except (NoSuchElementException, json.JSONDecodeError): continue
                
                if not mission_data:
                    gui_vars['gui_queue'].put(('status', f"Keine Einsätze. Warte {30}s...")); time.sleep(30); continue
                
                gui_vars['gui_queue'].put(('status', f"{len(mission_data)} Einsätze gefunden."))

                for i, mission in enumerate(mission_data):
                    if gui_vars['stop_event'].is_set(): break
                    if not gui_vars['pause_event'].is_set(): gui_vars['gui_queue'].put(('status' ,"Bot pausiert...")); gui_vars['pause_event'].wait()

                    if "[Verband]" in mission['name'] or mission['name'].lower() == "krankentransport" or "intensivverlegung" in mission['name'].lower(): continue
                    if mission['timeleft'] > MAX_START_DELAY_SECONDS: continue
                    
                    print(f"-----------------{mission['name']}-----------------")
                    gui_vars['gui_queue'].put(('mission_name', f"({i+1}/{len(mission_data)}) {mission['name']}"))

                    try:
                        sidebar_button_xpath = f"//div[@mission_id='{mission['id']}']//a[contains(@class, 'mission-alarm-button')]"
                        element_to_click = wait.until(EC.element_to_be_clickable((By.XPATH, sidebar_button_xpath)))
                        driver.execute_script("arguments[0].click();", element_to_click)
                        
                        main_alarm_button_id = f"alarm_button_{mission['id']}"
                        wait.until(EC.presence_of_element_located((By.ID, main_alarm_button_id)))

                        vehicles_on_scene = []
                        is_incomplete = False
                        try:
                            missing_alert_xpath = "//div[contains(@class, 'alert-danger') and .//div[@data-requirement-type]]"
                            driver.find_element(By.XPATH, missing_alert_xpath)
                            vehicles_on_scene = get_on_scene_and_driving_vehicles(driver, wait, vehicle_id_map)
                            is_incomplete = True
                        except NoSuchElementException: pass
                        
                        raw_requirements = get_mission_requirements(driver, wait, player_inventory, mission['patienten'], mission['name'], mission_cache)
                        if not raw_requirements: continue

                        try:
                            patient_alert_xpath = "//div[starts-with(@id, 'patients_missing_')]"
                            patient_alert = driver.find_element(By.XPATH, patient_alert_xpath)
                            alert_text = patient_alert.text
                            if "NEF" in alert_text: raw_requirements['fahrzeuge'].append(["NEF"])
                            if "RTW" in alert_text: raw_requirements['fahrzeuge'].append(["RTW"])
                        except NoSuchElementException: pass
                    except NoSuchElementException: pass

                    if mission['timeleft'] > 0 and raw_requirements.get('credits', 0) < MINIMUM_CREDITS: continue
                    
                    if is_incomplete and vehicles_on_scene:
                        provided_by_on_scene = {'personal_fw': 0, 'personal_thw': 0, 'personal_rd': 0, 'personal_pol': 0, 'wasser': 0, 'schaummittel': 0, 'patienten_kapazitaet': 0}
                        for vehicle_type in vehicles_on_scene:
                            if vehicle_type in VEHICLE_DATABASE:
                                props = VEHICLE_DATABASE[vehicle_type]
                                fraktion = props.get('fraktion')
                                if fraktion == 'FW': provided_by_on_scene['personal_fw'] += props.get('personal', 0)
                                elif fraktion == 'THW': provided_by_on_scene['personal_thw'] += props.get('personal', 0)
                                elif fraktion == 'RD': provided_by_on_scene['personal_rd'] += props.get('personal', 0)
                                elif fraktion == 'POL': provided_by_on_scene['personal_pol'] += props.get('personal', 0)
                                provided_by_on_scene['wasser'] += props.get('wasser', 0)
                                provided_by_on_scene['schaummittel'] += props.get('schaummittel', 0)
                                provided_by_on_scene['patienten_kapazitaet'] += props.get('patienten_kapazitaet', 0)                        

                        on_scene_counts = Counter(vehicles_on_scene)
                        still_needed_requirements = []
                        for required_options in raw_requirements['fahrzeuge']:
                            found_match_on_scene = False
                            for option in required_options:
                                if on_scene_counts[option] > 0:
                                    on_scene_counts[option] -= 1
                                    found_match_on_scene = True
                                    break
                            if not found_match_on_scene: still_needed_requirements.append(required_options)

                        raw_requirements['fahrzeuge'] = still_needed_requirements
                        raw_requirements['personal_fw'] = max(0, raw_requirements.get('personal_fw', 0) - provided_by_on_scene['personal_fw'])
                        raw_requirements['personal_thw'] = max(0, raw_requirements.get('personal_thw', 0) - provided_by_on_scene['personal_thw'])
                        raw_requirements['personal_rd'] = max(0, raw_requirements.get('personal_rd', 0) - provided_by_on_scene['personal_rd'])
                        raw_requirements['personal_pol'] = max(0, raw_requirements.get('personal_pol', 0) - provided_by_on_scene['personal_pol'])
                        raw_requirements['wasser'] = max(0, raw_requirements.get('wasser', 0) - provided_by_on_scene['wasser'])
                        raw_requirements['schaummittel'] = max(0, raw_requirements.get('schaummittel', 0) - provided_by_on_scene['schaummittel'])
                        raw_requirements['patienten'] = max(0, raw_requirements.get('patienten', 0) - provided_by_on_scene['patienten_kapazitaet'])
                    
                    final_requirements = raw_requirements
                    req_parts = []; readable_requirements = [" oder ".join(options) for options in final_requirements['fahrzeuge']]
                    vehicle_counts = Counter(readable_requirements)
                    for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")
                    if final_requirements.get('personal_fw', 0) > 0: req_parts.append(f"{final_requirements['personal_fw']} FW")
                    
                    req_string = ", ".join(req_parts) if req_parts else "Nichts mehr benötigt."
                    gui_vars['gui_queue'].put(('requirements', req_string))

                    available_vehicles = get_available_vehicles(driver, wait)
                    if not available_vehicles:
                        gui_vars['gui_queue'].put(('availability_text', "Keine Fahrzeuge frei."))
                        gui_vars['gui_queue'].put(('status', f"Keine Fahrzeuge. Pausiere {PAUSE_IF_NO_VEHICLES_SECONDS}s..."))
                        time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS); break
                    
                    # --- GRAFIK DATEN SENDEN ---
                    specific_types = [v['vehicle_type'] for v in available_vehicles]
                    available_counts = Counter(specific_types)
                    
                    # Neue Daten für die Liste senden
                    gui_vars['gui_queue'].put(('vehicle_list_data', available_counts))

                    vehicle_parts = [f"{count}x {v_type}" for v_type, count in available_counts.items()]
                    vehicle_str = "Fahrzeuge: " + (", ".join(vehicle_parts) if vehicle_parts else "Keine")
                    
                    personnel_counts = {'FW': 0, 'THW': 0, 'RD': 0, 'POL': 0}
                    total_water = 0; total_foam = 0
                    for v in available_vehicles:
                        props = v.get('properties', {}); total_water += props.get('wasser', 0); total_foam += props.get('schaummittel', 0)
                        fraktion = props.get('fraktion')
                        if fraktion in personnel_counts: personnel_counts[fraktion] += props.get('personal', 0)
                    
                    # Sende Daten für Tortendiagramm
                    gui_vars['gui_queue'].put(('stats_data', personnel_counts))
                    
                    personnel_str = (f"Personal: {personnel_counts['FW']} FW, {personnel_counts['THW']} THW, {personnel_counts['RD']} RD, {personnel_counts['POL']} POL")
                    resources_str = f"Ressourcen: {total_water}L Wasser, {total_foam}L Schaum"
                    gui_vars['gui_queue'].put(('availability_text', f"{vehicle_str}\n\n{personnel_str}\n{resources_str}"))

                    checkboxes_to_click = find_best_vehicle_combination(final_requirements, available_vehicles, VEHICLE_DATABASE)
                    if checkboxes_to_click:
                        gui_vars['gui_queue'].put(('status', "✓ Alarmiere...")); gui_vars['gui_queue'].put(('alarm_status', f"OK: {len(checkboxes_to_click)} Fahrzeuge"))
                        for checkbox in checkboxes_to_click: driver.execute_script("arguments[0].click();", checkbox)
                        try:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren und zum nächsten Einsatz']"); driver.execute_script("arguments[0].click();", alarm_button)
                        except NoSuchElementException:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren']"); driver.execute_script("arguments[0].click();", alarm_button)
                    else:
                        gui_vars['gui_queue'].put(('status', "❌ Nicht genug Einheiten.")); gui_vars['gui_queue'].put(('alarm_status', "FEHLT: Einheiten"))

                    short_wait = WebDriverWait(driver, 3) 
                    try:
                        short_wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
                        close_button_xpath = "//*[@id='lightbox_close_inside']"
                        short_wait.until(EC.element_to_be_clickable((By.XPATH, close_button_xpath))).click()
                    except TimeoutException: pass
                    finally: driver.switch_to.default_content()

                    wait.until(EC.visibility_of_element_located((By.ID, "missions_outer")))

                    update_data = {'status': "Lade nächsten Einsatz...", 'alarm_status': "-", 'requirements': "-", 'mission_name': "..."}
                    gui_vars['gui_queue'].put(('batch_update', update_data))

                    handle_sprechwunsche(driver, wait)

            except Exception as e:
                print(f"Fehler im Zyklus: {e}"); traceback.print_exc(); time.sleep(10)
    except Exception as e:
        print("FATALER FEHLER!")
        if driver: driver.save_screenshot('fehler.png')
        error_details = traceback.format_exc(); send_discord_notification(f"FATAL ERROR\n```\n{error_details}\n```", "dev")
        gui_vars['gui_queue'].put(('status', "ABSTURZ! Siehe Log."))
        
        with open(resource_path('error_log.txt'), 'a', encoding='utf-8') as f:
            f.write(f"\n--- FEHLER am {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"); f.write(error_details); f.write("-" * 50 + "\n")
    finally:
        if mission_cache: save_mission_cache(mission_cache)
        if driver: driver.quit()
        gui_vars['gui_queue'].put(('status', "Bot beendet."))

# -----------------------------------------------------------------------------------
# HAUPTPROGRAMM START
# -----------------------------------------------------------------------------------
if __name__ == "__main__":
    gui_queue = queue.Queue()

    pause_event = threading.Event()
    pause_event.set() 
    stop_event = threading.Event()

    gui_variables = { 
        "pause_event": pause_event,
        "stop_event": stop_event,
        "db_updated_flag": False,
        "gui_queue": gui_queue
    }

    bot_thread = threading.Thread(target=main_bot_logic, args=(gui_variables,))
    bot_thread.start()

    if USE_TERMINAL:
        terminal = TerminalHandler(pause_event, stop_event, gui_queue)
        terminal.wait_for_exit()
        bot_thread.join()
        print("Bot Prozess beendet.")
    else:
        app = ModernApp(pause_event, stop_event, gui_queue)
        app.mainloop()

        print("Fenster geschlossen. Warte auf Thread...")
        bot_thread.join()

        if gui_variables.get("db_updated_flag", False):
            root = tk.Tk(); root.withdraw()
            messagebox.showinfo("Update", "Fahrzeug-Datenbank wurde aktualisiert! Bitte JSON prüfen.")
            root.destroy()
        
    print("Programm beendet.")