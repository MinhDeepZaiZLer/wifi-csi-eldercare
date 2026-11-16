#pragma once

#include <stdbool.h>

#include "csi_features.h"

typedef struct {
    const char *state;
    bool presence;
    bool fall;
    float fall_score;
    float motion;
    bool model_ok;
} infer_result_t;

bool infer_init(void);
void infer_run(const csi_window_t *w, float motion, infer_result_t *out);
