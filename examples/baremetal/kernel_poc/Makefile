XU ?= xu

.PHONY: all build build-x64 build-arm64 build-rv64 qemu qemu-arm64 qemu-rv64 clean

all: build

build: build-x64 build-arm64 build-rv64

build-x64: kernel_x64.elf

kernel_x64.elf: main.xu
	$(XU) build --profile=freestanding --target=x64-none main.xu -o kernel_x64.elf

build-arm64: kernel_arm64.elf

kernel_arm64.elf: main.xu
	$(XU) build --profile=freestanding --target=arm64-none main.xu -o kernel_arm64.elf

build-rv64: kernel_rv64.elf

kernel_rv64.elf: main.xu
	$(XU) build --profile=freestanding --target=riscv64-none main.xu -o kernel_rv64.elf

qemu: kernel_x64.elf
	qemu-system-x86_64 -m 128M -kernel kernel_x64.elf -serial stdio -display none -no-reboot

qemu-arm64: kernel_arm64.elf
	qemu-system-aarch64 -M virt -cpu cortex-a53 -m 128M -kernel kernel_arm64.elf -serial stdio -display none -no-reboot

qemu-rv64: kernel_rv64.elf
	qemu-system-riscv64 -M virt -m 128M -bios none -kernel kernel_rv64.elf -serial stdio -display none -no-reboot

clean:
	rm -f kernel_x64.elf kernel_arm64.elf kernel_rv64.elf
