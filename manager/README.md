# Fusion Manager 1.2.0

Die native Linux-Anwendung verwaltet Fusion-Installation, Git-Updates, Prefix,
Proton, Start, SpaceMouse-Achsen, Tasten und Kamerageschwindigkeit. Sie benötigt
Qt 6 Widgets, einen C++17-Compiler, make/pkg-config und Python 3 (nur stdlib).
Es gibt keinen Webserver, Browser-/Electron-Prozess oder separaten root-Dienst.

```sh
make -C manager
./manager/run.sh
# Anderer Installationsordner:
./manager/run.sh --target /pfad/zu/autodesk-fusion
```

Nach `./install.sh --patch` bzw. `--apply-update` stehen der Menüeintrag
**Fusion Manager** und `fusion-manager` zur Verfügung. Mit **Einrichtung** einen
Installationsordner und den lokalen Checkout wählen. **Neu installieren** lädt
bei Bedarf Autodesks offiziellen Installer und startet dessen Setup; dabei
bleiben Anmeldung und Autodesk-Dialoge sichtbar. Ein bereits belegter
Installationsordner wird abgewiesen. **Vorhandene Installation einrichten**
übernimmt eine bestehende Installation; **Aktuellen Checkout anwenden**
installiert die bereits lokal vorliegende Integration ohne Git-Download.

**Repository laden** klont einen fehlenden Checkout in den ausgewählten, freien
Repo-Ordner; eine vorhandene Installation verwendet ihre gespeicherte Quelle und
ihren Branch. Vorhandene Dateien werden abgewiesen. **Updates prüfen** führt
nur einen expliziten Git-Fetch aus. Die angezeigten
Ahead-/Behind-Zahlen beziehen sich auf den letzten Abruf. **Git-Update
installieren** verwendet den bestehenden Fast-Forward-Updater und führt den
neu geholten Installer aus. Lokale Dateien werden weder gestasht noch verworfen.
Updates sichern ersetzte Helfer unter `backups/updates`, erhalten Dokumente,
aktive Prefix-/Proton-/GPU-/DXVK- und SpaceMouse-Einstellungen. Autodesk Fusion
selbst verwendet weiterhin seinen eigenen Updater. Eine GUI-Neuinstallation
installiert weder Steam noch ein Proton-Paket; diese müssen zuvor vorhanden sein.

**Laufzeit** wählt einen vorhandenen Prefix-Ordner und einen tatsächlich
installierten Proton-Ordner. Die Auswahl wird in `prefix-dir`, `proton-version`
und `proton-path` gespeichert; dadurch funktionieren auch benutzerdefinierte
Proton-Versionen aus weiteren Steam-Bibliotheken. **Fusion starten** benutzt
unverändert den produktiven Launcher und schreibt Startfehler nach
`logs/manager-launch.log`. Eine laufende Fusion-Sitzung verhindert Installation,
Updates, SDK-Wechsel und Profiländerungen, ohne Prozesse zu beenden.

## Zustandsquellen und Grenzen

- Fusion-Version: `fusion_version.txt`, ersatzweise `version.json` neben der
  tatsächlich gewählten `Fusion360.exe`. Keine erfundene Version bei Fehlen.
- Installierte Linux-Version/Revision: `repo-state.json`. Bei einer älteren
  vorhandenen Installation ohne Metadaten wird die Zuordnung als unbekannt gezeigt.
- Repo: tatsächliche Git-Revision, Branch, Arbeitsverzeichnis und Upstream.
- SpaceMouse: Linux-sysfs-Geräteidentität, ACL-Lesbarkeit und echter Brückenstatus.
  Die Live-Anzeige liest nur `status.json` alle 100 ms; ein separater 5-s-Timer
  aktualisiert Installations-/Git-/Protonstatus. Netzwerkzugriff erfolgt auf Aktion.
- Kamerawerte werden nur vorgemerkt. Fusion-Präferenzen ändern sich erst bei
  geschlossenem Fusion vor dem nächsten Start. Unter 25 % gilt die vorhandene
  Signaturprüfung für unterstützte Fusion-Versionen.

Für den USB-Universal-Receiver 256f:c652 bevorzugt die Brücke direkte HID-Reports.
Nur der eng geprüfte 448-Byte-Descriptor wird akzeptiert; weitere Receiver-
Interfaces werden nicht als Achseneingang gewählt. Fehlende HID-Leserechte zeigt
sie als **Rohzugriff einrichten**. Der benannte evdev-Fallback ist eingeschränkt:
Eine konstante Auslenkung wird nach 250 ms ohne ABS-Änderung sicher neutralisiert.
Er ersetzt damit keine vollständige native Haltebewegung.

**Gerätezugriff einrichten** startet ausschließlich auf ausdrücklichen Klick
`pkexec` mit einem festen, argumentlosen C++-Helfer. Nach Administratorfreigabe
kann dieser nur die enge uaccess-Regel
`/etc/udev/rules.d/70-fusion-spacemouse.rules` für USB 256f:c652 anlegen und die
udev-Regeln neu laden. Kein MODE=0666, keine wählbaren Root-Pfade/Kommandos und
kein Root-Dauerdienst. **Empfänger danach abziehen und neu anschließen**; die
aktive lokale Sitzung bekommt den Gerätezugriff. Ohne pkexec oder bei Abbruch
bleiben Rechte unverändert. Status/Start/Installation führen diese Aktion nicht
automatisch aus. Details und Regeltext: [SpaceMouse-Anleitung](../spacemouse/README.md).

HID-Motionreports werden einzeln und ohne künstliche Wiederholung weitergereicht.
250 ms ohne weiteren Motionreport bei letzter nichtneutraler Auslenkung lösen
einmalig Neutral und Tastenfreigabe aus. Batterie-/Vendorstatusreports verlängern
diese Frist nicht. Daraus wird kein Funkzustand oder echter Hardwaretakt abgeleitet.
Der reale Hand-/Halte-/Funkverlust-Test steht bis zur erlaubten Geräteprüfung aus.
Eine alte installierte Treiberintegration wird aus der neuen Oberfläche erst
bedienbar, nachdem der aktuelle Checkout bei geschlossenem Fusion angewendet wurde.

Nur die lokale Instanz pro Benutzer kann gleichzeitig eine Manager-Aktion
starten. Ein laufendes Installations-/Updateverfahren kann nicht durch Schließen
des GUI-Fensters abgebrochen werden; der native Autodesk-Installer bleibt bedienbar.

## Reproduzierbare Prüfung

```sh
make -C layer
make -C manager
bash spacemouse/build.sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s spacemouse/tests -p test_evdev.py -v
python3 -m unittest discover -s spacemouse/tests -p test_hidraw.py -v
python3 -m unittest discover -s spacemouse/tests -p test_camera_gain.py -v
python3 -m unittest discover -s spacemouse/tests -p test_processes.py -v
QT_QPA_PLATFORM=offscreen ./manager/run.sh --smoke-test --target /tmp/fusion-empty
QT_QPA_PLATFORM=offscreen ./manager/run.sh --screenshot /tmp/fusion-manager.png
```

`--app-dir` ist ein Alias für `--target`. `--page spacemouse` oder `--page setup`
und `--size 1130x1200` erlauben reproduzierbare Screenshots weiterer Seiten. Screenshot und Smoke-Test sind lesend:
sie starten weder Fusion noch die Brücke und schreiben keine Installation.
Die Tests verwenden lokale Git-Repositories, temporäre Installationsordner und
für den echten Daemon eine Pipe oder einen SOCK_SEQPACKET-Kanal als Eventquelle
plus einen freien TCP-Testport. Die Rechteaktion wird gemockt; es wird keine
produktive udev-Regel angelegt.
Produktive Geräte/Services werden dabei nicht umgeschaltet.

Der Manager und die direkte Linux-Eingabeschicht sind eigene Implementierungen.
Der verwendete ältere Wine-SDK-Bridge-Code bleibt GPL-3.0-or-later, MinHook
behält seine eigene Lizenz. Siehe `spacemouse/bridge/COPYING` und die Quellhinweise
in `spacemouse/README.md`. Qt wird dynamisch gebunden.
