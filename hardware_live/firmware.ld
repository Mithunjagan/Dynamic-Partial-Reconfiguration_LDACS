ENTRY(_start)
MEMORY { DDR_IMAGE (rwx) : ORIGIN = 0x01000000, LENGTH = 16M }
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
    . = ORIGIN(DDR_IMAGE);
    .text : { *(.text*) *(.rodata*) . = ALIGN(8); } > DDR_IMAGE :code
    .ARM.extab : { *(.ARM.extab*) } > DDR_IMAGE :code
    .ARM.exidx : { *(.ARM.exidx*) . = ALIGN(8); } > DDR_IMAGE :code
    .data : { *(.data*) . = ALIGN(8); } > DDR_IMAGE :data
    .bss (NOLOAD) : {
        __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(8); __bss_end = .;
    } > DDR_IMAGE :data
    /DISCARD/ : { *(.note.gnu.build-id) }
    __stack_top = ORIGIN(DDR_IMAGE) + LENGTH(DDR_IMAGE);
}
