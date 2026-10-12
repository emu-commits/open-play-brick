set(CORE ${CMAKE_CURRENT_LIST_DIR}/../../core)
idf_component_register(
    SRCS "main.c" "hal_espidf.c"
         "${CORE}/app.c" "${CORE}/catalog.c" "${CORE}/output.c" "${CORE}/pn5180.c" "${CORE}/sensors.c" "${CORE}/util.c"
    INCLUDE_DIRS "${CORE}"
    PRIV_REQUIRES driver esp_timer esp_partition esp_wifi nvs_flash esp_event esp_netif)
