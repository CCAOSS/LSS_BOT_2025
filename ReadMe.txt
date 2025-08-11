
#.exe erstellen
1. cmd im ordner mit den datein öffnen

2.
python -m PyInstaller --onefile --windowed --name="LSS_Bot" --add-data "config.json;." --add-data "vehicle_classes.json;." --add-binary "chromedriver.exe;." leitstellenspiel_bot.py