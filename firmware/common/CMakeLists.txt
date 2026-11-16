idf_component_register(
    SRCS "csi_ring.c" "csi_features.c" "infer.c" "tb_client.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_ringbuf mqtt json mbedtls esp_timer
)
