# Tool-Hub

Ein Launcher für die Windows-Tools von [github.com/phillhf](https://github.com/phillhf):
installieren, starten, aktualisieren und deinstallieren – alles an einer Stelle.

![Icon](installer/app_256.png)

## Installation

Das aktuelle `Tool-Hub-Setup-x.y.z.exe` unter [Releases](https://github.com/phillhf/tool-hub/releases) herunterladen
und ausführen. Es braucht keine Administratorrechte. Tool-Hub aktualisiert sich danach selbst.

## So funktioniert es

- **Welche Tools?** Tool-Hub fragt GitHub nach allen Repos von `phillhf`. Jedes Repo, dessen neuestes Release ein
  `Name-Setup-x.y.z.exe` enthält, erscheint als Kachel. Neue Tools tauchen also automatisch auf.
- **Installieren / Aktualisieren:** Das Setup wird geladen, die SHA-256-Prüfsumme geprüft und das Setup gestartet.
  Updates laufen still im Hintergrund, Neuinstallationen zeigen den Assistenten (abschaltbar).
  Tools, die Administratorrechte brauchen, lösen die übliche Windows-Rückfrage aus.
- **Erkennen:** Installierte Tools findet Tool-Hub über ihre Einträge unter „Apps & Features“ – auch solche,
  die vor Tool-Hub installiert wurden.
- **Starten:** Tool-Hub öffnet den Weblink, die Startverknüpfung oder das Programm des Tools.
- **Deinstallieren:** ruft das Deinstallationsprogramm des Tools still auf. Eigene Daten der Tools bleiben erhalten.

## Private Tools

Private Repos erscheinen erst mit einem GitHub-Token (Knopf „Private Tools freischalten …“):

1. [Fine-grained token erstellen](https://github.com/settings/personal-access-tokens/new), Resource owner `phillhf`,
   Ablaufdatum wählen.
2. Repository access: *Only select repositories* → die privaten Tools auswählen.
3. Permissions → Repository → **Contents: Read-only**.
4. Token in Tool-Hub einfügen.

Der Token wird in der Windows-Anmeldeinformationsverwaltung gespeichert (Eintrag `Tool-Hub/github-token`) und nur an
`api.github.com` geschickt. Er steckt nie im Programm selbst. Wer Zugriff bekommen soll, bekommt einen eigenen Token,
den man einzeln widerrufen kann.

## Entwickeln

```
python app.py                      # starten
python -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File installer\build.ps1   # EXE und Setup bauen (PyInstaller, Inno Setup 6)
```

Ein Release entsteht über GitHub Actions, sobald ein Tag `vX.Y.Z` gepusht wird, der zu `__version__` in
`toolhub/__init__.py` passt.

## Anforderungen an ein Tool

Damit ein Tool in Tool-Hub erscheint und sich steuern lässt:

- Release-Asset `Name-Setup-x.y.z.exe`, gebaut mit **Inno Setup**, das `/VERYSILENT` beherrscht.
- Der Name unter „Apps & Features“ beginnt mit dem Repo- oder Setup-Namen (z. B. `Music Renamer`, `Canio (Server)`).
- Zum Starten: ein `.url`/`.lnk` im Installationsordner, ein Startmenü-Eintrag oder ein `DisplayIcon`, das auf die EXE zeigt.
