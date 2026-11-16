#pragma once

#include <stdbool.h>

#include "csi_types.h"
#include "infer.h"

bool tb_client_start(void);
bool tb_client_is_connected(void);
void tb_client_publish_telemetry(const csi_features_t *f, const infer_result_t *r);
void tb_client_publish_fall(const infer_result_t *r);
