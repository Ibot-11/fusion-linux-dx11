// SPDX-License-Identifier: GPL-3.0-or-later
// Native Fusion Manager. Qt is dynamically linked.
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
#include "i18n.h"
#include "shortcut.h"
#include "update_notice.h"

static QString text(const QJsonObject &object, const char *key,
                    const QString &fallback = I18n::tr("Unknown")) {
    const auto value = object.value(QLatin1String(key));
    return value.isString() && !value.toString().isEmpty() ? value.toString() : fallback;
}

static QLabel *label(const QString &value, const char *kind = "") {
    auto *widget = new QLabel(value);
    widget->setWordWrap(true);
    widget->setProperty("kind", kind);
    return widget;
}

static QToolButton *infoButton(const QString &title, const QString &explanation) {
    auto *button = new QToolButton;
    button->setText("i");
    button->setObjectName("infoButton");
    button->setFixedSize(22, 22);
    button->setToolTip(explanation);
    button->setAccessibleName(I18n::tr("About %1").arg(title));
    QObject::connect(button, &QToolButton::clicked, button,
                     [button, title, explanation] { QMessageBox::information(button, title, explanation); });
    return button;
}

static QFrame *panel(const QString &title, const QString &explanation, QVBoxLayout *content) {
    auto *frame = new QFrame;
    frame->setObjectName("panel");
    frame->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Maximum);
    auto *layout = new QVBoxLayout(frame);
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(13);
    auto *heading = new QHBoxLayout;
    heading->setSpacing(8);
    heading->addWidget(label(title, "section"));
    heading->addStretch();
    if (!explanation.isEmpty())
        heading->addWidget(infoButton(title, explanation));
    layout->addLayout(heading);
    layout->addLayout(content);
    return frame;
}

static QWidget *details(const QString &title, QWidget *content) {
    auto *widget = new QWidget;
    auto *layout = new QVBoxLayout(widget);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(10);
    auto *toggle = new QToolButton;
    toggle->setText(QString(title).replace("&", "&&"));
    toggle->setObjectName("disclosure");
    toggle->setCheckable(true);
    toggle->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    toggle->setArrowType(Qt::RightArrow);
    toggle->setAccessibleName(title);
    content->hide();
    QObject::connect(toggle, &QToolButton::toggled, widget, [toggle, content](bool expanded) {
        toggle->setArrowType(expanded ? Qt::DownArrow : Qt::RightArrow);
        content->setVisible(expanded);
    });
    layout->addWidget(toggle, 0, Qt::AlignLeft);
    layout->addWidget(content);
    return widget;
}

static QIcon navigationIcon(int index) {
    QPixmap pixmap(40, 40);
    pixmap.fill(Qt::transparent);
    pixmap.setDevicePixelRatio(2);
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(QPen(QColor("#b4c1d3"), 1.45, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
    if (index == 0) {
        for (int x : {3, 11})
            for (int y : {3, 11})
                painter.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1, 1);
    } else if (index == 1) {
        painter.drawEllipse(QRectF(4.5, 3, 11, 7));
        painter.drawArc(QRectF(4.5, 6, 11, 7), 180 * 16, 180 * 16);
        painter.drawLine(QPointF(4.5, 6.5), QPointF(4.5, 9.5));
        painter.drawLine(QPointF(15.5, 6.5), QPointF(15.5, 9.5));
        painter.drawRoundedRect(QRectF(3, 13, 14, 4), 1.5, 1.5);
    } else if (index == 2) {
        for (int y : {5, 10, 15})
            painter.drawLine(QPointF(3, y), QPointF(17, y));
        painter.setBrush(QColor("#1b2330"));
        painter.drawEllipse(QPointF(7, 5), 2, 2);
        painter.drawEllipse(QPointF(13, 10), 2, 2);
        painter.drawEllipse(QPointF(9, 15), 2, 2);
    } else {
        painter.drawRoundedRect(QRectF(2.5, 3.5, 15, 13), 1.5, 1.5);
        painter.drawLine(QPointF(6, 7), QPointF(9, 10));
        painter.drawLine(QPointF(9, 10), QPointF(6, 13));
        painter.drawLine(QPointF(11, 13), QPointF(14, 13));
    }
    return QIcon(pixmap);
}

class Manager : public QMainWindow {
    QString backend, screenshot, currentAction;
    bool smoke = false, loaded = false, busy = false;
    QLineEdit *target = new QLineEdit, *repo = new QLineEdit, *installer = new QLineEdit;
    QComboBox *prefix = new QComboBox, *proton = new QComboBox, *language = new QComboBox;
    QCheckBox *withSpace = new QCheckBox(I18n::tr("Include SpaceMouse"));
    QLabel *headline = label(I18n::tr("Checking…"), "badge"), *subtitle = label("", "muted"),
           *fusionInfo = label("", "detail"), *repoInfo = label("", "detail");
    QLabel *overviewPrefix = label("—"), *overviewProton = label("—"), *integrationVersion = label("—"),
           *repoSummary = label(I18n::tr("Checking…"), "summary"), *repoBranch = label("", "muted"),
           *repoCheck = label("", "muted"), *spaceOverview = label("", "muted"),
           *overviewCamera = label("", "muted"), *locationSummary = label("", "muted");
    QLabel *driverInfo = label("", "muted"), *hardwareInfo = label("", "detail"),
           *deviceSummary = label("", "summary"), *buttonState = label("", "muted");
    QLabel *inputAccessInfo = label("", "warning"), *inputStateInfo = label("", "muted");
    QWidget *accessPanel = new QWidget;
    QPushButton *cloneButton = nullptr;
    QLabel *result = label(I18n::tr("Ready"), "muted"), *cameraHint = label(I18n::tr("Saved for next launch"), "muted");
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

    static void selectButtonBinding(QComboBox *combo, const QJsonValue &binding) {
        int selected = -1, custom = -1;
        for (int i = 0; i < combo->count(); ++i) {
            if (combo->itemData(i, Qt::UserRole + 1).toBool()) custom = i;
            if (QJsonValue::fromVariant(combo->itemData(i)) == binding) selected = i;
        }
        if (selected < 0) {
            if (custom < 0) {
                combo->insertItem(0, Shortcuts::display(binding), binding.toVariant());
                combo->setItemData(0, true, Qt::UserRole + 1);
                selected = 0;
            } else {
                combo->setItemText(custom, Shortcuts::display(binding));
                combo->setItemData(custom, binding.toVariant());
                selected = custom;
            }
        }
        combo->setCurrentIndex(selected);
        combo->setProperty("binding", binding.toVariant());
    }

    QPushButton *actionButton(const QString &title, const QString &action, const QStringList &extra = {},
                              bool primary = false) {
        auto *button = new QPushButton(QString(title).replace("&", "&&"));
        button->setProperty("primary", primary);
        button->setProperty("action", action);
        button->setObjectName("action-" + action);
        connect(button, &QPushButton::clicked, this, [this, action, extra] { startAction(action, extra); });
        mutationControls.append(button);
        return button;
    }

    QWidget *pathRow(QLineEdit *edit, const QString &placeholder, bool file = false) {
        edit->setPlaceholderText(placeholder);
        auto *row = new QWidget;
        auto *layout = new QHBoxLayout(row);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(8);
        layout->addWidget(edit, 1);
        auto *browse = new QPushButton(I18n::tr("Browse…"));
        layout->addWidget(browse);
        connect(browse, &QPushButton::clicked, this, [this, edit, file] {
            QFileDialog dialog(this, I18n::tr(file ? "Choose Autodesk installer" : "Choose folder"), edit->text());
            dialog.setOption(QFileDialog::DontUseNativeDialog);
            dialog.setAcceptMode(QFileDialog::AcceptOpen);
            dialog.setFileMode(file ? QFileDialog::ExistingFile : QFileDialog::Directory);
            if (file)
                dialog.setNameFilter(I18n::tr("Windows executable (*.exe)"));
            else
                dialog.setOption(QFileDialog::ShowDirsOnly);
            dialog.setLabelText(QFileDialog::LookIn, I18n::tr("Look in:"));
            dialog.setLabelText(QFileDialog::FileName, I18n::tr("File name:"));
            dialog.setLabelText(QFileDialog::FileType, I18n::tr("Files of type:"));
            dialog.setLabelText(QFileDialog::Accept, I18n::tr(file ? "Open" : "Select"));
            dialog.setLabelText(QFileDialog::Reject, I18n::tr("Cancel"));
            const QString value = dialog.exec() == QDialog::Accepted ? dialog.selectedFiles().value(0) : QString();
            if (!value.isEmpty()) {
                edit->setText(value);
                if (edit == target || edit == repo) {
                    loaded = false;
                    requestStatus();
                }
            }
        });
        mutationControls << edit << browse;
        return row;
    }

    void page(const QString &title, const QString &explanation, QVBoxLayout *&layout) {
        auto *widget = new QWidget;
        widget->setObjectName("page");
        layout = new QVBoxLayout(widget);
        layout->setContentsMargins(26, 22, 26, 24);
        layout->setSpacing(16);
        auto *heading = new QHBoxLayout;
        heading->addWidget(label(title, "title"));
        heading->addStretch();
        if (!explanation.isEmpty())
            heading->addWidget(infoButton(title, explanation));
        layout->addLayout(heading);
        auto *scroll = new QScrollArea;
        scroll->setWidgetResizable(true);
        scroll->setFrameShape(QFrame::NoFrame);
        scroll->setWidget(widget);
        pages->addWidget(scroll);
    }

    static void detailLabel(QLabel *widget) {
        widget->setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
    }

    static void field(QGridLayout *layout, int row, const QString &name, QLabel *value) {
        auto *caption = label(name, "muted");
        layout->addWidget(caption, row, 0, Qt::AlignTop);
        layout->addWidget(value, row, 1);
        layout->setColumnStretch(1, 1);
        layout->setHorizontalSpacing(20);
        layout->setVerticalSpacing(12);
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

    void updateCameraStatus(const QJsonObject &state) {
        const QString mode = state["state"].toString();
        const int percent = state["percent"].toInt();
        if (mode == "live" && percent >= 1 && percent <= 100)
            cameraHint->setText(I18n::tr("Live · %1 %").arg(percent));
        else if (mode == "pending")
            cameraHint->setText(I18n::tr("Applying…"));
        else if (mode == "unsupported")
            cameraHint->setText(I18n::tr("Next launch · live unavailable"));
        else
            cameraHint->setText(I18n::tr("Saved for next launch"));
        const QString help = I18n::tr(
            "Apply saves the speed and updates a supported running Fusion session. "
            "Live confirms the speed reported by Fusion. Input counts remain unchanged. ");
        cameraHint->setToolTip(help + I18n::tr(state["reason"].toString()));
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
                binds.append(QJsonValue::fromVariant(button->currentData()));
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
        if (action == "update") {
            const QString notice = UpdateNotice::forRepository(last["repo"].toObject());
            if (!notice.isEmpty()) {
                result->setText(notice);
                log->appendPlainText("\n› update\n" + notice + "\n");
                return;
            }
        }
        currentAction = action;
        busy = true;
        for (auto *widget : mutationControls)
            widget->setEnabled(false);
        progress->show();
        result->setText(I18n::tr("Working…"));
        log->appendPlainText("\n› " + action + "\n");
        operation->setProcessChannelMode(QProcess::MergedChannels);
        operation->start("python3", base() + QStringList{"--action", action} + extra);
    }

    void updateStatus(const QJsonObject &s) {
        last = s;
        updateAvailability();
        updateCameraStatus(s["camera_live"].toObject());
        const auto r = s["repo"].toObject(), installed = s["installed"].toObject();
        const bool present = s["fusion"].isString(), running = s["running"].toBool();
        headline->setText(running ? I18n::tr("●  Running")
                                  : present ? I18n::tr("●  Ready") : I18n::tr("Not installed"));
        headline->setProperty("tone", running || present ? "good" : "neutral");
        headline->style()->unpolish(headline);
        headline->style()->polish(headline);
        subtitle->setText(present ? I18n::tr("Version %1").arg(text(s, "fusion_version"))
                                  : I18n::tr("Choose an installation in Setup"));
        overviewPrefix->setText(text(s, "prefix"));
        overviewProton->setText(text(s, "proton"));
        integrationVersion->setText(
            text(installed, "version",
                 s["integration_exists"].toBool() ? I18n::tr("Existing · unlinked")
                                                  : I18n::tr("Not configured")));
        fusionInfo->setText(I18n::tr("Fusion: %1\nIntegration: %2\nRevision: %3\nPrefix: %4\nProton: %5\nExecutable: %6")
                                .arg(text(s, "fusion_version", I18n::tr("Not installed")),
                                     text(installed, "version",
                                          s["integration_exists"].toBool()
                                              ? I18n::tr("Installed; version metadata unavailable")
                                              : I18n::tr("Not configured")),
                                     text(installed, "revision"), text(s, "prefix"), text(s, "proton"),
                                     text(s, "fusion", I18n::tr("Fusion360.exe not found"))));
        locationSummary->setText(QFileInfo(target->text()).fileName());
        locationSummary->setToolTip(target->text());

        QString gitInfo = I18n::tr("Checkout: %1").arg(text(r, "path", I18n::tr("Not linked")));
        if (r["valid"].toBool()) {
            const bool dirty = r["dirty"].toBool();
            const int ahead = r["ahead"].toInt(), behind = r["behind"].toInt();
            if (dirty)
                repoSummary->setText(I18n::tr("Local changes"));
            else if (!r["upstream"].isString())
                repoSummary->setText(I18n::tr("No update source"));
            else if (ahead > 0)
                repoSummary->setText(I18n::tr("Local commits"));
            else if (behind > 0)
                repoSummary->setText(I18n::tr(behind == 1 ? "%1 new commit" : "%1 new commits").arg(behind));
            else
                repoSummary->setText(I18n::tr(r["checked"].isDouble() ? "Up to date" : "Check for updates"));
            repoSummary->setProperty("tone", dirty || ahead ? "warning" : "normal");
            repoBranch->setText(text(r, "branch") + "  ·  " + text(r, "version", I18n::tr("Version unknown")));
            repoCheck->setText(r["checked"].isDouble()
                                   ? I18n::tr("Checked %1").arg(QLocale().toString(
                                         QDateTime::fromSecsSinceEpoch(qint64(r["checked"].toDouble())),
                                         QLocale::ShortFormat))
                                   : I18n::tr("Remote not checked yet"));
            gitInfo += "\n" + I18n::tr("Version: %1").arg(text(r, "version")) + "\n" +
                       I18n::tr("Branch: %1").arg(text(r, "branch")) + "\n" +
                       I18n::tr("Revision: %1").arg(text(r, "revision")) + "\n" +
                       I18n::tr(dirty ? "Working tree: local changes" : "Working tree: clean");
            if (r["behind"].isDouble())
                gitInfo += "\n" + I18n::tr("Upstream: %1\nBehind: %2 · Ahead: %3")
                                      .arg(text(r, "upstream"))
                                      .arg(behind)
                                      .arg(ahead);
            else
                gitInfo += "\n" + I18n::tr("No upstream configured");
            gitInfo += "\n" + repoCheck->text();
        } else {
            repoSummary->setText(I18n::tr("Checkout not found"));
            repoBranch->setText(I18n::tr("Select or restore a repository in Setup"));
            repoCheck->clear();
            gitInfo += "\n" + I18n::tr("No usable Git checkout. Choose a folder in Setup.");
        }
        repoSummary->style()->unpolish(repoSummary);
        repoSummary->style()->polish(repoSummary);
        repoInfo->setText(gitInfo);
        cloneButton->setVisible(!r["valid"].toBool());

        QStringList deviceDetails;
        const auto detected = s["devices"].toArray();
        for (const auto &entry : detected) {
            const auto device = entry.toObject();
            deviceDetails << (text(device, "backend", "evdev") == "hidraw" ? I18n::tr("Direct HID · ")
                                                                            : I18n::tr("evdev fallback · ")) +
                                 text(device, "name") + "\n" + text(device, "path") +
                                 I18n::tr(device["readable"].toBool() ? " · Read access" : " · No read access");
            deviceDetails << QString("USB %1:%2")
                                 .arg(device["vendor"].toInt(), 4, 16, QChar('0'))
                                 .arg(device["product"].toInt(), 4, 16, QChar('0'));
            const auto axes = device["axis_info"].toArray();
            if (!axes.isEmpty()) {
                const auto axis = axes[0].toObject();
                QString range = I18n::tr("X range: %1 to %2")
                                    .arg(axis["minimum"].toInt())
                                    .arg(axis["maximum"].toInt());
                if (axis.contains("fuzz") && axis.contains("flat"))
                    range += I18n::tr(" · Fuzz %1 · Flat %2")
                                 .arg(axis["fuzz"].toInt())
                                 .arg(axis["flat"].toInt());
                deviceDetails << range;
            }
            if (device["profile"].isString())
                deviceDetails << I18n::tr("Profile: %1").arg(text(device, "profile"));
            if (device["descriptor_sha256"].isString())
                deviceDetails << I18n::tr("Descriptor SHA-256: %1").arg(text(device, "descriptor_sha256"));
            deviceDetails << "";
        }
        deviceSummary->setText(detected.isEmpty() ? I18n::tr("No device detected")
                                                  : text(detected.first().toObject(), "name")
                                                        .replace("3Dconnexion 3Dconnexion", "3Dconnexion"));
        const auto access = s["input_access"].toObject();
        const bool needsAccess = access["requires_setup"].toBool();
        accessPanel->setVisible(needsAccess);
        inputAccessInfo->setText(access["pkexec_available"].toBool()
                                     ? I18n::tr("Raw device access required")
                                     : I18n::tr("Raw access required · Polkit is missing"));
        inputAccessInfo->setToolTip(I18n::tr(
            "The receiver is detected, but direct HID read access is missing. "
            "The evdev fallback interrupts a held deflection after 250 ms without axis changes. "
            "Set up device access, approve the administrator prompt, then unplug and reconnect the receiver. "
            "The helper installs only the identity-restricted uaccess rule; no root service is added."));

        const auto driver = s["driver"].toObject();
        const bool fresh = driver["fresh"].toBool();
        QString bridge = fresh                         ? I18n::tr("Bridge online")
                         : s["direct_driver"].toBool() ? I18n::tr("Bridge offline")
                                                       : I18n::tr("Apply checkout to enable controls");
        driverInfo->setText(I18n::tr(s["spacemouse_enabled"].toBool() ? "Enabled" : "Disabled") + "  ·  " +
                            bridge);
        if (fresh) {
            deviceDetails << I18n::tr("Fusion clients: %1").arg(driver["clients"].toInt());
            if (driver["error"].isString())
                deviceDetails << I18n::tr("Error: %1").arg(text(driver, "error", ""));
            if (driver["warning"].isString())
                deviceDetails << I18n::tr("Warning: %1").arg(text(driver, "warning", ""));
        }
        hardwareInfo->setText(deviceDetails.isEmpty()
                                  ? I18n::tr("Connect the receiver and switch on the SpaceMouse.")
                                  : deviceDetails.join("\n"));
        spaceOverview->setText(fresh && driver["connected"].toBool()
                                   ? (text(driver, "input_backend", "") == "hidraw"
                                          ? I18n::tr("Connected · Direct HID")
                                          : I18n::tr("Connected · evdev fallback"))
                               : detected.isEmpty() ? I18n::tr("No device detected")
                               : needsAccess        ? I18n::tr("Device access required")
                                                    : I18n::tr("Receiver detected"));
        overviewCamera->setText(I18n::tr("Camera %1%").arg(s["camera"].toObject()["percent"].toInt(25)));

        if (!loaded) {
            if (repo->text().isEmpty())
                repo->setText(text(r, "path", ""));
            prefix->clear();
            for (const auto &entry : s["prefixes"].toArray())
                prefix->addItem(entry.toString());
            prefix->setCurrentText(text(s, "prefix", "compatdata-exp-dx11"));
            proton->clear();
            for (const auto &entry : s["protons"].toArray()) {
                const auto entryObject = entry.toObject();
                proton->addItem(text(entryObject, "name"), text(entryObject, "path"));
                proton->setItemData(proton->count() - 1, text(entryObject, "path"), Qt::ToolTipRole);
                if (text(entryObject, "path") == text(s, "proton_path", "") ||
                    text(entryObject, "name") == text(s, "proton", ""))
                    proton->setCurrentIndex(proton->count() - 1);
            }
            withSpace->setChecked(s["spacemouse_installed"].toBool() || !present);
            const auto config = s["device_config"].toObject();
            deadzone->setValue(config["deadzone"].toInt());
            for (int i = 0; i < 6; ++i) {
                enabled[i]->setChecked(config["enabled"].toArray()[i].toBool());
                inverted[i]->setChecked(config["inverted"].toArray()[i].toBool());
            }
            for (int i = 0; i < 2; ++i)
                selectButtonBinding(buttons[i], config["buttons"].toArray()[i]);
            camera->setValue(s["camera"].toObject()["percent"].toInt(25));
            loaded = true;
        }
        if (!s["error"].isNull() && !text(s, "error", "").isEmpty())
            result->setText(I18n::tr(text(s, "error")));
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
                reason = I18n::tr("Another action is running.");
            else if (action == "launch" && running)
                reason = I18n::tr("Fusion is already running.");
            else if (action == "launch" && !last["fusion"].isString())
                reason = I18n::tr("Fusion is not installed yet.");
            else if (running &&
                     (action == "update" || action == "install" || action == "patch" || action == "apply" ||
                      action == "profile" || action == "enable" || action == "disable"))
                reason = I18n::tr("Close Fusion before making this change.");
            else if ((action == "driver-start" || action == "driver-stop" || action == "enable" ||
                      action == "disable") &&
                     !last["direct_driver"].toBool())
                reason = I18n::tr(
                    "Apply the current checkout first. The older driver integration will remain unchanged.");
            else if (action == "setup-access" &&
                     !last["input_access"].toObject()["pkexec_available"].toBool())
                reason = I18n::tr("Polkit (pkexec) is required for the one-time device access setup.");
            else if (action == "setup-access" &&
                     !last["input_access"].toObject()["helper_available"].toBool())
                reason = I18n::tr("The access helper is missing. Build or update the Manager first.");
            else if (action == "clone" && r["valid"].toBool())
                reason = I18n::tr("The selected checkout already exists.");
            else if ((action == "update" || action == "check" || action == "apply" || action == "install" ||
                      action == "patch") &&
                     !r["valid"].toBool())
                reason = I18n::tr("Select a valid checkout first.");
            else if (action == "update" && !r["upstream"].isString())
                reason = I18n::tr("No update source is configured for this branch.");
            widget->setEnabled(reason.isEmpty());
            widget->setToolTip(reason);
        }
    }

    void buildOverview() {
        QVBoxLayout *layout;
        page(I18n::tr("Overview"),
             I18n::tr("Manage Fusion and its Linux integration. Version and update information comes from "
                      "the selected installation and Git checkout. Autodesk's own updater manages Fusion itself."),
             layout);
        auto *fusion = new QFrame;
        fusion->setObjectName("fusionPanel");
        auto *fusionRow = new QHBoxLayout(fusion);
        fusionRow->setContentsMargins(20, 19, 20, 19);
        fusionRow->setSpacing(16);
        auto *mark = label("F", "fusionMark");
        mark->setFixedSize(42, 42);
        mark->setAlignment(Qt::AlignCenter);
        fusionRow->addWidget(mark);
        auto *name = new QVBoxLayout;
        name->setSpacing(4);
        name->addWidget(label("Autodesk Fusion", "product"));
        name->addWidget(subtitle);
        fusionRow->addLayout(name, 1);
        fusionRow->addWidget(headline);
        fusionRow->addSpacing(8);
        fusionRow->addWidget(actionButton(I18n::tr("Launch Fusion"), "launch", {}, true));
        fusionRow->addWidget(actionButton(I18n::tr("Refresh"), "status"));
        layout->addWidget(fusion);

        auto *columns = new QHBoxLayout;
        columns->setSpacing(16);
        auto *runtime = new QVBoxLayout;
        auto *fields = new QGridLayout;
        field(fields, 0, I18n::tr("Integration"), integrationVersion);
        field(fields, 1, I18n::tr("Prefix"), overviewPrefix);
        field(fields, 2, "Proton", overviewProton);
        runtime->addLayout(fields);
        runtime->addStretch();
        runtime->addWidget(details(I18n::tr("Installation details"), fusionInfo));
        columns->addWidget(panel(I18n::tr("Runtime"),
                                 I18n::tr("The prefix and Proton selection are preserved across updates. "
                                          "Change them in Setup after closing Fusion. Expand installation details to "
                                          "see the full executable path and revision."),
                                 runtime),
                           1);

        auto *updates = new QVBoxLayout;
        updates->setSpacing(8);
        updates->addWidget(repoSummary);
        updates->addWidget(repoBranch);
        updates->addWidget(repoCheck);
        auto *actions = new QHBoxLayout;
        actions->addWidget(actionButton(I18n::tr("Check"), "check"));
        actions->addWidget(actionButton(I18n::tr("Update"), "update", {}, true));
        cloneButton = actionButton(I18n::tr("Restore checkout"), "clone");
        actions->addWidget(cloneButton);
        actions->addStretch();
        updates->addSpacing(4);
        updates->addLayout(actions);
        updates->addStretch();
        updates->addWidget(details(I18n::tr("Repository details"), repoInfo));
        columns->addWidget(
            panel(I18n::tr("Updates"),
                  I18n::tr("Check fetches the configured remote. Update accepts only a fast-forward "
                           "and runs the newly fetched installer. Local changes and divergent history are protected. "
                           "The displayed comparison reflects the last fetch. Restore checkout recreates a missing "
                           "repository without overwriting files."),
                  updates),
            1);
        for (int i = 0; i < columns->count(); ++i)
            columns->setAlignment(columns->itemAt(i)->widget(), Qt::AlignTop);
        layout->addLayout(columns);

        auto *device = new QVBoxLayout;
        auto *deviceRow = new QHBoxLayout;
        auto *summary = new QVBoxLayout;
        summary->setSpacing(5);
        summary->addWidget(spaceOverview);
        summary->addWidget(overviewCamera);
        deviceRow->addLayout(summary, 1);
        auto *configure = new QPushButton(I18n::tr("Configure"));
        connect(configure, &QPushButton::clicked, this, [this] { nav->setCurrentRow(1); });
        deviceRow->addWidget(configure);
        device->addLayout(deviceRow);
        layout->addWidget(panel(I18n::tr("SpaceMouse"),
                                I18n::tr("Device status comes from the real input bridge. Camera changes are queued "
                                         "for the next Fusion launch; input counts are preserved."),
                                device));
        layout->addStretch();
    }

    void buildSpaceMouse() {
        QVBoxLayout *layout;
        page(I18n::tr("SpaceMouse"),
             I18n::tr("Direct HID preserves complete hardware reports without input scaling or synthetic repetition. "
                      "The explicitly limited evdev fallback may interrupt held motion after 250 ms without axis "
                      "changes. "
                      "Only the reviewed Universal Receiver profile is used for raw HID input."),
             layout);
        auto *connection = new QVBoxLayout;
        connection->setSpacing(7);
        connection->addWidget(deviceSummary);
        connection->addWidget(inputStateInfo);
        connection->addWidget(driverInfo);
        auto *access = new QHBoxLayout(accessPanel);
        accessPanel->setObjectName("accessPanel");
        access->setContentsMargins(12, 10, 12, 10);
        access->addWidget(inputAccessInfo, 1);
        access->addWidget(
            infoButton(I18n::tr("Device access"),
                       I18n::tr("Set up device access is an explicit administrator action. "
                                "A fixed helper adds only the USB 256f:c652 uaccess rule, then reloads udev rules. "
                                "Unplug and reconnect the receiver afterwards. No root service or world-writable rule "
                                "is installed. "
                                "Missing raw access leaves only the limited evdev fallback.")));
        access->addWidget(actionButton(I18n::tr("Set up device access"), "setup-access", {}, true));
        accessPanel->hide();
        connection->addWidget(accessPanel);
        auto *diagnostics = new QWidget;
        auto *diagnosticLayout = new QVBoxLayout(diagnostics);
        diagnosticLayout->setContentsMargins(0, 3, 0, 0);
        diagnosticLayout->addWidget(hardwareInfo);
        auto *driverActions = new QHBoxLayout;
        for (const auto &entry : {qMakePair(I18n::tr("Start bridge"), QString("driver-start")),
                                  qMakePair(I18n::tr("Stop bridge"), QString("driver-stop")),
                                  qMakePair(I18n::tr("Enable"), QString("enable")),
                                  qMakePair(I18n::tr("Disable"), QString("disable"))})
            driverActions->addWidget(actionButton(entry.first, entry.second));
        driverActions->addStretch();
        diagnosticLayout->addLayout(driverActions);
        connection->addWidget(details(I18n::tr("Diagnostics & driver"), diagnostics));
        layout->addWidget(
            panel(I18n::tr("Connection"),
                  I18n::tr("Keyboard actions only work while Fusion has focus. "
                           "A 250 ms gap in motion reports safely neutralizes the last nonzero input; battery and "
                           "status reports "
                           "do not extend that deadline. Driver enable/disable requires Fusion to be closed."),
                  connection));

        auto *columns = new QHBoxLayout;
        columns->setSpacing(16);
        auto *axes = new QVBoxLayout;
        auto *grid = new QGridLayout;
        grid->setHorizontalSpacing(18);
        grid->setVerticalSpacing(9);
        grid->addWidget(label(I18n::tr("Axis"), "muted"), 0, 0);
        grid->addWidget(label(I18n::tr("Value"), "muted"), 0, 1, Qt::AlignRight);
        grid->addWidget(label(I18n::tr("Use"), "muted"), 0, 2, Qt::AlignHCenter);
        grid->addWidget(label(I18n::tr("Invert"), "muted"), 0, 3, Qt::AlignHCenter);
        const QStringList names = {"X", "Y", "Z", "RX", "RY", "RZ"};
        const QStringList descriptions = {I18n::tr("Pan left / right"), I18n::tr("Pan up / down"),
                                          I18n::tr("Zoom forward / back"), I18n::tr("Tilt"),
                                          I18n::tr("Rotate"), I18n::tr("Roll")};
        for (int i = 0; i < 6; ++i) {
            auto *name = label(names[i]);
            name->setToolTip(descriptions[i]);
            live[i] = label("—", "value");
            live[i]->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
            live[i]->setMinimumWidth(47);
            enabled[i] = new QCheckBox;
            inverted[i] = new QCheckBox;
            enabled[i]->setAccessibleName(I18n::tr("Enable %1").arg(names[i]));
            inverted[i]->setAccessibleName(I18n::tr("Invert %1").arg(names[i]));
            grid->addWidget(name, i + 1, 0);
            grid->addWidget(live[i], i + 1, 1, Qt::AlignRight);
            grid->addWidget(enabled[i], i + 1, 2, Qt::AlignHCenter);
            grid->addWidget(inverted[i], i + 1, 3, Qt::AlignHCenter);
            mutationControls << enabled[i] << inverted[i];
        }
        grid->setColumnStretch(0, 1);
        axes->addLayout(grid);
        axes->addStretch();
        auto *deadzoneRow = new QHBoxLayout;
        deadzone->setObjectName("deadzone");
        deadzone->setRange(0, 100);
        deadzone->setSuffix(I18n::tr(" counts"));
        deadzone->setFixedWidth(120);
        deadzone->setAlignment(Qt::AlignCenter);
        deadzoneRow->addWidget(label(I18n::tr("Deadzone"), "muted"));
        deadzoneRow->addStretch();
        deadzoneRow->addWidget(deadzone);
        axes->addSpacing(8);
        axes->addLayout(deadzoneRow);
        columns->addWidget(
            panel(I18n::tr("Axes"),
                  I18n::tr("Values are the mapped integer counts sent to Fusion. Default deadzone is zero. "
                           "Axis mapping is [X, −Z, −Y, RX, −RZ, −RY]. Enable or invert axes explicitly; there is no "
                           "smoothing, "
                           "input sensitivity scaling or batching. Save input applies both axes and button assignments."),
                axes),
            1);

        auto *bindings = new QVBoxLayout;
        bindings->setSpacing(12);
        auto *form = new QFormLayout;
        form->setHorizontalSpacing(14);
        form->setVerticalSpacing(12);
        for (int i = 0; i < 2; ++i) {
            buttons[i] = new QComboBox;
            buttons[i]->setObjectName(i == 0 ? "button-left" : "button-right");
            for (const auto &entry :
                 {qMakePair(I18n::tr("Record shortcut…"), QString("__record__")),
                  qMakePair(I18n::tr("Native SDK button"), QString("sdk")),
                  qMakePair(I18n::tr("No action"), QString("off"))})
                buttons[i]->addItem(entry.first, entry.second);
            auto *combo = buttons[i];
            combo->setProperty("binding", combo->currentData());
            connect(combo, qOverload<int>(&QComboBox::currentIndexChanged), this, [combo](int index) {
                if (combo->itemData(index).toString() != "__record__")
                    combo->setProperty("binding", combo->itemData(index));
            });
            connect(combo, qOverload<int>(&QComboBox::activated), this, [this, combo, i](int index) {
                if (combo->itemData(index).toString() != "__record__") return;
                const auto previous = QJsonValue::fromVariant(combo->property("binding"));
                Shortcuts::Recorder recorder(I18n::tr(i == 0 ? "Left button" : "Right button"), this);
                selectButtonBinding(combo, recorder.exec() == QDialog::Accepted
                                               ? QJsonValue(recorder.binding()) : previous);
            });
            form->addRow(I18n::tr(i == 0 ? "Left" : "Right"), buttons[i]);
            mutationControls << buttons[i];
        }
        bindings->addLayout(form);
        bindings->addWidget(buttonState);
        auto *separator = new QFrame;
        separator->setObjectName("separator");
        separator->setFixedHeight(1);
        bindings->addWidget(separator);
        auto *cameraRow = new QHBoxLayout;
        camera->setObjectName("camera");
        camera->setRange(1, 100);
        camera->setSuffix(" %");
        camera->setFixedWidth(100);
        camera->setAlignment(Qt::AlignCenter);
        cameraRow->addWidget(label(I18n::tr("Camera speed")));
        cameraRow->addStretch();
        cameraRow->addWidget(camera);
        cameraRow->addWidget(actionButton(I18n::tr("Apply"), "camera"));
        bindings->addLayout(cameraRow);
        cameraHint->setObjectName("camera-status");
        updateCameraStatus({});
        bindings->addWidget(cameraHint);
        bindings->addStretch();
        auto *save = new QHBoxLayout;
        save->addStretch();
        save->addWidget(actionButton(I18n::tr("Save input"), "settings", {}, true));
        bindings->addLayout(save);
        columns->addWidget(
            panel(I18n::tr("Buttons & camera"),
                  I18n::tr("Choose Record shortcut to assign any supported key or modifier combination. "
                           "Modifier keys can also be held on their own. Keyboard actions are sent only to focused Fusion. Held keys are released "
                           "on focus loss or disconnect. Save input applies axis and button settings within one second. "
                           "Camera Apply saves the speed and changes a supported running Fusion session immediately. "
                           "Live confirms the current speed; otherwise the setting is saved for the next launch. "
                           "Input counts remain unchanged."),
                bindings),
            1);
        for (int i = 0; i < columns->count(); ++i)
            columns->setAlignment(columns->itemAt(i)->widget(), Qt::AlignTop);
        layout->addLayout(columns);
        mutationControls << camera << deadzone;
        layout->addStretch();
    }

    void buildSetup() {
        QVBoxLayout *layout;
        page(I18n::tr("Setup"),
             I18n::tr("Install Fusion, adopt an existing installation, or apply the local checkout. "
                      "Close Fusion before changing installation files, its SDK integration, prefix or Proton. "
                      "Steam and a Proton version must already be installed."),
             layout);
        auto *runtime = new QVBoxLayout;
        auto *form = new QFormLayout;
        form->setHorizontalSpacing(20);
        form->setVerticalSpacing(12);
        prefix->setObjectName("prefix");
        proton->setObjectName("proton");
        form->addRow(I18n::tr("Prefix"), prefix);
        form->addRow("Proton", proton);
        runtime->addLayout(form);
        auto *applyRow = new QHBoxLayout;
        applyRow->addStretch();
        applyRow->addWidget(actionButton(I18n::tr("Apply runtime"), "profile"));
        runtime->addLayout(applyRow);
        layout->addWidget(
            panel(I18n::tr("Runtime"),
                  I18n::tr("Select an existing Wine prefix and an installed Proton version. "
                           "Their folders are preserved. Proton paths are available as item tooltips. A new "
                           "installation may "
                           "use a new prefix name; applying a runtime selection requires an existing prefix."),
                  runtime));
        mutationControls << prefix << proton;

        auto *installation = new QVBoxLayout;
        auto *installRow = new QHBoxLayout;
        installRow->addWidget(actionButton(I18n::tr("Install Fusion"), "install", {}, true));
        installRow->addWidget(actionButton(I18n::tr("Adopt existing"), "patch"));
        installRow->addWidget(actionButton(I18n::tr("Apply checkout"), "apply"));
        installRow->addStretch();
        installation->addLayout(installRow);
        installation->addWidget(withSpace);
        auto *advanced = new QWidget;
        auto *advancedLayout = new QVBoxLayout(advanced);
        advancedLayout->setContentsMargins(0, 0, 0, 0);
        advancedLayout->addWidget(label(I18n::tr("Installer executable (optional)"), "muted"));
        advancedLayout->addWidget(pathRow(installer, I18n::tr("Download the official Autodesk installer"), true));
        installation->addWidget(details(I18n::tr("Installer options"), advanced));
        layout->addWidget(panel(I18n::tr("Installation"),
                                I18n::tr("Install Fusion requires a free installation folder. The official Autodesk "
                                         "installer is downloaded unless an executable is selected. Setup and sign-in "
                                         "open in their own window. "
                                         "Adopt existing configures an existing installation. Apply checkout deploys "
                                         "local files without a Git fetch. "
                                         "Replaced helpers are backed up under backups/updates; documents and the "
                                         "complete Wine prefix are not included in that backup."),
                                installation));
        mutationControls << withSpace;

        auto *locations = new QVBoxLayout;
        locations->addWidget(locationSummary);
        auto *locationFields = new QWidget;
        auto *locationLayout = new QVBoxLayout(locationFields);
        locationLayout->setContentsMargins(0, 0, 0, 0);
        locationLayout->setSpacing(8);
        locationLayout->addWidget(label(I18n::tr("Installation folder"), "muted"));
        locationLayout->addWidget(pathRow(target, "~/.local/share/autodesk-fusion"));
        locationLayout->addWidget(label(I18n::tr("Repository checkout"), "muted"));
        locationLayout->addWidget(pathRow(repo, "fusion-linux-dx11"));
        locations->addWidget(details(I18n::tr("Change folders"), locationFields));
        layout->addWidget(panel(I18n::tr("Locations"),
                                I18n::tr("The selected installation and source checkout are used by every action. "
                                         "Choose an empty destination for a new installation. Existing files are "
                                         "never overwritten by repository cloning."),
                                locations));
        layout->addStretch();
    }

    void buildActivity() {
        QVBoxLayout *layout;
        page(I18n::tr("Activity"),
             I18n::tr("Output from actions started in this window. Installation and update failures are shown here. "
                      "Fusion launch output is saved in logs/manager-launch.log in the selected installation."),
             layout);
        auto *actions = new QHBoxLayout;
        auto *copy = new QPushButton(I18n::tr("Copy output"));
        connect(copy, &QPushButton::clicked, this,
                [this] { QApplication::clipboard()->setText(log->toPlainText()); });
        actions->addWidget(copy);
        auto *open = new QPushButton(I18n::tr("Open log folder"));
        connect(open, &QPushButton::clicked, this,
                [this] { QDesktopServices::openUrl(QUrl::fromLocalFile(target->text() + "/logs")); });
        actions->addWidget(open);
        actions->addStretch();
        layout->addLayout(actions);
        log->setReadOnly(true);
        log->setMaximumBlockCount(3000);
        log->setPlaceholderText(I18n::tr("No activity yet."));
        log->setMinimumHeight(340);
        layout->addWidget(log, 1);
    }

    void readLiveState() {
        const QString runtime =
            qEnvironmentVariable("XDG_RUNTIME_DIR", QString("/run/user/%1").arg(getuid()));
        QFile file(runtime + "/autodesk-fusion-spacemouse/status.json");
        QJsonObject state;
        if (file.open(QIODevice::ReadOnly))
            state = QJsonDocument::fromJson(file.readAll()).object();
        const double age = QDateTime::currentMSecsSinceEpoch() / 1000. - state["timestamp"].toDouble();
        const bool fresh = state["timestamp"].isDouble() && age >= 0 && age <= 3;
        const QString selectedApp = QFileInfo(target->text()).canonicalFilePath();
        const auto reportedCamera = state["camera_live"].toObject();
        const auto expectedCamera = last["camera_live"].toObject();
        const QString session = expectedCamera["session"].toString();
        const bool currentSession = !session.isEmpty() && reportedCamera["session"] == session &&
                                    (!expectedCamera["pid"].isDouble() ||
                                     reportedCamera["pid"] == expectedCamera["pid"]);
        const double cameraAge = QDateTime::currentMSecsSinceEpoch() / 1000. -
                                 reportedCamera["updated"].toDouble();
        const bool confirmed = reportedCamera["state"] != "live" ||
                               (reportedCamera["updated"].isDouble() && cameraAge >= 0 && cameraAge < 2.5);
        if (fresh && !selectedApp.isEmpty() &&
            QFileInfo(state["app"].toString()).canonicalFilePath() == selectedApp &&
            currentSession && confirmed) {
            updateCameraStatus(reportedCamera);
        } else {
            auto cameraState = last["camera_live"].toObject();
            if (cameraState["state"] == "live" || cameraState["state"] == "pending")
                cameraState = {{"state", "saved"},
                               {"reason", I18n::tr("No fresh camera confirmation for this installation.")}};
            updateCameraStatus(cameraState);
        }
        QString inputState = I18n::tr("Input offline");
        if (fresh) {
            inputState = state["input_backend"].toString() == "hidraw"  ? I18n::tr("Direct HID")
                         : state["input_backend"].toString() == "evdev" ? I18n::tr("Limited evdev fallback")
                                                                        : I18n::tr("No input connected");
            if (state["motion_watchdog"].toBool()) {
                inputState += I18n::tr("  ·  Safety stop");
                inputStateInfo->setToolTip(I18n::tr(
                    "Input was neutralized after 250 ms without a motion report. "
                    "Battery and status reports do not extend the safety deadline."));
            } else {
                inputStateInfo->setToolTip(I18n::tr(
                    "The current input source reported by the bridge. HID reports are forwarded "
                    "without synthetic repetition. The evdev fallback cannot reproduce continuously held "
                    "motion reliably."));
            }
            const auto telemetry = state["telemetry"].toObject();
            if (telemetry["battery_strength"].isDouble())
                inputState += I18n::tr("  ·  Battery %1/100").arg(telemetry["battery_strength"].toInt());
        }
        inputStateInfo->setText(inputState);
        const auto axes = state["axes"].toArray();
        for (int i = 0; i < 6; ++i)
            live[i]->setText(fresh && i < axes.size() ? QString::number(axes[i].toInt()) : "—");
        const auto buttonValues = state["buttons"].toArray();
        buttonState->setText(
            fresh ? QString("L ") +
                        I18n::tr(buttonValues.size() > 0 && buttonValues[0].toBool() ? "pressed" : "released") +
                        "  ·  R " +
                        I18n::tr(buttonValues.size() > 1 && buttonValues[1].toBool() ? "pressed" : "released")
                  : I18n::tr("Input offline"));
    }

    void restoreLanguageSelection() {
        const int index = language->findData(I18n::languageCode());
        if (index >= 0) language->setCurrentIndex(index);
    }

    static QStringList restartArguments(const QString &code) {
        const auto original = QCoreApplication::arguments().mid(1);
        QStringList args;
        for (int i = 0; i < original.size(); ++i) {
            if (original[i] == "--lang") {
                ++i;
            } else if (!original[i].startsWith("--lang=")) {
                args << original[i];
            }
        }
        args << "--lang" << code;
        return args;
    }

    void changeLanguage(const QString &code) {
        if (code == I18n::languageCode()) return;
        if (busy) {
            restoreLanguageSelection();
            return;
        }
        QMessageBox confirmation(this);
        confirmation.setWindowTitle(I18n::tr("Change language"));
        confirmation.setText(I18n::tr("Restart Fusion Manager to apply the language change to the Manager and Fusion?"));
        confirmation.setIcon(QMessageBox::Question);
        auto *restart = confirmation.addButton(I18n::tr("Restart now"), QMessageBox::AcceptRole);
        confirmation.addButton(I18n::tr("Cancel"), QMessageBox::RejectRole);
        confirmation.exec();
        if (confirmation.clickedButton() != restart) {
            restoreLanguageSelection();
            return;
        }
        QSettings settings;
        settings.setValue("language", code);
        settings.sync();
        if (smoke || !screenshot.isEmpty()) {
            restoreLanguageSelection();
            result->setText(I18n::tr("Language saved. Restart to apply."));
            return;
        }
        if (!QProcess::startDetached(QCoreApplication::applicationFilePath(), restartArguments(code))) {
            restoreLanguageSelection();
            QMessageBox::warning(this, I18n::tr("Restart failed"),
                                 I18n::tr("Unable to restart Fusion Manager. The new language will be used the next time you start it."));
            return;
        }
        QApplication::quit();
    }

  public:
    Manager(const QString &backendPath, const QString &appPath, const QString &repoPath,
            const QString &capture, bool smokeTest)
        : backend(backendPath), screenshot(capture), smoke(smokeTest) {
        setWindowTitle("Fusion Manager");
        resize(1120, 800);
        setMinimumSize(880, 640);
        prefix->setEditable(true);
        target->setText(appPath);
        repo->setText(repoPath);
        for (auto *edit : {target, repo})
            connect(edit, &QLineEdit::editingFinished, this, [this] {
                loaded = false;
                requestStatus();
            });
        proton->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
        proton->setMinimumContentsLength(18);
        for (auto *widget : {fusionInfo, repoInfo, hardwareInfo})
            detailLabel(widget);

        auto *root = new QWidget;
        auto *shell = new QHBoxLayout(root);
        shell->setContentsMargins(0, 0, 0, 0);
        shell->setSpacing(0);
        setCentralWidget(root);
        auto *rail = new QWidget;
        rail->setObjectName("rail");
        rail->setFixedWidth(188);
        auto *railLayout = new QVBoxLayout(rail);
        railLayout->setContentsMargins(16, 23, 16, 18);
        railLayout->setSpacing(18);
        auto *brand = new QHBoxLayout;
        brand->setSpacing(10);
        auto *mark = label("");
        mark->setPixmap(QIcon(":/manager/icon.png").pixmap(32, 32));
        mark->setAlignment(Qt::AlignCenter);
        mark->setFixedSize(32, 32);
        brand->addWidget(mark);
        brand->addWidget(label("Fusion\nManager", "brand"));
        brand->addStretch();
        railLayout->addLayout(brand);
        nav->setObjectName("navigation");
        const QStringList names = {I18n::tr("Overview"), I18n::tr("SpaceMouse"), I18n::tr("Setup"),
                                   I18n::tr("Activity")};
        for (int i = 0; i < names.size(); ++i) {
            auto *item = new QListWidgetItem(navigationIcon(i), names[i]);
            item->setSizeHint(QSize(150, 42));
            nav->addItem(item);
        }
        nav->setFrameShape(QFrame::NoFrame);
        nav->setIconSize(QSize(20, 20));
        nav->setSpacing(4);
        nav->setFocusPolicy(Qt::StrongFocus);
        nav->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        railLayout->addWidget(nav, 1);
        railLayout->addWidget(label(I18n::tr("Language"), "railnote"));
        language->setObjectName("language");
        language->setAccessibleName(I18n::tr("Language"));
        language->setToolTip(I18n::tr("Applies to Fusion Manager and Fusion at the next launch."));
        language->addItem("English", "en");
        language->addItem("Deutsch", "de");
        restoreLanguageSelection();
        connect(language, qOverload<int>(&QComboBox::activated), this, [this](int index) {
            changeLanguage(language->itemData(index).toString());
        });
        mutationControls << language;
        railLayout->addWidget(language);
        railLayout->addWidget(label("v1.2.0", "railnote"));
        shell->addWidget(rail);
        auto *workspace = new QWidget;
        workspace->setObjectName("workspace");
        auto *workspaceLayout = new QVBoxLayout(workspace);
        workspaceLayout->setContentsMargins(0, 0, 0, 0);
        workspaceLayout->setSpacing(0);
        workspaceLayout->addWidget(pages, 1);
        auto *footer = new QWidget;
        footer->setObjectName("footer");
        auto *footerLayout = new QHBoxLayout(footer);
        footerLayout->setContentsMargins(26, 9, 26, 9);
        footerLayout->addWidget(result, 1);
        progress->setFixedSize(110, 5);
        progress->setRange(0, 0);
        progress->hide();
        footerLayout->addWidget(progress);
        workspaceLayout->addWidget(footer);
        shell->addWidget(workspace, 1);

        buildOverview();
        buildSpaceMouse();
        buildSetup();
        buildActivity();
        connect(nav, &QListWidget::currentRowChanged, pages, &QStackedWidget::setCurrentIndex);
        nav->setCurrentRow(0);
        connect(statusProc, &QProcess::readyReadStandardOutput, this,
                [this] { statusBytes += statusProc->readAllStandardOutput(); });
        connect(statusProc, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
                [this](int code, QProcess::ExitStatus) {
                    QJsonParseError error;
                    const auto document = QJsonDocument::fromJson(statusBytes, &error);
                    if (code == 0 && error.error == QJsonParseError::NoError && document.isObject())
                        updateStatus(document.object());
                    else {
                        result->setText(I18n::tr("Unable to read status · See Activity"));
                        log->appendPlainText(QString::fromUtf8(statusProc->readAllStandardError()));
                        if (smoke || !screenshot.isEmpty())
                            QApplication::exit(1);
                    }
                });
        connect(statusProc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError) {
            result->setText(I18n::tr("Unable to start Python 3"));
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
                                        ? I18n::tr("Completed")
                                        : I18n::tr("Action failed · See Activity"));
                    if (code == 0 && currentAction == "setup-access")
                        result->setText(I18n::tr("Device access prepared · Reconnect the receiver"));
                    log->appendPlainText("\n" + I18n::tr("Exit code: %1").arg(code));
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
                result->setText(I18n::tr("Unable to run action: %1").arg(operation->errorString()));
            }
        });
        connect(&refresh, &QTimer::timeout, this, [this] { requestStatus(); });
        refresh.start(5000);
        connect(&liveRefresh, &QTimer::timeout, this, [this] { readLiveState(); });
        liveRefresh.start(100);
        QTimer::singleShot(0, this, [this] { requestStatus(); });
    }

    void selectPage(int index) { nav->setCurrentRow(index); }

    void closeEvent(QCloseEvent *event) override {
        if (busy) {
            QMessageBox::information(this, I18n::tr("Action in progress"),
                                     I18n::tr("Wait for the current action to finish. See Activity for progress."));
            event->ignore();
            return;
        }
        event->accept();
    }
};

int main(int argc, char **argv) {
    QApplication::setAttribute(Qt::AA_DontUseNativeDialogs);
    QApplication app(argc, argv);
    app.setApplicationName("Fusion Manager");
    app.setOrganizationName("fusion-linux-dx11");
    app.setDesktopFileName("fusion-manager");
    app.setWindowIcon(QIcon(":/manager/icon.png"));
    QSettings settings;
    QString selectedLanguage = settings.value("language", I18n::systemLanguageCode()).toString();
    const auto arguments = app.arguments();
    for (int i = 1; i < arguments.size(); ++i) {
        if (arguments[i] == "--lang" && i + 1 < arguments.size())
            selectedLanguage = arguments[++i];
        else if (arguments[i].startsWith("--lang="))
            selectedLanguage = arguments[i].mid(7);
    }
    I18n::setLanguage(selectedLanguage);
    QLocale::setDefault(I18n::locale());
    QCommandLineParser parser;
    parser.setApplicationDescription(I18n::tr("Native Fusion and SpaceMouse manager for Linux"));
    parser.addHelpOption();
    parser.addOption({"backend", I18n::tr("Python backend"), "path"});
    parser.addOption(
        {{"target", "app-dir"},
         I18n::tr("Installation folder"),
         "path",
         QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/autodesk-fusion"});
    parser.addOption({"repo", I18n::tr("Git checkout"), "path"});
    parser.addOption({"screenshot", I18n::tr("Save the window as a PNG and exit"), "path"});
    parser.addOption({"smoke-test", I18n::tr("Read status and exit without changing the installation")});
    parser.addOption({"page", I18n::tr("Initial page: overview, spacemouse, setup, log"), "name", "overview"});
    parser.addOption({"size", I18n::tr("Window size, for example 1130x1200"), "size"});
    parser.addOption({"lang", I18n::tr("UI language: en or de"), "code"});
    parser.process(app);
    if (parser.isSet("lang")) {
        I18n::setLanguage(parser.value("lang"));
        QLocale::setDefault(I18n::locale());
    }
    if (parser.value("backend").isEmpty()) {
        qCritical("--backend PATH is required. Use manager/run.sh or the installed Manager launcher.");
        return 2;
    }
    app.setStyle("Fusion");
    app.setFont(QFont("Sans Serif", 10));
    QPalette palette;
    palette.setColor(QPalette::Window, QColor("#202938"));
    palette.setColor(QPalette::WindowText, QColor("#e1e7ef"));
    palette.setColor(QPalette::Base, QColor("#18212d"));
    palette.setColor(QPalette::AlternateBase, QColor("#283446"));
    palette.setColor(QPalette::Text, QColor("#e1e7ef"));
    palette.setColor(QPalette::Button, QColor("#2e3b4e"));
    palette.setColor(QPalette::ButtonText, QColor("#e1e7ef"));
    palette.setColor(QPalette::Highlight, QColor("#367fc3"));
    palette.setColor(QPalette::HighlightedText, Qt::white);
    palette.setColor(QPalette::ToolTipBase, QColor("#334259"));
    palette.setColor(QPalette::ToolTipText, QColor("#f0f3f8"));
    palette.setColor(QPalette::Disabled, QPalette::Text, QColor("#738095"));
    palette.setColor(QPalette::Disabled, QPalette::ButtonText, QColor("#738095"));
    app.setPalette(palette);
    app.setStyleSheet(R"(
        QWidget { color:#e1e7ef; }
        QMainWindow, #workspace, #page, QScrollArea, QScrollArea > QWidget > QWidget { background:#202938; }
        QLabel { background:transparent; }
        QLabel[kind="title"] { font-size:23px; font-weight:600; color:#f0f3f7; }
        QLabel[kind="product"] { font-size:19px; font-weight:600; color:#f0f3f7; }
        QLabel[kind="section"] { font-size:13px; font-weight:600; color:#dbe4f0; }
        QLabel[kind="summary"] { font-size:15px; font-weight:600; color:#e1e8f2; }
        QLabel[kind="muted"], QLabel[kind="detail"] { color:#a6b3c5; font-size:12px; }
        QLabel[kind="detail"] { line-height:1.4; }
        QLabel[kind="warning"], QLabel[tone="warning"] { color:#edb472; }
        QLabel[kind="value"] { color:#8fc2ef; font-family:monospace; font-size:12px; font-weight:600; }
        QLabel[kind="badge"] { background:#303c4c; border-radius:4px; padding:5px 9px; color:#b4c2d3; font-size:12px; }
        QLabel[kind="badge"][tone="good"] { background:#263f3d; color:#a9d5be; }
        QLabel[kind="fusionMark"] { background:#df7932; color:#fff3e8; font-size:27px; font-weight:700; border-radius:6px; }
        #rail { background:#19212d; border-right:1px solid #313d4f; }
        QLabel[kind="brand"] { color:#e7edf5; font-size:15px; font-weight:600; }
        QLabel[kind="railnote"] { color:#748399; font-size:11px; padding-left:10px; }
        #navigation { background:transparent; outline:0; border:0; }
        #navigation::item { color:#aebcd0; padding:11px 10px; border-left:2px solid transparent; border-radius:4px; }
        #navigation::item:hover { background:#253145; }
        #navigation::item:selected { background:#2b394e; color:#f0f4f9; border-left-color:#e88a42; }
        #panel, #fusionPanel { background:#273345; border:1px solid #3a4659; border-radius:6px; }
        #accessPanel { background:#393b3e; border:1px solid #60513e; border-radius:4px; }
        #separator { background:#3a4659; border:0; }
        QPushButton { background:#34435a; border:1px solid #4b5c74; border-radius:4px; padding:7px 12px; font-weight:500; }
        QPushButton:hover { background:#40526c; border-color:#637894; }
        QPushButton:pressed { background:#2a3b54; }
        QPushButton[primary="true"] { background:#397fbf; border-color:#478dca; color:#fff; }
        QPushButton[primary="true"]:hover { background:#498fce; }
        QPushButton:disabled, QPushButton[primary="true"]:disabled { color:#77879c; background:#2c3749; border-color:#3b485d; }
        QToolButton { color:#a4b6cd; background:transparent; border:0; padding:3px; }
        QToolButton:hover { color:#e5edf7; background:#35465e; border-radius:3px; }
        QToolButton#infoButton { color:#8ea2bc; border:1px solid #53647c; border-radius:10px; font-size:12px; font-style:italic; padding:0; }
        QToolButton#disclosure { color:#a2b3ca; font-size:12px; }
        QLineEdit, QComboBox, QSpinBox { background:#1c2736; border:1px solid #526179; border-radius:4px; padding:6px 8px; min-height:20px; selection-background-color:#397fbf; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color:#70a4d2; }
        QSpinBox { padding-right:22px; }
        QSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right; width:20px; background:#29394d; border-left:1px solid #526179; border-bottom:1px solid #526179; border-top-right-radius:3px; }
        QSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right; width:20px; background:#29394d; border-left:1px solid #526179; border-bottom-right-radius:3px; }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover { background:#40526c; }
        QSpinBox::up-arrow { image:url(:/manager/up.xpm); width:8px; height:5px; }
        QSpinBox::down-arrow { image:url(:/manager/down.xpm); width:8px; height:5px; }
        QComboBox QAbstractItemView { background:#263448; color:#e1e7ef; selection-background-color:#3d628c; border:1px solid #53647c; outline:0; }
        QCheckBox { spacing:8px; }
        QCheckBox::indicator { width:15px; height:15px; }
        QPlainTextEdit { background:#18212d; color:#c7d4e7; border:1px solid #3b485d; border-radius:5px; padding:14px; font-family:monospace; font-size:12px; }
        QToolTip { background:#334259; color:#f0f3f8; border:1px solid #60718a; padding:7px; }
        QScrollBar:vertical { background:transparent; width:9px; margin:2px; }
        QScrollBar::handle:vertical { background:#495b72; border-radius:3px; min-height:28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }
        #footer { background:#1b2431; border-top:1px solid #364254; }
        QProgressBar { background:#29364a; border:0; border-radius:2px; }
        QProgressBar::chunk { background:#5d9bd0; }
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
