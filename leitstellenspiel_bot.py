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

# Importiere Playwright-spezifische Module
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

# -----------------------------------------------------------------------------------
# HELPER-FUNKTIONEN UND KONFIGURATION (UNVERÄNDERT)
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
BOT_VERSION = "V1.0.5 - Playwright Build"
PAUSE_IF_NO_VEHICLES_SECONDS = 300
MAX_START_DELAY_SECONDS = 3600
MINIMUM_CREDITS = 10000

ADDED_TO_DATABASE = []


# -----------------------------------------------------------------------------------
# DIE KLASSE FÜR DAS STATUS-FENSTER (UNVERÄNDERT)
# -----------------------------------------------------------------------------------
class StatusWindow(tk.Tk):
    def __init__(self, pause_event, stop_event, gui_queue):
        super().__init__()
        self.gui_queue = gui_queue
        self.pause_event = pause_event
        self.stop_event = stop_event
        self.title(f"LSS Bot {BOT_VERSION} | User: {LEITSTELLENSPIEL_USERNAME}")
        self.geometry("450x350"); self.minsize(450, 350)
        self.configure(bg="#2E2E2E")
        style = ttk.Style(self); style.theme_use('clam')
        style.configure("TLabel", background="#2E2E2E", foreground="#FFFFFF", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TFrame", background="#2E2E2E")
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
        ttk.Label(self, textvariable=self.availability_var, justify=tk.LEFT).pack(anchor="w", padx=20)
        ttk.Label(self, text="Alarmierungsstatus:", style="Header.TLabel").pack(pady=(10, 0), anchor="w", padx=10)
        ttk.Label(self, textvariable=self.alarm_status_var).pack(anchor="w", padx=20)
        button_frame = ttk.Frame(self, style="TFrame")
        button_frame.pack(side="bottom", pady=10, fill="x", padx=10)
        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause)
        self.pause_button.pack(side="left", expand=True, padx=5)
        stop_button = ttk.Button(button_frame, text="Bot Stoppen & Schließen", command=self.stop_bot)
        stop_button.pack(side="right", expand=True, padx=5)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.process_queue()

    def process_queue(self):
        try:
            message = self.gui_queue.get_nowait()
            key, value = message
            if key == 'batch_update':
                for update_key, update_value in value.items():
                    if update_key == 'status': self.status_var.set(update_value)
                    elif update_key == 'mission_name': self.mission_name_var.set(update_value)
                    elif update_key == 'alarm_status': self.alarm_status_var.set(update_value)
                    elif update_key == 'requirements': self.requirements_var.set(update_value)
                    elif update_key == 'availability': self.availability_var.set(update_value)
            else:
                if key == 'status': self.status_var.set(value)
                elif key == 'mission_name': self.mission_name_var.set(value)
                elif key == 'requirements': self.requirements_var.set(value)
                elif key == 'availability': self.availability_var.set(value)
                elif key == 'alarm_status': self.alarm_status_var.set(value)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.config(text="Continue")
            self.status_var.set("Bot pausiert.")
        else:
            self.pause_event.set()
            self.pause_button.config(text="Pause")
            self.status_var.set("Bot wird fortgesetzt...")

    def stop_bot(self):
        print("Info: Stop-Signal gesetzt. Beende den Bot-Thread...")
        self.status_var.set("Beende Bot...")
        self.stop_event.set()
        self.after(500, self.destroy)

    def on_closing(self):
        self.stop_bot()

# -----------------------------------------------------------------------------------
# PLAYWRIGHT-SPEZIFISCHE BOT-HILFSFUNKTIONEN
# -----------------------------------------------------------------------------------

def get_mission_requirements(page, player_inventory, given_patients, mission_name, mission_cache):
    """
    Ermittelt die Einsatzanforderungen mit Playwright und nutzt einen Cache.
    """
    translation_map = {
        "Feuerwehrkräne (FwK)": "FwK", "Drehleitern": "Drehleiter", "Rettungswagen": "RTW",
        "Löschfahrzeuge": "Löschfahrzeug", "Gerätewagen Öl": "GW-Öl", "Seenotrettungsboote": "Seenotrettungsboot",
        "Funkstreifenwagen (Dienstgruppenleitung)": "FuStW (DGL)"
    }
    raw_requirements = {
        'fahrzeuge': [], 'fahrzeuge_optional': [], 'patienten': 0, 'credits': 0,
        'wasser': 0, 'schaummittel': 0, 'personal_fw': 0, 'personal_thw': 0,
        'personal_rd': 0, 'personal_pol': 0, 'betreuung_ratio': 0
    }
    
    # Playwright: Finde den iFrame und arbeite innerhalb seines Kontexts
    iframe_locator = page.frame_locator("iframe.lightbox_iframe, iframe:visible")

    try:
        # Playwright: Klicke den Hilfe-Button im iFrame. auto-wait ist inklusive.
        iframe_locator.locator("#mission_help").click(timeout=15000)

        # Caching-Logik
        credits_text = iframe_locator.locator("xpath=//td[normalize-space()='Credits im Durchschnitt']/following-sibling::td").text_content(timeout=5000).strip().replace(".", "").replace(",", "")
        credits = int(credits_text) if credits_text.isdigit() else 0
        
        min_patients_text = iframe_locator.locator("xpath=//td[normalize-space()='Mindest Patientenanzahl']/following-sibling::td").text_content(timeout=5000).strip()
        min_patients = int(min_patients_text) if min_patients_text.isdigit() else 0
        
        max_patients_text = iframe_locator.locator("xpath=//td[normalize-space()='Maximale Patientenanzahl']/following-sibling::td").text_content(timeout=5000).strip()
        max_patients = int(max_patients_text) if max_patients_text.isdigit() else 0

        cache_key = f"{mission_name}_{credits}_{min_patients}_{max_patients}"
        if cache_key in mission_cache:
            print(f"Info: Anforderungen für '{cache_key}' aus dem Cache geladen.")
            cached_reqs = mission_cache[cache_key].copy()
            cached_reqs['patienten'] = given_patients if given_patients > 0 else min_patients
            return cached_reqs
        
        print(f"Info: Einsatz '{cache_key}' nicht im Cache. Lese Anforderungen neu ein.")

        # Fahrzeuganforderungen auslesen
        vehicle_table = iframe_locator.locator("xpath=//table[.//th[contains(text(), 'Fahrzeuge')]]")
        # Playwright: .all() statt .find_elements()
        rows = vehicle_table.locator("tbody tr").all()

        def normalize_name(name):
            clean = name.replace("Benötigte ", "")
            return translation_map.get(clean, clean)

        def player_has_vehicle_of_type(required_type, inventory, database):
            for owned_vehicle_name in inventory:
                if owned_vehicle_name in database and required_type in database[owned_vehicle_name].get("typ", []): return True
            return False

        ignored_optional_types = set()
        for row in rows:
            cells = row.locator('td').all()
            if len(cells) < 2: continue
            requirement_text = cells[0].text_content().strip()
            is_optional = "anforderungswahrscheinlichkeit" in requirement_text.lower() or "nur angefordert, wenn vorhanden" in requirement_text.lower()
            if is_optional:
                clean_name = requirement_text.replace("nur angefordert, wenn vorhanden", "").replace("Anforderungswahrscheinlichkeit", "").replace("Benötigte", "").strip()
                normalized_name = normalize_name(clean_name)
                if not player_has_vehicle_of_type(normalized_name, player_inventory, VEHICLE_DATABASE):
                    print(f"       -> Info: Anforderung '{normalized_name}' wird für diesen Einsatz ignoriert (nicht im Inventar).")
                    ignored_optional_types.add(normalized_name)
        
        for row in rows:
            cells = row.locator('td').all()
            if len(cells) < 2: continue
            requirement_text, count_text = cells[0].text_content().strip(), cells[1].text_content().strip().replace(" L", "")
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
            if 'polizisten' in req_lower: raw_requirements['personal_pol'] += count; continue
            elif 'personalanzahl (thw)' in req_lower: raw_requirements['personal_thw'] += count; continue
            elif 'rettungsdienst' in req_lower: raw_requirements['personal_rd'] += count; continue
            elif 'feuerwehrleute' in req_lower: raw_requirements['personal_fw'] += count; continue
            if 'betreuungs- und verpflegungsausstattung' in req_lower:
                ratio_match = re.search(r'pro (\d+)', count_text)
                if ratio_match:
                    ratio = int(ratio_match.group(1))
                    raw_requirements['betreuung_ratio'] = ratio
                    print(f"       -> Info: Betreuung benötigt (1 pro {ratio} Personen).")
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

        def process_probability_requirement(vehicle_name, probability_text_identifier):
            try:
                prob_text_cell = iframe_locator.locator(f"xpath=//td[contains(text(), '{probability_text_identifier}')]")
                prob_value_cell = prob_text_cell.locator("./following-sibling::td")
                match = re.search(r'(\d+)', prob_value_cell.text_content())
                if not match: return
                probability = int(match.group(1))
                if player_has_vehicle_of_type(vehicle_name, player_inventory, VEHICLE_DATABASE):
                    if probability > 80: raw_requirements['fahrzeuge'].append([vehicle_name])
                    else: raw_requirements['fahrzeuge_optional'].append([vehicle_name])
            except PlaywrightTimeoutError: pass
        
        process_probability_requirement("NEF", "NEF Anforderungswahrscheinlichkeit")
        process_probability_requirement("RTH", "RTH Anforderungswahrscheinlichkeit")

        raw_requirements['credits'] = credits
        raw_requirements['patienten'] = given_patients if given_patients > 0 else min_patients
        
        final_reqs_for_cache = raw_requirements.copy()
        final_reqs_for_cache['patienten'] = min_patients
        mission_cache[cache_key] = final_reqs_for_cache
        print(f"       -> Anforderungen für '{cache_key}' zum Cache hinzugefügt.")
        
        return raw_requirements

    except PlaywrightTimeoutError:
        print(f"FEHLER: Der 'Hilfe'-Button oder eine Anforderungstabelle konnte im iFrame nicht gefunden werden.")
        return None
    finally:
        # Playwright: Kein switch_to.default_content() nötig. Klicke einfach den Schließen-Button auf der Hauptseite.
        # Ein try-except Block stellt sicher, dass es weitergeht, auch wenn der Button nicht da ist.
        try:
            page.locator("a.close, a:text('Zurück'), a:text('Schließen')").first.click(timeout=5000)
        except PlaywrightTimeoutError:
            page.reload() # Fallback

def get_available_vehicles(page):
    """
    Findet verfügbare Fahrzeuge mit Playwright und speichert den 'vehicle_type'.
    """
    available_vehicles = []
    try:
        load_more_button = page.locator("a.missing_vehicles_load")
        if load_more_button.is_visible():
            print("Info: 'Fehlende Fahrzeuge laden'-Button gefunden. Klicke ihn...")
            vehicle_table = page.locator("#vehicle_show_table_all")
            initial_rows = vehicle_table.locator("tbody tr").count()
            load_more_button.click()
            # Playwright: Warte, bis die Anzahl der Zeilen größer ist
            page.wait_for_function(f"() => document.querySelectorAll('#vehicle_show_table_all tbody tr').length > {initial_rows}", timeout=10000)
            print("Info: Zusätzliche Fahrzeuge wurden geladen.")
        else:
            print("Info: Alle Fahrzeuge werden bereits angezeigt.")

        vehicle_table = page.locator("#vehicle_show_table_all")
        # Playwright: .all() um über alle Elemente zu iterieren
        vehicle_rows = vehicle_table.locator("tbody tr").all()
        
        for row in vehicle_rows:
            # Playwright: try-except für den Fall, dass eine Zeile keine Checkbox hat
            try:
                checkbox = row.locator("input.vehicle_checkbox")
                # Prüfe, ob die Checkbox existiert (count > 0)
                if checkbox.count() > 0:
                    vehicle_type = row.get_attribute('vehicle_type')
                    if vehicle_type and vehicle_type in VEHICLE_DATABASE:
                        full_vehicle_name = row.get_attribute('vehicle_caption') or "Unbekannter Name"
                        vehicle_properties = VEHICLE_DATABASE[vehicle_type]
                        available_vehicles.append({
                            'properties': vehicle_properties,
                            'checkbox': checkbox, # Hier wird der Playwright Locator gespeichert
                            'name': full_vehicle_name,
                            'vehicle_type': vehicle_type
                        })
            except PlaywrightError:
                continue
    except PlaywrightTimeoutError:
        print(f"FEHLER: Die Fahrzeug-Tabelle konnte nicht gefunden werden.")
    
    return available_vehicles


# DIESE FUNKTION IST REINES PYTHON UND BLEIBT UNVERÄNDERT
def find_best_vehicle_combination(requirements, available_vehicles, vehicle_data):
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
    # 2. Fahrzeugauswahl
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
    # 3. Ressourcen-Defizite auffüllen
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
            print(f"Info: Dynamischer Bedarf von {deficit}x Betreuungsausstattung berechnet.")
            betreuungs_fahrzeuge = [v for v in pool if "Betreuungsausstattung" in v['properties'].get('typ', [])]
            betreuungs_personal_fahrzeuge = [v for v in pool if "Betreuungsausstattung_Personal" in v['properties'].get('typ', [])]
            for _ in range(deficit):
                if not betreuungs_fahrzeuge: print("Warnung: Nicht genügend Betreuungsfahrzeuge verfügbar."); break
                if not betreuungs_personal_fahrzeuge: print("Warnung: Nicht genügend Betreuungsfahrzeuge verfügbar."); break
                vehicle_to_add = betreuungs_fahrzeuge.pop(0)
                vehicle_to_add_2 = betreuungs_personal_fahrzeuge.pop(0)
                vehicles_to_send.append(vehicle_to_add)
                vehicles_to_send.append(vehicle_to_add_2)
                pool.remove(vehicle_to_add)
                pool.remove(vehicle_to_add_2)
    
    # 4. Finale Prüfung
    final_provided_fw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'FW')
    final_provided_thw = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'THW')
    final_provided_rd = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'RD')
    final_provided_pol = sum(v['properties'].get('personal', 0) for v in vehicles_to_send if v['properties'].get('fraktion') == 'POL')
    final_provided_wasser = sum(v['properties'].get('wasser', 0) for v in vehicles_to_send)
    final_provided_schaummittel = sum(v['properties'].get('schaummittel', 0) for v in vehicles_to_send)
    final_provided_patienten_kapazitaet = sum(v['properties'].get('patienten_kapazitaet', 0) for v in vehicles_to_send)
    all_reqs_met = (
        not unfulfilled_slots and final_provided_fw >= needed_fw and final_provided_thw >= needed_thw and
        final_provided_rd >= needed_rd and final_provided_pol >= needed_pol and
        final_provided_wasser >= needed_wasser and final_provided_schaummittel >= needed_schaummittel and
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
                print(f"       - {count}x {' oder '.join(slot_tuple)}")
        if final_provided_fw < needed_fw: print(f"-> Es fehlen {needed_fw - final_provided_fw} Personal (FW).")
        if final_provided_thw < needed_thw: print(f"-> Es fehlen {needed_thw - final_provided_thw} Personal (THW).")
        if final_provided_rd < needed_rd: print(f"-> Es fehlen {needed_rd - final_provided_rd} Personal (RD).")
        if final_provided_pol < needed_pol: print(f"-> Es fehlen {needed_pol - final_provided_pol} Personal (POL).")
        if final_provided_wasser < needed_wasser: print(f"-> Es fehlen {needed_wasser - final_provided_wasser} L Wasser.")
        if final_provided_schaummittel < needed_schaummittel: print(f"-> Es fehlen {needed_schaummittel - final_provided_schaummittel} L Schaummittel.")
        if final_provided_patienten_kapazitaet < patient_bedarf: print(f"-> Es fehlen {patient_bedarf - final_provided_patienten_kapazitaet} Patienten-Transportplätze.")
        return []

def get_on_scene_and_driving_vehicles(page, vehicle_id_map):
    """
    Liest Fahrzeuge aus dem Einsatz-iFrame aus und gibt alle erfüllten Rollen/Typen zurück.
    """
    fulfilled_roles = []
    if not vehicle_id_map:
        print("WARNUNG: vehicle_id_map nicht geladen.")
        return []

    try:
        # Playwright: Finde den iFrame und arbeite im Kontext
        iframe = page.frame_locator("iframe.lightbox_iframe")
        container_ids = ["mission_vehicle_driving", "mission_vehicle_at_mission"]

        for container_id in container_ids:
            # Playwright: .all() um alle passenden Links zu finden
            vehicle_links = iframe.locator(f"table#{container_id} a[vehicle_type_id]").all()
            for link in vehicle_links:
                type_id = link.get_attribute('vehicle_type_id')
                if type_id in vehicle_id_map:
                    vehicle_name = vehicle_id_map[type_id]
                    fulfilled_roles.append(vehicle_name)
                    if vehicle_name in VEHICLE_DATABASE:
                        generic_types = VEHICLE_DATABASE[vehicle_name].get("typ", [])
                        for t in generic_types:
                            if t != vehicle_name:
                                fulfilled_roles.append(t)
    except PlaywrightTimeoutError:
        # Passiert, wenn der iFrame oder die Tabellen nicht existieren. Das ist okay.
        pass
    
    if fulfilled_roles:
        print(f"Info: Alarmierte Fahrzeuge erfüllen folgende Rollen: {', '.join(sorted(list(set(fulfilled_roles))))}")
    return fulfilled_roles

# DIE FOLGENDEN FUNKTIONEN SIND GRÖSSTENTEILS UNVERÄNDERT
def send_discord_notification(message, priority):
    highcommand_url = "https://discord.com/api/webhooks/1408578295779557427/vFXyXnLzdzWRqyhT2Zs7hNK5i457yUaKAeG0ehAUcJU922ApUvAMfXcC3yaFlALkPsNz"
    ROLE_ID_TO_PING = config["ROLE_ID_TO_PING"]
    ping_text = f"<@&{ROLE_ID_TO_PING}> " if ROLE_ID_TO_PING else ""
    if "dev" in priority:
        data = {"content": f"{ping_text} | 🚨 **LSS Bot Alert - User: {LEITSTELLENSPIEL_USERNAME} | {BOT_VERSION} **\n>>> {message}", "allowed_mentions": {"parse": ["roles"]}}
        try: requests.post(highcommand_url, json=data)
        except requests.exceptions.RequestException: print("FEHLER: Discord-Benachrichtigung senden fehlgeschlagen.")
    if "discord_webhook_url" in config and config["discord_webhook_url"]:
        data = {"content": f"{ping_text} | ℹ️ **LSS Bot Message:**\n>>> {message}", "allowed_mentions": {"parse": ["roles"]}}
        try: requests.post(config["discord_webhook_url"], json=data)
        except requests.exceptions.RequestException: print("FEHLER: Discord-Benachrichtigung senden fehlgeschlagen.")

def check_and_claim_daily_bonus(page):
    try:
        page.locator("span.glyphicon-calendar.bonus-active").click(timeout=5000)
        iframe = page.frame_locator("iframe.lightbox_iframe, iframe:visible")
        iframe.locator("div.collect-possible-block button.collect-button").click(timeout=10000)
        time.sleep(3) # Kurze Pause, um die Animation abzuwarten
    except PlaywrightTimeoutError:
        pass # Kein Bonus verfügbar
    finally:
        # Schließe das Fenster, falls es noch offen ist
        try: page.locator("#lightbox_close").click(timeout=2000)
        except PlaywrightTimeoutError: pass

def check_and_claim_tasks(page):
    print("Info: Prüfe auf erledigte Aufgaben...")
    try:
        # Playwright: Finde den Zähler für erledigte Aufgaben. is_visible() prüft, ob er da ist.
        task_counter = page.locator("#completed_tasks_counter:not(.hidden)")
        if task_counter.is_visible(timeout=5000):
            print("Info: Erledigte Aufgabe(n) gefunden! Öffne Aufgaben-Seite...")
            page.locator("#menu_profile").click()
            page.locator("div.tasks_and_events_navbar").click()

            iframe = page.frame_locator("iframe.lightbox_iframe, iframe:visible")
            claim_buttons = iframe.locator("input[value='Abholen'].btn").all()
            
            clicked_count = 0
            print(f"Info: {len(claim_buttons)} potenzielle Belohnungs-Buttons gefunden.")
            
            for button in claim_buttons:
                if button.is_enabled():
                    print("       -> Aktiver Button gefunden. Klicke 'Abholen'...")
                    button.click()
                    clicked_count += 1
                    print("       -> Belohnung erfolgreich abgeholt.")
                    time.sleep(1.5)
            
            if clicked_count > 0:
                print(f"Info: {clicked_count} Belohnung(en) insgesamt abgeholt.")
            else:
                print("Info: Keine aktiven Belohnungen zum Abholen gefunden.")
            
            # Schließe das Aufgabenfenster
            page.locator("#lightbox_close").click()
        else:
            print("Info: Keine neuen, erledigten Aufgaben.")
            # Klicke weg, um das Profilmenü zu schließen
            page.locator('body').click(timeout=2000, force=True)

    except PlaywrightTimeoutError:
        print("Info: Keine neuen, erledigten Aufgaben.")
    except Exception as e:
        print(f"FEHLER beim Prüfen der Aufgaben: {e}")

def handle_sprechwunsche(page):
    navigated_away = False
    try:
        print("Info: Prüfe auf Sprechwünsche...")
        sprechwunsch_list = page.locator("#radio_messages_important")
        messages = sprechwunsch_list.locator("li").all()
        vehicle_urls_to_process = []
        for message in messages:
            if "Sprechwunsch" in message.text_content():
                link = message.locator("a[href*='/vehicles/']")
                if link.count() > 0:
                    vehicle_urls_to_process.append({
                        'url': "https://www.leitstellenspiel.de" + link.get_attribute('href'),
                        'name': link.text_content().strip()
                    })
        
        if not vehicle_urls_to_process:
            print("Info: Keine neuen Sprechwünsche."); return

        navigated_away = True
        print(f"Info: {len(vehicle_urls_to_process)} Sprechwünsche gefunden. Bearbeite...")
        for vehicle_info in vehicle_urls_to_process:
            page.goto(vehicle_info['url'])
            try:
                # Playwright: Finde den ersten grünen Button für Patienten oder Gefangene
                transport_button = page.locator("a[href*='/patient/'][class*='btn-success'], a[href*='/prisoner/'][class*='btn-success'], a[href*='/gefangener/'][class*='btn-success']").first
                transport_button.click()
                print(f"       -> Sprechwunsch für '{vehicle_info['name']}' bearbeitet.")
                time.sleep(2)
            except PlaywrightTimeoutError:
                print(f"       -> WARNUNG: Konnte keinen Transport-Button für '{vehicle_info['name']}' finden.")

    except PlaywrightError:
        print("Info: Keine wichtigen Funksprüche vorhanden.")
    finally:
        if navigated_away:
            print("Info: Kehre nach Sprechwunsch-Bearbeitung zur Hauptseite zurück.")
            page.goto("https://www.leitstellenspiel.de/")


# LADE- UND SPEICHERFUNKTIONEN BLEIBEN UNVERÄNDERT
def load_vehicle_id_map(file_path=resource_path("vehicle_id.json")):
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return None

def save_vehicle_database(database, file_path=resource_path("fahrzeug_datenbank.json")):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=4, ensure_ascii=False)
        print("Info: Fahrzeug-Datenbank wurde erfolgreich mit neuen Fahrzeugen aktualisiert.")
    except Exception as e: print(f"FEHLER: Konnte die Fahrzeug-Datenbank nicht speichern: {e}")

def load_mission_cache(file_path=resource_path("mission_cache.json")):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            print("Info: Missions-Cache erfolgreich geladen.")
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_mission_cache(cache_data, file_path=resource_path("mission_cache.json")):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
        print("Info: Missions-Cache wurde erfolgreich gespeichert.")
    except Exception as e: print(f"FEHLER: Konnte den Missions-Cache nicht speichern: {e}")

def get_player_vehicle_inventory(page):
    print("Info: Lese den kompletten Fuhrpark (Inventar) ein...")
    vehicle_id_map = load_vehicle_id_map()
    if not vehicle_id_map:
        print("WARNUNG: Fahrzeug-ID-Map konnte nicht geladen werden.")
        return set(), False

    inventory = set()
    database_updated = False
    try:
        page.goto("https://www.leitstellenspiel.de/vehicles", timeout=60000)
        # Playwright: Warte, bis die Tabelle sichtbar ist
        page.locator("table.table-striped").wait_for(state="visible", timeout=30000)
        vehicle_rows = page.locator("tbody tr").all()
        print(f"Info: {len(vehicle_rows)} Zeilen in der Fahrzeugtabelle gefunden. Analysiere...")

        for row in vehicle_rows:
            image_tag = row.locator("img[vehicle_type_id]")
            if image_tag.count() > 0:
                vehicle_id = image_tag.get_attribute('vehicle_type_id')
                if vehicle_id:
                    vehicle_name = vehicle_id_map.get(vehicle_id)
                    if vehicle_name:
                        inventory.add(vehicle_name)
                        if vehicle_name not in VEHICLE_DATABASE:
                            print(f"--> NEUES FAHRZEUG: '{vehicle_name}' wird zur Datenbank hinzugefügt.")
                            VEHICLE_DATABASE[vehicle_name] = {
                                "fraktion": "", "personal": 0, "typ": [vehicle_name]
                            }
                            ADDED_TO_DATABASE.append(vehicle_name)
                            database_updated = True
                    else:
                        print(f"Warnung: Unbekannte Fahrzeug-ID '{vehicle_id}' im Inventar gefunden.")
        print(f"Info: Inventar mit {len(inventory)} einzigartigen Fahrzeugtypen erfolgreich erstellt.")
    except Exception as e:
        print(f"FEHLER: Konnte den Fuhrpark nicht einlesen: {e}")
        traceback.print_exc()
    return inventory, database_updated

# -----------------------------------------------------------------------------------
# HAUPT-THREAD FÜR DIE BOT-LOGIK (MIT PLAYWRIGHT)
# -----------------------------------------------------------------------------------
def main_bot_logic(gui_vars):
    # Playwright-Initialisierung
    with sync_playwright() as p:
        browser = None
        page = None
        mission_cache = load_mission_cache()
        try:
            gui_vars['gui_queue'].put(('status', "Initialisiere Browser..."))
            
            # Browser starten
            browser = p.chromium.launch(headless=True)
            
            # User-Agent und andere Kontext-Optionen
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            if sys.platform.startswith('linux'):
                user_agent = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
            
            context = browser.new_context(
                user_agent=user_agent,
                viewport={'width': 1920, 'height': 1080},
                java_script_enabled=True,
                # Blockiert Bilder für bessere Performance
                route_handler=lambda route: route.abort() if route.request.resource_type == "image" else route.continue_()
            )
            # Verhindert, dass die Seite den Automatisierungs-Status erkennt
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            page = context.new_page()
            page.set_default_timeout(30000) # Standard-Timeout für Aktionen

            vehicle_id_map = load_vehicle_id_map()

            gui_vars['gui_queue'].put(('status', "Logge ein..."))
            page.goto("https://www.leitstellenspiel.de/users/sign_in")
            page.locator("#user_email").fill(LEITSTELLENSPIEL_USERNAME)
            page.locator("#user_password").fill(LEITSTELLENSPIEL_PASSWORD)
            time.sleep(1)
            page.locator("input[name='commit']").click()
            
            gui_vars['gui_queue'].put(('status', "Warte auf Hauptseite..."))
            page.wait_for_selector("#missions_outer", timeout=60000)
            gui_vars['gui_queue'].put(('status', "Login erfolgreich! Bot aktiv."))
            
            send_discord_notification(f"Bot erfolgreich gestartet auf Account: **{LEITSTELLENSPIEL_USERNAME}**", "user")
            
            player_inventory, db_updated = get_player_vehicle_inventory(page)
            if db_updated:
                save_vehicle_database(VEHICLE_DATABASE)
                gui_vars["db_updated_flag"] = True
            
            last_check_date = None
            bonus_checked_today = False
            
            while not gui_vars['stop_event'].is_set():
                if not gui_vars['pause_event'].is_set():
                    gui_vars['gui_queue'].put(('status', "Bot pausiert..."))
                    gui_vars['pause_event'].wait()

                gui_vars['gui_queue'].put(('status', "Prüfe Status (Boni, etc.)..."))
                page.goto("https://www.leitstellenspiel.de/", timeout=120000)
                page.wait_for_selector("#missions_outer", timeout=120000)
                
                today = date.today()
                if last_check_date != today:
                    bonus_checked_today = False
                    last_check_date = today
                if not bonus_checked_today:
                    check_and_claim_daily_bonus(page)
                    bonus_checked_today = True
                
                check_and_claim_tasks(page)

                gui_vars['gui_queue'].put(('status', "Lade Einsatzliste..."))
                
                try:
                    page.wait_for_selector("#missions_outer .missionSideBarEntry", timeout=10000)
                except PlaywrightTimeoutError:
                    gui_vars['gui_queue'].put(('status', f"Keine Einsätze. Warte {30}s..."))
                    time.sleep(30)
                    continue

                mission_entries = page.locator("#missions_outer div.missionSideBarEntry").all()
                mission_data = []
                for entry in mission_entries:
                    try:
                        mission_id = entry.get_attribute('mission_id')
                        url_element = entry.locator(f"#mission_caption_{mission_id}")
                        full_name = url_element.text_content().strip()
                        name = full_name.split(',')[0].strip()
                        
                        patient_count = 0; timeleft = 0
                        sort_data_str = entry.get_attribute('data-sortable-by')
                        if sort_data_str:
                            sort_data = json.loads(sort_data_str)
                            patient_count = sort_data.get('patients_count', [0, 0])[0]
                        
                        countdown_element = entry.locator(f"div#mission_overview_countdown_{mission_id}")
                        if countdown_element.count() > 0:
                            timeleft_str = countdown_element.get_attribute('timeleft')
                            if timeleft_str and timeleft_str.isdigit(): timeleft = int(timeleft_str)
                        
                        panel_div = entry.locator(f"div#mission_panel_{mission_id}")
                        panel_class = panel_div.get_attribute('class') or ""
                        is_red = 'mission_panel_red' in panel_class

                        if name and mission_id and is_red:
                            mission_data.append({
                                'id': mission_id, 'name': name, 'patienten': patient_count, 'timeleft': timeleft
                            })
                    except (PlaywrightError, json.JSONDecodeError):
                        continue
                
                if not mission_data:
                    gui_vars['gui_queue'].put(('status', f"Keine Einsätze. Warte {30}s...")); time.sleep(30); continue
                
                gui_vars['gui_queue'].put(('status', f"{len(mission_data)} Einsätze gefunden. Bearbeite..."))

                for i, mission in enumerate(mission_data):
                    if gui_vars['stop_event'].is_set(): break
                    if not gui_vars['pause_event'].is_set():
                         gui_vars['gui_queue'].put(('status' ,"Bot pausiert...")); gui_vars['pause_event'].wait()
                    
                    if "[Verband]" in mission['name'] or mission['name'].lower() == "krankentransport" or "intensivverlegung" in mission['name'].lower():
                        continue
                    if mission['timeleft'] > MAX_START_DELAY_SECONDS:
                        continue
                    
                    print(f"-----------------{mission['name']}-----------------")
                    gui_vars['gui_queue'].put(('mission_name', f"({i+1}/{len(mission_data)}) {mission['name']}"))

                    try:
                        # Schritt 1: Zum Einsatz navigieren
                        sidebar_button_locator = f"//div[@mission_id='{mission['id']}']//a[contains(@class, 'mission-alarm-button')]"
                        page.locator(sidebar_button_locator).click()
                        
                        # Warten bis das Einsatzfenster geladen ist
                        page.wait_for_selector(f"#alarm_button_{mission['id']}", timeout=20000)

                        # Schritt 2: Prüfen, ob der Einsatz unvollständig ist
                        vehicles_on_scene = []
                        is_incomplete = False
                        missing_alert_locator = "//div[contains(@class, 'alert-danger') and .//div[@data-requirement-type]]"
                        if page.locator(missing_alert_locator).count() > 0:
                            print(" -> Warnmeldung für fehlende Einheiten gefunden. Bereite Nachalarmierung vor.")
                            vehicles_on_scene = get_on_scene_and_driving_vehicles(page, vehicle_id_map)
                            is_incomplete = True
                        else:
                            print(" -> Keine Warnmeldung für fehlende Einheiten. Einsatz wird voll bearbeitet.")
                        
                        raw_requirements = get_mission_requirements(page, player_inventory, mission['patienten'], mission['name'], mission_cache)
                        if not raw_requirements: continue
                        
                        try:
                            patient_alert_xpath = "//div[starts-with(@id, 'patients_missing_')]"
                            patient_alert = page.locator(patient_alert_xpath)
                            if patient_alert.count() > 0:
                                alert_text = patient_alert.text_content()
                                print(f" -> Patienten-Anforderung gefunden: '{alert_text}'")
                                if "NEF" in alert_text:
                                    raw_requirements['fahrzeuge'].append(["NEF"])
                                    print("       -> Füge 1x NEF zum Bedarf hinzu.")
                                if "RTW" in alert_text:
                                    match = re.search(r'(\d+)\s*x?\s*RTW', alert_text)
                                    if match:
                                        num_rtw = int(match.group(1))
                                        for _ in range(num_rtw): raw_requirements['fahrzeuge'].append(["RTW"])
                                        print(f"       -> Füge {num_rtw}x RTW zum Bedarf hinzu.")
                                    elif "RTW" in alert_text:
                                        raw_requirements['fahrzeuge'].append(["RTW"])
                                        print("       -> Füge 1x RTW zum Bedarf hinzu.")
                        except PlaywrightError: pass

                        if mission['timeleft'] > 0 and raw_requirements.get('credits', 0) < MINIMUM_CREDITS:
                            continue

                        # Nachalarmierungslogik
                        if is_incomplete and vehicles_on_scene:
                            # (Dieser Logikblock ist reines Python und bleibt unverändert)
                            on_scene_counts = Counter(vehicles_on_scene)
                            still_needed_requirements = []
                            for required_options in raw_requirements['fahrzeuge']:
                                found_match = False
                                for option in required_options:
                                    if on_scene_counts[option] > 0:
                                        on_scene_counts[option] -= 1; found_match = True; break
                                if not found_match: still_needed_requirements.append(required_options)
                            raw_requirements['fahrzeuge'] = still_needed_requirements
                        
                        final_requirements = raw_requirements
                        req_parts = []; readable_requirements = [" oder ".join(options) for options in final_requirements['fahrzeuge']]
                        vehicle_counts = Counter(readable_requirements)
                        for vehicle, count in vehicle_counts.items(): req_parts.append(f"{count}x {vehicle}")
                        if final_requirements.get('personal_fw', 0) > 0: req_parts.append(f"{final_requirements['personal_fw']} Pers. (FW)")
                        # ... (restliche Personal-Anforderungen)

                        gui_vars['gui_queue'].put(('requirements', "Bedarf: " + (", ".join(req_parts) if req_parts else "Nichts mehr benötigt.")))

                        available_vehicles = get_available_vehicles(page)
                        if not available_vehicles:
                            gui_vars['gui_queue'].put(('availability', "Verfügbar: Keine"))
                            gui_vars['gui_queue'].put(('status', f"Keine Fahrzeuge frei. Pausiere {PAUSE_IF_NO_VEHICLES_SECONDS}s..."))
                            time.sleep(PAUSE_IF_NO_VEHICLES_SECONDS); break
                        
                        # (GUI-Anzeige-Logik bleibt gleich)
                        
                        checkboxes_to_click = find_best_vehicle_combination(final_requirements, available_vehicles, VEHICLE_DATABASE)
                        if checkboxes_to_click:
                            gui_vars['gui_queue'].put(('status', "✓ Alarmiere..."))
                            gui_vars['gui_queue'].put(('alarm_status', f"Status: ALARMIERT ({len(checkboxes_to_click)} FZ)"))
                            # Playwright: Klicke die Checkboxen der ausgewählten Fahrzeuge
                            for checkbox_locator in checkboxes_to_click:
                                checkbox_locator.check() # .check() ist für Checkboxen besser als .click()
                            
                            # Alarmieren-Button klicken
                            alarm_next_button = page.locator("input[value='Alarmieren und zum nächsten Einsatz']")
                            if alarm_next_button.is_visible():
                                alarm_next_button.click()
                            else:
                                page.locator("input[value='Alarmieren']").click()
                        else:
                            gui_vars['gui_queue'].put(('status', "❌ Nicht genug Einheiten frei."))
                            gui_vars['gui_queue'].put(('alarm_status', "Status: WARTE AUF EINHEITEN"))

                        page.wait_for_selector("#missions_outer", timeout=30000)
                        
                        update_data = {'status': "Lade nächsten Einsatz...", 'alarm_status': "Status: -", 'requirements': "Bedarf: -", 'availability': "Verfügbar: -"}
                        gui_vars['gui_queue'].put(('batch_update', update_data))
                        
                        handle_sprechwunsche(page)

                    except Exception as e:
                        print(f"Fehler bei der Einsatzbearbeitung: {e}"); traceback.print_exc(); time.sleep(10)

        except Exception as e:
            print("FATALER FEHLER! Erstelle Screenshot 'fehler.png'...")
            if page:
                page.screenshot(path='fehler.png')
            error_details = traceback.format_exc()
            send_discord_notification(f"FATALER FEHLER! Bot beendet.\n```\n{error_details}\n```", "dev")
            gui_vars['gui_queue'].put(('status', "FATALER FEHLER! Details in error_log.txt"))
            messagebox.showerror("Fataler Fehler!", "Der Bot wurde angehalten! Prüfe das Fehler-Log.")
            with open(resource_path('error_log.txt'), 'a', encoding='utf-8') as f:
                f.write(f"\n--- FEHLER am {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{error_details}\n" + "-" * 50 + "\n")
        finally:
            if mission_cache:
                save_mission_cache(mission_cache)
            if browser:
                browser.close()
            gui_vars['gui_queue'].put(('status', "Bot beendet."))

# -----------------------------------------------------------------------------------
# HAUPTPROGRAMM (UNVERÄNDERT)
# -----------------------------------------------------------------------------------
if __name__ == "__main__":
    gui_queue = queue.Queue()
    pause_event = threading.Event(); pause_event.set()
    stop_event = threading.Event()
    
    app_window = StatusWindow(pause_event, stop_event, gui_queue)
    
    gui_variables = {
        "pause_event": pause_event,
        "stop_event": stop_event,
        "db_updated_flag": False,
        "gui_queue": gui_queue
    }

    bot_thread = threading.Thread(target=main_bot_logic, args=(gui_variables,))
    bot_thread.start()

    app_window.mainloop()

    print("Fenster geschlossen. Warte auf sauberes Herunterfahren des Bot-Threads...")
    bot_thread.join()

    if gui_variables.get("db_updated_flag", False):
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(
            "Datenbank-Update",
            "Die Fahrzeug-Datenbank wurde mit neuen Einträgen aktualisiert! Es müssen noch Daten eingetragen werden."
        )
        send_discord_notification(f"Fahrzeuge zu Datenbank hinzugefügt! \n```\n{ADDED_TO_DATABASE}\n```", "dev_update")
        root.destroy()
    
    print("Bot wurde ordnungsgemäß beendet.")