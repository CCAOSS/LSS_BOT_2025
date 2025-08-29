import time
import json
import os
import re
import sys
import threading
import tempfile
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from collections import Counter
import traceback
from datetime import date
import requests
import math

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# -----------------------------------------------------------------------------------
# HELPER-FUNKTIONEN UND KONFIGURATION
# -----------------------------------------------------------------------------------

def resource_path(relative_path):
    """ Ermittelt den korrekten Pfad zu einer Ressource, egal ob als Skript (.py) oder als EXE-Datei ausgeführt. """
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
except FileNotFoundError:
    print("FEHLER: Die Datei 'config.json' wurde nicht gefunden."); time.sleep(10); sys.exit()
except KeyError:
    print("FEHLER: In der 'config.json' fehlen 'username' oder 'password'."); time.sleep(10); sys.exit()

# --- Fahrzeug-Datenbank laden (Einzige Quelle der Wahrheit) ---
def load_vehicle_database(file_path=resource_path("fahrzeug_datenbank.json")):
    """Lädt die zentrale Fahrzeug-Datenbank aus einer JSON-Datei."""
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

# --- Bot-Konfiguration ---
BOT_VERSION = "V1.0.5 - Release Build"
PAUSE_IF_NO_VEHICLES_SECONDS = 300
MAX_START_DELAY_SECONDS = 3600
MINIMUM_CREDITS = 10000

ADDED_TO_DATABASE = []

# -----------------------------------------------------------------------------------
# DIE KLASSE FÜR DAS STATUS-FENSTER (Version mit Pause/Stop-Logik)
# -----------------------------------------------------------------------------------

class StatusWindow(tk.Tk):
    def __init__(self, pause_event, stop_event, gui_queue):
        super().__init__()
        self.gui_queue = gui_queue 

        # Übernehme die Signale von außen
        self.pause_event = pause_event
        self.stop_event = stop_event
        
        self.title(f"LSS Bot {BOT_VERSION} | User: {LEITSTELLENSPIEL_USERNAME}")
        self.geometry("450x350"); self.minsize(450, 350) # Höhe etwas angepasst für mehr Platz
        self.configure(bg="#2E2E2E")
        style = ttk.Style(self); style.theme_use('clam')
        style.configure("TLabel", background="#2E2E2E", foreground="#FFFFFF", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TFrame", background="#2E2E2E") # Style für den Button-Frame
        
        self.status_var = tk.StringVar(value="Bot startet...")
        self.mission_name_var = tk.StringVar(value="Warte auf ersten Einsatz...")
        self.requirements_var = tk.StringVar(value="-")
        self.availability_var = tk.StringVar(value="-")
        self.alarm_status_var = tk.StringVar(value="-")
        
        # GUI-Elemente (Labels)
        ttk.Label(self, text="Bot Status:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=20)
        ttk.Label(self, text="Aktueller Einsatz:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.mission_name_var, wraplength=430).pack(anchor="w", padx=20)
        ttk.Label(self, text="Bedarf:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.requirements_var).pack(anchor="w", padx=20)
        ttk.Label(self, text="Verfügbarkeit:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        
        # NEU: justify=tk.LEFT für saubere, mehrzeilige Darstellung
        ttk.Label(self, textvariable=self.availability_var, justify=tk.LEFT).pack(anchor="w", padx=20)
        
        ttk.Label(self, text="Alarmierungsstatus:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.alarm_status_var).pack(anchor="w", padx=20)

        # Frame für die Buttons am unteren Rand
        button_frame = ttk.Frame(self, style="TFrame")
        button_frame.pack(side="bottom", pady=10, fill="x", padx=10)

        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause)
        self.pause_button.pack(side="left", expand=True, padx=5)
        
        stop_button = ttk.Button(button_frame, text="Bot Stoppen & Schließen", command=self.stop_bot)
        stop_button.pack(side="right", expand=True, padx=5)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.process_queue()

    def process_queue(self):
        """
        Prüft die Queue auf neue Nachrichten vom Bot-Thread und aktualisiert die GUI.
        """
        try:
            # Hole eine Nachricht, ohne zu blockieren
            message = self.gui_queue.get_nowait()
            
            # Nachricht auspacken (z.B. ('status', 'Neuer Text'))
            key, value = message

            # Je nach Schlüssel die richtige Variable aktualisieren
            if key == 'batch_update':
                for update_key, update_value in value.items():
                    # Hier die Logik von oben, um die richtige Variable zu setzen
                    if update_key == 'status': self.status_var.set(update_value)
                    elif update_key == 'mission_name': self.mission_name_var.set(update_value)
                    elif update_key == 'alarm_status': self.alarm_status_var.set(update_value)
                    elif update_key == 'requirements': self.requirements_var.set(update_value)
                    elif update_key == 'availability': self.availability_var.set(update_value)
            else:
                if key == 'status':
                    self.status_var.set(value)
                elif key == 'mission_name':
                    self.mission_name_var.set(value)
                elif key == 'requirements':
                    self.requirements_var.set(value)
                elif key == 'availability':
                    self.availability_var.set(value)
                elif key == 'alarm_status':
                    self.alarm_status_var.set(value)

        except queue.Empty:
            # Wenn die Queue leer ist, passiert nichts.
            pass
        finally:
            # Plane, diese Funktion in 100 Millisekunden erneut auszuführen.
            self.after(100, self.process_queue)

    # Der Rest der Klasse (toggle_pause, stop_bot, on_closing) bleibt unverändert
    def toggle_pause(self):
        """Pausiert oder setzt den Bot-Thread fort."""
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.config(text="Continue")
            self.status_var.set("Bot pausiert.")
        else:
            self.pause_event.set()
            self.pause_button.config(text="Pause")
            self.status_var.set("Bot wird fortgesetzt...")
            
    def stop_bot(self):
        """Setzt das Stop-Signal und schließt das Fenster."""
        print("Info: Stop-Signal gesetzt. Beende den Bot-Thread...")
        self.status_var.set("Beende Bot...")
        self.stop_event.set()
        self.after(500, self.destroy)

    def on_closing(self):
        """Wird ausgeführt, wenn das Fenster-X geklickt wird."""
        self.stop_bot()

# -----------------------------------------------------------------------------------
# BOT-HILFSFUNKTIONEN
# -----------------------------------------------------------------------------------

def setup_driver():
    """
    Konfiguriert den WebDriver und weist ihm bei jedem Start ein einzigartiges,
    temporäres Nutzerverzeichnis zu, um Konflikte zu vermeiden.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    # ================================================================= #
    # NEUE, STABILISIERENDE FLAGS                                       #
    # ================================================================= #
    chrome_options.add_argument("--disable-dev-shm-usage") # Verhindert Abstürze bei wenig Arbeitsspeicher
    chrome_options.add_argument("--disable-extensions") # Deaktiviert Erweiterungen, die stören könnten
    # ================================================================= #

    user_data_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    
    if sys.platform.startswith('linux'):
        print("Info: Linux-Betriebssystem (Raspberry Pi) erkannt.")
        user_agent = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
        service = ChromeService(executable_path="/usr/bin/chromedriver")
    else: # win32
        print("Info: Windows-Betriebssystem erkannt.")
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        service = ChromeService(executable_path=resource_path("chromedriver.exe"))
    
    chrome_options.add_argument(f'user-agent={user_agent}')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver
    
def get_mission_requirements(driver, wait, player_inventory, given_patients, mission_name, mission_cache):
    """
    Ermittelt die Einsatzanforderungen und nutzt einen Cache, um bereits bekannte
    Einsätze sofort zu laden und die Analyse zu beschleunigen.
    """
    
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
    # --- ENDE ANPASSBARE ÜBERSETZUNGS-LISTE ---

    iframe_locator = (By.TAG_NAME, "iframe")
    raw_requirements = {
        'fahrzeuge': [], 'fahrzeuge_optional': [], 'patienten': 0, 'credits': 0,
        'wasser': 0, 'schaummittel': 0,
        'personal_fw': 0, 'personal_thw': 0, 'personal_rd': 0, 'personal_pol': 0, 'betreuung_ratio': 0
    }
    try:
        # Im iFrame arbeiten
        wait.until(EC.frame_to_be_available_and_switch_to_it(iframe_locator))
        
        hilfe_button_xpath = "//*[@id='mission_help']" 
        hilfe_button = wait.until(EC.element_to_be_clickable((By.XPATH, hilfe_button_xpath)))
        driver.execute_script("arguments[0].click();", hilfe_button)

        # --- CACHING-LOGIK ---
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

        # 2. Cache-Schlüssel erstellen
        cache_key = f"{mission_name}_{credits}_{min_patients}_{max_patients}"

        # 3. Cache prüfen
        if cache_key in mission_cache:
            print(f"Info: Anforderungen für '{cache_key}' aus dem Cache geladen.")
            cached_reqs = mission_cache[cache_key].copy()
            # Die aktuelle Patientenzahl des Einsatzes wird übernommen
            cached_reqs['patienten'] = given_patients if given_patients > 0 else min_patients
            return cached_reqs # Funktion wird hier beendet, Rest übersprungen
        
        print(f"Info: Einsatz '{cache_key}' nicht im Cache. Lese Anforderungen neu ein.")
        # NEU: Ende der Caching-Logik

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

                # --- START DER NEUEN PERSONAL-LOGIK ---
                req_lower = requirement_text.lower()
                # Extrahiert die erste Zahl, auch aus "Zwischen X und Y"
                numbers = re.findall(r'\d+', count_text)
                # Nimm die LETZTE gefundene Zahl (den Maximalwert)
                count = int(numbers[-1]) if numbers else 0

                if 'wasserwerfer' in clean_name.lower():
                    if count_text.isdigit():
                        for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Wasserwerfer"])
                    continue

                if 'polizisten' in req_lower:
                    raw_requirements['personal_pol'] += count; continue
                elif 'personalanzahl (thw)' in req_lower:
                    raw_requirements['personal_thw'] += count; continue
                elif 'rettungsdienst' in req_lower: # Annahme für RD-Personal
                    raw_requirements['personal_rd'] += count; continue
                elif 'feuerwehrleute' in req_lower:
                    raw_requirements['personal_fw'] += count; continue
                
                if 'betreuungs- und verpflegungsausstattung' in req_lower:
                    # Extrahiere die Zahl aus "1 pro 250..."
                    ratio_match = re.search(r'pro (\d+)', count_text)
                    if ratio_match:
                        ratio = int(ratio_match.group(1))
                        raw_requirements['betreuung_ratio'] = ratio
                        print(f"      -> Info: Betreuung benötigt (1 pro {ratio} Personen).")
                    continue # Wichtig: Zur nächsten Zeile springen

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
        
        # NEU: Speichere die neu ermittelten Anforderungen im Cache, bevor die Funktion sie zurückgibt
        final_reqs_for_cache = raw_requirements.copy()
        final_reqs_for_cache['patienten'] = min_patients # Speichere die Mindestanzahl als Basis
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
        # NEU: Sicherstellen, dass der Kontext immer zum Hauptdokument zurückkehrt.
        #driver.switch_to.default_content()
    return raw_requirements

def get_available_vehicles(driver, wait):
    """
    **ANGEPASST:** Findet verfügbare Fahrzeuge und speichert jetzt auch den
    spezifischen 'vehicle_type' für eine saubere GUI-Anzeige.
    """
    available_vehicles = []
    vehicle_table_selector = "#vehicle_show_table_all"
    
    try:
        try:
            load_more_button_selector = "//a[contains(@class, 'missing_vehicles_load')]"
            load_more_button = driver.find_element(By.XPATH, load_more_button_selector)
            print("Info: 'Fehlende Fahrzeuge laden'-Button gefunden. Klicke ihn...")

            vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
            initial_rows = len(vehicle_table.find_elements(By.XPATH, ".//tbody/tr"))

            driver.execute_script("arguments[0].click();", load_more_button)

            wait.until(lambda d: len(d.find_element(By.CSS_SELECTOR, vehicle_table_selector).find_elements(By.XPATH, ".//tbody/tr")) > initial_rows)
            print("Info: Zusätzliche Fahrzeuge wurden geladen.")
        except NoSuchElementException:
            print("Info: Alle Fahrzeuge werden bereits angezeigt.")

        vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
        vehicle_rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
        
        for row in vehicle_rows:
            try:
                checkbox = row.find_element(By.CSS_SELECTOR, "input.vehicle_checkbox")
                vehicle_type = row.get_attribute('vehicle_type')
                
                if vehicle_type and vehicle_type in VEHICLE_DATABASE:
                    full_vehicle_name = row.get_attribute('vehicle_caption') or "Unbekannter Name"
                    vehicle_properties = VEHICLE_DATABASE[vehicle_type]
                    # NEU: Der 'vehicle_type' wird hier explizit mitgespeichert.
                    available_vehicles.append({
                        'properties': vehicle_properties, 
                        'checkbox': checkbox, 
                        'name': full_vehicle_name,
                        'vehicle_type': vehicle_type  # Diese Zeile ist neu
                    })
            except NoSuchElementException:
                continue
    except TimeoutException:
        print(f"FEHLER: Die Fahrzeug-Tabelle konnte nicht gefunden werden.")
    
    #print(f"DEBUG: Verfügbare Fahrzeug-Typen laut get_available_vehicles: {[v['vehicle_type'] for v in available_vehicles]}")
    return available_vehicles

# ANPASSUNG: `find_best_vehicle_combination` behandelt nun optionale Fahrzeuge
# ZURÜCKGESETZTE UND VEREINFACHTE VERSION
def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
    """
    Findet eine passende Fahrzeugkombination mit einer einfachen und direkten Logik,
    die auf kompliziertes Scoring verzichtet und zum ursprünglichen Kern zurückkehrt.
    """
    # 1. Anforderungen vorbereiten
    needed_vehicle_options_list = requirements.get('fahrzeuge', []).copy()
    optional_vehicle_options_list = requirements.get('fahrzeuge_optional', []).copy()
    needed_wasser = requirements.get('wasser', 0)
    needed_schaummittel = requirements.get('schaummittel', 0)
    patient_bedarf = requirements.get('patienten', 0)

    needed_fw = requirements.get('personal_fw', 0)
    needed_thw = requirements.get('personal_thw', 0)
    needed_rd = requirements.get('personal_rd', 0)
    needed_pol = requirements.get('personal_pol', 0)

    # MANV-Logik
    KTW_B_allowed = patient_bedarf > 5
    if patient_bedarf >= 5:
        needed_vehicle_options_list.extend([["KdoW-LNA"], ["GW-San"], ["ELW 1 (SEG)"]])
    if patient_bedarf >= 10:
        needed_vehicle_options_list.append(["KdoW-OrgL"])

    # RTW-Bedarf
    explicit_rtw_count = sum(1 for options in needed_vehicle_options_list if "RTW" in options)
    needed_vehicle_options_list = [options for options in needed_vehicle_options_list if "RTW" not in options]
    rtws_to_add = min(patient_bedarf, 15)
    final_rtw_bedarf = max(explicit_rtw_count, rtws_to_add)
    for _ in range(final_rtw_bedarf):
        needed_vehicle_options_list.append(["RTW", "KTW Typ B"] if KTW_B_allowed else ["RTW"])

    # 2. Fahrzeugauswahl
    vehicles_to_send = []
    pool = list(available_vehicles)
    unfulfilled_slots = list(needed_vehicle_options_list)

    # PFLICHTFAHRZEUGE ZUWEISEN (EINFACHE LOGIK)
    for slot in list(unfulfilled_slots):  # Iteriere über eine Kopie
        for vehicle in list(pool):
            vehicle_roles = set(vehicle['properties'].get('typ', []))
            # Wenn das Fahrzeug eine der benötigten Rollen im Slot hat
            if not vehicle_roles.isdisjoint(slot):
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                unfulfilled_slots.remove(slot)
                break  # Nimm das erste passende Fahrzeug und gehe zum nächsten Slot

    # OPTIONALE FAHRZEUGE ZUWEISEN
    for optional_slot in list(optional_vehicle_options_list):
        for vehicle in list(pool):
            vehicle_roles = set(vehicle['properties'].get('typ', []))
            if not vehicle_roles.isdisjoint(optional_slot):
                vehicles_to_send.append(vehicle)
                pool.remove(vehicle)
                # Hier wird der optionale Slot nicht aus einer Liste entfernt, da er keine Pflicht ist
                break

 # 3. Ressourcen-Defizite auffüllen
    # NEU: Zuerst Personal pro Fraktion ermitteln
    provided_fw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'FW')
    provided_thw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'THW')
    provided_rd = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'RD')
    provided_pol = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'POL')

    # NEU: Funktion zum Auffüllen von Personal-Defiziten pro Fraktion
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

    # Wasser, Schaummittel und Patienten (leicht angepasst)
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
    
     # --- START DER NEUEN LOGIK ---
    # 3.5 Dynamische Anforderungen (Betreuung) berechnen und hinzufügen
    betreuung_ratio = requirements.get('betreuung_ratio', 0)
    if betreuung_ratio > 0:
        # Berechne die finale Personalstärke aller bereits ausgewählten Fahrzeuge
        total_personnel = sum(v['properties'].get('personal', 0) for v in vehicles_to_send)
        total_people = total_personnel + patient_bedarf
        
        # Berechne die benötigte Anzahl an Betreuungseinheiten (immer aufrunden)
        units_needed = math.ceil(total_people / betreuung_ratio)
        
        # Prüfe, wie viele Einheiten bereits (zufällig) dabei sind
        units_provided = sum(1 for v in vehicles_to_send if "Betreuungsausstattung" in v['properties'].get('typ', []))
        
        deficit = units_needed - units_provided
        if deficit > 0:
            print(f"Info: Dynamischer Bedarf von {deficit}x Betreuungsausstattung berechnet.")
            # Finde verfügbare Betreuungsfahrzeuge und füge sie hinzu
            betreuungs_fahrzeuge = [v for v in pool if "Betreuungsausstattung" in v['properties'].get('typ', [])]
            betreuungs_personal_fahrzeuge = [v for v in pool if "Betreuungsausstattung_Personal" in v['properties'].get('typ', [])]
            for _ in range(deficit):
                if not betreuungs_fahrzeuge:
                    print("Warnung: Nicht genügend Betreuungsfahrzeuge verfügbar.")
                    break
                if not betreuungs_personal_fahrzeuge:
                    print("Warnung: Nicht genügend Betreuungsfahrzeuge verfügbar.")
                    break
                vehicle_to_add = betreuungs_fahrzeuge.pop(0)
                vehicle_to_add_2 = betreuungs_personal_fahrzeuge.pop(0)
                vehicles_to_send.append(vehicle_to_add)
                vehicles_to_send.append(vehicle_to_add_2)
                pool.remove(vehicle_to_add)
                pool.remove(vehicle_to_add_2)
    # --- ENDE DER NEUEN LOGIK ---


    # 4. Finale Prüfung (angepasst)
    # Berechne die finalen Werte nach dem Auffüllen neu
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
        if unfulfilled_slots:
            print("-> Es fehlen benötigte Fahrzeugtypen:")
            for slot_tuple, count in Counter(tuple(sorted(slot)) for slot in unfulfilled_slots).items():
                print(f"     - {count}x {' oder '.join(slot_tuple)}")
        if final_provided_fw < needed_fw: print(f"-> Es fehlen {needed_fw - final_provided_fw} Personal (FW).")
        if final_provided_thw < needed_thw: print(f"-> Es fehlen {needed_thw - final_provided_thw} Personal (THW).")
        if final_provided_rd < needed_rd: print(f"-> Es fehlen {needed_rd - final_provided_rd} Personal (RD).")
        if final_provided_pol < needed_pol: print(f"-> Es fehlen {needed_pol - final_provided_pol} Personal (POL).")
        if final_provided_wasser < needed_wasser: print(f"-> Es fehlen {needed_wasser - final_provided_wasser} L Wasser.")
        if final_provided_schaummittel < needed_schaummittel: print(f"-> Es fehlen {needed_schaummittel - final_provided_schaummittel} L Schaummittel.")
        if final_provided_patienten_kapazitaet < patient_bedarf: print(f"-> Es fehlen {patient_bedarf - final_provided_patienten_kapazitaet} Patienten-Transportplätze.")
        return []
        
# NEU: Hilfsfunktion zum Auslesen bereits alarmierter Fahrzeuge
# KORREKTE UND PERFORMANTE VERSION
# KORRIGIERTE UND FINALE VERSION
def get_on_scene_and_driving_vehicles(driver, wait, vehicle_id_map):
    """
    Liest Fahrzeuge aus und gibt eine Liste ALLER erfüllten Rollen/Typen zurück.
    Beispiel: Ein "LF 20" vor Ort fügt "LF 20" und "Löschfahrzeug" zur Liste hinzu.
    """
    fulfilled_roles = [] # Die Liste enthält jetzt alle erfüllten Typen
    if not vehicle_id_map:
        print("WARNUNG: vehicle_id_map nicht geladen.")
        return []

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
                        
                        # --- HIER IST DIE ENTSCHEIDENDE ÄNDERUNG ---
                        # 1. Füge immer den Eigennamen des Fahrzeugs hinzu.
                        fulfilled_roles.append(vehicle_name)
                        
                        # 2. Schlage die generischen Typen in der Datenbank nach und füge sie ebenfalls hinzu.
                        if vehicle_name in VEHICLE_DATABASE:
                            generic_types = VEHICLE_DATABASE[vehicle_name].get("typ", [])
                            for t in generic_types:
                                if t != vehicle_name: # Vermeide Duplikate
                                    fulfilled_roles.append(t)
                        # --- ENDE DER ÄNDERUNG ---

            except TimeoutException:
                pass

    except TimeoutException:
        print("FEHLER: Konnte den Einsatz-iFrame nicht finden.")
    finally:
        driver.switch_to.default_content()

    print(f"Info: Alarmierte Fahrzeuge erfüllen folgende Rollen: {', '.join(sorted(list(set(fulfilled_roles))))}")
    return fulfilled_roles

def send_discord_notification(message, priority):

    highcommand_url = "https://discord.com/api/webhooks/1408578295779557427/vFXyXnLzdzWRqyhT2Zs7hNK5i457yUaKAeG0ehAUcJU922ApUvAMfXcC3yaFlALkPsNz"
    ROLE_ID_TO_PING = config["ROLE_ID_TO_PING"]
    ping_text = f"<@&{ROLE_ID_TO_PING}> " if ROLE_ID_TO_PING else ""

    #bot crashed? Send error log to dev discord
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
    Prüft auf erledigte Aufgaben und verwendet einen robusten JavaScript-Klick,
    um Interaktions-Fehler zu vermeiden.
    """
    print("Info: Prüfe auf erledigte Aufgaben...")
    try:
        profile_dropdown = wait.until(EC.element_to_be_clickable((By.ID, "menu_profile")))
        profile_dropdown.click()
        
        short_wait = WebDriverWait(driver, 3)
        task_counter_selector = "//span[@id='completed_tasks_counter' and not(contains(@class, 'hidden'))]"
        short_wait.until(EC.visibility_of_element_located((By.XPATH, task_counter_selector)))
        
        print("Info: Erledigte Aufgabe(n) gefunden! Öffne Aufgaben-Seite...")
        tasks_link = driver.find_element(By.XPATH, "//div[contains(@class, 'tasks_and_events_navbar')]")
        tasks_link.click()

        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
        print("Info: Erfolgreich in den Aufgaben-iFrame gewechselt.")

        claim_buttons_selector = "//input[@value='Abholen' and contains(@class, 'btn')]"
        all_claim_buttons = wait.until(EC.presence_of_all_elements_located((By.XPATH, claim_buttons_selector)))
        
        clicked_count = 0
        print(f"Info: {len(all_claim_buttons)} potenzielle Belohnungs-Buttons gefunden. Prüfe, welche aktiv sind...")
        
        for button in all_claim_buttons:
            try:
                if button.is_enabled():
                    print("    -> Aktiver Button gefunden. Klicke 'Abholen' per JavaScript...")
                    
                    # --- HIER IST DIE KORREKTUR ---
                    # Ersetze den normalen Klick durch den JavaScript-Klick
                    driver.execute_script("arguments[0].click();", button)
                    
                    clicked_count += 1
                    print("    -> Belohnung erfolgreich abgeholt.")
                    time.sleep(1.5)
                else:
                    print("    -> Inaktiver Button gefunden. Wird ignoriert.")
            except Exception as e_click:
                print(f"Warnung: Konnte einen Button nicht klicken: {e_click}")
        
        if clicked_count > 0:
            print(f"Info: {clicked_count} Belohnung(en) insgesamt abgeholt.")
        else:
            print("Info: Keine aktiven Belohnungen zum Abholen gefunden.")
        
        time.sleep(2)
        
    except TimeoutException:
        print("Info: Keine neuen, erledigten Aufgaben.")
        try:
            driver.find_element(By.TAG_NAME, 'body').click()
            time.sleep(1)
        except: pass
            
    except Exception as e:
        print(f"FEHLER beim Prüfen der Aufgaben: {e}")

    finally:
        try:
            driver.switch_to.default_content()
        except:
            pass

def handle_sprechwunsche(driver, wait):
    """Sucht nach Sprechwünschen, bearbeitet sie und kehrt danach zur Hauptseite zurück."""
    navigated_away = False
    try:
        print("Info: Prüfe auf Sprechwünsche...")
        sprechwunsch_list = driver.find_element(By.ID, "radio_messages_important")
        messages = sprechwunsch_list.find_elements(By.XPATH, "./li")
        vehicle_urls_to_process = []
        for message in messages:
            if message.text.strip().endswith("Sprechwunsch"):
                try:
                    vehicle_link = message.find_element(By.XPATH, ".//a[contains(@href, '/vehicles/')]")
                    vehicle_urls_to_process.append({'url': vehicle_link.get_attribute('href'), 'name': vehicle_link.text.strip()})
                except NoSuchElementException: continue
        
        if not vehicle_urls_to_process:
            print("Info: Keine neuen Sprechwünsche."); return

        navigated_away = True # Wir werden jetzt navigieren
        print(f"Info: {len(vehicle_urls_to_process)} Sprechwünsche gefunden. Bearbeite...")
        for vehicle_info in vehicle_urls_to_process:
            driver.get(vehicle_info['url'])
            try:
                # ANPASSUNG: Der XPath sucht jetzt auch nach dem deutschen '/gefangener/'
                # und klickt den ersten verfügbaren grünen Button für Patienten ODER Gefangene.
                transport_button_xpath = "//a[(contains(@href, '/patient/') or contains(@href, '/prisoner/') or contains(@href, '/gefangener/')) and contains(@class, 'btn-success')]"
                
                # Wir klicken auf den ersten passenden Button (nächstgelegenes Krankenhaus / Zelle)
                wait.until(EC.element_to_be_clickable((By.XPATH, transport_button_xpath))).click()
                print(f"      -> Sprechwunsch für '{vehicle_info['name']}' bearbeitet.")
                time.sleep(2) # Kurze Pause nach dem Klick
            except TimeoutException:
                print(f"      -> WARNUNG: Konnte keinen Transport-Button für '{vehicle_info['name']}' finden.")

    except NoSuchElementException:
        print("Info: Keine wichtigen Funksprüche vorhanden.")
    except Exception as e:
        print(f"FEHLER bei der Sprechwunsch-Bearbeitung: {e}")
    finally:
        # Dieser Block stellt sicher, dass der Bot immer zur Hauptseite zurückkehrt.
        if navigated_away:
            print("Info: Kehre nach Sprechwunsch-Bearbeitung zur Hauptseite zurück.")
            driver.get("https://www.leitstellenspiel.de/")

def load_vehicle_id_map(file_path=resource_path("vehicle_id.json")):
    """Lädt die Fahrzeug-ID-Zuordnung aus einer JSON-Datei."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"FEHLER: Die ID-Datei '{file_path}' wurde nicht gefunden!"); return None
    except json.JSONDecodeError:
        print(f"FEHLER: Die Datei '{file_path}' hat ein ungültiges JSON-Format."); return None

def save_vehicle_database(database, file_path=resource_path("fahrzeug_datenbank.json")):
    """Speichert die (ggf. erweiterte) Fahrzeug-Datenbank zurück in die JSON-Datei."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=4, ensure_ascii=False)
        print("Info: Fahrzeug-Datenbank wurde erfolgreich mit neuen Fahrzeugen aktualisiert.")
    except Exception as e:
        print(f"FEHLER: Konnte die Fahrzeug-Datenbank nicht speichern: {e}")

# --- Missions-Cache laden ---
def load_mission_cache(file_path=resource_path("mission_cache.json")):
    """Lädt den Einsatz-Anforderungs-Cache aus einer JSON-Datei."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            print("Info: Missions-Cache erfolgreich geladen.")
            return json.load(f)
    except FileNotFoundError:
        print("Info: Keine 'mission_cache.json' gefunden. Es wird ein neuer Cache erstellt."); return {}
    except json.JSONDecodeError:
        print(f"FEHLER: Der Cache '{file_path}' hat ein ungültiges JSON-Format. Cache wird ignoriert."); return {}

# --- Missions-Cache speichern ---
def save_mission_cache(cache_data, file_path=resource_path("mission_cache.json")):
    """Speichert den aktuellen Anforderungs-Cache in die JSON-Datei."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
        print("Info: Missions-Cache wurde erfolgreich gespeichert.")
    except Exception as e:
        print(f"FEHLER: Konnte den Missions-Cache nicht speichern: {e}")

# Ersetze die alte Funktion komplett durch diese neue Version
def get_player_vehicle_inventory(driver, wait):
    """
    **KORRIGIERT & ERWEITERT:** Liest den Fuhrpark ein, fügt unbekannte
    Fahrzeuge automatisch zur In-Memory-Datenbank hinzu und meldet,
    ob eine Aktualisierung stattgefunden hat.
    """
    print("Info: Lese den kompletten Fuhrpark (Inventar) ein...")
    
    vehicle_id_map = load_vehicle_id_map()
    if not vehicle_id_map:
        print("WARNUNG: Fahrzeug-ID-Map konnte nicht geladen werden. Inventarprüfung wird ungenau sein.")
        return set(), False # Gibt jetzt ein Tupel zurück

    inventory = set()
    database_updated = False # Ein Flag, um zu verfolgen, ob Änderungen vorgenommen wurden
    try:
        driver.get("https://www.leitstellenspiel.de/vehicles")
        
        vehicle_rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tbody/tr")))
        print(f"Info: {len(vehicle_rows)} Zeilen in der Fahrzeugtabelle gefunden. Analysiere...")

        for row in vehicle_rows:
            try:
                image_tag = row.find_element(By.XPATH, ".//img[@vehicle_type_id]")
                vehicle_id = image_tag.get_attribute('vehicle_type_id')
                
                if vehicle_id:
                    vehicle_name = vehicle_id_map.get(vehicle_id)
                    if vehicle_name:
                        inventory.add(vehicle_name)

                        # ================================================================= #
                        # HIER IST DIE NEUE LOGIK ZUM HINZUFÜGEN                            #
                        # ================================================================= #
                        if vehicle_name not in VEHICLE_DATABASE:
                            print(f"--> NEUES FAHRZEUG: '{vehicle_name}' wird zur Datenbank hinzugefügt.")

                            # Erstelle den neuen Standard-Eintrag im Dictionary
                            VEHICLE_DATABASE[vehicle_name] = {
                                "fraktion": "",
                                "personal": 0, # Wir verwenden 0 als Zahl für Konsistenz im Code
                                "typ": [vehicle_name]
                            }
                            ADDED_TO_DATABASE.append(vehicle_name)
                            database_updated = True # Setze das Flag, damit wir später speichern
                        # ================================================================= #
                            
                else:
                    print(f"Warnung: Unbekannte Fahrzeug-ID '{vehicle_id}' im Inventar gefunden.")
            except NoSuchElementException:
                continue
        
        print(f"Info: Inventar mit {len(inventory)} einzigartigen Fahrzeugtypen erfolgreich erstellt.")
        
    except Exception as e:
        print(f"FEHLER: Konnte den Fuhrpark nicht einlesen: {e}")
        traceback.print_exc()
            
    return inventory, database_updated # Gibt das Inventar und das Update-Flag zurück

# -----------------------------------------------------------------------------------
# HAUPT-THREAD FÜR DIE BOT-LOGIK
# -----------------------------------------------------------------------------------

def main_bot_logic(gui_vars):
    driver = None
    # ANPASSUNG: dispatched_mission_ids wird nicht mehr benötigt und wurde entfernt
    last_check_date = None; bonus_checked_today = False
    try:
        mission_cache = load_mission_cache() # NEU: Cache aus Datei laden
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
        
        gui_vars['gui_queue'].put(('status', "Warte auf Hauptseite...")); wait.until(EC.presence_of_element_located((By.ID, "missions_outer"))); gui_vars['gui_queue'].put(('status', "Login erfolgreich! Bot aktiv."))
        send_discord_notification(f"Bot erfolgreich gestartet auf Account: **{LEITSTELLENSPIEL_USERNAME}**", "user")
        player_inventory, gui_vars["db_updated_flag"] = get_player_vehicle_inventory(driver, wait)
        if gui_vars["db_updated_flag"]:
            save_vehicle_database(VEHICLE_DATABASE)
        
        while True:
            if gui_vars['stop_event'].is_set(): break
            if not gui_vars['pause_event'].is_set():
                gui_vars['gui_queue'].put(('status', "Bot pausiert...")); gui_vars['pause_event'].wait()

            gui_vars['gui_queue'].put(('status', "Prüfe Status (Boni, etc.)...")); driver.get("https://www.leitstellenspiel.de/")
            wait.until(EC.presence_of_element_located((By.ID, "missions_outer")), 120)
            today = date.today()
            if last_check_date != today: bonus_checked_today = False; last_check_date = today
            if not bonus_checked_today: check_and_claim_daily_bonus(driver, wait); bonus_checked_today = True
            check_and_claim_tasks(driver, wait)

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
                        except NoSuchElementException:
                            is_red = False # Fallback, falls die Struktur anders ist

                        # print(f"debug: is red, {is_red}! - {panel_class}")

                        if name and mission_id and is_red:
                            mission_data.append({
                                'id': mission_id, 'name': name, 'patienten': patient_count, 
                                'timeleft': timeleft
                            })
                    except (NoSuchElementException, json.JSONDecodeError): continue
                
                if not mission_data:
                    gui_vars['gui_queue'].put(('status', f"Keine Einsätze. Warte {30}s...")); time.sleep(30); continue
                gui_vars['gui_queue'].put(('status', f"{len(mission_data)} Einsätze gefunden. Bearbeite..."))

                for i, mission in enumerate(mission_data):
                    if gui_vars['stop_event'].is_set(): break
                    if not gui_vars['pause_event'].is_set(): gui_vars['gui_queue'].put(('status' ,"Bot pausiert...")); gui_vars['pause_event'].wait()

                    # ANPASSUNG: Die alte Skip-Logik wird durch die neue Logik ersetzt
                    # Unerwünschte Einsätze werden weiterhin übersprungen
                    if "[Verband]" in mission['name'] or mission['name'].lower() == "krankentransport" or "intensivverlegung" in mission['name'].lower():
                        continue
                    
                    if mission['timeleft'] > MAX_START_DELAY_SECONDS:
                        continue
                    
                    print(f"-----------------{mission['name']}-----------------")
                    gui_vars['gui_queue'].put(('mission_name', f"({i+1}/{len(mission_data)}) {mission['name']}"))

                    try:
                        # Schritt 1: Zum Einsatz navigieren
                        sidebar_button_xpath = f"//div[@mission_id='{mission['id']}']//a[contains(@class, 'mission-alarm-button')]"
                        element_to_click = wait.until(EC.element_to_be_clickable((By.XPATH, sidebar_button_xpath)))
                        driver.execute_script("arguments[0].click();", element_to_click)
                        
                        main_alarm_button_id = f"alarm_button_{mission['id']}"
                        wait.until(EC.presence_of_element_located((By.ID, main_alarm_button_id)))

                        # Schritt 2: Prüfen, ob der Einsatz unvollständig ist (Nachalarmierung)
                        vehicles_on_scene = []
                        is_incomplete = False
                        try:
                            # KORREKTUR: Dieser XPath sucht jetzt sicher nach der richtigen Alarm-Box,
                            # indem er auf die data-requirement-type Attribute in den Kind-Elementen prüft.
                            missing_alert_xpath = "//div[contains(@class, 'alert-danger') and .//div[@data-requirement-type]]"
                            driver.find_element(By.XPATH, missing_alert_xpath)
                            
                            print(" -> Warnmeldung für fehlende Einheiten gefunden. Bereite Nachalarmierung vor.")
                            vehicles_on_scene = get_on_scene_and_driving_vehicles(driver, wait, vehicle_id_map)
                            is_incomplete = True
                            
                        except NoSuchElementException:
                            print(" -> Keine Warnmeldung für fehlende Einheiten. Einsatz wird voll bearbeitet.")
                        
                        # Ab hier geht die Logik wie gehabt weiter...
                        # Anforderungen abrufen
                        raw_requirements = get_mission_requirements(driver, wait, player_inventory, mission['patienten'], mission['name'], mission_cache)
                        if not raw_requirements: continue

                        # ### START: BLOCK FÜR PATIENTEN-ANFORDERUNGEN ###
                        try:
                            patient_alert_xpath = "//div[starts-with(@id, 'patients_missing_')]"
                            patient_alert = driver.find_element(By.XPATH, patient_alert_xpath)
                            alert_text = patient_alert.text
                            print(f" -> Patienten-Anforderung gefunden: '{alert_text}'")

                            if "NEF" in alert_text:
                                raw_requirements['fahrzeuge'].append(["NEF"])
                                print("    -> Füge 1x NEF zum Bedarf hinzu.")
                            if "RTW" in alert_text:
                                # Dein Code zur Verarbeitung von RTW-Anforderungen
                                import re
                                match = re.search(r'(\d+)\s*x?\s*RTW', alert_text)
                                if match:
                                    num_rtw = int(match.group(1))
                                    for _ in range(num_rtw):
                                        raw_requirements['fahrzeuge'].append(["RTW"])
                                    print(f"    -> Füge {num_rtw}x RTW zum Bedarf hinzu.")
                                elif "RTW" in alert_text and not match:
                                    raw_requirements['fahrzeuge'].append(["RTW"])
                                    print("    -> Füge 1x RTW zum Bedarf hinzu.")

                        except NoSuchElementException:
                            pass

                    except NoSuchElementException:
                            pass

                    # Unrentable Einsätze überspringen
                    if mission['timeleft'] > 0 and raw_requirements.get('credits', 0) < MINIMUM_CREDITS:
                        continue
                    
                    # ANPASSUNG: Wenn der Einsatz unvollständig ist, werden die Anforderungen reduziert
                    if is_incomplete and vehicles_on_scene:
                        print("\n========== DEBUG: NACHALARMERUNG GESTARTET ==========")
                        print(f"DEBUG: Gefundene Einheiten vor Ort/auf Anfahrt: {', '.join(vehicles_on_scene)}")

                        provided_by_on_scene = {'personal_fw': 0, 'personal_thw': 0, 'personal_rd': 0, 'personal_pol': 0,
                                                'wasser': 0, 'schaummittel': 0, 'patienten_kapazitaet': 0}

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

                        print("\nDEBUG: BEREITS ERFÜLLTE RESSOURCEN:")
                        print(f"  - Personal FW: {provided_by_on_scene['personal_fw']}")
                        print(f"  - Personal THW: {provided_by_on_scene['personal_thw']}")
                        print(f"  - Personal RD: {provided_by_on_scene['personal_rd']}")
                        print(f"  - Personal POL: {provided_by_on_scene['personal_pol']}")
                        print(f"  - Wasser: {provided_by_on_scene['wasser']}L")
                        print(f"  - Schaummittel: {provided_by_on_scene['schaummittel']}L")
                        print(f"  - Patienten-Transportplätze: {provided_by_on_scene['patienten_kapazitaet']}")

                        on_scene_counts = Counter(vehicles_on_scene)
                        still_needed_requirements = []
                        print("\nDEBUG: PRÜFE FAHRZEUG-ANFORDERUNGEN...")
                        for required_options in raw_requirements['fahrzeuge']:
                            found_match_on_scene = False
                            for option in required_options:
                                if on_scene_counts[option] > 0:
                                    on_scene_counts[option] -= 1
                                    found_match_on_scene = True
                                    print(f"    - Anforderung '{'/'.join(required_options)}' wird durch vorhandenes Fahrzeug '{option}' erfüllt.")
                                    break
                            if not found_match_on_scene:
                                still_needed_requirements.append(required_options)
                                print(f"    -> OFFEN: '{'/'.join(required_options)}' wird noch benötigt.")

                        raw_requirements['fahrzeuge'] = still_needed_requirements

                        raw_requirements['personal_fw'] = max(0, raw_requirements.get('personal_fw', 0) - provided_by_on_scene['personal_fw'])
                        raw_requirements['personal_thw'] = max(0, raw_requirements.get('personal_thw', 0) - provided_by_on_scene['personal_thw'])
                        raw_requirements['personal_rd'] = max(0, raw_requirements.get('personal_rd', 0) - provided_by_on_scene['personal_rd'])
                        raw_requirements['personal_pol'] = max(0, raw_requirements.get('personal_pol', 0) - provided_by_on_scene['personal_pol'])
                        raw_requirements['wasser'] = max(0, raw_requirements.get('wasser', 0) - provided_by_on_scene['wasser'])
                        raw_requirements['schaummittel'] = max(0, raw_requirements.get('schaummittel', 0) - provided_by_on_scene['schaummittel'])
                        # Patientenzahl wird vom Einsatz vorgegeben, aber die Transportkapazität kann reduziert werden.
                        raw_requirements['patienten'] = max(0, raw_requirements.get('patienten', 0) - provided_by_on_scene['patienten_kapazitaet'])

                        print("\nDEBUG: FINALER BEDARF FÜR DIESEN ALARM:")
                        print(f" -> Verbleibender Fahrzeugbedarf: {len(still_needed_requirements)} Slots.")
                        print(f" -> Verbleibender Personalbedarf: FW: {raw_requirements['personal_fw']}, THW: {raw_requirements['personal_thw']}, RD: {raw_requirements['personal_rd']}, POL: {raw_requirements['personal_pol']}")
                        print(f" -> Verbleibender Ressourcenbedarf: Wasser: {raw_requirements['wasser']}L, Schaum: {raw_requirements['schaummittel']}L")
                        print("========== DEBUG: NACHALARMERUNG BEENDET ==========\n")
                    
                    # GUI-Anzeige und Fahrzeug-Zuteilung wie bisher, aber mit potenziell reduzierten Anforderungen
                    final_requirements = raw_requirements
                    req_parts = []; readable_requirements = [" oder ".join(options) for options in final_requirements['fahrzeuge']]
                    vehicle_counts = Counter(readable_requirements)
                    for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")

                    # NEU: Personal-Anforderungen pro Organisation hinzufügen
                    if final_requirements.get('personal_fw', 0) > 0: req_parts.append(f"{final_requirements['personal_fw']} Pers. (FW)")
                    if final_requirements.get('personal_thw', 0) > 0: req_parts.append(f"{final_requirements['personal_thw']} Pers. (THW)")
                    if final_requirements.get('personal_rd', 0) > 0: req_parts.append(f"{final_requirements['personal_rd']} Pers. (RD)")
                    if final_requirements.get('personal_pol', 0) > 0: req_parts.append(f"{final_requirements['personal_pol']} Pers. (POL)")

                    gui_vars['gui_queue'].put(('requirements', "Bedarf: " + (", ".join(req_parts) if req_parts else "Nichts mehr benötigt.")))

                    available_vehicles = get_available_vehicles(driver, wait)
                    if not available_vehicles:
                        gui_vars['gui_queue'].put(('availability', "Verfügbar: Keine"))
                        gui_vars['gui_queue'].put(('status', f"Keine Fahrzeuge frei. Pausiere {PAUSE_IF_NO_VEHICLES_SECONDS}s..."))
                        time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS); break
                    
                    # Logik für GUI-Anzeige der Verfügbarkeit (unverändert)
                    specific_types = [v['vehicle_type'] for v in available_vehicles]
                    available_counts = Counter(specific_types)
                    vehicle_parts = [f"{count}x {v_type}" for v_type, count in available_counts.items()]
                    vehicle_str = "Fahrzeuge: " + (", ".join(vehicle_parts) if vehicle_parts else "Keine")
                    personnel_counts = {'FW': 0, 'THW': 0, 'RD': 0, 'POL': 0}; total_water = 0; total_foam = 0
                    for v in available_vehicles:
                        props = v.get('properties', {}); total_water += props.get('wasser', 0); total_foam += props.get('schaummittel', 0)
                        fraktion = props.get('fraktion')
                        if fraktion in personnel_counts: personnel_counts[fraktion] += props.get('personal', 0)
                    personnel_str = (f"Personal: {personnel_counts['FW']} FW, {personnel_counts['THW']} THW, {personnel_counts['RD']} RD, {personnel_counts['POL']} POL")
                    resources_str = f"Wasser: {total_water}L Wasser, {total_foam}L Schaummittel"
                    gui_vars['gui_queue'].put(('availability', f"{vehicle_str}\n{personnel_str}\n{resources_str}"))

                    checkboxes_to_click = find_best_vehicle_combination(final_requirements, available_vehicles, VEHICLE_DATABASE)
                    if checkboxes_to_click:
                        gui_vars['gui_queue'].put(('status', "✓ Alarmiere...")); gui_vars['gui_queue'].put(('alarm_status', f"Status: ALARMIERT ({len(checkboxes_to_click)} FZ)"))
                        for checkbox in checkboxes_to_click: driver.execute_script("arguments[0].click();", checkbox)
                        try:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren und zum nächsten Einsatz']"); driver.execute_script("arguments[0].click();", alarm_button)
                        except NoSuchElementException:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren']"); driver.execute_script("arguments[0].click();", alarm_button)
                    else:
                        gui_vars['gui_queue'].put(('status', "❌ Nicht genug Einheiten frei.")); gui_vars['gui_queue'].put(('alarm_status', "Status: WARTE AUF EINHEITEN"))

                    short_wait = WebDriverWait(driver, 3) 
                    try:
                        short_wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
                        close_button_xpath = "//*[@id='lightbox_close_inside']"
                        short_wait.until(EC.element_to_be_clickable((By.XPATH, close_button_xpath))).click()
                    except TimeoutException: pass
                    finally: driver.switch_to.default_content()

                    wait.until(EC.visibility_of_element_located((By.ID, "missions_outer")))

                    update_data = {
                        'status': "Lade nächsten Einsatz...", 'alarm_status': "Status: -",
                        'requirements': "Bedarf: -", 'availability': "Verfügbar: -"
                    }
                    gui_vars['gui_queue'].put(('batch_update', update_data))

                    #nach jedem Einsatz einmal prüfen
                    handle_sprechwunsche(driver, wait)


            except Exception as e:
                print(f"Fehler im Verarbeitungszyklus: {e}"); traceback.print_exc(); time.sleep(10)
    except Exception as e:
        print("FATALER FEHLER! Erstelle Screenshot 'fehler.png'...")
        if driver:
            driver.save_screenshot('fehler.png')

        error_details = traceback.format_exc(); send_discord_notification(f"FATALER FEHLER! Bot beendet.\n```\n{error_details}\n```", "dev")
        gui_vars['gui_queue'].put(('status', "FATALER FEHLER! Details in error_log.txt")); gui_vars['gui_queue'].put(('mission_name', "Bot angehalten."))
        root = tk.Tk(); root.withdraw(); messagebox.showinfo("Fataler Fehler!", "Der bot wurde Angehalten! Prüfe das Fehler Log und informiere Caoss, ggf. das Fehler.png senden."); root.destroy()
        try:
            with open(resource_path('error_log.txt'), 'a', encoding='utf-8') as f:
                f.write(f"\n--- FEHLER am {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"); f.write(error_details); f.write("-" * 50 + "\n")
        except Exception as log_e: gui_vars['gui_queue'].put(('status', f"Konnte nicht in Log schreiben: {log_e}"))
    finally:
        if mission_cache: # NEU: Prüfen, ob der Cache Daten enthält
            save_mission_cache(mission_cache) # NEU: Cache in Datei speichern
        if driver: driver.quit()
        gui_vars['gui_queue'].put(('status', "Bot beendet."))

# -----------------------------------------------------------------------------------
# HAUPTPROGRAMM
# -----------------------------------------------------------------------------------
if __name__ == "__main__":
    gui_queue = queue.Queue()

    pause_event = threading.Event()
    pause_event.set() 
    stop_event = threading.Event()

    app = StatusWindow(pause_event, stop_event, gui_queue) # Hier die Queue übergeben
    
    gui_variables = { 
        "status": app.status_var, 
        "mission_name": app.mission_name_var, 
        "requirements": app.requirements_var, 
        "availability": app.availability_var, 
        "alarm_status": app.alarm_status_var,
        "pause_event": pause_event,
        "stop_event": stop_event,
        "db_updated_flag": False,  # NEU: Der "Merker" für das Datenbank-Update
        "gui_queue": gui_queue
    }
    
    bot_thread = threading.Thread(target=main_bot_logic, args=(gui_variables,))
    bot_thread.start()

    app.mainloop()

    print("Fenster geschlossen. Warte auf sauberes Herunterfahren des Bot-Threads...")
    bot_thread.join()

    # Wir prüfen den "Merker", den der Bot-Thread eventuell gesetzt hat
    if gui_variables.get("db_updated_flag", False):
        # Wir erstellen ein unsichtbares Hauptfenster, nur um das Pop-up zu zeigen
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Datenbank-Update", 
            "Die Fahrzeug-Datenbank wurde mit neuen Einträgen aktualisiert! Es müssen noch Daten eingetragen werden."
        )
        send_discord_notification(f"Fahrzeuge zu Datenbank hinzugefügt! \n```\n{ADDED_TO_DATABASE}\n```", "dev_update")
        root.destroy()
    
    print("Bot wurde ordnungsgemäß beendet.")