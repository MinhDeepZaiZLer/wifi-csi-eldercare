#pragma once

#include "csi_types.h"

void uart_out_init(void);
void uart_csv_emit(const csi_pkt_t *pkt);
void uart_line_emit(const char *line);
