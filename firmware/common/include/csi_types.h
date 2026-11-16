#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_wifi_types.h"

#define CSI_MAX_LEN 384
#define CSI_MAX_SUBCARRIERS (CSI_MAX_LEN / 2)
#define CSI_WINDOW_PACKETS 250
#define CSI_TB_VERSION "0.1.0"

typedef struct {
    wifi_pkt_rx_ctrl_t rx_ctrl;
    uint8_t mac[6];
    uint16_t len;
    uint8_t first_word_invalid;
    uint32_t seq;
    float gain;
    int8_t buf[CSI_MAX_LEN];
} csi_pkt_t;

typedef struct {
    float rssi;
    float pps;
    float motion;
    bool presence;
    uint16_t csi_len;
    uint32_t packets_total;
    uint32_t packets_dropped;
} csi_features_t;
