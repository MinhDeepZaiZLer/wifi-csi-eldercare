#include "tb_client.h"

#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include "sdkconfig.h"

static const char *TAG = "tb_client";

static esp_mqtt_client_handle_t s_client;
static volatile bool s_connected;

static void publish_json(const char *topic, const char *json, int retain)
{
    if (!s_client || !s_connected || !json) {
        return;
    }
    esp_mqtt_client_publish(s_client, topic, json, 0, 1, retain);
}

static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void)args;
    (void)base;
    (void)event_data;

    switch (event_id) {
    case MQTT_EVENT_CONNECTED: {
        s_connected = true;
        ESP_LOGI(TAG, "MQTT connected");
        char attrs[160];
        snprintf(attrs, sizeof(attrs), "{\"fw\":\"%s\",\"room\":\"%s\",\"subject\":\"%s\"}",
                 CSI_TB_VERSION, CONFIG_TB_ROOM, CONFIG_TB_SUBJECT);
        esp_mqtt_client_publish(s_client, "v1/devices/me/attributes", attrs, 0, 1, 1);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        s_connected = false;
        ESP_LOGW(TAG, "MQTT disconnected");
        break;
    case MQTT_EVENT_ERROR:
        s_connected = false;
        ESP_LOGE(TAG, "MQTT error");
        break;
    default:
        break;
    }
}

bool tb_client_start(void)
{
    if (strlen(CONFIG_TB_TOKEN) == 0) {
        ESP_LOGE(TAG, "CONFIG_TB_TOKEN is empty; set it with menuconfig");
        return false;
    }

    static char uri[160];
#if CONFIG_TB_TLS
    snprintf(uri, sizeof(uri), "mqtts://%s:%d", CONFIG_TB_HOST, CONFIG_TB_PORT);
#else
    snprintf(uri, sizeof(uri), "mqtt://%s:%d", CONFIG_TB_HOST, CONFIG_TB_PORT);
#endif

    esp_mqtt_client_config_t cfg = {0};
    cfg.broker.address.uri = uri;
    cfg.credentials.username = CONFIG_TB_TOKEN;
    cfg.credentials.authentication.password = "";
    cfg.session.keepalive = 60;
    cfg.network.reconnect_timeout_ms = 5000;
#if CONFIG_TB_TLS
    cfg.broker.verification.crt_bundle_attach = esp_crt_bundle_attach;
#endif

    s_client = esp_mqtt_client_init(&cfg);
    if (!s_client) {
        ESP_LOGE(TAG, "esp_mqtt_client_init failed");
        return false;
    }

    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_err_t err = esp_mqtt_client_start(s_client);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_mqtt_client_start failed: %s", esp_err_to_name(err));
        return false;
    }

    ESP_LOGI(TAG, "connecting to %s", uri);
    return true;
}

bool tb_client_is_connected(void)
{
    return s_connected;
}

void tb_client_publish_telemetry(const csi_features_t *f, const infer_result_t *r)
{
    if (!f || !r) {
        return;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return;
    }

    cJSON_AddNumberToObject(root, "rssi", f->rssi);
    cJSON_AddNumberToObject(root, "pps", f->pps);
    cJSON_AddNumberToObject(root, "motion", f->motion);
    cJSON_AddNumberToObject(root, "presence", f->presence ? 1 : 0);
    cJSON_AddStringToObject(root, "state", r->state ? r->state : "unknown");
    cJSON_AddNumberToObject(root, "csi_len", f->csi_len);

    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        publish_json("v1/devices/me/telemetry", json, 0);
        cJSON_free(json);
    }
    cJSON_Delete(root);
}

void tb_client_publish_fall(const infer_result_t *r)
{
    if (!r) {
        return;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return;
    }

    cJSON_AddStringToObject(root, "event", "fall");
    cJSON_AddNumberToObject(root, "score", r->fall_score);
    cJSON_AddStringToObject(root, "state", r->state ? r->state : "fall");

    char *json = cJSON_PrintUnformatted(root);
    if (json) {
        publish_json("v1/devices/me/telemetry", json, 1);
        cJSON_free(json);
    }
    cJSON_Delete(root);
}
