idf_component_register(
    SRCS
        "idf_cyd_main.c"
        "hid_abs.c"
        "status_lcd.c"
        "xu_host.c"
    INCLUDE_DIRS "."
    REQUIRES
        nvs_flash
        esp_event
        esp_netif
        esp_wifi
        bt
        esp_hid
        esp_lcd
        esp_driver_spi
        esp_driver_gpio
)

# Xu application code, compiled to an Xtensa relocatable object by the Xu
# compiler and linked into this component like any other object. The
# dashboard is status_demo's ui.xu (#embedded/display), staged next to xu/
# because @main sources must share one directory.
set(XU_BIN "${CMAKE_CURRENT_LIST_DIR}/../../../../bin/xu" CACHE FILEPATH "Xu compiler")
get_filename_component(XU_REPO "${CMAKE_CURRENT_LIST_DIR}/../../../.." ABSOLUTE)
file(GLOB XU_APP_SRCS CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/../xu/*.xu")
set(XU_SRCS ${XU_APP_SRCS} "${XU_REPO}/examples/esp32/status_demo/ui.xu")
set(XU_STAGE "${CMAKE_CURRENT_BINARY_DIR}/xu_src")
set(XU_STAGED "")
foreach(src ${XU_SRCS})
    get_filename_component(name "${src}" NAME)
    list(APPEND XU_STAGED "${XU_STAGE}/${name}")
endforeach()
set(XU_OBJ "${CMAKE_CURRENT_BINARY_DIR}/xu_app.o")
add_custom_command(
    OUTPUT "${XU_OBJ}"
    COMMAND "${CMAKE_COMMAND}" -E rm -rf "${XU_STAGE}"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${XU_STAGE}"
    COMMAND "${CMAKE_COMMAND}" -E copy ${XU_SRCS} "${XU_STAGE}"
    COMMAND "${XU_BIN}" build --target xtensa-esp32-none --emit-obj -o "${XU_OBJ}" ${XU_STAGED}
    WORKING_DIRECTORY "${XU_REPO}"
    DEPENDS ${XU_SRCS} "${XU_BIN}"
    COMMENT "Compiling Xu sources to ${XU_OBJ}"
    VERBATIM)
set_source_files_properties("${XU_OBJ}" PROPERTIES EXTERNAL_OBJECT TRUE GENERATED TRUE)
target_sources(${COMPONENT_LIB} PRIVATE "${XU_OBJ}")
