ENTRY(_start)

SECTIONS {
    . = 1M;

    .text : {
        *(.text.boot)
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
    }

    .data : {
        *(.data .data.*)
    }

    .bss : {
        *(.bss .bss.*)
        . = ALIGN(4096);
        _stack_bottom = .;
        . += 16K;
        _stack_top = .;
    }
}
