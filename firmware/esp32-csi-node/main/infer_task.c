#include "infer_task.h"

#include <stdio.h>

#include "csi_features.h"
#include "csi_ring.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "infer.h"
#include "sdkconfig.h"
#include "tb_client.h"
#include "uart_out.h"

static const char *TAG = "infer_task";
static csi_window_t s_window;

static void infer_task(void *arg)
{
    (void)arg;

    csi_window_init(&s_window);
    csi_pkt_t pkt;
    int64_t last_us = esp_timer_get_time();
    uint32_t packets_this_period = 0;
    uint32_t total = 0;
    uint32_t dropped = 0;
    float last_rssi = 0.0f;
    uint16_t last_len = 0;
#if CONFIG_LINK_MODE_WIFI_MQTT
    int64_t last_publish_us = 0;
    bool previous_fall = false;
#endif

    while (1) {
        while (csi_ring_pop(&pkt, 0)) {
            csi_window_push(&s_window, &pkt);
            packets_this_period++;
            last_rssi = (float)pkt.rx_ctrl.rssi;
            last_len = pkt.len;
        }

        const int64_t now_us = esp_timer_get_time();
        const int64_t period_us = (int64_t)CONFIG_INFER_PERIOD_MS * 1000;
        if (now_us - last_us < period_us) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        csi_ring_stats(&total, &dropped);
        const float pps = (float)packets_this_period * 1000000.0f / (float)(now_us - last_us);
        packets_this_period = 0;
        last_us = now_us;

        const float motion = csi_window_motion(&s_window);
        infer_result_t res = {
            .state = "warmup",
            .presence = motion > 0.02f,
            .fall = false,
            .fall_score = 0.0f,
            .motion = motion,
            .model_ok = false,
        };
        if (csi_window_ready(&s_window)) {
            infer_run(&s_window, motion, &res);
        }

        const csi_features_t features = {
            .rssi = last_rssi,
            .pps = pps,
            .motion = res.motion,
            .presence = res.presence,
            .csi_len = last_len,
            .packets_total = total,
            .packets_dropped = dropped,
        };

        char line[256];
        snprintf(line, sizeof(line),
                 "INFER,{\"rssi\":%.1f,\"pps\":%.1f,\"motion\":%.4f,\"presence\":%d,"
                 "\"state\":\"%s\",\"fall\":%d,\"score\":%.4f,\"model_ok\":%d,"
                 "\"csi_len\":%u,\"total\":%lu,\"dropped\":%lu}",
                 features.rssi, features.pps, features.motion,
                 features.presence ? 1 : 0, res.state ? res.state : "unknown",
                 res.fall ? 1 : 0, res.fall_score, res.model_ok ? 1 : 0,
                 (unsigned)features.csi_len, (unsigned long)features.packets_total,
                 (unsigned long)features.packets_dropped);
        uart_line_emit(line);

#if CONFIG_LINK_MODE_WIFI_MQTT
        if (res.fall && !previous_fall) {
            tb_client_publish_fall(&res);
        }
        previous_fall = res.fall;

        if (last_publish_us == 0 ||
            now_us - last_publish_us >= (int64_t)CONFIG_TB_PUBLISH_INTERVAL_S * 1000000) {
            tb_client_publish_telemetry(&features, &res);
            last_publish_us = now_us;
        }
#endif
    }
}

void infer_task_start(void)
{
    BaseType_t ok = xTaskCreatePinnedToCore(infer_task, "infer", 6144, NULL, 5, NULL, 1);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "failed to create inference task");
    }
}
