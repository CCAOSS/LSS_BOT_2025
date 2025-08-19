import time
import json
import os
import sys
import threading
import tempfile # Füge diesen Import oben bei den anderen hinzu
import tkinter as tk
from tkinter import ttk
from collections import Counter
import traceback
from datetime import date
import requests

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
BOT_VERSION = "V6.2 - Final Logic"
PAUSE_IF_NO_VEHICLES_SECONDS = 300
MAX_START_DELAY_SECONDS = 3600
MINIMUM_CREDITS = 10000

# -----------------------------------------------------------------------------------
# DIE KLASSE FÜR DAS STATUS-FENSTER (Version mit Pause/Stop-Logik)
# -----------------------------------------------------------------------------------

class StatusWindow(tk.Tk):
    def __init__(self, pause_event, stop_event):
        super().__init__()
        
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
    chrome_options.add_argument("--headless"); chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3"); chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("--no-sandbox")

    # --- NEU: Einzigartiges Nutzerverzeichnis erstellen ---
    # Erstellt einen zufälligen, temporären Ordner für diese Sitzung
    user_data_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    
    # Betriebssystem-Erkennung (bleibt unverändert)
    if sys.platform.startswith('linux'):
        print("Info: Linux-Betriebssystem (Raspberry Pi) erkannt.")
        user_agent = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
        service = ChromeService(executable_path="/usr/bin/chromedriver")
    else: # win32
        print("Info: Windows-Betriebssystem erkannt.")
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        service = ChromeService(executable_path=resource_path("chromedriver.exe"))
    
    chrome_options.add_argument(f'user-agent={user_agent}'); chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"]); chrome_options.add_experimental_option('useAutomationExtension', False)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"); return driver
    

    
def get_mission_requirements(driver, wait, player_inventory):
    """
    **FINALER FIX V17:** Löst das Problem durch eine saubere Zwei-Phasen-Logik,
    die sicherstellt, dass Wahrscheinlichkeits-Anforderungen NUR dann berücksichtigt
    werden, wenn das Fahrzeug im Inventar vorhanden ist.
    """
    
    # --- ANPASSBARE ÜBERSETZUNGS-LISTE ---
    translation_map = {
        "Feuerwehrkran": "FwK",
        "Drehleiter": "DLK 23",
        "Rettungswagen": "RTW",
        "Löschfahrzeuge": "Löschfahrzeug",
        "Rüstwagen": "RW",
        "Gerätewagen Öl": "GW-Öl",
    }
    # --- ENDE ANPASSBARE ÜBERSETZUNGS-LISTE ---

    raw_requirements = {'fahrzeuge': [], 'personal': 0, 'wasser': 0, 'schaummittel': 0, 'credits': 0}
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Hilfe')]"))).click()
        try:
            vehicle_table = wait.until(EC.visibility_of_element_located((By.XPATH, "//table[.//th[contains(text(), 'Fahrzeuge')]]")))
            rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")

            # Hilfsfunktion, um Namen konsistent zu bereinigen und zu übersetzen
            def normalize_name(name):
                clean = name.split('(')[0].strip().replace("Benötigte ", "")
                if clean.endswith("kräne"): clean = clean.replace("kräne", "kran")
                elif clean.endswith("wägen"): clean = clean.replace("wägen", "wagen")
                elif clean.endswith("leitern"): clean = clean.replace("leitern", "leiter")
                return translation_map.get(clean, clean)

            # --- PHASE 1: Alle Anforderungen sammeln und ihren Typ (fest/prob) vermerken ---
            collected_reqs = {}
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) < 2: continue
                
                requirement_text, count_text = cells[0].text.strip(), cells[1].text.strip().replace(" L", "")
                is_prob = "anforderungswahrscheinlichkeit" in requirement_text.lower()
                
                clean_name = requirement_text.split('(')[0].strip().replace("Benötigte ", "")
                
                # Ressourcen direkt verarbeiten
                if any(keyword in clean_name.lower() for keyword in ["personal", "feuerwehrleute", "wasser", "schaummittel"]):
                    if "personal" in clean_name.lower() or "feuerwehrleute" in clean_name.lower():
                        if count_text.isdigit(): raw_requirements['personal'] += int(count_text)
                    elif "wasser" in clean_name.lower():
                        if count_text.isdigit(): raw_requirements['wasser'] += int(count_text)
                    elif "schaummittel" in clean_name.lower():
                        if count_text.isdigit(): raw_requirements['schaummittel'] += int(count_text)
                    continue

                # Fahrzeuganforderungen sammeln
                options_text = [p.strip() for p in clean_name.replace(",", " oder ").split(" oder ")]
                final_options = tuple(sorted([normalize_name(opt) for opt in options_text if opt])) # Tupel als Key für das Dictionary

                if not final_options: continue
                
                # Zähle, wie oft diese Anforderung vorkommt
                count = int(count_text) if count_text.isdigit() else 0
                
                if final_options not in collected_reqs:
                    collected_reqs[final_options] = {'count': 0, 'is_prob': True} # Starte mit Annahme "is_prob"
                
                collected_reqs[final_options]['count'] += count
                if not is_prob:
                    collected_reqs[final_options]['is_prob'] = False # Eine feste Anforderung überschreibt immer eine Wahrscheinlichkeit

            # --- PHASE 2: Endgültige Anforderungsliste basierend auf den gesammelten Daten erstellen ---
            for options, data in collected_reqs.items():
                is_hard_req = not data['is_prob']
                
                # Prüfe, ob ALLE Optionen der Anforderung im Inventar sind (wichtig für Wahrscheinlichkeiten)
                owned = all(opt in player_inventory for opt in options)

                if is_hard_req or (data['is_prob'] and owned):
                    # Anforderung hinzufügen
                    for _ in range(data['count']):
                        raw_requirements['fahrzeuge'].append(list(options))
                else:
                    # Anforderung ignorieren
                    print(f"    -> Info: Ignoriere Anforderung '{'/'.join(options)}' (Wahrscheinlichkeit & nicht im Bestand).")

        except TimeoutException: print("Info: Keine Fahrzeug-Anforderungstabellen gefunden.")
        
        try:
            credits_selector = "//td[normalize-space()='Credits im Durchschnitt']/following-sibling::td"
            credits_text = driver.find_element(By.XPATH, credits_selector).text.strip().replace(".", "").replace(",", "")
            if credits_text.isdigit(): raw_requirements['credits'] = int(credits_text)
        except NoSuchElementException: pass

    except TimeoutException: return None
    finally:
        try: wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Zurück']"))).click()
        except: driver.refresh()
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
            driver.execute_script("arguments[0].click();", load_more_button)
            time.sleep(2)
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
    
    return available_vehicles

def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
    """
    **NEUE LOGIK V3:** Findet die beste Fahrzeugkombination mit einer verbesserten,
    "gierigen" Auswahl-Logik, die Fahrzeuge mit mehreren Rollen korrekt behandelt.
    """
    # Vorbereitung der Anforderungen (unverändert)
    needed_vehicle_options_list = requirements.get('fahrzeuge', [])
    needed_personal = requirements.get('personal', 0)
    needed_wasser = requirements.get('wasser', 0)
    needed_schaummittel = requirements.get('schaummittel', 0)
    patient_bedarf = requirements.get('patienten', 0)

    if patient_bedarf > 5:
        needed_vehicle_options_list.append(["KdoW-LNA"])
    elif patient_bedarf > 10:
        needed_vehicle_options_list.append(["GW-San"])
        needed_vehicle_options_list.append(["ELW 1 (SEG)"])
        needed_vehicle_options_list.append(["KdoW-OrgL"])

    explicit_rtw_count = sum(1 for options in needed_vehicle_options_list if "RTW" in options)
    needed_vehicle_options_list = [options for options in needed_vehicle_options_list if "RTW" not in options]
    rtws_to_add = min(patient_bedarf, 15)
    final_rtw_bedarf = max(explicit_rtw_count, rtws_to_add)
    for _ in range(final_rtw_bedarf):
        needed_vehicle_options_list.append(["RTW"])

    # --- START DER NEUEN AUSWAHL-LOGIK ---
    vehicles_to_send = []
    pool = list(available_vehicles)
    
    # Wandle die Anforderungsliste in eine zählbare Form um
    needed_counts = Counter(opt for sublist in needed_vehicle_options_list for opt in sublist)
    
    # Die Schleife läuft, solange es ungedeckte Anforderungen und verfügbare Fahrzeuge gibt
    while True:
        # 1. Zähle die aktuell durch `vehicles_to_send` abgedeckten Rollen
        current_provided_roles = [role for v in vehicles_to_send for role in v['properties'].get('typ', [])]
        current_counts = Counter(current_provided_roles)

        # 2. Finde die beste nächste Wahl aus dem Pool
        best_vehicle_to_add = None
        highest_score = 0

        for vehicle in pool:
            score = 0
            vehicle_roles = vehicle['properties'].get('typ', [])
            # Bewerte das Fahrzeug danach, wie viele *noch benötigte* Rollen es erfüllt
            temp_counts = current_counts.copy()
            for role in vehicle_roles:
                if temp_counts.get(role, 0) < needed_counts.get(role, 0):
                    score += 1
                    temp_counts[role] = temp_counts.get(role, 0) + 1
            
            if score > highest_score:
                highest_score = score
                best_vehicle_to_add = vehicle

        # 3. Wenn ein nützliches Fahrzeug gefunden wurde, füge es hinzu. Sonst beende die Suche.
        if best_vehicle_to_add:
            vehicles_to_send.append(best_vehicle_to_add)
            pool.remove(best_vehicle_to_add)
        else:
            break  # Kein Fahrzeug im Pool kann eine offene Anforderung mehr erfüllen
            
    # --- ENDE DER NEUEN AUSWAHL-LOGIK ---

    # 2. Berechne, was die ausgewählten Fahrzeuge mitbringen (unverändert)
    provided_personal = sum(v['properties'].get('personal', 0) for v in vehicles_to_send)
    provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    provided_patienten_kapazitaet = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)

    # 3. Defizit-Auffüllung für Ressourcen (Wasser, Personal etc.) - füllt ggf. weiter auf
    def fill_deficit(resource_key, current_provided, needed, resource_name):
        nonlocal pool, vehicles_to_send, provided_personal, provided_wasser, provided_schaummittel, provided_patienten_kapazitaet
        if current_provided < needed:
            pool.sort(key=lambda v: v['properties'].get(resource_key, 0), reverse=True)
            for vehicle in list(pool):
                if current_provided >= needed: break
                props = vehicle['properties']
                resource_val = props.get(resource_key, 0)
                if resource_val > 0:
                    vehicles_to_send.append(vehicle); pool.remove(vehicle)
                    provided_personal += props.get('personal', 0)
                    provided_wasser += props.get('wasser', 0)
                    provided_schaummittel += props.get('schaummittel', 0)
                    provided_patienten_kapazitaet += props.get('patienten_kapazitaet', 0)
                    current_provided += resource_val
        return current_provided

    provided_wasser = fill_deficit('wasser', provided_wasser, needed_wasser, 'Liter Wasser')
    provided_schaummittel = fill_deficit('schaummittel', provided_schaummittel, needed_schaummittel, 'Liter Schaummittel')
    provided_personal = fill_deficit('personal', provided_personal, needed_personal, 'Personal')
    provided_patienten_kapazitaet = fill_deficit('patienten_kapazitaet', provided_patienten_kapazitaet, patient_bedarf, 'Patienten-Transportplätze')

    # 4. Finale Prüfung (unverändert, dient als finales Sicherheitsnetz)
    final_vehicle_roles = [role for v in vehicles_to_send for role in v['properties'].get('typ', [])]
    final_counts = Counter(final_vehicle_roles)
    
    all_vehicles_met = True
    temp_needed_counts = Counter(opt for sublist in needed_vehicle_options_list for opt in sublist)
    
    for role, required_num in temp_needed_counts.items():
        if final_counts.get(role, 0) < required_num:
            all_vehicles_met = False
            break

    if all_vehicles_met and provided_personal >= needed_personal and provided_wasser >= needed_wasser and provided_schaummittel >= needed_schaummittel and provided_patienten_kapazitaet >= patient_bedarf:
        print(f"Erfolgreiche Zuteilung gefunden! Sende {len(vehicles_to_send)} Fahrzeuge.")
        return [v['checkbox'] for v in vehicles_to_send]
    else:
        print("Keine passende Fahrzeugkombination gefunden.")
        # Detaillierte Fehlerausgabe...
        if not all_vehicles_met:
            print("-> Es fehlen benötigte Fahrzeugtypen:")
            for role, required_num in temp_needed_counts.items():
                sent_num = final_counts.get(role, 0)
                if sent_num < required_num:
                    print(f"     - {required_num - sent_num}x {role}")
        
        if provided_personal < needed_personal: print(f"-> Es fehlen {needed_personal - provided_personal} Personal.")
        if provided_wasser < needed_wasser: print(f"-> Es fehlen {needed_wasser - provided_wasser} L Wasser.")
        if provided_schaummittel < needed_schaummittel: print(f"-> Es fehlen {needed_schaummittel - provided_schaummittel} L Schaummittel.")
        if provided_patienten_kapazitaet < patient_bedarf: print(f"-> Es fehlen {patient_bedarf - provided_patienten_kapazitaet} Patienten-Transportplätze.")
        return []
        
def send_discord_notification(message):
    if "discord_webhook_url" in config and config["discord_webhook_url"]:
        data = {"content": f"🚨 **LSS Bot Alert:**\n>>> {message}"}
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
                transport_button_xpath = "//a[(contains(@href, '/patient/') or contains(@href, '/prisoner/')) and contains(@class, 'btn-success')]"
                wait.until(EC.element_to_be_clickable((By.XPATH, transport_button_xpath))).click(); time.sleep(2)
            except TimeoutException: print(f"    -> WARNUNG: Kein Transport-Button für '{vehicle_info['name']}' gefunden.")
    except NoSuchElementException:
        print("Info: Keine wichtigen Funksprüche vorhanden.")
    except Exception as e:
        print(f"FEHLER bei der Sprechwunsch-Bearbeitung: {e}")
    finally:
        # NEU: Dieser Block wird immer ausgeführt, egal was passiert.
        # Wenn wir auf eine Fahrzeugseite navigiert sind, kehren wir zur Hauptseite zurück.
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

# Ersetze die alte Funktion komplett durch diese neue Version
def get_player_vehicle_inventory(driver, wait):
    """
    **KORRIGIERT:** Timeout behoben. Liest die 'vehicle_type_id' jetzt
    korrekt vom <img>-Tag innerhalb jeder Tabellenzeile aus.
    """
    print("Info: Lese den kompletten Fuhrpark (Inventar) ein...")
    
    vehicle_id_map = load_vehicle_id_map()
    if not vehicle_id_map:
        print("WARNUNG: Fahrzeug-ID-Map konnte nicht geladen werden. Inventarprüfung wird ungenau sein.")
        return set()

    inventory = set()
    try:
        driver.get("https://www.leitstellenspiel.de/vehicles")
        
        # Warte einfach auf die Tabellenzeilen, ohne ein spezielles Attribut zu fordern
        vehicle_rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//tbody/tr")))
        print(f"Info: {len(vehicle_rows)} Zeilen in der Fahrzeugtabelle gefunden. Analysiere...")

        for row in vehicle_rows:
            try:
                # SUCHE das <img>-Tag INNERHALB der aktuellen Zeile und lies dort das Attribut aus.
                image_tag = row.find_element(By.XPATH, ".//img[@vehicle_type_id]")
                vehicle_id = image_tag.get_attribute('vehicle_type_id')
                
                if vehicle_id:
                    # Finde den passenden Namen in unserer ID-Map
                    vehicle_name = vehicle_id_map.get(vehicle_id)
                    if vehicle_name:
                        inventory.add(vehicle_name)
                    else:
                        print(f"Warnung: Unbekannte Fahrzeug-ID '{vehicle_id}' im Inventar gefunden.")
            except NoSuchElementException:
                # Ignoriere Zeilen, die kein passendes <img>-Tag haben (z.B. Kopfzeilen, Trenner)
                continue
        
        print(f"Info: Inventar mit {len(inventory)} einzigartigen Fahrzeugtypen erfolgreich erstellt: {inventory}")
        
    except Exception as e:
        print(f"FEHLER: Konnte den Fuhrpark nicht einlesen: {e}")
        traceback.print_exc()
            
    return inventory

# -----------------------------------------------------------------------------------
# HAUPT-THREAD FÜR DIE BOT-LOGIK
# -----------------------------------------------------------------------------------

def main_bot_logic(gui_vars):
    driver = None; dispatched_mission_ids = set()
    last_check_date = None; bonus_checked_today = False
    try:
        gui_vars['status'].set("Initialisiere..."); driver = setup_driver(); wait = WebDriverWait(driver, 30)
        gui_vars['status'].set("Logge ein..."); driver.get("https://www.leitstellenspiel.de/users/sign_in")
        wait.until(EC.visibility_of_element_located((By.ID, "user_email"))).send_keys(LEITSTELLENSPIEL_USERNAME)
        driver.find_element(By.ID, "user_password").send_keys(LEITSTELLENSPIEL_PASSWORD)
        time.sleep(1)
        try:
            login_button = wait.until(EC.element_to_be_clickable((By.NAME, "commit"))); login_button.click()
        except ElementClickInterceptedException:
            login_button = wait.until(EC.presence_of_element_located((By.NAME, "commit"))); driver.execute_script("arguments[0].click();", login_button)
        
        gui_vars['status'].set("Warte auf Hauptseite..."); wait.until(EC.presence_of_element_located((By.ID, "missions_outer"))); gui_vars['status'].set("Login erfolgreich! Bot aktiv.")
        send_discord_notification(f"Bot erfolgreich gestartet auf Account: **{LEITSTELLENSPIEL_USERNAME}**")
        player_inventory = get_player_vehicle_inventory(driver, wait)
        
        while True:
            if gui_vars['stop_event'].is_set(): break
            if not gui_vars['pause_event'].is_set():
                gui_vars['status'].set("Bot pausiert..."); gui_vars['pause_event'].wait()

            gui_vars['status'].set("Prüfe Status (Boni, etc.)..."); driver.get("https://www.leitstellenspiel.de/"); wait.until(EC.presence_of_element_located((By.ID, "missions_outer")))
            today = date.today();
            if last_check_date != today: bonus_checked_today = False; last_check_date = today
            if not bonus_checked_today: check_and_claim_daily_bonus(driver, wait); bonus_checked_today = True
            check_and_claim_tasks(driver, wait)
            handle_sprechwunsche(driver, wait)
            
            try:
                gui_vars['status'].set("Lade Einsatzliste..."); driver.get("https://www.leitstellenspiel.de/"); mission_list_container = wait.until(EC.presence_of_element_located((By.ID, "missions_outer")))
                mission_entries = mission_list_container.find_elements(By.XPATH, ".//div[contains(@class, 'missionSideBarEntry')]")
                mission_data = []; current_mission_ids = set()
                for entry in mission_entries:
                    try:
                        mission_id = entry.get_attribute('mission_id'); url_element = entry.find_element(By.XPATH, ".//a[contains(@class, 'mission-alarm-button')]"); href = url_element.get_attribute('href')
                        name_element = entry.find_element(By.XPATH, ".//a[contains(@id, 'mission_caption_')]"); full_name = name_element.text.strip(); name = full_name.split(',')[0].strip()
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
                        if href and name and mission_id:
                            mission_data.append({'id': mission_id, 'url': href, 'name': name, 'patienten': patient_count, 'timeleft': timeleft}); current_mission_ids.add(mission_id)
                    except (NoSuchElementException, json.JSONDecodeError): continue
                dispatched_mission_ids.intersection_update(current_mission_ids)
                if not mission_data:
                    gui_vars['status'].set(f"Keine Einsätze. Warte {30}s..."); time.sleep(30); continue
                gui_vars['status'].set(f"{len(mission_data)} Einsätze gefunden. Bearbeite...")
                for i, mission in enumerate(mission_data):
                    if gui_vars['stop_event'].is_set(): break
                    if not gui_vars['pause_event'].is_set(): gui_vars['status'].set("Bot pausiert..."); gui_vars['pause_event'].wait()
                    if "[Verband]" in mission['name'] or mission['id'] in dispatched_mission_ids: continue
                    
                    if mission['timeleft'] > MAX_START_DELAY_SECONDS:
                        print(f"Info: Ignoriere zukünftigen Einsatz '{mission['name']}' (Start in {mission['timeleft'] // 60} min)"); continue
                    
                    gui_vars['mission_name'].set(f"({i+1}/{len(mission_data)}) {mission['name']}"); driver.get(mission['url'])
                    raw_requirements = get_mission_requirements(driver, wait, player_inventory)
                    if not raw_requirements: continue
                    
                    if mission['timeleft'] > 0 and raw_requirements.get('credits', 0) < MINIMUM_CREDITS:
                        print(f"Info: Ignoriere unrentablen zukünftigen Einsatz '{mission['name']}' (Credits: {raw_requirements.get('credits', 0)} < {MINIMUM_CREDITS})"); continue

                    # Anforderungs-Aufbereitung bleibt gleich...
                    final_requirements = raw_requirements # Vereinfacht, da die alte Aufbereitung entfernt wurde
                    
                    # GUI-Anzeige für Bedarf bleibt gleich...
                    req_parts = []; readable_requirements = [" oder ".join(options) for options in final_requirements['fahrzeuge']]
                    vehicle_counts = Counter(readable_requirements)
                    for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")
                    if final_requirements['personal'] > 0: req_parts.append(f"{final_requirements['personal']} Personal")
                    gui_vars['requirements'].set("Bedarf: " + (", ".join(req_parts) if req_parts else "-"))

                    available_vehicles = get_available_vehicles(driver, wait)
                    
                    # --- NEUER, ERWEITERTER ANZEIGE-BLOCK FÜR VERFÜGBARKEIT ---
                    if available_vehicles:
                        # 1. Zähle die exakten Fahrzeugtypen für die erste Zeile
                        specific_types = [v['vehicle_type'] for v in available_vehicles]
                        available_counts = Counter(specific_types)
                        vehicle_parts = [f"{count}x {v_type}" for v_type, count in available_counts.items()]
                        vehicle_str = "Fahrzeuge: " + (", ".join(vehicle_parts) if vehicle_parts else "Keine")

                        # 2. Summiere Personal nach Fraktion und Ressourcen
                        personnel_counts = {'FW': 0, 'THW': 0, 'RD': 0, 'POL': 0}
                        total_water = 0
                        total_foam = 0
                        for v in available_vehicles:
                            props = v.get('properties', {})
                            total_water += props.get('wasser', 0)
                            total_foam += props.get('schaummittel', 0)
                            
                            fraktion = props.get('fraktion')
                            if fraktion and fraktion in personnel_counts:
                                personnel_counts[fraktion] += props.get('personal', 0)
                        
                        personnel_str = (f"Personal: {personnel_counts['FW']} Feuerwehr, {personnel_counts['THW']} THW, "
                                         f"{personnel_counts['RD']} Rettungsdienst, {personnel_counts['POL']} Polizei")
                        
                        resources_str = f"Wasser: {total_water}L Wasser, {total_foam}L Schaummittel"

                        # 3. Setze den finalen, mehrzeiligen Text
                        final_availability_str = f"{vehicle_str}\n{personnel_str}\n{resources_str}"
                        gui_vars['availability'].set(final_availability_str)

                    else:
                        gui_vars['availability'].set("Verfügbar: Keine")
                        gui_vars['status'].set(f"Keine Fahrzeuge frei. Pausiere {PAUSE_IF_NO_VEHICLES_SECONDS}s...")
                        time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS)
                        break
                    # --- ENDE NEUER ANZEIGE-BLOCK ---
                    
                    checkboxes_to_click = find_best_vehicle_combination(final_requirements, available_vehicles, VEHICLE_DATABASE)
                    if checkboxes_to_click:
                        dispatched_mission_ids.add(mission['id'])
                        gui_vars['status'].set("✓ Alarmiere..."); gui_vars['alarm_status'].set(f"Status: ALARMIERT ({len(checkboxes_to_click)} FZ)")
                        for checkbox in checkboxes_to_click: driver.execute_script("arguments[0].click();", checkbox)
                        try:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren und zum nächsten Einsatz']"); driver.execute_script("arguments[0].click();", alarm_button)
                        except NoSuchElementException:
                            alarm_button = driver.find_element(By.XPATH, "//input[@value='Alarmieren']"); driver.execute_script("arguments[0].click();", alarm_button)
                    else:
                        gui_vars['status'].set("❌ Nicht genug Einheiten frei."); gui_vars['alarm_status'].set("Status: WARTE AUF EINHEITEN")
                    time.sleep(3)
            except Exception as e:
                print(f"Fehler im Verarbeitungszyklus: {e}"); traceback.print_exc(); time.sleep(10)
    except Exception as e:
        error_details = traceback.format_exc(); send_discord_notification(f"FATALER FEHLER! Bot beendet.\n```\n{error_details}\n```")
        gui_vars['status'].set("FATALER FEHLER! Details in error_log.txt"); gui_vars['mission_name'].set("Bot angehalten.")
        try:
            with open(resource_path('error_log.txt'), 'a', encoding='utf-8') as f:
                f.write(f"\n--- FEHLER am {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"); f.write(error_details); f.write("-" * 50 + "\n")
        except Exception as log_e: gui_vars['status'].set(f"Konnte nicht in Log schreiben: {log_e}")
    finally:
        if driver: driver.quit()
        gui_vars['status'].set("Bot beendet.")

# -----------------------------------------------------------------------------------
# HAUPTPROGRAMM
# -----------------------------------------------------------------------------------
if __name__ == "__main__":
    # Erstelle die zentralen Signale
    pause_event = threading.Event()
    pause_event.set() # Starte den Bot im laufenden Zustand
    stop_event = threading.Event()

    # Erstelle das GUI-Fenster und übergib die Signale
    app = StatusWindow(pause_event, stop_event)
    
    # Erstelle das Dictionary, um die GUI-Variablen UND Signale an den Bot zu übergeben
    gui_variables = { 
        "status": app.status_var, 
        "mission_name": app.mission_name_var, 
        "requirements": app.requirements_var, 
        "availability": app.availability_var, 
        "alarm_status": app.alarm_status_var,
        "pause_event": pause_event,
        "stop_event": stop_event
    }
    
    # Erstelle und starte den Bot in einem separaten Thread
    bot_thread = threading.Thread(target=main_bot_logic, args=(gui_variables,), daemon=True)
    bot_thread.start()

    # Starte die GUI-Hauptschleife
    app.mainloop()