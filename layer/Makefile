CC ?= gcc
CFLAGS ?= -O2 -Wall -fPIC
LDFLAGS ?= -shared

TARGET = libVkLayer_fusion_present_sync.so
SRC = libVkLayer_fusion_present_sync.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
