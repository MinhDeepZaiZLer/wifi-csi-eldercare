#include "infer.h"

#include "esp_log.h"

static const char *TAG = "infer";

#define PRESENCE_THRESHOLD 0.02f

bool infer_init(void)
{
    ESP_LOGW(TAG, "TFLite Micro model not integrated; using rule-based fallback");
    return false;
}

void infer_run(const csi_window_t *w, float motion, infer_result_t *out)
{
    if (!out) {
        return;
    }

    (void)w;
    out->motion = motion;
    out->presence = motion > PRESENCE_THRESHOLD;
    out->state = out->presence ? "motion" : "empty";
    out->fall = false;
    out->fall_score = 0.0f;
    out->model_ok = false;
}
