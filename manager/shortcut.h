// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QtWidgets>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include "i18n.h"

namespace Shortcuts {
inline QString modifierName(int key) {
    switch (key) {
    case Qt::Key_Control: return "CTRL";
    case Qt::Key_Shift: return "SHIFT";
    case Qt::Key_Alt: return "ALT";
    case Qt::Key_Meta: return "META";
    case Qt::Key_AltGr: return "ALTGR";
    default: return {};
    }
}
inline QString keyName(int key) {
    if (!modifierName(key).isEmpty()) return modifierName(key);
    if (key >= Qt::Key_F1 && key <= Qt::Key_F24)
        return "F" + QString::number(key - Qt::Key_F1 + 1);
    switch (key) {
    case Qt::Key_Escape: return "ESC";
    case Qt::Key_Tab: case Qt::Key_Backtab: return "TAB";
    case Qt::Key_Return: case Qt::Key_Enter: return "ENTER";
    case Qt::Key_Backspace: return "BACKSPACE";
    case Qt::Key_Delete: return "DELETE";
    case Qt::Key_Insert: return "INSERT";
    case Qt::Key_Home: return "HOME";
    case Qt::Key_End: return "END";
    case Qt::Key_PageUp: return "PAGEUP";
    case Qt::Key_PageDown: return "PAGEDOWN";
    case Qt::Key_Left: return "LEFT";
    case Qt::Key_Right: return "RIGHT";
    case Qt::Key_Up: return "UP";
    case Qt::Key_Down: return "DOWN";
    case Qt::Key_Pause: return "PAUSE";
    case Qt::Key_Print: return "PRINTSCREEN";
    case Qt::Key_CapsLock: return "CAPSLOCK";
    case Qt::Key_NumLock: return "NUMLOCK";
    case Qt::Key_ScrollLock: return "SCROLLLOCK";
    case Qt::Key_Menu: return "MENU";
    case Qt::Key_Space: return "SPACE";
    default:
        if (key > 0x20 && key <= 0xffff && QChar(ushort(key)).isPrint())
            return QString(QChar(ushort(key)));
        return {};
    }
}
inline QJsonObject chord(QKeyEvent *event) {
    QString key = keyName(event->key());
    if (event->modifiers() & Qt::KeypadModifier) {
        if (event->key() >= Qt::Key_0 && event->key() <= Qt::Key_9)
            key = "NUM" + QString::number(event->key() - Qt::Key_0);
        else {
            switch (event->key()) {
            case Qt::Key_Return: case Qt::Key_Enter: key = "NUMENTER"; break;
            case Qt::Key_Plus: key = "NUMADD"; break;
            case Qt::Key_Minus: key = "NUMSUBTRACT"; break;
            case Qt::Key_Asterisk: key = "NUMMULTIPLY"; break;
            case Qt::Key_Slash: key = "NUMDIVIDE"; break;
            case Qt::Key_Period: case Qt::Key_Comma: key = "NUMDECIMAL"; break;
            default: break;
            }
        }
    }
    if (key.isEmpty()) return {};
    QJsonArray modifiers;
    const auto flags = event->modifiers();
    for (const auto &item : {qMakePair(Qt::ControlModifier, QString("CTRL")),
                             qMakePair(Qt::ShiftModifier, QString("SHIFT")),
                             qMakePair(Qt::AltModifier, QString("ALT")),
                             qMakePair(Qt::MetaModifier, QString("META")),
                             qMakePair(Qt::GroupSwitchModifier, QString("ALTGR"))})
        if ((flags & item.first) && key != item.second)
            modifiers.append(item.second);
    if (event->key() == Qt::Key_Backtab && !modifiers.contains("SHIFT"))
        modifiers.append("SHIFT");
    return {{"key", key}, {"modifiers", modifiers}};
}
inline QString displayKey(const QString &key) {
    static const QHash<QString, QString> names{
        {"ESC", "Esc"}, {"CTRL", "Ctrl"}, {"SHIFT", "Shift"}, {"ALT", "Alt"},
        {"META", "Super"}, {"ALTGR", "AltGr"}, {"SPACE", "Space"}, {"TAB", "Tab"},
        {"ENTER", "Enter"}, {"BACKSPACE", "Backspace"}, {"DELETE", "Delete"},
        {"INSERT", "Insert"}, {"HOME", "Home"}, {"END", "End"},
        {"PAGEUP", "Page Up"}, {"PAGEDOWN", "Page Down"}, {"LEFT", "Left"},
        {"RIGHT", "Right"}, {"UP", "Up"}, {"DOWN", "Down"}, {"PAUSE", "Pause"},
        {"PRINTSCREEN", "Print Screen"}, {"CAPSLOCK", "Caps Lock"},
        {"NUMLOCK", "Num Lock"}, {"SCROLLLOCK", "Scroll Lock"}, {"MENU", "Menu"},
        {"NUMENTER", "Num Enter"}, {"NUMADD", "Num +"}, {"NUMSUBTRACT", "Num −"},
        {"NUMMULTIPLY", "Num ×"}, {"NUMDIVIDE", "Num ÷"}, {"NUMDECIMAL", "Num Decimal"}};
    return I18n::tr(names.value(key, key));
}
inline QString display(const QJsonValue &binding) {
    if (binding.isString()) {
        if (binding.toString() == "off") return I18n::tr("No action");
        if (binding.toString() == "sdk") return I18n::tr("Native SDK button");
        return displayKey(binding.toString());
    }
    const auto object = binding.toObject();
    QStringList parts;
    for (const auto &modifier : object["modifiers"].toArray())
        parts << displayKey(modifier.toString());
    parts << displayKey(object["key"].toString());
    return parts.join(" + ");
}
inline QJsonObject parse(const QString &value) {
    QString input = value.trimmed();
    if (input.isEmpty()) return {};
    input.replace(QRegularExpression("\\bSuper\\b", QRegularExpression::CaseInsensitiveOption), "Meta");
    input.replace(QRegularExpression("\\s*\\+\\s*"), "+");
    const auto parts = input.toUpper().split('+');
    const QStringList names{"CTRL", "SHIFT", "ALT", "META", "ALTGR"};
    bool modifiersOnly = true;
    for (const auto &part : parts)
        if (!names.contains(part.trimmed())) modifiersOnly = false;
    if (modifiersOnly) {
        const QString key = parts.last().trimmed();
        QJsonArray modifiers;
        for (const auto &name : names)
            if (name != key && parts.contains(name)) modifiers.append(name);
        return {{"key", key}, {"modifiers", modifiers}};
    }
    const auto sequence = QKeySequence::fromString(input, QKeySequence::PortableText);
    if (sequence.count() == 1) {
        const auto combination = sequence[0];
        QKeyEvent event(QEvent::KeyPress, combination.key(), combination.keyboardModifiers());
        const auto result = chord(&event);
        if (!result.isEmpty()) return result;
    }
    for (int i = 0; i < parts.size() - 1; ++i)
        if (!names.contains(parts[i])) return {};
    const QString rawKey = input.section('+', -1);
    const auto base = QKeySequence::fromString(rawKey, QKeySequence::PortableText);
    QString key;
    if (QRegularExpression("^NUM(?:[0-9]|ENTER|ADD|SUBTRACT|MULTIPLY|DIVIDE|DECIMAL)$")
            .match(rawKey.toUpper()).hasMatch()) key = rawKey.toUpper();
    else if (base.count() == 1) key = keyName(base[0].key());
    if (key.isEmpty()) return {};
    QJsonArray modifiers;
    for (const auto &name : names)
        if (parts.mid(0, parts.size() - 1).contains(name)) modifiers.append(name);
    return {{"key", key}, {"modifiers", modifiers}};
}
inline QString portable(const QJsonObject &binding) {
    QStringList parts;
    for (const auto &modifier : binding["modifiers"].toArray()) parts << modifier.toString();
    parts << binding["key"].toString();
    return parts.join('+');
}

class Recorder : public QDialog {
    QLabel *preview = new QLabel(I18n::tr("Press a key or shortcut"));
    QLabel *hint = new QLabel;
    QPushButton *use = new QPushButton(I18n::tr("Use shortcut"));
    QPushButton *manualMode = new QPushButton(I18n::tr("Type shortcut"));
    QLineEdit *manual = new QLineEdit;
    QSet<quint64> held;
    QJsonObject candidate;
    bool listening = true, mainKey = false, invalid = false;

    static quint64 physicalKey(QKeyEvent *event) {
        return event->nativeScanCode() ? (quint64(1) << 32) | event->nativeScanCode()
                                      : quint64(event->key() == Qt::Key_Backtab ? Qt::Key_Tab : event->key());
    }
    void reset() {
        held.clear();
        candidate = {};
        mainKey = false;
        invalid = false;
        listening = true;
        preview->setText(I18n::tr("Press a key or shortcut"));
        preview->show();
        manual->hide();
        manualMode->setText(I18n::tr("Type shortcut"));
        hint->clear();
        use->setEnabled(false);
        preview->setFocus();
    }
  protected:
    bool eventFilter(QObject *watched, QEvent *event) override {
        auto *widget = qobject_cast<QWidget *>(watched);
        if (!listening || !isVisible() || !widget || widget->window() != this)
            return QDialog::eventFilter(watched, event);
        if (event->type() == QEvent::WindowDeactivate && watched == this) {
            reset();
            return false;
        }
        if (event->type() == QEvent::ShortcutOverride) {
            event->accept();
            return true;
        }
        if (event->type() != QEvent::KeyPress && event->type() != QEvent::KeyRelease)
            return QDialog::eventFilter(watched, event);
        auto *key = static_cast<QKeyEvent *>(event);
        if (key->isAutoRepeat()) return true;
        if (event->type() == QEvent::KeyPress) {
            held.insert(physicalKey(key));
            if (!mainKey && !invalid) {
                const auto value = chord(key);
                if (value.isEmpty()) {
                    invalid = true;
                    candidate = {};
                    hint->setText(I18n::tr("This key is not supported. Try another key."));
                } else {
                    candidate = value;
                    mainKey = modifierName(key->key()).isEmpty();
                    preview->setText(display(candidate));
                    hint->setText(I18n::tr("Release the keys"));
                }
            }
        } else {
            held.remove(physicalKey(key));
            if (held.isEmpty() && invalid) {
                invalid = false;
                mainKey = false;
                preview->setText(I18n::tr("Press a key or shortcut"));
            }
            if (held.isEmpty() && !candidate.isEmpty()) {
                listening = false;
                hint->clear();
                use->setEnabled(true);
                use->setFocus();
            }
        }
        event->accept();
        return true;
    }
  public:
    explicit Recorder(const QString &title, QWidget *parent = nullptr) : QDialog(parent) {
        setObjectName("shortcut-recorder");
        setWindowTitle(title);
        setMinimumWidth(480);
        auto *layout = new QVBoxLayout(this);
        layout->setContentsMargins(24, 22, 24, 20);
        layout->setSpacing(16);
        auto *heading = new QHBoxLayout;
        auto *titleLabel = new QLabel(I18n::tr("Keyboard shortcut"));
        titleLabel->setProperty("kind", "section");
        heading->addWidget(titleLabel, 1);
        auto *info = new QToolButton;
        info->setObjectName("infoButton");
        info->setText("i");
        info->setFixedSize(22, 22);
        info->setAccessibleName(I18n::tr("About shortcut recording"));
        const QString explanation = I18n::tr(
            "Press a key with optional Ctrl, Shift, Alt or Super modifiers, then release it. "
            "Modifier keys can also be assigned on their own. Esc and Tab can be recorded; "
            "click Cancel to leave. Use Type shortcut to enter shortcuts reserved by your desktop. "
            "Assignments apply only while Fusion has focus. Printable keys use Fusion's keyboard layout; "
            "characters unavailable in that layout cannot be sent.");
        info->setToolTip(explanation);
        connect(info, &QToolButton::clicked, this, [this, explanation] {
            QMessageBox::information(this, I18n::tr("Shortcut recording"), explanation);
        });
        heading->addWidget(info);
        layout->addLayout(heading);
        preview->setObjectName("shortcut-preview");
        preview->setAlignment(Qt::AlignCenter);
        preview->setMinimumHeight(76);
        preview->setFocusPolicy(Qt::StrongFocus);
        preview->setStyleSheet("background:#1c2736; border:1px solid #526179; border-radius:4px; "
                              "padding:12px; font-size:18px;");
        layout->addWidget(preview);
        manual->setObjectName("manual-shortcut");
        manual->setPlaceholderText("Ctrl+Shift+S");
        manual->setMinimumHeight(52);
        manual->hide();
        layout->addWidget(manual);
        connect(manual, &QLineEdit::textChanged, this, [this](const QString &value) {
            if (!manual->isVisible()) return;
            candidate = parse(value);
            use->setEnabled(!candidate.isEmpty());
            hint->setText(value.isEmpty() || !candidate.isEmpty() ? "" : I18n::tr("Enter one key or shortcut"));
        });
        hint->setProperty("kind", "muted");
        hint->setMinimumHeight(18);
        layout->addWidget(hint);
        auto *actions = new QHBoxLayout;
        auto *again = new QPushButton(I18n::tr("Record again"));
        again->setObjectName("record-again");
        connect(again, &QPushButton::clicked, this, [this] { reset(); });
        actions->addWidget(again);
        manualMode->setObjectName("type-shortcut");
        connect(manualMode, &QPushButton::clicked, this, [this] {
            if (manual->isVisible()) { reset(); return; }
            listening = false;
            held.clear();
            preview->hide();
            manual->show();
            manualMode->setText(I18n::tr("Record keys"));
            hint->clear();
            manual->setText(candidate.isEmpty() ? "" : portable(candidate));
            candidate = parse(manual->text());
            use->setEnabled(!candidate.isEmpty());
            manual->setFocus();
            manual->selectAll();
        });
        actions->addWidget(manualMode);
        actions->addStretch();
        auto *cancel = new QPushButton(I18n::tr("Cancel"));
        cancel->setObjectName("cancel-recording");
        connect(cancel, &QPushButton::clicked, this, &QDialog::reject);
        actions->addWidget(cancel);
        use->setObjectName("use-shortcut");
        use->setProperty("primary", true);
        use->setDefault(true);
        use->setEnabled(false);
        connect(use, &QPushButton::clicked, this, &QDialog::accept);
        actions->addWidget(use);
        layout->addLayout(actions);
        qApp->installEventFilter(this);
        QTimer::singleShot(0, this, [this] { preview->setFocus(); });
    }
    ~Recorder() override { qApp->removeEventFilter(this); }
    QJsonObject binding() const { return candidate; }
};
} // namespace Shortcuts
