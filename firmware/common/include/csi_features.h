#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "csi_types.h"

typedef struct {
    uint8_t amp[CSI_WINDOW_PACKETS][CSI_MAX_SUBCARRIERS];
    uint16_t head;
    uint16_t count;
    uint16_t subcarriers;
} csi_window_t;

void csi_window_init(csi_window_t *w);
bool csi_window_push(csi_window_t *w, const csi_pkt_t *pkt);
bool csi_window_ready(const csi_window_t *w);
void csi_window_copy(const csi_window_t *w, uint8_t *out);
float csi_window_motion(const csi_window_t *w);
