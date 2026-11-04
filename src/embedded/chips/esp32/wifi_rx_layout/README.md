# ESP32 RX DMA layout

`#embedded/chips/esp32/wifi_rx_layout` exposes:

```xu
layout := wifi_rx_layout.parse_owned_packet(&raw)
```

`raw` is the complete byte snapshot of one already-completed owned DMA packet,
including the RX control header, optional CSI, packet vector, MPDU, and word
padding. Its length must equal the descriptor's completed length. The caller
checks descriptor ownership/completion, buffer capacity/identity, and sentinels
before constructing the snapshot. The helper does no MMIO, imports no driver,
and allocates no packet storage or copied strings.

`Layout.bounded` confirms the selected offsets, frame length and zero padding
fit this snapshot exactly. `Layout.valid` additionally requires the selected
hardware RX status to be zero. A structurally bounded packet with status `0xE4`
has `bounded=true`, `valid=false`, and `status=0xE4`; its unpublished error code
is not interpreted as successful CRC or decryption. Invalid structural results
have `bounded=false`, `valid=false`, `status=-1`, and zero frame offsets/lengths.

The helper models the task's independently measured DMA profile: `sig_len`
includes four FCS bytes that the hardware physically strips before DMA. It
requires `frame_length=sig_len-4 >= 24` and the exact length:

```
raw.len = round_up_4(frame_offset + frame_length)
```

All bytes between the unpadded end and `raw.len` must be zero. Snapshots shorter
than 28 bytes or longer than 1600 bytes are rejected. Other RX DMA profiles,
multiple descriptors, A-MPDU deaggregation, and hardware-stripped crypto
trailers need their own contracts and are unsupported here.

The first 24 bytes are RX control metadata. CSI's reported length is bits 8..17
of the word at byte 20, rounded up to four bytes. With no CSI, the vector is at
byte 24, the MPDU is at byte 28, and `bug_case=-1`. When CSI is reported, both
candidate vector reads must fit before the native bug selection is applied:

| bug_case | vector/status source | frame_offset | csi_length |
| --- | --- | --- | --- |
| 0 | byte 24 + aligned CSI | 28 + aligned CSI | aligned CSI |
| 1 | byte 24 | 28 + aligned CSI | aligned CSI |
| 2 | byte 24 | 28 | 0 |
| 3 | rejected unknown CSI bug | 0 | 0 |

`csi_length` is the effective aligned length after the native correction. Case
2 discards the reported CSI length. Case 1 uses the original vector but the
shifted MPDU, matching the native sniffer's vector-copy correction. The parser
uses individual bytes for both 12-bit lengths and the status, avoiding signed
32-bit assembly of a vector whose status has its high bit set.

The contract comes from the installed ESP-IDF `libpp.a` member `wdev.o` (SHA-256
`9ed885984f82e8cfe9fa9309653aca00221e855501df94e345fe71eb73627493`), inspected
with REA/Ghidra 12.1.4 and Xtensa objdump. These are recovered pseudocode and
instruction observations, not original source or an observed hardware run:

- `wdev_csi_len_align`: evidence `ev_8768bfb213f7aa62c1f1eb027d2a3aad59e5086ea8b0f85fcb76bbf6b78537bf`.
- `wdev_csi_hw_bug_check`: evidence `ev_99e9258139ef8f85ef1729601e19223cbaac16216c90e1f8f7395a521c8e99b8`.
- `wDev_SnifferRxData`: evidence `ev_91e1267cd9370891e45a58986cbcb138f5f239176ca4a4868c57e75d9503502d`.
- Existing `wDev_ProcessRxSucData` evidence plus independently extracted assembly
  establishes the original/shifted status and frame pointer selections.

Complete evidence, readable pseudocode, instruction extracts, and the finding
ledger are in ignored `build/esp32-wifi/rx-crypto-*` development artifacts.
The packet-layout oracle uses independent Python construction of synthetic
DMA snapshots, malformed lengths/status/padding, all CSI branches, and every
truncated prefix. Host execution and an Xtensa build validate the helper;
hardware behavior is established separately by the owner's captures.
