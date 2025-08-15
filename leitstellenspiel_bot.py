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
BOT_VERSION = "V6.1 - Final Logic"
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
        self.geometry("450x300"); self.minsize(450, 300)
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
        ttk.Label(self, textvariable=self.availability_var).pack(anchor="w", padx=20)
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
    """Liest Rohdaten inkl. Credits aus dem Hilfe-Fenster mit dem korrekten Selektor."""
    raw_requirements = {'fahrzeuge': [], 'personal': 0, 'wasser': 0, 'schaummittel': 0, 'credits': 0}
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Hilfe')]"))).click()
        
        try:
            table_selector = "//table[.//th[contains(text(), 'Fahrzeuge') or contains(text(), 'Rettungsmittel')]]"
            vehicle_table = wait.until(EC.visibility_of_element_located((By.XPATH, table_selector)))
            rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 2:
                    requirement_text, count_text = cells[0].text.strip(), cells[1].text.strip().replace(" L", "")
                    req_lower = requirement_text.lower()
                    if "anforderungswahrscheinlichkeit" in req_lower:
                        # Extrahiere den Fahrzeugtyp aus dem Text
                        vehicle_type_needed = requirement_text.split("Anforderungswahrscheinlichkeit")[0].strip()
                        
                        # NEU: Prüfe gegen das Inventar
                        if vehicle_type_needed in player_inventory:
                            raw_requirements['fahrzeuge'].append([vehicle_type_needed])
                            print(f"    -> Info: Wahrscheinlichkeits-Anforderung '{vehicle_type_needed}' als 1x Bedarf gewertet (Fahrzeug vorhanden).")
                        else:
                            print(f"    -> Info: Ignoriere Wahrscheinlichkeits-Anforderung '{vehicle_type_needed}' (Fahrzeug nicht im Bestand).")
                        continue
                        
                    if "schlauchwagen" in req_lower:
                        if count_text.isdigit():
                            for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Schlauchwagen"])
                    elif "schaummittel" in req_lower or "sonderlöschmittelbedarf" in req_lower:
                        if count_text.isdigit(): raw_requirements['schaummittel'] += int(count_text)
                    elif "feuerlöschpumpe" in req_lower:
                        if count_text.isdigit():
                            for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(["Löschfahrzeug", "Tanklöschfahrzeug"])
                    elif "personal" in req_lower or "feuerwehrleute" in req_lower:
                        if count_text.isdigit(): raw_requirements['personal'] += int(count_text)
                    elif "wasser" in req_lower or "wasserbedarf" in req_lower:
                        if count_text.isdigit(): raw_requirements['wasser'] += int(count_text)
                    else:
                        if count_text.isdigit():
                            clean_text = requirement_text.replace("Benötigte ", "").strip()
                            if " oder " in clean_text:
                                options = [opt.strip() for opt in clean_text.split(" oder ")]
                                for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append(options)
                            else:
                                for _ in range(int(count_text)): raw_requirements['fahrzeuge'].append([clean_text])
        except TimeoutException:
            print("Info: Keine Fahrzeug-Anforderungstabelle gefunden.")

        try:
            credits_selector = "//td[normalize-space()='Credits im Durchschnitt']/following-sibling::td"
            credits_element = driver.find_element(By.XPATH, credits_selector)
            credits_text = credits_element.text.strip().replace(".", "").replace(",", "")
            if credits_text.isdigit():
                raw_requirements['credits'] = int(credits_text)
                print(f"Info: Durchschnittlicher Verdienst: {raw_requirements['credits']} Credits.")
        except NoSuchElementException:
            print("Info: Konnte den durchschnittlichen Verdienst nicht finden.")

    except TimeoutException:
        print("FEHLER: Hilfe-Button nicht gefunden.")
        return None
    finally:
        try: wait.until(EC.element_to_be_clickable((By.XPATH, "//a[text()='Zurück']"))).click()
        except: driver.refresh()
            
    return raw_requirements

def get_available_vehicles(driver, wait):
    """
    Findet Fahrzeuge, klickt aber zuerst auf den "Fehlende Fahrzeuge laden"-Button,
    falls dieser vorhanden ist, um die vollständige Liste zu erhalten.
    """
    available_vehicles = []
    vehicle_table_selector = "#vehicle_show_table_all"
    
    try:
        # --- NEUE LOGIK: "MEHR LADEN"-BUTTON SUCHEN UND KLICKEN ---
        try:
            # Suche gezielt nach dem Button, den du gefunden hast
            load_more_button_selector = "//a[contains(@class, 'missing_vehicles_load')]"
            load_more_button = driver.find_element(By.XPATH, load_more_button_selector)
            
            print("Info: 'Fehlende Fahrzeuge laden'-Button gefunden. Klicke ihn per JavaScript...")
            # KORREKTUR: Ersetze den normalen Klick durch den JavaScript-Klick
            driver.execute_script("arguments[0].click();", load_more_button)
            
            # Gib der Seite einen Moment Zeit, die neuen Fahrzeuge nachzuladen
            time.sleep(2)
            
        except NoSuchElementException:
            # Das ist der Normalfall, wenn alle Fahrzeuge bereits angezeigt werden.
            print("Info: Alle Fahrzeuge werden bereits angezeigt.")

        # --- Die bestehende Logik läuft jetzt mit der vollständigen Liste ---
        vehicle_table = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, vehicle_table_selector)))
        vehicle_rows = vehicle_table.find_elements(By.XPATH, ".//tbody/tr")
        
        # ... (Der Rest der Funktion zum Auslesen der Fahrzeuge bleibt unverändert) ...
        for row in vehicle_rows:
            try:
                checkbox = row.find_element(By.CSS_SELECTOR, "input.vehicle_checkbox")
                full_vehicle_name = row.get_attribute('vehicle_caption') or row.text.strip()
                vehicle_properties = None
                found_identifier = None
                for identifier, properties in VEHICLE_DATABASE.items():
                    if identifier.startswith("/") and identifier in full_vehicle_name:
                        vehicle_properties = properties; found_identifier = identifier; break
                if not vehicle_properties:
                    standard_type_from_attr = row.get_attribute('vehicle_type')
                    if standard_type_from_attr in VEHICLE_DATABASE:
                        vehicle_properties = VEHICLE_DATABASE[standard_type_from_attr]; found_identifier = standard_type_from_attr
                if vehicle_properties:
                    available_vehicles.append({'properties': vehicle_properties, 'checkbox': checkbox, 'name': full_vehicle_name})
            except NoSuchElementException:
                continue
    except TimeoutException:
        print(f"FEHLER: Die Fahrzeug-Tabelle konnte nicht gefunden werden.")
    
    return available_vehicles

def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
    """
    Findet die beste Kombination und gibt bei einem Fehlschlag eine
    detaillierte Liste der fehlenden Fahrzeugtypen aus.
    """
    if requirements.get('patienten', 0) > 0:
        for _ in range(requirements['patienten']):
            requirements['fahrzeuge'].append(["RTW"])

    needed_vehicle_options_list = requirements.get('fahrzeuge', [])
    needed_personal = requirements.get('personal', 0)
    needed_wasser = requirements.get('wasser', 0)
    needed_schaummittel = requirements.get('schaummittel', 0)
    needed_patienten = requirements.get('patienten', 0)
    
    # Zähle, wie oft jeder Typ ODER jede "Oder"-Gruppe benötigt wird
    needed_vehicle_roles = Counter(" oder ".join(options) for options in needed_vehicle_options_list)
    
    vehicles_to_send = []
    pool = list(available_vehicles)

    # 1. Decke den spezifischen Fahrzeug-Typ-Bedarf
    for needed_options in needed_vehicle_options_list:
        found_match = False
        for needed_type in needed_options:
            for vehicle in list(pool):
                if needed_type in vehicle['properties'].get('typ', []):
                    vehicles_to_send.append(vehicle); pool.remove(vehicle); found_match = True; break
            if found_match: break
    
    # 2. Ressourcen berechnen und Defizite auffüllen
    provided_personal = sum(v['properties'].get('personal', 0) for v in vehicles_to_send)
    provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    provided_patienten = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)
    
    def fill_deficit(resource_key, current_provided, needed, resource_name):
        nonlocal pool, vehicles_to_send, provided_personal, provided_wasser, provided_schaummittel, provided_patienten
        if current_provided < needed:
            deficit = needed - current_provided
            print(f"Info: {deficit} {resource_name} wird noch benötigt.")
            pool.sort(key=lambda v: v['properties'].get(resource_key, 0), reverse=True)
            for vehicle in list(pool):
                if current_provided >= needed: break
                props = vehicle['properties']
                resource_val = props.get(resource_key, 0)
                if resource_val > 0:
                    vehicles_to_send.append(vehicle); pool.remove(vehicle)
                    provided_personal += props.get('personal', 0); provided_wasser += props.get('wasser', 0)
                    provided_schaummittel += props.get('schaummittel', 0); provided_patienten += props.get('patienten_kapazitaet', 0)
                    current_provided += resource_val
        return current_provided

    provided_wasser = fill_deficit('wasser', provided_wasser, needed_wasser, 'Liter Wasser')
    provided_schaummittel = fill_deficit('schaummittel', provided_schaummittel, needed_schaummittel, 'Liter Schaummittel')
    provided_personal = fill_deficit('personal', provided_personal, needed_personal, 'Personal')
    provided_patienten = fill_deficit('patienten_kapazitaet', provided_patienten, needed_patienten, 'Patienten-Transportplätze')

    # 4. Finale Prüfung
    final_vehicle_counts = Counter(role for v in vehicles_to_send for role in v['properties'].get('typ', []))
    all_vehicles_met = True
    temp_final_counts = final_vehicle_counts.copy()
    for needed_options in needed_vehicle_options_list:
        requirement_fulfilled = False
        for option in needed_options:
            if temp_final_counts.get(option, 0) > 0:
                temp_final_counts[option] -= 1; requirement_fulfilled = True; break
        if not requirement_fulfilled:
            all_vehicles_met = False; break
    
    if all_vehicles_met and provided_personal >= needed_personal and provided_wasser >= needed_wasser and provided_schaummittel >= needed_schaummittel and provided_patienten >= needed_patienten:
        print(f"Erfolgreiche Zuteilung gefunden! Sende {len(vehicles_to_send)} Fahrzeuge.")
        return [v['checkbox'] for v in vehicles_to_send]
    else:
        print("Keine passende Fahrzeugkombination gefunden.")
        
        # --- NEU: Detaillierte Fehlbedarfsliste für Fahrzeugtypen ---
        if not all_vehicles_met:
            print("-> Es fehlen benötigte Fahrzeugtypen:")
            # Zähle, was benötigt wird
            needed_counts = Counter(" oder ".join(options) for options in needed_vehicle_options_list)
            # Zähle, was am Ende in der Sendeliste gelandet ist
            sent_options = []
            for v in vehicles_to_send:
                # Finde heraus, welche Anforderung dieses Fahrzeug erfüllt hat
                for needed_options in needed_vehicle_options_list:
                    if any(role in v['properties'].get('typ', []) for role in needed_options):
                        sent_options.append(" oder ".join(needed_options))
                        break
            sent_counts = Counter(sent_options)
            
            # Vergleiche "Benötigt" mit "Gesendet"
            for needed_str, needed_num in needed_counts.items():
                sent_num = sent_counts.get(needed_str, 0)
                if sent_num < needed_num:
                    print(f"    - {needed_num - sent_num}x {needed_str}")
        
        if provided_personal < needed_personal: print(f"-> Es fehlen {needed_personal - provided_personal} Personal.")
        if provided_wasser < needed_wasser: print(f"-> Es fehlen {needed_wasser - provided_wasser} L Wasser.")
        if provided_schaummittel < needed_schaummittel: print(f"-> Es fehlen {needed_schaummittel - provided_schaummittel} L Schaummittel.")
        if provided_patienten < needed_patienten: print(f"-> Es fehlen {needed_patienten - provided_patienten} Patienten-Transportplätze.")
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

def get_player_vehicle_inventory(driver, wait):
    """
    Liest den Fuhrpark aus der korrekten Tabellenstruktur der /vehicles-Seite aus.
    """
    print("Info: Lese den kompletten Fuhrpark (Inventar) ein...")
    inventory = set()
    try:
        driver.get("https://www.leitstellenspiel.de/vehicles")
        
        # Der iFrame-Befehl ist hier nicht nötig, da es eine normale Tabelle ist.
        # Wir suchen nach allen Tabellenzeilen (tr) im Tabellenkörper (tbody).
        vehicle_rows_selector = "//tbody/tr"
        
        # Warte, bis die Zeilen geladen sind
        vehicle_rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, vehicle_rows_selector)))
        
        print(f"Info: {len(vehicle_rows)} Fahrzeuge im Fuhrpark gefunden. Analysiere Typen...")

        for row in vehicle_rows:
            try:
                # Finde den Link in der zweiten Spalte (td[2]), der den Namen enthält
                link_element = row.find_element(By.XPATH, "./td[2]/a")
                link_text = link_element.text.strip()
                if not link_text: continue

                # Extrahiere den reinen Fahrzeugtyp (z.B. "HLF 20", "RTW")
                vehicle_type = link_text.split('(')[0].strip()
                
                # Füge nur Typen hinzu, die in unserer Datenbank bekannt sind
                if vehicle_type in VEHICLE_DATABASE:
                    inventory.add(vehicle_type)
            except (NoSuchElementException, IndexError):
                # Ignoriere Zeilen, die nicht dem erwarteten Muster entsprechen
                continue
        
        print(f"Info: Inventar mit {len(inventory)} einzigartigen Fahrzeugtypen erfolgreich erstellt.")
        
    except Exception as e:
        print(f"FEHLER: Konnte den Fuhrpark nicht einlesen: {e}")
        traceback.print_exc()
            
    return inventory

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
        time.sleep(1)
        try:
            login_button = wait.until(EC.element_to_be_clickable((By.NAME, "commit"))); login_button.click()
        except ElementClickInterceptedException:
            login_button = wait.until(EC.presence_of_element_located((By.NAME, "commit"))); driver.execute_script("arguments[0].click();", login_button)
        try:
            gui_vars['status'].set("Warte auf Hauptseite..."); wait.until(EC.presence_of_element_located((By.ID, "missions_outer"))); gui_vars['status'].set("Login erfolgreich! Bot aktiv.")
            send_discord_notification(f"Bot erfolgreich gestartet auf Account: **{LEITSTELLENSPIEL_USERNAME}**")
            player_inventory = get_player_vehicle_inventory(driver, wait)
        except TimeoutException: raise Exception("Login fehlgeschlagen.")
        
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
                        patient_count = 0; timeleft = 0; credits = 0
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

                    # --- KORRIGIERTE LOGIK ZUR ANFORDERUNGS-AUFBEREITUNG ---
                    # Übersetze die Roh-Fahrzeugtexte in Standard-Rollen
                    translation_map = {"Rettungswagen": "RTW", "Löschfahrzeuge": "Löschfahrzeug", "Drehleitern": "Drehleiter"}
                    final_fahrzeuge_list = []
                    for req_options in raw_requirements['fahrzeuge']:
                        processed_options = []
                        for req_text in req_options:
                            clean_text = req_text.replace("Benötigte ", "").strip(); translated = False
                            for key, value in translation_map.items():
                                if key in clean_text: processed_options.append(value); translated = True; break
                            if not translated: processed_options.append(clean_text)
                        final_fahrzeuge_list.append(processed_options)

                    # Kombiniere Bedarfe intelligent (verhindert Doppel-Zählung)
                    explicit_rtw_count = sum(1 for options in final_fahrzeuge_list if "RTW" in options)
                    patient_bedarf = mission['patienten']
                    final_rtw_bedarf = max(explicit_rtw_count, patient_bedarf)
                    
                    # Erstelle die finale Anforderungsliste
                    final_requirements = {'personal': raw_requirements['personal'], 'wasser': raw_requirements['wasser'], 'schaummittel': raw_requirements['schaummittel'], 'patienten': patient_bedarf}
                    final_requirements['fahrzeuge'] = [options for options in final_fahrzeuge_list if "RTW" not in options]
                    for _ in range(final_rtw_bedarf):
                        final_requirements['fahrzeuge'].append(["RTW"])
                    
                    # GUI-Anzeige
                    req_parts = []; readable_requirements = [" oder ".join(options) for options in final_requirements['fahrzeuge']]
                    vehicle_counts = Counter(readable_requirements)
                    for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")
                    if final_requirements['personal'] > 0: req_parts.append(f"{final_requirements['personal']} Personal")
                    gui_vars['requirements'].set("Bedarf: " + (", ".join(req_parts) if req_parts else "-"))

                    available_vehicles = get_available_vehicles(driver, wait)
                    if available_vehicles:
                        generic_types_available = []
                        for vehicle in available_vehicles:
                            if 'properties' in vehicle and 'typ' in vehicle['properties']:
                                generic_types_available.extend(vehicle['properties']['typ'])
                        available_counts = Counter(generic_types_available); avail_parts = [f"{count}x {v_type}" for v_type, count in available_counts.items()]
                        gui_vars['availability'].set("Verfügbar (Typen): " + (", ".join(avail_parts)))
                    else:
                        gui_vars['availability'].set("Verfügbar: Keine"); gui_vars['status'].set(f"Keine Fahrzeuge frei. Pausiere..."); time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS); break
                    
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