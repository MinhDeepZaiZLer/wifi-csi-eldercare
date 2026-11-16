#include "uart_out.h"

#include <stdbool.h>

#include "esp_mac.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static SemaphoreHandle_t s_mutex;
static bool s_header_printed;

void uart_out_init(void)
{
    if (!s_mutex) {
        s_mutex = xSemaphoreCreateMutex();
    }
}

void uart_line_emit(const char *line)
{
    if (!line) {
        return;
    }
    if (!s_mutex) {
        uart_out_init();
    }
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    esp_rom_printf("%s\n", line);
    xSemaphoreGive(s_mutex);
}

void uart_csv_emit(const csi_pkt_t *pkt)
{
    if (!pkt) {
        return;
    }
    if (!s_mutex) {
        uart_out_init();
    }

    const wifi_pkt_rx_ctrl_t *r = &pkt->rx_ctrl;

    xSemaphoreTake(s_mutex, portMAX_DELAY);

    if (!s_header_printed) {
        esp_rom_printf("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,"
                       "not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,"
                       "ampdu_cnt,channel,secondary_channel,local_timestamp,ant,"
                       "sig_len,rx_state,len,first_word,data\n");
        s_header_printed = true;
    }

    esp_rom_printf("CSI_DATA,%lu," MACSTR ",%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
                   (unsigned long)pkt->seq, MAC2STR(pkt->mac),
                   (int)r->rssi, (int)r->rate, (int)r->sig_mode, (int)r->mcs,
                   (int)r->cwb, (int)r->smoothing, (int)r->not_sounding,
                   (int)r->aggregation, (int)r->stbc, (int)r->fec_coding,
                   (int)r->sgi, (int)r->noise_floor, (int)r->ampdu_cnt,
                   (int)r->channel, (int)r->secondary_channel,
                   (int)r->timestamp, (int)r->ant, (int)r->sig_len,
                   (int)r->rx_state);

    esp_rom_printf(",%d,%d,\"[%d", pkt->len, pkt->first_word_invalid,
                   (int)(pkt->gain * pkt->buf[0]));
    for (int i = 1; i < pkt->len; i++) {
        esp_rom_printf(",%d", (int)(pkt->gain * pkt->buf[i]));
    }
    esp_rom_printf("]\"\n");

    xSemaphoreGive(s_mutex);
}
