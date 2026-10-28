// SPDX-License-Identifier: GPL-3.0-or-later
#include "../i18n.h"
#include "../update_notice.h"
#include <iostream>

static void check(bool condition, const char *message) {
    if (!condition) { std::cerr << message << std::endl; std::exit(1); }
}

int main() {
    check(I18n::languageFromCode("de") == I18n::Language::German, "de must select German");
    check(I18n::languageFromCode("de_DE") == I18n::Language::German, "German locales must select German");
    check(I18n::languageFromCode("en_US") == I18n::Language::English, "English locales must select English");
    check(I18n::languageFromCode("fr_FR") == I18n::Language::English, "Other locales must fall back to English");
    check(I18n::languageCode(I18n::Language::German) == "de", "German must have a stable settings code");
    check(I18n::locale(I18n::Language::German).language() == QLocale::German,
          "German UI must use a German QLocale");
    check(I18n::locale(I18n::Language::English).language() == QLocale::English,
          "English UI must use an English QLocale");

    I18n::setLanguage("en");
    check(I18n::tr("Overview") == "Overview", "English must preserve source strings");
    check(I18n::tr("%1 new commits").arg(3) == "3 new commits", "English formatting must work");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"ahead", 0}, {"behind", 0}}) ==
              "Already up to date · No update required",
          "A current checkout must produce explicit feedback");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"ahead", 2}, {"behind", 0}}) ==
              "Local checkout is ahead · No update required",
          "Local commits must be explained without attempting an update");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"ahead", 1}, {"behind", 1}}) ==
              "Divergent Git history · Update not started",
          "Divergent history must be rejected before running Git");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"dirty", true}, {"behind", 2}}) ==
              "Local changes present · Update not started",
          "Local changes must be explained before running Git");
    check(UpdateNotice::forRepository({{"ahead", 0}, {"behind", 0}}).isEmpty(),
          "An unchecked checkout must still fetch instead of claiming to be current");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"ahead", 0}, {"behind", 2}}).isEmpty(),
          "Available upstream commits must start the update");
    I18n::setLanguage("de");
    check(I18n::tr("Overview") == "Übersicht", "German navigation must be translated");
    check(I18n::tr("Another action is running.") == "Eine andere Aktion wird ausgeführt.",
          "Dynamic availability messages must be translated");
    check(I18n::tr("%1 new commit").arg(1) == "1 neuer Commit", "German singular formatting must work");
    check(I18n::tr("%1 new commits").arg(3) == "3 neue Commits", "German plural formatting must work");
    check(UpdateNotice::forRepository({{"checked", 1.0}, {"ahead", 0}, {"behind", 0}}) ==
              "Bereits aktuell · Keine Aktualisierung erforderlich",
          "Current-checkout feedback must be translated");
    check(I18n::tr("backend-provided technical detail") == "backend-provided technical detail",
          "Unknown technical details must pass through unchanged");
    check(I18n::german().size() > 150, "The complete UI dictionary must be available");
    std::cout << "PASS i18n: locale selection, stable codes, German dictionary, formatting, update feedback and fallback\n";
    return 0;
}
