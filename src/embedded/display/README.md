# Embedded display surfaces

`Surface#T` is a controller-independent drawing boundary. It owns typed
backend state `T`, dimensions and two callbacks: rectangle fill and an
RGB565 row write. Widgets use the surface; board code selects the adapter.
The package has no chip, SPI, GPIO, font, Wi-Fi or Bluetooth dependency.

```xu
#embedded/display
#embedded/display/memory

fn example() bool {
    $surface := memory.create(320,240)
    if !surface.clear(0) { << false }
    if !surface.fill_rect(8,8,40,20,0xFFFF) { << false }
    << memory.pixel(8,8,&surface) == 0xFFFF
}
```

Import `#embedded/display/geometry` for `Rect` and `Span`. Adapters provide
`fn($&T,&geometry.Rect,int) bool` and
`fn($&T,&geometry.Span,&[]int) bool`, then call `display.create` with their
state and logical dimensions. Backends receive clipped coordinates and
validated buffer bounds. `Span.offset` and `Span.count` are pixel indices
and counts. Each input integer is a logical RGB565 color in `0..65535`;
the adapter handles its controller's pixel format and wire byte order.
Callbacks are synchronous and must not retain the pixel buffer borrow.
An invalid surface or malformed write returns false; empty/offscreen draws
on a valid surface succeed without invoking the backend. Backend failure
propagates to the caller. Copying or borrowing backend state follows normal
Xu ownership rules; the interface uses no untyped context pointer.

`#embedded/display/memory` provides a reference framebuffer for software
rendering and tests, bounded to 262144 pixels. `memory.pixel(x,y,&surface)`
reads a color; `memory.rgb565_bytes(&surface)` returns an independent packed
snapshot with high byte first. Its full framebuffer is optional: hardware
adapters can stream short rows without allocating one. The CYD status demo's
ST7789 adapter is one such implementation; its status cards render sixteen
pixels per radio event-loop iteration.

The interface supports logical dimensions from 1 to 32768 on each axis.
Individual widgets can require a minimum size: the status demo requires
320 × 240 and adjusts card widths, heights and positions for larger surfaces.
Controller initialization, rotation, backlight and bus selection belong to
the adapter; fonts, labels and status state belong to the UI.
