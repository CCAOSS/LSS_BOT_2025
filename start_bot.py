import subprocess
import sys

def run_command(command):
    """Führt einen Shell-Befehl aus und gibt die Ausgabe zurück."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout.strip()

print("--- LSS Bot Launcher ---")

# 1. Prüfe den Remote-Status (ohne schon etwas herunterzuladen)
print("1. Suche nach Updates auf GitHub...")
run_command(["git", "remote", "update"])

# 2. Vergleiche die lokale Version mit der Online-Version
local_version = run_command(["git", "rev-parse", "@"])
remote_version = run_command(["git", "rev-parse", "@{u}"])

# 3. Entscheide, ob ein Update nötig ist
if local_version == remote_version:
    print("-> Du hast bereits die aktuellste Version.")
else:
    print("-> Neue Version gefunden! Führe 'git pull' aus...")
    # Führe das Update durch
    pull_result = subprocess.run(["git", "pull"], check=True)
    if pull_result.returncode == 0:
        print("-> Update erfolgreich!")
    else:
        print("-> FEHLER beim Update. Starte trotzdem mit der alten Version.")

# 4. Starte den Haupt-Bot
print("\n2. Starte den Haupt-Bot (leitstellenspiel_bot.py)...")
print("-" * 25)

try:
    # Führe das Hauptskript aus
    subprocess.run([sys.executable, "leitstellenspiel_bot.py"], check=True)
except KeyboardInterrupt:
    print("\nLauncher durch Benutzer beendet.")
except Exception as e:
    print(f"\nEin Fehler ist beim Ausführen des Haupt-Bots aufgetreten: {e}")

print("\n--- LSS Bot Launcher beendet ---")