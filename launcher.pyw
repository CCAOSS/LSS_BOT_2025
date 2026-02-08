import sys
import subprocess
import importlib.util
import time
import os

# --- WICHTIG: ARBEITSVERZEICHNIS KORRIGIEREN ---
# Dies zwingt das Skript, immer im Ordner der .pyw Datei zu arbeiten,
# egal ob per Doppelklick, CMD oder IDE gestartet.
try:
    # Ermittle den Pfad, in dem diese Datei liegt
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Wechsle das Arbeitsverzeichnis dorthin
    os.chdir(script_dir)
    print(f"Arbeitsverzeichnis gesetzt auf: {script_dir}")
except Exception as e:
    print(f"Konnte Arbeitsverzeichnis nicht setzen: {e}")

# --- 1. BOOTSTRAPPER (Installations-Routine) ---
def install_and_check_packages():
    required_packages = [
        ("requests", "requests"),
        ("customtkinter", "customtkinter"),
        ("matplotlib", "matplotlib"),
        ("selenium", "selenium"),
        ("webdriver-manager", "webdriver_manager"),
        ("packaging", "packaging"),
        ("pillow", "PIL")
    ]

    pkgs_to_install = []
    
    for package, import_name in required_packages:
        if importlib.util.find_spec(import_name) is None:
            pkgs_to_install.append(package)

    if pkgs_to_install:
        try:
            import tkinter as tk
            from tkinter import ttk
            splash = tk.Tk()
            splash.title("LSS Bot Setup")
            splash.geometry("400x200")
            splash.eval('tk::PlaceWindow . center')
            
            lbl_title = tk.Label(splash, text="Erstinstallation läuft...", font=("Arial", 12, "bold"))
            lbl_title.pack(pady=10)
            
            lbl_status = tk.Label(splash, text="Prüfe Voraussetzungen...", font=("Arial", 10))
            lbl_status.pack(pady=5)
            
            progress = ttk.Progressbar(splash, orient="horizontal", length=300, mode="indeterminate")
            progress.pack(pady=10)
            progress.start()
            
            splash.update()
        except:
            splash = None

        for pkg in pkgs_to_install:
            print(f"Installiere {pkg}...")
            if splash:
                lbl_status.config(text=f"Installiere Paket: {pkg}\nBitte warten...")
                splash.update()
            
            try:
                # Wir nutzen sys.executable um sicherzustellen, dass es im richtigen Python landet
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            except Exception as e:
                print(f"Fehler bei {pkg}: {e}")
                if splash:
                    lbl_status.config(text=f"Fehler bei {pkg}!", fg="red")
                    splash.update()
                    time.sleep(2)

        if splash:
            lbl_status.config(text="Fertig! Starte Launcher...", fg="green")
            progress.stop()
            splash.update()
            time.sleep(1)
            splash.destroy()

# Check ausführen
install_and_check_packages()

# --- 2. HAUPTPROGRAMM ---
import requests
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import shutil

# --- KONFIGURATION ---
BOT_SCRIPT = "leitstellenspiel_bot.pyw"
RESTART_INTERVAL_MS = 6 * 60 * 60 * 1000 
CHECK_INTERVAL_MS = 5000 

class LSSLauncher(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("LSS Bot Launcher 2025")
        self.geometry("450x500")
        self.process = None
        self.auto_restart_timer = None
        self.running = False

        self.setup_ui()
        # Kurze Verzögerung, damit GUI lädt, bevor Git geprüft wird
        self.after(200, self.check_git_update)

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        header = ttk.Label(self, text="LSS Bot Control", font=("Segoe UI", 16, "bold"))
        header.pack(pady=10)

        self.status_var = tk.StringVar(value="Status: Bereit")
        lbl_status = ttk.Label(self, textvariable=self.status_var, foreground="blue")
        lbl_status.pack(pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=20, fill='x', padx=20)

        self.btn_start = ttk.Button(btn_frame, text="Starten", command=self.start_bot)
        self.btn_start.pack(fill='x', pady=2)

        self.btn_stop = ttk.Button(btn_frame, text="Beenden (Stop)", command=self.stop_bot, state='disabled')
        self.btn_stop.pack(fill='x', pady=2)

        self.btn_restart = ttk.Button(btn_frame, text="Neustarten (Manuell)", command=self.restart_bot, state='disabled')
        self.btn_restart.pack(fill='x', pady=2)

        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=10)

        self.btn_config = ttk.Button(self, text="Config bearbeiten", command=self.open_config_editor)
        self.btn_config.pack(fill='x', padx=20, pady=2)
        
        self.btn_close = ttk.Button(self, text="Alles Schließen", command=self.on_close)
        self.btn_close.pack(fill='x', padx=20, pady=2)

        self.log_widget = scrolledtext.ScrolledText(self, height=8, state='disabled', font=("Consolas", 8))
        self.log_widget.pack(fill='both', expand=True, padx=10, pady=10)

    def log(self, message):
        self.log_widget.config(state='normal')
        self.log_widget.insert(tk.END, f"{time.strftime('%H:%M:%S')}: {message}\n")
        self.log_widget.see(tk.END)
        self.log_widget.config(state='disabled')

    def check_git_update(self):
        # Jetzt ist cwd korrekt, also sollte os.path.isdir(".git") funktionieren
        if not shutil.which("git"):
            self.log("Git nicht installiert. Auto-Update deaktiviert.")
            return

        if not os.path.isdir(".git"):
            self.log("Kein Git-Repository erkannt (ZIP-Download?).")
            self.log("Auto-Update ist deaktiviert.")
            return

        self.log("Prüfe auf Updates...")
        try:
            # git fetch im aktuellen Verzeichnis
            subprocess.run(["git", "fetch"], check=True, capture_output=True, timeout=10)
            status = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True, timeout=5).stdout
            
            if "behind" in status:
                self.log("Update verfügbar! Lade herunter...")
                subprocess.run(["git", "pull"], check=True)
                self.log("Update erfolgreich! Bitte Neustarten.")
                messagebox.showinfo("Update", "Update installiert. Bitte Launcher neu starten!")
            else:
                self.log("Version ist aktuell.")
        except subprocess.TimeoutExpired:
            self.log("Update-Check: Zeitüberschreitung.")
        except subprocess.CalledProcessError as e:
            self.log(f"Git Fehler (Code {e.returncode}).")
        except Exception as e:
            self.log(f"Update Fehler: {e}")

    def start_bot(self):
        if self.process is not None:
            return

        self.log("Starte Bot-Prozess...")
        try:
            if sys.platform.startswith('win'):
                creationflags = subprocess.CREATE_NEW_CONSOLE
            else:
                creationflags = 0

            # Auch hier ist wichtig: Wir nutzen das korrigierte CWD automatisch
            self.process = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                creationflags=creationflags,
                cwd=os.getcwd() # Explizit das korrekte Verzeichnis übergeben
            )
            
            self.running = True
            self.status_var.set(f"Status: Bot läuft (PID: {self.process.pid})")
            self.btn_start.config(state='disabled')
            self.btn_stop.config(state='normal')
            self.btn_restart.config(state='normal')

            self.auto_restart_timer = self.after(RESTART_INTERVAL_MS, self.restart_bot)
            self.check_process_health()

        except Exception as e:
            self.log(f"Fehler beim Starten: {e}")
            messagebox.showerror("Fehler", f"Konnte Bot nicht starten:\n{e}")

    def check_process_health(self):
        if self.running and self.process:
            if self.process.poll() is not None:
                return_code = self.process.returncode
                self.log(f"ACHTUNG: Bot beendet (Code {return_code})")
                self.send_discord_alert(f"⚠️ Bot unerwartet abgestürzt! Code: {return_code}")
                self.stop_bot_logic()
            else:
                self.after(CHECK_INTERVAL_MS, self.check_process_health)

    def stop_bot(self):
        self.log("Beende Bot...")
        self.stop_bot_logic()

    def stop_bot_logic(self):
        if self.auto_restart_timer:
            self.after_cancel(self.auto_restart_timer)
            self.auto_restart_timer = None

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None

        self.running = False
        self.status_var.set("Status: Gestoppt")
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')
        self.btn_restart.config(state='disabled')

    def restart_bot(self):
        self.log("Führe Neustart durch...")
        self.stop_bot_logic()
        self.after(2000, self.start_bot)

    def open_config_editor(self):
        editor = tk.Toplevel(self)
        editor.title("Config Editor")
        editor.geometry("600x600")

        text_area = scrolledtext.ScrolledText(editor, font=("Consolas", 10))
        text_area.pack(fill='both', expand=True)

        try:
            # Liest jetzt garantiert aus dem richtigen Ordner
            with open('config.json', 'r', encoding='utf-8') as f:
                text_area.insert(tk.END, f.read())
        except FileNotFoundError:
            default_conf = {"username": "", "password": "", "discord_webhook_url": ""}
            text_area.insert(tk.END, json.dumps(default_conf, indent=4))

        def save_config():
            try:
                new_content = text_area.get("1.0", tk.END)
                json.loads(new_content)
                # Schreibt jetzt garantiert in den richtigen Ordner
                with open('config.json', 'w', encoding='utf-8') as f:
                    f.write(new_content)
                messagebox.showinfo("Info", "Config gespeichert!")
                editor.destroy()
            except json.JSONDecodeError:
                messagebox.showerror("Fehler", "Ungültiges JSON Format!")

        ttk.Button(editor, text="Speichern", command=save_config).pack(fill='x', pady=5)

    def send_discord_alert(self, message):
        try:
            with open('config.json', 'r') as f:
                conf = json.load(f)
            url = conf.get('discord_webhook_url')
            if url:
                requests.post(url, json={"content": message})
        except:
            pass

    def on_close(self):
        if self.process:
            self.stop_bot_logic()
        self.destroy()

if __name__ == "__main__":
    app = LSSLauncher()
    app.mainloop()