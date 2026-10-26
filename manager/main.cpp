// SPDX-License-Identifier: GPL-3.0-or-later
// Native Fusion Manager. GPL-3.0-or-later; Qt is dynamically linked.
#include <QDesktopServices>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>
#include <QUrl>
#include <QtWidgets>
#include <array>
#include <unistd.h>

static QString text(const QJsonObject &o, const char *key,
                    const QString &fallback = QStringLiteral("Unbekannt")) {
    const auto value = o.value(QLatin1String(key));
    return value.isString() && !value.toString().isEmpty() ? value.toString() : fallback;
}
static QLabel *label(const QString &value, const char *kind = "") {
    auto *w = new QLabel(value);
    w->setWordWrap(true);
    w->setProperty("kind", kind);
    return w;
}
static QGroupBox *card(const QString &title, QVBoxLayout *layout) {
    auto *box = new QGroupBox(QString(title).replace("&", "&&"));
    box->setLayout(layout);
    return box;
}
class Manager : public QMainWindow {
    QString backend, screenshot, currentAction;
    bool smoke = false, loaded = false, busy = false;
    QLineEdit *target = new QLineEdit, *repo = new QLineEdit, *installer = new QLineEdit;
    QComboBox *prefix = new QComboBox;
    QComboBox *proton = new QComboBox;
    QCheckBox *withSpace = new QCheckBox("SpaceMouse mit einrichten");
    QLabel *headline = label("Installation wird geprüft …", "hero"), *subtitle = label(""),
           *fusionInfo = label(""), *repoInfo = label("");
    QLabel *driverInfo = label(""), *hardwareInfo = label(""), *deviceSummary = label(""), *buttonState = label("");
    QLabel *inputAccessInfo = label("", "warning"), *inputStateInfo = label("");
    QLabel *result = label("Bereit"), *cameraHint = label("Wirksam beim nächsten Start von Fusion.");
    QPlainTextEdit *log = new QPlainTextEdit;
    QProgressBar *progress = new QProgressBar;
    QSpinBox *deadzone = new QSpinBox, *camera = new QSpinBox;
    std::array<QCheckBox *, 6> enabled{}, inverted{};
    std::array<QLabel *, 6> live{};
    std::array<QComboBox *, 2> buttons{};
    QListWidget *nav = new QListWidget;
    QStackedWidget *pages = new QStackedWidget;
    QProcess *statusProc = new QProcess(this), *operation = new QProcess(this);
    QJsonObject last;
    QList<QWidget *> mutationControls;
    QByteArray statusBytes;
    QTimer refresh, liveRefresh;

    QPushButton *actionButton(const QString &title, const QString &action, const QStringList &extra = {},
                              bool primary = false) {
        auto *button = new QPushButton(QString(title).replace("&", "&&"));
        button->setProperty("primary", primary);
        button->setProperty("action", action);
        connect(button, &QPushButton::clicked, this, [this, action, extra] { startAction(action, extra); });
        mutationControls.append(button);
        return button;
    }
    QWidget *pathRow(QLineEdit *edit, const QString &placeholder, bool file = false) {
        edit->setPlaceholderText(placeholder);
        auto *row = new QWidget;
        auto *layout = new QHBoxLayout(row);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->addWidget(edit, 1);
        auto *browse = new QPushButton("Auswählen …");
        layout->addWidget(browse);
        connect(browse, &QPushButton::clicked, this, [this, edit, file] {
            QString value = file ? QFileDialog::getOpenFileName(this, "Autodesk-Installer wählen",
                                                                edit->text(), "Windows-Installer (*.exe)")
                                 : QFileDialog::getExistingDirectory(this, "Ordner wählen", edit->text());
            if (!value.isEmpty()) {
                edit->setText(value);
                if (edit == target || edit == repo) {
                    loaded = false;
                    requestStatus();
                }
            }
        });
        mutationControls.append(edit);
        mutationControls.append(browse);
        return row;
    }
    QWidget *page(const QString &title, const QString &description, QVBoxLayout *&layout) {
        auto *widget = new QWidget;
        layout = new QVBoxLayout(widget);
        layout->setContentsMargins(30, 24, 30, 22);
        layout->setSpacing(16);
        layout->addWidget(label(title, "title"));
        layout->addWidget(label(description, "muted"));
        auto *scroll = new QScrollArea;
        scroll->setWidgetResizable(true);
        scroll->setFrameShape(QFrame::NoFrame);
        scroll->setWidget(widget);
        pages->addWidget(scroll);
        return widget;
    }
    QStringList base() const {
        QStringList args = {backend, "--target", target->text()};
        if (!repo->text().isEmpty())
            args << "--repo" << repo->text();
        return args;
    }
    void requestStatus() {
        if (statusProc->state() != QProcess::NotRunning || busy || target->text().isEmpty())
            return;
        statusBytes.clear();
        statusProc->start("python3", base());
    }
    void startAction(const QString &action, QStringList extra = {}) {
        if (busy)
            return;
        if (action == "status") {
            requestStatus();
            return;
        }
        if (action == "settings") {
            QJsonArray axes, inversions, binds;
            for (int i = 0; i < 6; ++i) {
                axes.append(enabled[i]->isChecked());
                inversions.append(inverted[i]->isChecked());
            }
            for (auto *button : buttons)
                binds.append(button->currentData().toString());
            QJsonObject config{{"deadzone", deadzone->value()},
                               {"enabled", axes},
                               {"inverted", inversions},
                               {"buttons", binds}};
            extra << "--settings" << QString::fromUtf8(QJsonDocument(config).toJson(QJsonDocument::Compact));
        } else if (action == "camera")
            extra << "--percent" << QString::number(camera->value());
        else if (action == "profile")
            extra << "--prefix" << prefix->currentText() << "--proton" << proton->currentData().toString();
        else if (action == "install" || action == "patch" || action == "apply" || action == "update") {
            if (withSpace->isChecked())
                extra << "--spacemouse";
            if (action == "install") {
                if (!installer->text().isEmpty())
                    extra << "--installer" << installer->text();
                extra << "--prefix"
                      << (prefix->currentText().isEmpty() ? "compatdata-exp-dx11" : prefix->currentText());
                if (!proton->currentData().toString().isEmpty())
                    extra << "--proton" << proton->currentData().toString();
            }
        }
        currentAction = action;
        busy = true;
        for (auto *widget : mutationControls)
            widget->setEnabled(false);
        progress->show();
        result->setText("Aktion läuft …");
        log->appendPlainText("\n› " + action + "\n");
        operation->setProcessChannelMode(QProcess::MergedChannels);
        operation->start("python3", base() + QStringList{"--action", action} + extra);
    }
    void updateStatus(const QJsonObject &s) {
        last = s;
        updateAvailability();
        const auto r = s["repo"].toObject(), installed = s["installed"].toObject();
        const bool present = s["fusion"].isString(), running = s["running"].toBool();
        headline->setText(running ? "Fusion läuft" : present ? "Fusion ist bereit" : "Fusion einrichten");
        subtitle->setText(present ? "Autodesk Fusion " + text(s, "fusion_version") + "  ·  " +
                                        (running ? "Aktive Sitzung" : "Bereit zum Starten")
                                  : "Wähle eine bestehende Installation oder starte eine neue Einrichtung.");
        fusionInfo->setText("Fusion-Version: " + text(s, "fusion_version", "Nicht installiert") +
                            "\nLinux-Integration: " +
                            text(installed, "version",
                                 s["integration_exists"].toBool() ? "Vorhanden · Version nicht zugeordnet"
                                                                  : "Noch nicht eingerichtet") +
                            "\nInstallierte Revision: " + text(installed, "revision", "Unbekannt").left(12) +
                            "\nPrefix: " + text(s, "prefix") + "\nProton: " + text(s, "proton") +
                            "\nPfad: " + text(s, "fusion", "Keine Fusion360.exe gefunden"));
        QString gitInfo = "Checkout: " + text(r, "path", "Nicht zugeordnet");
        if (r["valid"].toBool()) {
            gitInfo += "\nRepo-Version: " + text(r, "version") + "  ·  Branch: " + text(r, "branch") +
                       "\nRevision: " + text(r, "revision").left(12);
            gitInfo += r["dirty"].toBool()
                           ? "\nLokale Änderungen vorhanden – Git-Update schützt diese Dateien."
                           : "\nArbeitsverzeichnis unverändert.";
            if (r["behind"].isDouble())
                gitInfo += "\n" + QString::number(r["behind"].toInt()) + " neue Commits, " +
                           QString::number(r["ahead"].toInt()) + " eigene Commits gegenüber " +
                           text(r, "upstream");
            else
                gitInfo += "\nKein Upstream zum Vergleichen eingerichtet.";
            gitInfo +=
                r["checked"].isDouble()
                    ? "\nLetzter Abruf: " + QDateTime::fromSecsSinceEpoch(qint64(r["checked"].toDouble()))
                                                .toString("dd.MM.yyyy HH:mm")
                    : "\nNoch kein Remote-Abruf. Mit „Updates prüfen“ vergleichen.";
        } else
            gitInfo += "\nKein verwendbarer Git-Checkout. Bitte unter Einrichtung auswählen.";
        repoInfo->setText(gitInfo);
        QStringList devices;
        for (const auto &entry : s["devices"].toArray()) {
            auto d = entry.toObject();
            devices << (text(d, "backend", "evdev") == "hidraw" ? "Direktes HID · " : "evdev-Fallback · ") +
                           text(d, "name") + "  ·  " + text(d, "path") +
                           (d["readable"].toBool() ? "  ·  lesbar"
                                                   : "  ·  keine Leserechte in dieser Sitzung");
            devices << QString("USB %1:%2")
                           .arg(d["vendor"].toInt(), 4, 16, QChar('0'))
                           .arg(d["product"].toInt(), 4, 16, QChar('0'));
            const auto info = d["axis_info"].toArray();
            if (!info.isEmpty()) {
                auto a = info[0].toObject();
                QString detail =
                    QString("Bereich X: %1 bis %2").arg(a["minimum"].toInt()).arg(a["maximum"].toInt());
                if (a.contains("fuzz") && a.contains("flat"))
                    detail += QString(" · Fuzz %1 · Flat %2").arg(a["fuzz"].toInt()).arg(a["flat"].toInt());
                devices << detail;
            }
        }
        hardwareInfo->setText(
            devices.isEmpty()
                ? "Keine passende SpaceMouse gefunden. Gerät/Empfänger anschließen und einschalten."
                : devices.join("\n"));
        const auto detected = s["devices"].toArray();
        deviceSummary->setText(detected.isEmpty()
            ? "SpaceMouse anschließen und einschalten."
            : text(detected.first().toObject(), "name")
                  .replace("3Dconnexion 3Dconnexion", "3Dconnexion") + " · 6 Achsen");
        const auto access = s["input_access"].toObject();
        QString accessMessage;
        if (access["requires_setup"].toBool())
            accessMessage =
                "Rohzugriff einrichten: Der Universal Receiver ist erkannt, aber HID-Leserechte fehlen. "
                "Der evdev-Fallback ist eingeschränkt: Konstantes Halten wird nach 250 ms ohne "
                "Achsenänderung unterbrochen. "
                "Für vollständige Originalreports „Gerätezugriff einrichten“ wählen und den Empfänger danach "
                "neu anschließen.";
        else if (access["hid_readable"].toBool())
            accessMessage = "Direkter HID-Rohzugriff ist verfügbar. Originalreports werden ohne künstliche "
                            "Wiederholung weitergereicht.";
        else
            accessMessage = "Kein geprüftes HID-Eingangsprofil gefunden. Ein verfügbarer evdev-Eingang ist "
                            "nur ein eingeschränkter Fallback; "
                            "konstantes Halten endet nach 250 ms ohne Achsenänderung.";
        if (!access["pkexec_available"].toBool())
            accessMessage +=
                " Für die einmalige Rechte-Einrichtung fehlt pkexec (Polkit-Paket der Distribution).";
        inputAccessInfo->setText(accessMessage);
        auto d = s["driver"].toObject();
        driverInfo->setText(QString("Anbindung: ") +
                            (s["spacemouse_enabled"].toBool() ? "aktiviert" : "deaktiviert") + "\nBrücke: " +
                            (d["fresh"].toBool()           ? "läuft"
                             : s["direct_driver"].toBool() ? "gestoppt / kein aktueller Status"
                                                           : "vorhandene Integration noch nicht übernommen") +
                            (d["fresh"].toBool() ? "  ·  " + QString::number(d["clients"].toInt()) +
                                                       " Fusion-Verbindung(en)\n" + text(d, "error", "")
                                                 : ""));
        if (!loaded) {
            if (repo->text().isEmpty())
                repo->setText(text(r, "path", ""));
            prefix->clear();
            for (const auto &entry : s["prefixes"].toArray())
                prefix->addItem(entry.toString());
            prefix->setCurrentText(text(s, "prefix", "compatdata-exp-dx11"));
            proton->clear();
            for (const auto &entry : s["protons"].toArray()) {
                auto p = entry.toObject();
                proton->addItem(text(p, "name") + "  —  " + text(p, "path"), text(p, "path"));
                if (text(p, "path") == text(s, "proton_path", "") || text(p, "name") == text(s, "proton", ""))
                    proton->setCurrentIndex(proton->count() - 1);
            }
            withSpace->setChecked(s["spacemouse_installed"].toBool() || !present);
            auto config = s["device_config"].toObject();
            deadzone->setValue(config["deadzone"].toInt());
            for (int i = 0; i < 6; ++i) {
                enabled[i]->setChecked(config["enabled"].toArray()[i].toBool());
                inverted[i]->setChecked(config["inverted"].toArray()[i].toBool());
            }
            for (int i = 0; i < 2; ++i) {
                int index = buttons[i]->findData(config["buttons"].toArray()[i].toString());
                if (index >= 0)
                    buttons[i]->setCurrentIndex(index);
            }
            camera->setValue(s["camera"].toObject()["percent"].toInt(25));
            loaded = true;
        }
        if (!s["error"].isNull() && !text(s, "error", "").isEmpty())
            result->setText(text(s, "error"));
        if (smoke || !screenshot.isEmpty()) {
            QTimer::singleShot(300, this, [this] {
                const bool ok = screenshot.isEmpty() || grab().save(screenshot);
                QApplication::exit(ok ? 0 : 1);
            });
        }
    }
    void updateAvailability() {
        const bool running = last["running"].toBool();
        const auto r = last["repo"].toObject();
        for (auto *widget : mutationControls) {
            QString reason;
            const QString action = widget->property("action").toString();
            if (busy)
                reason = "Eine Aktion läuft bereits.";
            else if (action == "launch" && running)
                reason = "Fusion läuft bereits.";
            else if (action == "launch" && !last["fusion"].isString())
                reason = "Fusion ist noch nicht installiert.";
            else if (running &&
                     (action == "update" || action == "install" || action == "patch" || action == "apply" ||
                      action == "profile" || action == "enable" || action == "disable"))
                reason = "Fusion vor dieser Änderung vollständig schließen.";
            else if ((action == "driver-start" || action == "driver-stop" || action == "enable" ||
                      action == "disable") &&
                     !last["direct_driver"].toBool())
                reason = "Checkout zuerst anwenden. Die vorhandene ältere Treiberintegration bleibt bis "
                         "dahin unverändert.";
            else if (action == "setup-access" &&
                     !last["input_access"].toObject()["pkexec_available"].toBool())
                reason = "pkexec fehlt. Das Polkit-Paket der Distribution wird für die einmalige Freigabe "
                         "benötigt.";
            else if (action == "setup-access" &&
                     !last["input_access"].toObject()["helper_available"].toBool())
                reason = "Der feste Zugriffshelfer fehlt; bitte Manager bauen oder aktualisieren.";
            else if (action == "clone" && r["valid"].toBool())
                reason = "Der ausgewählte Checkout ist bereits vorhanden.";
            else if ((action == "update" || action == "check" || action == "apply" || action == "install" ||
                      action == "patch") &&
                     !r["valid"].toBool())
                reason = "Zuerst einen gültigen Checkout auswählen.";
            else if (action == "update" && r["dirty"].toBool())
                reason = "Lokale Änderungen zuerst selbst sichern oder committen.";
            else if (action == "update" && (!r["upstream"].isString() || r["ahead"].toInt() > 0))
                reason = "Kein eindeutiger Fast-Forward-Pfad zum Upstream.";
            widget->setEnabled(reason.isEmpty());
            widget->setToolTip(reason);
        }
    }

  public:
    Manager(const QString &backendPath, const QString &appPath, const QString &repoPath,
            const QString &capture, bool smokeTest)
        : backend(backendPath), screenshot(capture), smoke(smokeTest) {
        setWindowTitle("Fusion Manager");
        resize(1130, 850);
        setMinimumSize(880, 640);
        prefix->setEditable(true);
        for (auto *edit : {target, repo})
            connect(edit, &QLineEdit::editingFinished, this, [this] {
                loaded = false;
                requestStatus();
            });
        target->setText(appPath);
        repo->setText(repoPath);
        proton->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
        proton->setMinimumContentsLength(18);
        auto *root = new QWidget;
        auto *shell = new QHBoxLayout(root);
        shell->setContentsMargins(0, 0, 0, 0);
        shell->setSpacing(0);
        setCentralWidget(root);
        auto *rail = new QWidget;
        rail->setObjectName("rail");
        rail->setFixedWidth(205);
        auto *rl = new QVBoxLayout(rail);
        rl->setContentsMargins(20, 28, 16, 20);
        rl->addWidget(label("FUSION\nMANAGER", "brand"));
        rl->addSpacing(22);
        nav->addItems({"Übersicht", "SpaceMouse", "Einrichtung", "Protokoll"});
        nav->setFrameShape(QFrame::NoFrame);
        nav->setSpacing(6);
        rl->addWidget(nav, 1);
        rl->addWidget(label("Fusion Manager 1.2.0\nFür deinen Linux-Arbeitsplatz", "railnote"));
        shell->addWidget(rail);
        auto *right = new QWidget;
        auto *rightLayout = new QVBoxLayout(right);
        rightLayout->setContentsMargins(0, 0, 0, 0);
        rightLayout->setSpacing(0);
        rightLayout->addWidget(pages, 1);
        auto *footer = new QWidget;
        footer->setObjectName("footer");
        auto *fl = new QHBoxLayout(footer);
        fl->setContentsMargins(28, 10, 28, 10);
        fl->addWidget(result, 1);
        progress->setFixedSize(130, 7);
        progress->setRange(0, 0);
        progress->hide();
        fl->addWidget(progress);
        rightLayout->addWidget(footer);
        shell->addWidget(right, 1);
        QVBoxLayout *v;
        page("Dein Arbeitsplatz", "Fusion, Linux-Integration und Hardware an einem Ort verwalten.", v);
        auto *hero = new QVBoxLayout;
        hero->addWidget(headline);
        hero->addWidget(subtitle);
        auto *heroActions = new QHBoxLayout;
        heroActions->addWidget(actionButton("Fusion starten", "launch", {}, true));
        heroActions->addWidget(actionButton("Status aktualisieren", "status"));
        heroActions->addStretch();
        hero->addLayout(heroActions);
        v->addWidget(card("", hero));
        auto *info = new QVBoxLayout;
        info->addWidget(fusionInfo);
        v->addWidget(card("Installation", info));
        auto *git = new QVBoxLayout;
        git->addWidget(repoInfo);
        auto *gitActions = new QHBoxLayout;
        gitActions->addWidget(actionButton("Updates prüfen", "check"));
        gitActions->addWidget(actionButton("Repository laden", "clone"));
        gitActions->addWidget(actionButton("Git-Update installieren", "update", {}, true));
        gitActions->addStretch();
        git->addLayout(gitActions);
        v->addWidget(card("Repository & Updates", git));
        v->addWidget(label("Git-Updates verwenden Fast-Forward und bewahren lokale Änderungen. Während "
                           "Fusion läuft, sind Änderungen an Installation, Prefix und Proton gesperrt.",
                           "muted"));
        v->addStretch();
        page("SpaceMouse",
             "Volle Hardware-Auflösung. Native Achsenkonvention. Keine Eingabeskalierung oder Glättung.", v);
        auto *device = new QVBoxLayout;
        device->addWidget(deviceSummary);
        auto *details = new QToolButton;
        details->setText("Technische Gerätedaten");
        details->setCheckable(true);
        details->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        details->setArrowType(Qt::RightArrow);
        hardwareInfo->hide();
        connect(details, &QToolButton::toggled, this, [this, details](bool visible) {
            hardwareInfo->setVisible(visible);
            details->setArrowType(visible ? Qt::DownArrow : Qt::RightArrow);
        });
        device->addWidget(details, 0, Qt::AlignLeft);
        device->addWidget(hardwareInfo);
        device->addWidget(driverInfo);
        device->addWidget(inputStateInfo);
        device->addWidget(inputAccessInfo);
        device->addWidget(actionButton("Gerätezugriff einrichten", "setup-access", {}, true));
        device->addWidget(label(
            "Diese ausdrückliche Aktion öffnet die Administratorfreigabe für eine enge Gerätezugriffsregel. "
            "Danach den Universal Receiver abziehen und neu anschließen.",
            "muted"));
        auto *da = new QHBoxLayout;
        for (const auto &pair : {qMakePair(QString("Brücke starten"), QString("driver-start")),
                                 qMakePair(QString("Brücke stoppen"), QString("driver-stop")),
                                 qMakePair(QString("Aktivieren"), QString("enable")),
                                 qMakePair(QString("Deaktivieren"), QString("disable"))})
            da->addWidget(actionButton(pair.first, pair.second));
        device->addLayout(da);
        v->addWidget(card("Gerät & Verbindung", device));
        auto *axisLayout = new QVBoxLayout;
        auto *grid = new QGridLayout;
        QStringList names = {"X · links / rechts", "Y · hoch / runter", "Z · vor / zurück",
                             "RX · kippen",        "RY · drehen",       "RZ · rollen"};
        grid->addWidget(label("Achse"), 0, 0);
        grid->addWidget(label("Eingabe"), 0, 1);
        grid->addWidget(label("Aktiv"), 0, 2);
        grid->addWidget(label("Umkehren"), 0, 3);
        for (int i = 0; i < 6; ++i) {
            live[i] = label("—");
            live[i]->setProperty("kind", "value");
            enabled[i] = new QCheckBox;
            inverted[i] = new QCheckBox;
            grid->addWidget(label(names[i]), i + 1, 0);
            grid->addWidget(live[i], i + 1, 1);
            grid->addWidget(enabled[i], i + 1, 2);
            grid->addWidget(inverted[i], i + 1, 3);
            mutationControls << enabled[i] << inverted[i];
        }
        axisLayout->addLayout(grid);
        auto *dz = new QHBoxLayout;
        deadzone->setRange(0, 100);
        deadzone->setSuffix(" Counts");
        dz->addWidget(label("Deadzone"));
        dz->addWidget(deadzone);
        dz->addStretch();
        axisLayout->addLayout(dz);
        axisLayout->addWidget(label("Standard: 0. Kleinste Hardwarecounts bleiben erhalten. Die Werte zeigen "
                                    "die an Fusion übergebenen Achsen.",
                                    "muted"));
        v->addWidget(card("Achsen · Live", axisLayout));
        auto *binding = new QVBoxLayout;
        auto *bf = new QFormLayout;
        for (int i = 0; i < 2; ++i) {
            buttons[i] = new QComboBox;
            for (const auto &pair :
                 {qMakePair(QString("Abbrechen · Esc"), QString("ESC")),
                  qMakePair(QString("Messen · I"), QString("I")),
                  qMakePair(QString("Taste F"), QString("F")),
                  qMakePair(QString("Home"), QString("HOME")), qMakePair(QString("Taste 1"), QString("1")),
                  qMakePair(QString("Taste 2"), QString("2")), qMakePair(QString("Taste 3"), QString("3")),
                  qMakePair(QString("Nativer SDK-Button"), QString("sdk")),
                  qMakePair(QString("Keine Aktion"), QString("off"))})
                buttons[i]->addItem(pair.first, pair.second);
            bf->addRow(i == 0 ? "Linke Taste" : "Rechte Taste", buttons[i]);
            mutationControls << buttons[i];
        }
        binding->addLayout(bf);
        binding->addWidget(buttonState);
        binding->addWidget(label("Tastaturaktionen gelten nur bei Fusion-Fokus. Tasten werden bei "
                                 "Fokusverlust und Trennung freigegeben.",
                                 "muted"));
        binding->addWidget(actionButton("Achsen & Tasten speichern", "settings", {}, true));
        v->addWidget(card("Tasten", binding));
        auto *speed = new QVBoxLayout;
        auto *speedRow = new QHBoxLayout;
        camera->setRange(1, 100);
        camera->setSuffix(" %");
        speedRow->addWidget(label("Kamerageschwindigkeit"));
        speedRow->addWidget(camera);
        speedRow->addWidget(actionButton("Für nächsten Start speichern", "camera"));
        speedRow->addStretch();
        speed->addLayout(speedRow);
        speed->addWidget(cameraHint);
        speed->addWidget(
            label("Die Geschwindigkeit wird nach der Eingabe in Fusion angepasst. Die Hardwarewerte werden "
                  "nicht gerundet. Werte unter 25 % benötigen eine unterstützte Fusion-Version.",
                  "muted"));
        v->addWidget(card("Kamera", speed));
        v->addStretch();
        mutationControls << camera << deadzone;
        page("Einrichtung",
             "Bestehende Installation übernehmen, neu installieren oder den lokalen Repo-Stand anwenden.", v);
        auto *paths = new QVBoxLayout;
        paths->addWidget(label("Installationsordner"));
        paths->addWidget(pathRow(target, "~/.local/share/autodesk-fusion"));
        paths->addWidget(label("Lokaler Git-Checkout"));
        paths->addWidget(pathRow(repo, "fusion-linux-dx11"));
        v->addWidget(card("Orte", paths));
        auto *profile = new QVBoxLayout;
        auto *pf = new QFormLayout;
        pf->addRow("Aktives Prefix", prefix);
        pf->addRow("Installiertes Proton", proton);
        profile->addLayout(pf);
        profile->addWidget(actionButton("Prefix & Proton übernehmen", "profile"));
        profile->addWidget(label("Bestehende Prefix-Ordner bleiben erhalten. Proton wird aus deinen Steam- "
                                 "und benutzerdefinierten Kompatibilitätstools gewählt.",
                                 "muted"));
        v->addWidget(card("Laufzeit", profile));
        mutationControls << prefix << proton;
        auto *setup = new QVBoxLayout;
        setup->addWidget(withSpace);
        setup->addWidget(label(
            "Autodesk-Installer (optional). Ohne Datei wird der offizielle Installer geladen.", "muted"));
        setup->addWidget(pathRow(installer, "Fusion360installer.exe", true));
        auto *installActions = new QHBoxLayout;
        installActions->addWidget(actionButton("Neu installieren", "install", {}, true));
        installActions->addWidget(actionButton("Vorhandene Installation einrichten", "patch"));
        setup->addLayout(installActions);
        setup->addWidget(actionButton("Aktuellen Checkout anwenden", "apply"));
        setup->addWidget(
            label("Eine Neuinstallation verwendet einen freien Installationsordner. Autodesk-Setup und "
                  "Anmeldung laufen in einem eigenen Fenster. Der Fortschritt steht im Protokoll. Updates "
                  "sichern ersetzte Helferdateien unter backups/updates.",
                  "muted"));
        v->addWidget(card("Installation & Reparatur", setup));
        v->addStretch();
        mutationControls << withSpace;
        page("Protokoll", "Ausgaben der gestarteten Aktionen und genaue Fehlermeldungen.", v);
        log->setReadOnly(true);
        log->setMaximumBlockCount(3000);
        log->setMinimumHeight(340);
        v->addWidget(log, 1);
        auto *logButtons = new QHBoxLayout;
        auto *copy = new QPushButton("Protokoll kopieren");
        connect(copy, &QPushButton::clicked, this,
                [this] { QApplication::clipboard()->setText(log->toPlainText()); });
        logButtons->addWidget(copy);
        auto *open = new QPushButton("Logordner öffnen");
        connect(open, &QPushButton::clicked, this,
                [this] { QDesktopServices::openUrl(QUrl::fromLocalFile(target->text() + "/logs")); });
        logButtons->addWidget(open);
        logButtons->addStretch();
        v->addLayout(logButtons);
        connect(nav, &QListWidget::currentRowChanged, pages, &QStackedWidget::setCurrentIndex);
        nav->setCurrentRow(0);
        connect(statusProc, &QProcess::readyReadStandardOutput, this,
                [this] { statusBytes += statusProc->readAllStandardOutput(); });
        connect(statusProc, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
                [this](int code, QProcess::ExitStatus) {
                    QJsonParseError error;
                    auto doc = QJsonDocument::fromJson(statusBytes, &error);
                    if (code == 0 && error.error == QJsonParseError::NoError && doc.isObject())
                        updateStatus(doc.object());
                    else {
                        result->setText("Status konnte nicht gelesen werden.");
                        log->appendPlainText(QString::fromUtf8(statusProc->readAllStandardError()));
                        if (smoke || !screenshot.isEmpty())
                            QApplication::exit(1);
                    }
                });
        connect(statusProc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError) {
            result->setText("Python 3 konnte nicht gestartet werden.");
            if (smoke || !screenshot.isEmpty())
                QApplication::exit(1);
        });
        connect(operation, &QProcess::readyReadStandardOutput, this, [this] {
            log->moveCursor(QTextCursor::End);
            log->insertPlainText(QString::fromUtf8(operation->readAllStandardOutput()));
            log->ensureCursorVisible();
        });
        connect(operation, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
                [this](int code, QProcess::ExitStatus state) {
                    busy = false;
                    updateAvailability();
                    progress->hide();
                    result->setText(code == 0 && state == QProcess::NormalExit
                                        ? "Aktion abgeschlossen"
                                        : "Aktion fehlgeschlagen · Details im Protokoll");
                    if (code == 0 && currentAction == "setup-access")
                        result->setText("Gerätezugriff vorbereitet · Universal Receiver neu anschließen");
                    log->appendPlainText("\nExit-Code: " + QString::number(code));
                    loaded = false;
                    requestStatus();
                    if (code != 0)
                        nav->setCurrentRow(3);
                });
        connect(operation, &QProcess::errorOccurred, this, [this](QProcess::ProcessError) {
            if (operation->state() == QProcess::NotRunning) {
                busy = false;
                updateAvailability();
                progress->hide();
                result->setText(operation->errorString());
            }
        });
        connect(&refresh, &QTimer::timeout, this, [this] { requestStatus(); });
        refresh.start(5000);
        connect(&liveRefresh, &QTimer::timeout, this, [this] {
            QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR", QString("/run/user/%1").arg(getuid()));
            QFile file(runtime + "/autodesk-fusion-spacemouse/status.json");
            QJsonObject state;
            if (file.open(QIODevice::ReadOnly))
                state = QJsonDocument::fromJson(file.readAll()).object();
            const bool fresh =
                state["timestamp"].isDouble() &&
                QDateTime::currentMSecsSinceEpoch() / 1000. - state["timestamp"].toDouble() >= 0 &&
                QDateTime::currentMSecsSinceEpoch() / 1000. - state["timestamp"].toDouble() <= 3;
            QString inputState = "Kein aktueller Eingangsstatus";
            if (fresh) {
                inputState = state["input_backend"].toString() == "hidraw" ? "Aktiver Eingang: direktes HID"
                             : state["input_backend"].toString() == "evdev"
                                 ? "Aktiver Eingang: eingeschränkter evdev-Fallback"
                                 : "Kein Eingang verbunden";
                if (state["motion_watchdog"].toBool())
                    inputState += " · Sicherheitsstopp nach 250 ms ohne Bewegungsreport";
                const auto telemetry = state["telemetry"].toObject();
                if (telemetry["battery_strength"].isDouble())
                    inputState +=
                        " · Batteriestärke: " + QString::number(telemetry["battery_strength"].toInt()) +
                        "/100";
            }
            inputStateInfo->setText(inputState);
            const auto axes = state["axes"].toArray();
            for (int i = 0; i < 6; ++i)
                live[i]->setText(fresh && i < axes.size() ? QString::number(axes[i].toInt()) : "—");
            const auto b = state["buttons"].toArray();
            buttonState->setText(
                fresh ? QString("Links: ") + (b.size() > 0 && b[0].toBool() ? "gedrückt" : "frei") +
                            "   ·   Rechts: " + (b.size() > 1 && b[1].toBool() ? "gedrückt" : "frei")
                      : "Kein aktueller Eingabestatus");
        });
        liveRefresh.start(100);
        QTimer::singleShot(0, this, [this] { requestStatus(); });
    }
    void selectPage(int index) { nav->setCurrentRow(index); }
    void closeEvent(QCloseEvent *event) override {
        if (busy) {
            QMessageBox::information(
                this, "Aktion läuft",
                "Die laufende Aktion muss zuerst abgeschlossen werden. Details im Protokoll.");
            event->ignore();
            return;
        }
        event->accept();
    }
};
int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setApplicationName("Fusion Manager");
    app.setOrganizationName("fusion-linux-dx11");
    QCommandLineParser parser;
    parser.setApplicationDescription("Native Verwaltung für Fusion unter Linux und SpaceMouse");
    parser.addHelpOption();
    parser.addOption({"backend", "Python-Backend", "path"});
    parser.addOption(
        {{"target", "app-dir"},
         "Installationsordner",
         "path",
         QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/autodesk-fusion"});
    parser.addOption({"repo", "Git-Checkout", "path"});
    parser.addOption({"screenshot", "Fenster als PNG speichern und beenden", "path"});
    parser.addOption({"smoke-test", "Status lesend prüfen und beenden"});
    parser.addOption({"page", "Anfangsseite: overview, spacemouse, setup, log", "name", "overview"});
    parser.addOption({"size", "Fenstergröße für Screenshots, z.B. 1130x1200", "size"});
    parser.process(app);
    if (parser.value("backend").isEmpty()) {
        qCritical("--backend PATH fehlt. manager/run.sh oder installierten Manager-Starter verwenden.");
        return 2;
    }
    app.setStyle("Fusion");
    app.setFont(QFont("Sans Serif", 10));
    app.setStyleSheet(R"(
      QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {background:#f3f6fa;color:#1e293b;}
      QWidget {color:#243449;} QLabel {background:transparent;} QLabel[kind="title"] {font-size:27px;font-weight:700;color:#142539;} QLabel[kind="hero"] {font-size:25px;font-weight:700;color:#123b55;}
      QLabel[kind="warning"] {color:#8a570d;font-weight:600;} QLabel[kind="muted"] {color:#62748a;font-size:12px;} QLabel[kind="value"] {font-family:monospace;font-weight:700;color:#087f8c;}
      #rail {background:#10293d;} #rail QLabel {color:#e5f3f8;} #rail QLabel[kind="brand"] {font-size:24px;font-weight:800;letter-spacing:2px;} #rail QLabel[kind="railnote"] {color:#96b2c3;font-size:11px;}
      #rail QListWidget {background:transparent;color:#bdd0df;outline:0;border:0;font-size:14px;} #rail QListWidget::item {padding:13px 10px;border-radius:8px;} #rail QListWidget::item:selected {background:#1a4860;color:white;}
      QGroupBox {background:white;border:1px solid #dce4ed;border-radius:11px;margin-top:10px;padding:17px 16px 14px;font-weight:600;} QGroupBox::title {subcontrol-origin:margin;left:17px;padding:0 6px;color:#375168;}
      QPushButton {background:#edf3f8;border:1px solid #d7e2eb;border-radius:7px;padding:9px 12px;font-weight:600;} QPushButton:hover {background:#dfebf3;} QPushButton[primary="true"] {background:#087f8c;color:white;border-color:#087f8c;} QPushButton[primary="true"]:hover {background:#056b77;} QPushButton:disabled {color:#98a5b3;background:#edf0f4;}
      QLineEdit,QComboBox,QSpinBox {background:white;border:1px solid #cfdae5;border-radius:6px;padding:7px;min-height:21px;} QCheckBox {spacing:8px;font-weight:400;} QPlainTextEdit {background:#10293d;color:#d3e8ef;border:0;border-radius:9px;padding:12px;font-family:monospace;font-size:12px;}
      #footer {background:white;border-top:1px solid #dce4ed;} QProgressBar {background:#e3edf1;border:0;border-radius:3px;} QProgressBar::chunk {background:#087f8c;}
    )");
    Manager window(parser.value("backend"), parser.value("target"), parser.value("repo"),
                   parser.value("screenshot"), parser.isSet("smoke-test"));
    window.selectPage(QStringList{"overview", "spacemouse", "setup", "log"}.indexOf(parser.value("page")));
    const auto dimensions = parser.value("size").split('x');
    if (dimensions.size() == 2)
        window.resize(dimensions[0].toInt(), dimensions[1].toInt());
    window.show();
    return app.exec();
}
