import subprocess
import sys
import os

print("--- LSS Bot Launcher ---")
print("1. Synchronisiere mit der neuesten Version von GitHub...")

# Stelle sicher, dass wir im richtigen Verzeichnis sind
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

try:
    # --- NEU: Zuerst alle lokalen Änderungen verwerfen ---
    # Das ist der entscheidende Schritt, um den "overwrite"-Fehler zu verhindern.
    print("   -> Setze lokale Dateien zurück (git reset --hard)...")
    subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)

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