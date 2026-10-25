# GPL-3.0-or-later. Build with MinGW; no proprietary SDK/toolchain download.
SRC := ../siappdll/src
CXX := x86_64-w64-mingw32-g++
CC := x86_64-w64-mingw32-gcc
AR := x86_64-w64-mingw32-ar
CXXFLAGS := -O2 -std=c++17 -MMD -MP -I$(SRC) -Iminhook/include
OBJECTS := $(addprefix obj/,$(addsuffix .o,siappdll syncapi sock log camera_scale))

all: static
static: dist/siappdll-static.dll
obj dist:
	mkdir -p $@
obj/%.o: $(SRC)/%.cpp | obj
	$(CXX) $(CXXFLAGS) -c $< -o $@
-include $(OBJECTS:.o=.d)
obj/libminhook.a: | obj
	cd minhook && $(CC) -O2 -c -Iinclude -Isrc src/*.c src/hde/*.c
	$(AR) rcs $@ minhook/*.o
	rm -f minhook/*.o

dist/siappdll-static.dll: $(OBJECTS) ../siappdll/siappdll.def obj/libminhook.a | dist
	$(CXX) -shared -o $@ $(OBJECTS) ../siappdll/siappdll.def -Lobj -lminhook -lws2_32 -lbcrypt -static -s \
	    -Wl,--no-insert-timestamp -Wl,--image-base=0x6a000000 -Wl,--disable-auto-image-base
clean:
	rm -rf obj dist
.PHONY: all static clean
