#include <string.h>

#include "csi_ring.h"
#include "csi_types.h"
#include "esp_csi_gain_ctrl.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "infer.h"
#include "infer_task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "tb_client.h"
#include "uart_out.h"

static const char *TAG = "csi-node";
static const uint8_t SENDER_MAC[6] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || \
    CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C6 || CONFIG_IDF_TARGET_ESP32C61
#define GAIN_CONTROL 1
#else
#define GAIN_CONTROL 0
#endif

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi disconnected; reconnecting");
        esp_wifi_connect();
    }
}

static void wifi_init(bool connect_sta)
{
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_ERROR_CHECK(esp_netif_init());

    if (connect_sta) {
        esp_netif_create_default_wifi_sta();
    }

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT40));

    if (connect_sta) {
        ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                            &wifi_event_handler, NULL, NULL));
        wifi_config_t wc = {0};
        strncpy((char *)wc.sta.ssid, CONFIG_WIFI_SSID, sizeof(wc.sta.ssid) - 1);
        strncpy((char *)wc.sta.password, CONFIG_WIFI_PASSWORD, sizeof(wc.sta.password) - 1);
        wc.sta.threshold.authmode = WIFI_AUTH_OPEN;
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    }

    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    if (connect_sta) {
        ESP_LOGI(TAG, "connecting to SSID '%s'", CONFIG_WIFI_SSID);
        esp_wifi_connect();
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_CSI_CHANNEL, WIFI_SECOND_CHAN_BELOW));
        ESP_LOGI(TAG, "UART mode on channel %d", CONFIG_CSI_CHANNEL);
    }
}

static void esp_now_link_init(void)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));

    esp_now_peer_info_t peer = {
        .channel = CONFIG_CSI_CHANNEL,
        .ifidx = WIFI_IF_STA,
        .encrypt = false,
        .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
    };
    esp_err_t err = esp_now_add_peer(&peer);
    if (err != ESP_OK && err != ESP_ERR_ESPNOW_EXIST) {
        ESP_ERROR_CHECK(err);
    }

    esp_now_rate_config_t rate = {
        .phymode = WIFI_PHY_MODE_HT40,
        .rate = WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false,
    };
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate));
}

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;

    if (!info || !info->buf || info->len == 0 || info->len > CSI_MAX_LEN || (info->len % 2)) {
        return;
    }
    if (memcmp(info->mac, SENDER_MAC, sizeof(SENDER_MAC)) != 0) {
        return;
    }

    static int s_count;
    float gain_compensation = 1.0f;

#if GAIN_CONTROL
    static uint8_t agc_gain;
    static int8_t fft_gain;
    static uint8_t agc_baseline;
    static int8_t fft_baseline;
    esp_csi_gain_ctrl_get_rx_gain(&info->rx_ctrl, &agc_gain, &fft_gain);
    if (s_count < 100) {
        esp_csi_gain_ctrl_record_rx_gain(agc_gain, fft_gain);
    } else if (s_count == 100) {
        esp_csi_gain_ctrl_get_rx_gain_baseline(&agc_baseline, &fft_baseline);
        ESP_LOGI(TAG, "gain baseline agc=%u fft=%d", agc_baseline, fft_baseline);
    }
    esp_csi_gain_ctrl_get_gain_compensation(&gain_compensation, agc_gain, fft_gain);
#endif

    csi_pkt_t pkt = {0};
    pkt.rx_ctrl = info->rx_ctrl;
    memcpy(pkt.mac, info->mac, sizeof(pkt.mac));
    pkt.len = info->len;
    pkt.first_word_invalid = info->first_word_invalid;
    pkt.gain = gain_compensation;
    if (info->payload) {
        memcpy(&pkt.seq, info->payload + 15, sizeof(pkt.seq));
    }
    memcpy(pkt.buf, info->buf, info->len);

    if (!csi_ring_push(&pkt) && (s_count % 100) == 0) {
        ESP_LOGW(TAG, "CSI ring full; dropping packet");
    }

#if CONFIG_UART_CSV_ENABLE
    uart_csv_emit(&pkt);
#endif

    s_count++;
}

static void csi_init(void)
{
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

    wifi_csi_config_t csi_config = {
        .lltf_en = true,
        .htltf_en = true,
        .stbc_htltf2_en = true,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = false,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    uart_out_init();
    if (!csi_ring_init()) {
        ESP_LOGE(TAG, "CSI ring init failed");
        return;
    }

#if CONFIG_LINK_MODE_WIFI_MQTT
    const bool connect_sta = true;
#else
    const bool connect_sta = false;
#endif

    wifi_init(connect_sta);
    esp_now_link_init();
    csi_init();

    infer_init();
    infer_task_start();

#if CONFIG_LINK_MODE_WIFI_MQTT
    if (!tb_client_start()) {
        ESP_LOGE(TAG, "ThingsBoard client failed to start");
    }
#endif

    ESP_LOGI(TAG, "ready: mode=%s channel=%d uart_csv=%d",
             connect_sta ? "wifi+mqtt" : "uart", CONFIG_CSI_CHANNEL,
             CONFIG_UART_CSV_ENABLE);
}
