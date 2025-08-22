import subprocess
import sys
import os
import shutil

print("--- LSS Bot Launcher ---")
print("1. Synchronisiere mit der neuesten Version von GitHub...")

# Stelle sicher, dass wir im richtigen Verzeichnis sind
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

def check_prerequisites():
    """Prüft, ob Git und eine passende Python-Version installiert sind."""
    print("     -> Prüfe Python & GIT installation")

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

try:
    # --- NEU: Zuerst alle lokalen Änderungen verwerfen ---
    # Das ist der entscheidende Schritt, um den "overwrite"-Fehler zu verhindern.
    print("   -> Setze lokale Dateien zurück (git reset --hard)...")
    subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)

    check_prerequisites()

    # --- Danach die neueste Version herunterladen ---
    print("   -> Lade neueste Version herunter (git pull)...")
    subprocess.run(["git", "pull"], check=True)
    print("-> Synchronisierung abgeschlossen. Du hast die aktuellste Version.")

except Exception as e:
    print(f"-> FEHLER bei der Synchronisierung mit GitHub: {e}")
    print("-> Starte trotzdem mit der zuletzt bekannten lokalen Version.")


# Starte den Haupt-Bot
print("\n2. Starte den Haupt-Bot (leitstellenspiel_bot.py)...")
print("-" * 25)

try:
    subprocess.run([sys.executable, "leitstellenspiel_bot.py"], check=True)

except KeyboardInterrupt:
    print("\nLauncher durch Benutzer beendet.")

except Exception as e:
    print(f"\nEin Fehler ist beim Ausführen des Haupt-Bots aufgetreten: {e}")

print("\n--- LSS Bot Launcher beendet ---") 