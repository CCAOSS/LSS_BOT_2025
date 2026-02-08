import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import sys
import os
import json
import time
import threading
import shutil
import requests

# --- KONFIGURATION LAUNCHER ---
BOT_SCRIPT = "leitstellenspiel_bot.pyw"
RESTART_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 Stunden in Millisekunden
CHECK_INTERVAL_MS = 5000  # Alle 5 Sekunden prüfen, ob Bot noch lebt

class LSSLauncher(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("LSS Bot Launcher 2025")
        self.geometry("400x450")
        self.process = None
        self.auto_restart_timer = None
        self.running = False

        self.setup_ui()
        self.check_git_update()

    def setup_ui(self):
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Header
        header = ttk.Label(self, text="LSS Bot Control", font=("Segoe UI", 16, "bold"))
        header.pack(pady=10)

        # Status
        self.status_var = tk.StringVar(value="Status: Bereit")
        lbl_status = ttk.Label(self, textvariable=self.status_var, foreground="blue")
        lbl_status.pack(pady=5)

        # Buttons
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
        
        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=10)

        self.btn_close = ttk.Button(self, text="Alles Schließen", command=self.on_close)
        self.btn_close.pack(fill='x', padx=20, pady=2)

        # Output Log (mini console)
        self.log_widget = scrolledtext.ScrolledText(self, height=8, state='disabled', font=("Consolas", 8))
        self.log_widget.pack(fill='both', expand=True, padx=10, pady=10)

    def log(self, message):
        self.log_widget.config(state='normal')
        self.log_widget.insert(tk.END, f"{time.strftime('%H:%M:%S')}: {message}\n")
        self.log_widget.see(tk.END)
        self.log_widget.config(state='disabled')

    def check_git_update(self):
        self.log("Prüfe auf Updates...")
        if shutil.which("git"):
            try:
                subprocess.run(["git", "fetch"], check=True, capture_output=True)
                status = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True).stdout
                if "behind" in status:
                    self.log("Update verfügbar! Lade herunter...")
                    subprocess.run(["git", "pull"], check=True)
                    self.log("Update erfolgreich.")
                else:
                    self.log("Version ist aktuell.")
            except Exception as e:
                self.log(f"Git Fehler: {e}")
        else:
            self.log("Git nicht gefunden. Überspringe Update.")

    def start_bot(self):
        if self.process is not None:
            return

        self.log("Starte Bot-Prozess...")
        try:
            # Starte das Skript in einem separaten Prozess
            if sys.platform.startswith('win'):
                creationflags = subprocess.CREATE_NEW_CONSOLE
            else:
                creationflags = 0

            self.process = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                creationflags=creationflags
            )
            
            self.running = True
            self.status_var.set("Status: Bot läuft (PID: {})".format(self.process.pid))
            self.btn_start.config(state='disabled')
            self.btn_stop.config(state='normal')
            self.btn_restart.config(state='normal')

            # 6-Stunden Timer setzen
            self.auto_restart_timer = self.after(RESTART_INTERVAL_MS, self.restart_bot)
            
            # Healthcheck Loop starten
            self.check_process_health()

        except Exception as e:
            self.log(f"Fehler beim Starten: {e}")

    def check_process_health(self):
        if self.running and self.process:
            if self.process.poll() is not None:
                # Prozess ist tot, obwohl er laufen sollte
                return_code = self.process.returncode
                self.log(f"ACHTUNG: Bot unerwartet beendet (Code {return_code})")
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
        self.log("Führe Neustart durch (6h Timer oder Manuell)...")
        self.stop_bot_logic()
        self.after(2000, self.start_bot) # 2 Sekunden warten vor Neustart

    def open_config_editor(self):
        editor = tk.Toplevel(self)
        editor.title("Config Editor")
        editor.geometry("600x600")

        text_area = scrolledtext.ScrolledText(editor, font=("Consolas", 10))
        text_area.pack(fill='both', expand=True)

        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                content = f.read()
                text_area.insert(tk.END, content)
        except FileNotFoundError:
            text_area.insert(tk.END, "{\n  \"username\": \"\",\n  \"password\": \"\"\n}")

        def save_config():
            try:
                new_content = text_area.get("1.0", tk.END)
                # Validierung ob valides JSON
                json.loads(new_content) 
                with open('config.json', 'w', encoding='utf-8') as f:
                    f.write(new_content)
                messagebox.showinfo("Info", "Config gespeichert!")
                editor.destroy()
            except json.JSONDecodeError:
                messagebox.showerror("Fehler", "Ungültiges JSON Format! Bitte prüfen.")

        btn_save = ttk.Button(editor, text="Speichern", command=save_config)
        btn_save.pack(fill='x', pady=5)

    def send_discord_alert(self, message):
        # Versucht, die Webhook URL aus der Config zu lesen
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