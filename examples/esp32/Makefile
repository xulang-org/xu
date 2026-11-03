XU ?= ../../bin/xu
PYTHON ?= python3
PORT ?= /dev/cu.usbserial-2110
OUT := build/console

.PHONY: all build pack verify flash clean
all: verify

build:
	mkdir -p build
	$(XU) build main.xu --target xtensa-esp32-none -o $(OUT).elf

pack: build
	$(PYTHON) ../../scripts/esp32_image.py pack $(OUT).elf $(OUT).bin --radio

verify: pack
	$(PYTHON) ../../scripts/esp32_image.py verify $(OUT).bin

flash: verify
	$(PYTHON) -m esptool --chip esp32 --port $(PORT) write_flash 0x10000 $(OUT).bin

clean:
	rm -rf build
