#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "csi_types.h"

bool csi_ring_init(void);
bool csi_ring_push(const csi_pkt_t *pkt);
bool csi_ring_pop(csi_pkt_t *pkt, TickType_t ticks_to_wait);
void csi_ring_stats(uint32_t *pushed, uint32_t *dropped);
