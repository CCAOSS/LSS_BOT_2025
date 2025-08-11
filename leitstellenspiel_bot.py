import time
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk
from collections import Counter
import traceback
from datetime import date

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
            print(f"Info: Lade Fahrzeug-Datenbank aus '{file_path}'...")
            return json.load(f)
    except FileNotFoundError:
        print(f"FEHLER: Die Datenbank-Datei '{file_path}' wurde nicht gefunden!"); return None
    except json.JSONDecodeError:
        print(f"FEHLER: Die Datei '{file_path}' hat ein ungültiges JSON-Format."); return None

VEHICLE_DATABASE = load_vehicle_database()
if not VEHICLE_DATABASE:
    print("Bot wird beendet, da die Fahrzeug-Datenbank nicht geladen werden konnte."); time.sleep(10); sys.exit()

# --- Bot-Konfiguration ---
BOT_VERSION = "V5.3 - Final Build"
PAUSE_IF_NO_VEHICLES_SECONDS = 300
CHROMEDRIVER_PATH = resource_path("chromedriver.exe")

# -----------------------------------------------------------------------------------
# DIE KLASSE FÜR DAS STATUS-FENSTER
# -----------------------------------------------------------------------------------

class StatusWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"LSS Bot {BOT_VERSION} | User: {LEITSTELLENSPIEL_USERNAME}")
        self.geometry("450x300"); self.minsize(450, 300)
        self.configure(bg="#2E2E2E")
        style = ttk.Style(self); style.theme_use('clam')
        style.configure("TLabel", background="#2E2E2E", foreground="#FFFFFF", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10))
        self.status_var = tk.StringVar(value="Bot startet...")
        self.mission_name_var = tk.StringVar(value="Warte auf ersten Einsatz...")
        self.requirements_var = tk.StringVar(value="-")
        self.availability_var = tk.StringVar(value="-")
        self.alarm_status_var = tk.StringVar(value="-")
        ttk.Label(self, text="Bot Status:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=20)
        ttk.Label(self, text="Aktueller Einsatz:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.mission_name_var, wraplength=430).pack(anchor="w", padx=20)
        ttk.Label(self, text="Bedarf:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.requirements_var).pack(anchor="w", padx=20)
        ttk.Label(self, text="Verfügbarkeit:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.availability_var).pack(anchor="w", padx=20)
        ttk.Label(self, text="Alarmierungsstatus:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.alarm_status_var).pack(anchor="w", padx=20)
        ttk.Button(self, text="Bot Stoppen", command=self.stop_bot).pack(side="bottom", pady=10)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
    def stop_bot(self):
        self.status_var.set("Beende Bot...")
        with open(resource_path('stop.txt'), 'w') as f: f.write('stop')
    def on_closing(self):
        self.stop_bot()
        self.destroy()

# -----------------------------------------------------------------------------------
# BOT-HILFSFUNKTIONEN
# -----------------------------------------------------------------------------------

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless"); chrome_options.add_argument("--window-size=1920,1080")
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    chrome_options.add_argument(f'user-agent={user_agent}'); chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"]); chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--log-level=3"); chrome_options.add_argument("--disable-gpu")
    service = ChromeService(executable_path=CHROMEDRIVER_PATH); driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"); return driver
    
def get_mission_requirements(driver, wait):
    """Liest die Rohdaten und ignoriert jetzt reine Wahrscheinlichkeits-Zeilen."""
    raw_requirements = {'fahrzeuge': [], 'personal': 0, 'wasser': 0, 'schaummittel': 0} # Wasser/Schaum hinzugefügt
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Hilfe')]"))).click()
        table_selector = "//table[.//th[contains(text(), 'Fahrzeuge') or contains(text(), 'Rettungsmittel')]]"
        vehicle_table = wait.until(EC.visibility_of_element_located((By.XPATH, table_selector)))
        rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2:
                requirement_text, count_text = cells[0].text.strip(), cells[1].text.strip().replace(" L", "")
                req_lower = requirement_text.lower()

                # NEU: Ignoriere reine Info-Zeilen über Wahrscheinlichkeit komplett
                if "anforderungswahrscheinlichkeit" in req_lower:
                    print(f"    -> Info: Ignoriere Wahrscheinlichkeits-Zusatzinfo: '{requirement_text}'")
                    continue

                # Bestehende Logik
                if "personal" in req_lower or "feuerwehrleute" in req_lower:
                    if count_text.isdigit(): raw_requirements['personal'] += int(count_text)
                elif "wasser" in req_lower or "wasserbedarf" in req_lower: # Erkennt jetzt auch "Wasserbedarf"
                    if count_text.isdigit(): raw_requirements['wasser'] += int(count_text)
                elif "schaummittel" in req_lower:
                    if count_text.isdigit(): raw_requirements['schaummittel'] += int(count_text)
                else:
                    if count_text.isdigit():
                        for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(requirement_text)
    except TimeoutException:
        print("Info: Keine Anforderungstabelle im Hilfe-Fenster gefunden.")
    finally:
        try: wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Zurück']"))).click()
        except: driver.refresh()
    return raw_requirements

def get_available_vehicles(driver, wait):
    """Findet Fahrzeuge und ordnet ihnen ihre Eigenschaften aus der zentralen Datenbank zu."""
    available_vehicles = []
    vehicle_table_selector = "#vehicle_show_table_all"
    try:
        vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
        vehicle_rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
        for row in vehicle_rows:
            try:
                checkbox = row.find_element(By.CSS_SELECTOR, "input.vehicle_checkbox")
                full_vehicle_name = row.get_attribute('vehicle_caption') or row.text.strip()
                vehicle_properties = None
                found_identifier = None
                for identifier, properties in VEHICLE_DATABASE.items():
                    if identifier in full_vehicle_name:
                        vehicle_properties = properties; found_identifier = identifier; break
                if not vehicle_properties:
                    standard_type_from_attr = row.get_attribute('vehicle_type')
                    if standard_type_from_attr in VEHICLE_DATABASE:
                        vehicle_properties = VEHICLE_DATABASE[standard_type_from_attr]; found_identifier = standard_type_from_attr
                if vehicle_properties:
                    available_vehicles.append({'properties': vehicle_properties, 'checkbox': checkbox, 'name': full_vehicle_name})
            except NoSuchElementException:
                continue
    except TimeoutException: print(f"FEHLER: Die Fahrzeug-Tabelle konnte nicht gefunden werden.")
    return available_vehicles

def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
    """
    Findet die beste Kombination und greift jetzt auf die korrekte 'properties'-Struktur zu.
    """
    # Wandle Patientenbedarf direkt in Fahrzeugbedarf um
    if requirements.get('patienten', 0) > 0:
        for _ in range(requirements['patienten']):
            requirements['fahrzeuge'].append("RTW")

    needed_vehicle_roles = Counter(requirements.get('fahrzeuge', []))
    needed_personal = requirements.get('personal', 0)
    needed_wasser = requirements.get('wasser', 0)
    needed_schaummittel = requirements.get('schaummittel', 0)
    needed_patienten = requirements.get('patienten', 0)
    
    vehicles_to_send = []; pool = list(available_vehicles)

    # 1. Decke den spezifischen Fahrzeug-Typ-Bedarf
    for needed_role, needed_count in needed_vehicle_roles.items():
        found_count = 0
        for vehicle in list(pool):
            if found_count >= needed_count: break
            
            # KORREKTUR: Greife direkt auf die 'properties' des Fahrzeugs zu.
            if needed_role in vehicle['properties'].get('typ', []):
                vehicles_to_send.append(vehicle); pool.remove(vehicle); found_count += 1
    
    # 2. Berechne, was die bisher ausgewählten Fahrzeuge mitbringen
    provided_personal = sum(v['properties'].get('personal', 0) for v in vehicles_to_send)
    provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    provided_patienten = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)
    
    # 3. Defizit-Auffüllung
    def fill_deficit(pool_ref, vehicles_to_send_ref, current_provided, needed, resource_key, resource_name):
        nonlocal provided_personal, provided_wasser, provided_schaummittel, provided_patienten
        if current_provided < needed:
            deficit = needed - current_provided
            print(f"Info: {deficit} {resource_name} wird noch benötigt.")
            # KORREKTUR: Greife auch hier auf 'properties' zu
            pool_ref.sort(key=lambda v: v['properties'].get(resource_key, 0), reverse=True)
            for vehicle in list(pool_ref):
                if current_provided >= needed: break
                props = vehicle['properties']
                resource_val = props.get(resource_key, 0)
                if resource_val > 0:
                    vehicles_to_send_ref.append(vehicle); pool_ref.remove(vehicle)
                    provided_personal += props.get('personal', 0)
                    provided_wasser += props.get('wasser', 0)
                    provided_schaummittel += props.get('schaummittel', 0)
                    provided_patienten += props.get('patienten_kapazitaet', 0)
                    current_provided += resource_val
        return current_provided

    provided_wasser = fill_deficit(pool, vehicles_to_send, provided_wasser, needed_wasser, 'wasser', 'Liter Wasser')
    provided_schaummittel = fill_deficit(pool, vehicles_to_send, provided_schaummittel, needed_schaummittel, 'schaummittel', 'Liter Schaummittel')
    provided_personal = fill_deficit(pool, vehicles_to_send, provided_personal, needed_personal, 'personal', 'Personal')

    # 4. Finale Prüfung
    final_vehicle_counts = Counter(role for v in vehicles_to_send for role in v['properties'].get('typ', []))
    all_vehicles_met = all(final_vehicle_counts.get(role, 0) >= count for role, count in needed_vehicle_roles.items())

    if all_vehicles_met and provided_personal >= needed_personal and provided_wasser >= needed_wasser and provided_schaummittel >= needed_schaummittel and provided_patienten >= needed_patienten:
        return [v['checkbox'] for v in vehicles_to_send]
    else:
        print("Keine passende Fahrzeugkombination gefunden.")
        # ... (Fehlerausgabe)
        return []

def check_and_claim_daily_bonus(driver, wait):
    """Prüft auf die tägliche Belohnung und sucht dabei optimiert direkt im iFrame."""
    print("Info: Prüfe auf tägliche Belohnung...")
    try:
        bonus_icon_selector = "//span[contains(@class, 'glyphicon-calendar') and contains(@class, 'bonus-active')]"
        bonus_icon = driver.find_element(By.XPATH, bonus_icon_selector)
        print("Info: Tägliche Belohnung verfügbar! Öffne Bonus-Seite...")
        bonus_icon.click()
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
        print("Info: Erfolgreich in den Bonus-iFrame gewechselt.")
        claim_button_selector = "div.collect-possible-block button.collect-button"
        claim_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, claim_button_selector)))
        bonus_text = claim_button.text.strip().replace("\n", " "); print(f"Info: Löse Belohnung ein: '{bonus_text}'"); claim_button.click()
        time.sleep(3); print("Info: Belohnung erfolgreich abgeholt!")
    except (NoSuchElementException, TimeoutException):
        print("Info: Keine neue tägliche Belohnung verfügbar oder bereits abgeholt.")
    except Exception as e:
        print(f"FEHLER beim Abholen der Belohnung: {e}")
    finally:
        try: driver.switch_to.default_content()
        except: pass

def check_and_claim_tasks(driver, wait):
    """Prüft auf erledigte Aufgaben und klickt nur die wirklich aktiven 'Abholen'-Buttons."""
    print("Info: Prüfe auf erledigte Aufgaben...")
    try:
        profile_dropdown = wait.until(EC.element_to_be_clickable((By.ID, "menu_profile"))); profile_dropdown.click()
        short_wait = WebDriverWait(driver, 3)
        task_counter_selector = "//span[@id='completed_tasks_counter' and not(contains(@class, 'hidden'))]"
        short_wait.until(EC.visibility_of_element_located((By.XPATH, task_counter_selector)))
        print("Info: Erledigte Aufgabe(n) gefunden! Öffne Aufgaben-Seite...")
        tasks_link = driver.find_element(By.XPATH, "//div[contains(@class, 'tasks_and_events_navbar')]"); tasks_link.click()
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
        print("Info: Erfolgreich in den Aufgaben-iFrame gewechselt.")
        claim_buttons_selector = "//input[@value='Abholen' and contains(@class, 'btn')]"
        all_claim_buttons = wait.until(EC.presence_of_all_elements_located((By.XPATH, claim_buttons_selector)))
        clicked_count = 0
        for button in all_claim_buttons:
            try:
                if button.is_enabled():
                    button.click(); clicked_count += 1; print("    -> Belohnung erfolgreich abgeholt."); time.sleep(1.5)
            except Exception as e_click:
                print(f"Warnung: Konnte einen Button nicht klicken: {e_click}")
        if clicked_count > 0: print(f"Info: {clicked_count} Belohnung(en) insgesamt abgeholt.")
    except TimeoutException:
        print("Info: Keine neuen, erledigten Aufgaben.")
        try: driver.find_element(By.TAG_NAME, 'body').click(); time.sleep(1)
        except: pass
    except Exception as e: print(f"FEHLER beim Prüfen der Aufgaben: {e}")
    finally:
        try: driver.switch_to.default_content()
        except: pass

# -----------------------------------------------------------------------------------
# HAUPT-THREAD FÜR DIE BOT-LOGIK
# -----------------------------------------------------------------------------------

def main_bot_logic(gui_vars):
    driver = None; stop_file_path = resource_path('stop.txt')
    if os.path.exists(stop_file_path): os.remove(stop_file_path)
    dispatched_mission_ids = set()
    last_check_date = None; bonus_checked_today = False
    try:
        gui_vars['status'].set("Initialisiere..."); driver = setup_driver(); wait = WebDriverWait(driver, 30)
        gui_vars['status'].set("Logge ein..."); driver.get("https://www.leitstellenspiel.de/users/sign_in")
        wait.until(EC.visibility_of_element_located((By.ID, "user_email"))).send_keys(LEITSTELLENSPIEL_USERNAME)
        driver.find_element(By.ID, "user_password").send_keys(LEITSTELLENSPIEL_PASSWORD)
        time.sleep(1); driver.find_element(By.NAME, "commit").click()
        try:
            gui_vars['status'].set("Warte auf Hauptseite..."); wait.until(EC.presence_of_element_located((By.ID, "missions_outer"))); gui_vars['status'].set("Login erfolgreich! Bot aktiv.")
        except TimeoutException: raise Exception("Login fehlgeschlagen. Hauptseite nicht erreicht.")
        while True:
            if os.path.exists(stop_file_path): gui_vars['status'].set("Stoppe..."); os.remove(stop_file_path); break
            
            # --- START DER HAUPTSCHLEIFE ---
            gui_vars['status'].set("Lade Hauptseite & prüfe Status...")
            driver.get("https://www.leitstellenspiel.de/")
            wait.until(EC.presence_of_element_located((By.ID, "missions_outer")))

            today = date.today();
            if last_check_date != today: bonus_checked_today = False; last_check_date = today
            if not bonus_checked_today:
                check_and_claim_daily_bonus(driver, wait); bonus_checked_today = True
            
            check_and_claim_tasks(driver, wait)
            
            try:
                gui_vars['status'].set("Prüfe Einsätze...")
                mission_list_container = driver.find_element(By.ID, "missions_outer")
                mission_entries = mission_list_container.find_elements(By.XPATH, ".//div[contains(@class, 'missionSideBarEntry')]")
                mission_data = []; current_mission_ids = set()
                for entry in mission_entries:
                    try:
                        mission_id = entry.get_attribute('mission_id'); url_element = entry.find_element(By.XPATH, ".//a[contains(@class, 'mission-alarm-button')]"); href = url_element.get_attribute('href')
                        name_element = entry.find_element(By.XPATH, ".//a[contains(@id, 'mission_caption_')]"); full_name = name_element.text.strip(); name = full_name.split(',')[0].strip()
                        patient_count = 0; sort_data_str = entry.get_attribute('data-sortable-by')
                        if sort_data_str: patient_count = json.loads(sort_data_str).get('patients_count', [0, 0])[0]
                        if href and name and mission_id:
                            mission_data.append({'id': mission_id, 'url': href, 'name': name, 'patienten': patient_count}); current_mission_ids.add(mission_id)
                    except (NoSuchElementException, json.JSONDecodeError): continue
                
                dispatched_mission_ids.intersection_update(current_mission_ids)
                if not mission_data:
                    gui_vars['status'].set(f"Keine Einsätze. Warte {30}s..."); time.sleep(30); continue
                
                gui_vars['status'].set(f"{len(mission_data)} Einsätze gefunden. Bearbeite...")
                for i, mission in enumerate(mission_data):
                    if os.path.exists(stop_file_path): break
                    if "[Verband]" in mission['name'] or mission['id'] in dispatched_mission_ids: continue
                    gui_vars['mission_name'].set(f"({i+1}/{len(mission_data)}) {mission['name']}"); gui_vars['alarm_status'].set("Status: Prüfe Bedarf...")
                    driver.get(mission['url'])
                    
                    raw_requirements = get_mission_requirements(driver, wait)
                    if not raw_requirements: continue
                    
                    # Logik zur Aufbereitung der Anforderungen
                    final_requirements = {'fahrzeuge': [], 'personal': raw_requirements['personal'], 'patienten': mission['patienten']}
                    translation_map = {"Rettungswagen": "RTW", "Löschfahrzeuge": "Löschfahrzeug", "Drehleitern": "Drehleiter"}
                    for req_text in raw_requirements['fahrzeuge']:
                        clean_text = req_text.replace("Benötigte ", "").strip(); translated = False
                        for key, value in translation_map.items():
                            if key in clean_text: final_requirements['fahrzeuge'].append(value); translated = True; break
                        if not translated: final_requirements['fahrzeuge'].append(clean_text)
                    if final_requirements['patienten'] > 0:
                        for _ in range(final_requirements['patienten']): final_requirements['fahrzeuge'].append("RTW")
                    
                    # Anzeige des Bedarfs
                    req_parts = []; vehicle_counts = Counter(final_requirements['fahrzeuge'])
                    for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")
                    if final_requirements['personal'] > 0: req_parts.append(f"{final_requirements['personal']} Personal")
                    gui_vars['requirements'].set("Bedarf: " + (", ".join(req_parts) if req_parts else "-"))

                    available_vehicles = get_available_vehicles(driver, wait)
                    
                    # --- HIER WAR DER FEHLER - JETZT KORRIGIERT ---
                    if available_vehicles:
                        generic_types_available = []
                        for vehicle in available_vehicles:
                            # Greife direkt auf die Rollen ('typ'-Liste) innerhalb von 'properties' zu
                            if 'properties' in vehicle and 'typ' in vehicle['properties']:
                                generic_types_available.extend(vehicle['properties']['typ'])
                        
                        available_counts = Counter(generic_types_available)
                        avail_parts = [f"{count}x {v_type}" for v_type, count in available_counts.items()]
                        gui_vars['availability'].set("Verfügbar (Typen): " + (", ".join(avail_parts)))
                    else:
                        gui_vars['availability'].set("Verfügbar: Keine"); gui_vars['status'].set(f"Keine Fahrzeuge frei. Pausiere..."); time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS); break
                    
                    checkboxes_to_click = find_best_vehicle_combination(final_requirements, available_vehicles, VEHICLE_DATABASE)
                    
                    if checkboxes_to_click:
                        dispatched_mission_ids.add(mission['id'])
                        gui_vars['status'].set("✓ Alarmiere..."); gui_vars['alarm_status'].set(f"Status: ALARMIERT ({len(checkboxes_to_click)} FZ)")
                        for checkbox in checkboxes_to_click: checkbox.click()
                        try: driver.find_element(By.XPATH, "//input[@value='Alarmieren und zum nächsten Einsatz']").click()
                        except NoSuchElementException: driver.find_element(By.XPATH, "//input[@value='Alarmieren']").click()
                    else:
                        gui_vars['status'].set("❌ Nicht genug Einheiten frei."); gui_vars['alarm_status'].set("Status: WARTE AUF EINHEITEN")
                    time.sleep(3)
            except Exception: raise
    except Exception as e:
        error_details = traceback.format_exc(); gui_vars['status'].set("FATALER FEHLER! Details in error_log.txt"); gui_vars['mission_name'].set("Bot angehalten.")
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
    app = StatusWindow()
    gui_variables = { "status": app.status_var, "mission_name": app.mission_name_var, "requirements": app.requirements_var, "availability": app.availability_var, "alarm_status": app.alarm_status_var }
    bot_thread = threading.Thread(target=main_bot_logic, args=(gui_variables,), daemon=True)
    bot_thread.start()
    app.mainloop()