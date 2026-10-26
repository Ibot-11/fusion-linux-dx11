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
$(BUILD)/fusion-manager: main.cpp $(BUILD)/resources.cpp
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -fPIC $(QT_CFLAGS) $^ -o $@ $(QT_LIBS)
$(BUILD)/fusion-spacemouse-access: $(ROOT)/spacemouse/access-helper.cpp
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror $< -o $@
clean:
	rm -f $(BUILD)/fusion-manager $(BUILD)/fusion-spacemouse-access $(BUILD)/resources.cpp
.PHONY: all clean
