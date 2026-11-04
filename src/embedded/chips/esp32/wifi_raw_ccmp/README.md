# ESP32 raw CCMP receive policy

`#embedded/chips/esp32/wifi_raw_ccmp` provides the measured interface-zero
receive policy for a driver that owns the ESP32 Wi-Fi MAC and performs CCMP
in Xu. `prepare()` requires the Wi-Fi clock, stopped RX, an empty native key
table, and the caller's fully enabled station ACK address. It changes only
the crypto receive policy register and verifies its readback.

The caller must configure the raw routing and DMA arena, then authenticate
complete encrypted MPDUs with the installed software key and per-transmitter,
per-TID PN before exposing any payload. Hardware RX errors, malformed frames,
wrong addresses, and failed MICs remain failures. Hardware ACK stays enabled.

This is an experimental low-level primitive. It does not initialize PHY,
implement a persistent station driver, or activate the `WifiDevice` API.
