idf_component_register(
    SRCS
        "idf_cyd_main.c"
        "control_parse.c"
        "hid_abs.c"
        "mqtt_bridge.c"
    INCLUDE_DIRS "."
    REQUIRES
        nvs_flash
        esp_event
        esp_netif
        esp_wifi
        bt
        esp_hid
        mqtt
)
