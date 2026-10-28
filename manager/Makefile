CXX ?= c++
CXXFLAGS ?= -O2
ROOT := $(abspath ..)
BUILD := $(ROOT)/.build/manager
QT_CFLAGS := $(shell pkg-config --cflags Qt6Widgets)
QT_LIBS := $(shell pkg-config --libs Qt6Widgets)
RCC ?= $(shell pkg-config --variable=libexecdir Qt6Core)/rcc
all: $(BUILD)/fusion-manager $(BUILD)/fusion-spacemouse-access
$(BUILD)/resources.cpp: resources.qrc $(ROOT)/desktop/fusion-manager.png icons/up.xpm icons/down.xpm
	mkdir -p $(BUILD)
	$(RCC) --name manager $< -o $@
$(BUILD)/fusion-manager: main.cpp $(BUILD)/resources.cpp shortcut.h i18n.h update_notice.h
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -fPIC $(QT_CFLAGS) main.cpp $(BUILD)/resources.cpp -o $@ $(QT_LIBS)
$(BUILD)/fusion-spacemouse-access: $(ROOT)/spacemouse/access-helper.cpp
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror $< -o $@
$(BUILD)/shortcut-test: tests/shortcut_test.cpp shortcut.h i18n.h
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -fPIC $(shell pkg-config --cflags Qt6Widgets Qt6Test) $< -o $@ $(shell pkg-config --libs Qt6Widgets Qt6Test)
$(BUILD)/i18n-test: tests/i18n_test.cpp i18n.h update_notice.h
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -fPIC $(shell pkg-config --cflags Qt6Core) $< -o $@ $(shell pkg-config --libs Qt6Core)
check: $(BUILD)/shortcut-test $(BUILD)/i18n-test
	QT_QPA_PLATFORM=offscreen $(BUILD)/shortcut-test
	$(BUILD)/i18n-test
clean:
	rm -f $(BUILD)/fusion-manager $(BUILD)/fusion-spacemouse-access $(BUILD)/resources.cpp $(BUILD)/shortcut-test $(BUILD)/i18n-test
.PHONY: all clean check
