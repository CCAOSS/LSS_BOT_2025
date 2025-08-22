import subprocess
import sys
import os
import shutil

# --- Konfiguration ---
VENV_DIR = "venv"  # Name des Ordners für die virtuelle Umgebung

def check_prerequisites():
    """Prüft, ob Git und eine passende Python-Version installiert sind."""
    print("1. Prüfe Systemvoraussetzungen...")

    # Prüfe Python-Version
    if sys.version_info < (3, 8):
        print(f"-> FEHLER: Dein Bot benötigt Python 3.8 oder neuer. Du hast Version {sys.version.split(' ')[0]}.")
        print("-> Bitte installiere eine aktuelle Python-Version von: https://www.python.org/downloads/")
        sys.exit(1)
    print("   -> Python-Version ist in Ordnung.")

    # Prüfe, ob Git installiert ist
    if not shutil.which("git"):
        print("-> FEHLER: Git wurde nicht gefunden. Git wird für das automatische Update benötigt.")
        print("-> Bitte installiere Git von: https://git-scm.com/downloads")
        sys.exit(1)
    print("   -> Git ist installiert.")

def setup_venv():
    """Richtet die virtuelle Umgebung ein und installiert die Abhängigkeiten."""
    print("\n2. Richte die Python-Umgebung (venv) ein...")
    
    # Pfade zum Python-Interpreter im venv bestimmen (abhängig vom Betriebssystem)
    if sys.platform == "win32":
        python_executable = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        python_executable = os.path.join(VENV_DIR, "bin", "python")

    # Virtuelle Umgebung erstellen, falls sie nicht existiert
    if not os.path.exists(python_executable):
        print(f"   -> Virtuelle Umgebung '{VENV_DIR}' wird erstellt...")
        try:
            subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
            print("   -> Umgebung erfolgreich erstellt.")
        except subprocess.CalledProcessError as e:
            print(f"-> FEHLER beim Erstellen der virtuellen Umgebung: {e}")
            sys.exit(1)
    else:
        print("   -> Virtuelle Umgebung existiert bereits.")

    # Abhängigkeiten aus requirements.txt installieren/aktualisieren
    print("   -> Installiere/aktualisiere notwendige Pakete (selenium, requests)...")
    try:
        subprocess.run([python_executable, "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([python_executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        print("   -> Alle Pakete sind auf dem neuesten Stand.")
    except subprocess.CalledProcessError as e:
        print(f"-> FEHLER bei der Installation der Pakete: {e}")
        sys.exit(1)
        
    return python_executable

def update_repo():
    """Synchronisiert das Skript mit der neuesten Version von GitHub."""
    print("\n3. Synchronisiere mit der neuesten Version von GitHub...")
    try:
        print("   -> Setze lokale Änderungen zurück (git reset --hard)...")
        subprocess.run(["git", "reset", "--hard", "HEAD"], check=True, capture_output=True, text=True)
        
        # NEU: Entferne alle unbekannten Dateien, die im Weg sein könnten (wie die lokale requirements.txt)
        print("   -> Bereinige unbekannte Dateien (git clean -fd)...")
        subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True, text=True)

        print("   -> Lade neueste Version herunter (git pull)...")
        subprocess.run(["git", "pull"], check=True)
        
        print("-> Synchronisierung abgeschlossen.")
    except subprocess.CalledProcessError as e:
        print(f"-> FEHLER bei der Synchronisierung mit GitHub: {e.stderr}")
        print("-> Starte trotzdem mit der zuletzt bekannten lokalen Version.")

def run_bot(python_executable):
    """Startet den Haupt-Bot mit dem Interpreter aus der virtuellen Umgebung."""
    print("\n4. Starte den Haupt-Bot (leitstellenspiel_bot.py)...")
    print("-" * 35)
    try:
        # Starte den Bot mit dem Python aus dem venv
        subprocess.run([python_executable, "leitstellenspiel_bot.py"], check=True)
    except KeyboardInterrupt:
        print("\n-> Launcher durch Benutzer beendet.")
    except Exception as e:
        print(f"\n-> Ein Fehler ist beim Ausführen des Haupt-Bots aufgetreten: {e}")

if __name__ == "__main__":
    print("--- LSS Bot Launcher ---")
    
    # Stelle sicher, dass wir im richtigen Verzeichnis sind
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    check_prerequisites()
    python_exe = setup_venv()
    update_repo()
    run_bot(python_exe)

    print("\n--- LSS Bot Launcher beendet ---")