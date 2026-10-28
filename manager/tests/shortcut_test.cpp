// SPDX-License-Identifier: GPL-3.0-or-later
#include "../shortcut.h"
#include <QtTest>
#include <iostream>

static void check(bool condition, const char *message) {
    if (!condition) { std::cerr << message << std::endl; std::exit(1); }
}
static QPushButton *useButton(Shortcuts::Recorder &dialog) {
    return dialog.findChild<QPushButton *>("use-shortcut");
}
static void ready(Shortcuts::Recorder &dialog) {
    dialog.show();
    QTest::qWait(10);
}
int main(int argc, char **argv) {
    QApplication app(argc, argv);
    I18n::setLanguage("en");
    {
        Shortcuts::Recorder dialog("Left button"); ready(dialog);
        QTest::keyClick(&dialog, Qt::Key_G);
        check(dialog.binding()["key"] == "G", "An arbitrary letter must be recorded");
        check(dialog.binding()["modifiers"].toArray().isEmpty(), "Plain letter must not gain Shift");
        check(useButton(dialog)->isEnabled(), "Released key must be ready to apply");
    }
    {
        Shortcuts::Recorder dialog("Left button"); ready(dialog);
        QTest::keyClick(&dialog, Qt::Key_S, Qt::ControlModifier | Qt::ShiftModifier);
        const auto modifiers = dialog.binding()["modifiers"].toArray();
        check(dialog.binding()["key"] == "S" && modifiers.contains("CTRL") && modifiers.contains("SHIFT"),
              "Ctrl+Shift+S must retain its key and both modifiers");
        check(useButton(dialog)->isEnabled(), "Chord must finish only after keys are released");
        check(Shortcuts::display(dialog.binding()) == "Ctrl + Shift + S", "Chord label must be readable");
        dialog.findChild<QPushButton *>("record-again")->click();
        check(!useButton(dialog)->isEnabled(), "Record again must clear the previous shortcut");
        QTest::keyClick(&dialog, Qt::Key_F12);
        check(dialog.binding()["key"] == "F12", "Function keys must be assignable");
    }
    {
        Shortcuts::Recorder dialog("Right button"); ready(dialog);
        QTest::keyPress(&dialog, Qt::Key_Control);
        check(!useButton(dialog)->isEnabled(), "A held modifier must not finish recording early");
        QTest::keyRelease(&dialog, Qt::Key_Control);
        check(dialog.binding()["key"] == "CTRL" && useButton(dialog)->isEnabled(),
              "A modifier-only hold must be assignable");
    }
    for (auto key : {Qt::Key_Escape, Qt::Key_Tab, Qt::Key_Backtab, Qt::Key_Delete, Qt::Key_Adiaeresis}) {
        Shortcuts::Recorder dialog("Right button"); ready(dialog);
        QTest::keyClick(&dialog, key);
        check(dialog.isVisible() && useButton(dialog)->isEnabled(),
              "Esc, Tab, navigation and layout characters must be recordable without closing the dialog");
        check(!dialog.binding()["key"].toString().isEmpty(), "Recorded key must have a stable identity");
    }
    {
        Shortcuts::Recorder dialog("Right button"); ready(dialog);
        QTest::keyPress(&dialog, Qt::Key_Control);
        QTest::keyClick(&dialog, Qt::Key_VolumeUp, Qt::ControlModifier);
        QTest::keyRelease(&dialog, Qt::Key_Control);
        check(!useButton(dialog)->isEnabled() && dialog.binding().isEmpty(),
              "An unsupported key must not silently become a modifier-only binding");
        QTest::keyClick(&dialog, Qt::Key_Home);
        check(dialog.binding()["key"] == "HOME" && useButton(dialog)->isEnabled(),
              "Recording must recover after an unsupported key");
        dialog.findChild<QPushButton *>("cancel-recording")->click();
        check(dialog.result() == QDialog::Rejected, "Cancel must discard recording");
    }
    {
        Shortcuts::Recorder dialog("Right button"); ready(dialog);
        dialog.findChild<QPushButton *>("type-shortcut")->click();
        auto *edit = dialog.findChild<QLineEdit *>("manual-shortcut");
        QTest::keyClicks(edit, "Ctrl+Alt+Delete");
        check(dialog.binding()["key"] == "DELETE" && useButton(dialog)->isEnabled(),
              "Desktop-reserved shortcuts must also be assignable by text");
        edit->setText("Ctrl+A, Ctrl+B");
        check(!useButton(dialog)->isEnabled(), "A multi-step sequence is not a single shortcut");
        edit->setText("Super+D");
        check(dialog.binding()["modifiers"].toArray().contains("META"), "Super must map to Meta");
        edit->setText("Ctrl+Shift");
        check(dialog.binding()["key"] == "SHIFT" && dialog.binding()["modifiers"].toArray().contains("CTRL"),
              "A modifier-only combination must also be available in text mode");
        edit->setText("Ctrl + Shift");
        check(dialog.binding()["modifiers"].toArray().contains("CTRL"), "Spaces must not drop modifiers");
        edit->setText("AltGr+Q");
        check(dialog.binding()["modifiers"].toArray().contains("ALTGR"), "AltGr must work in text mode");
        edit->setText("Ctrl+NUMENTER");
        check(dialog.binding()["key"] == "NUMENTER", "Keypad names must work in text mode");
        dialog.findChild<QPushButton *>("record-again")->click();
        QTest::keyClick(&dialog, Qt::Key_F24);
        check(dialog.binding()["key"] == "F24", "Recording must work after leaving text mode");
    }
    {
        Shortcuts::Recorder dialog("Right button"); ready(dialog);
        QTest::keyClick(&dialog, Qt::Key_1, Qt::KeypadModifier);
        check(dialog.binding()["key"] == "NUM1", "Keypad digits must retain their distinct identity");
    }
    {
        I18n::setLanguage("de");
        Shortcuts::Recorder dialog("Rechte Taste"); ready(dialog);
        check(dialog.findChild<QLabel *>("shortcut-preview")->text() == "Taste oder Tastenkürzel drücken",
              "Recorder instructions must follow the selected language");
        check(useButton(dialog)->text() == "Tastenkürzel übernehmen",
              "Recorder actions must follow the selected language");
        check(dialog.findChild<QPushButton *>("cancel-recording")->text() == "Abbrechen",
              "Recorder cancellation must follow the selected language");
        check(Shortcuts::display(QJsonValue("off")) == "Keine Aktion",
              "Binding labels must follow the selected language");
        QTest::keyClick(&dialog, Qt::Key_Home);
        check(dialog.findChild<QLabel *>("shortcut-preview")->text() == "Pos1",
              "German key labels must not change the recorded key identity");
        check(dialog.binding()["key"] == "HOME", "German recording must retain stable backend keys");
        check(Shortcuts::display(Shortcuts::parse("Ctrl+Shift+S")) == "Strg + Umschalt + S",
              "German modifier labels must be localized without changing portable input");
        I18n::setLanguage("en");
    }
    std::cout << "PASS shortcut capture: arbitrary keys, chords, modifiers, reserved dialog keys, retry and cancel\n";
    std::cout << "PASS shortcut i18n: localized controls, key labels and stable backend identities\n";
    return 0;
}
