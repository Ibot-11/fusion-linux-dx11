CXX ?= c++
CXXFLAGS ?= -O2
ROOT := $(abspath ..)
BUILD := $(ROOT)/.build/manager
QT_CFLAGS := $(shell pkg-config --cflags Qt6Widgets)
QT_LIBS := $(shell pkg-config --libs Qt6Widgets)
all: $(BUILD)/fusion-manager $(BUILD)/fusion-spacemouse-access
$(BUILD)/fusion-manager: main.cpp
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror -fPIC $(QT_CFLAGS) $< -o $@ $(QT_LIBS)
$(BUILD)/fusion-spacemouse-access: $(ROOT)/spacemouse/access-helper.cpp
	mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Werror $< -o $@
clean:
	rm -f $(BUILD)/fusion-manager $(BUILD)/fusion-spacemouse-access
.PHONY: all clean
