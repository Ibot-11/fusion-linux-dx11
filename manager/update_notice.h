// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "i18n.h"
#include <QJsonObject>

namespace UpdateNotice {
inline QString forRepository(const QJsonObject &repo) {
    const int ahead = repo["ahead"].toInt(), behind = repo["behind"].toInt();
    if (repo["dirty"].toBool())
        return I18n::tr("Local changes present · Update not started");
    if (ahead > 0 && behind > 0)
        return I18n::tr("Divergent Git history · Update not started");
    if (repo["checked"].isDouble() && behind == 0)
        return I18n::tr(ahead > 0 ? "Local checkout is ahead · No update required"
                                  : "Already up to date · No update required");
    return {};
}
} // namespace UpdateNotice
