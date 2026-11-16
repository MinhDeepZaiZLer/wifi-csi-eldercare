#include "csi_features.h"

#include <math.h>
#include <string.h>

void csi_window_init(csi_window_t *w)
{
    if (!w) {
        return;
    }
    memset(w, 0, sizeof(*w));
}

bool csi_window_push(csi_window_t *w, const csi_pkt_t *pkt)
{
    if (!w || !pkt || pkt->len != CSI_MAX_LEN) {
        return false;
    }

    const float gain = (pkt->gain > 0.0f) ? pkt->gain : 1.0f;
    for (uint16_t k = 0; k < CSI_MAX_SUBCARRIERS; k++) {
        const float imag = gain * (float)pkt->buf[2 * k];
        const float real = gain * (float)pkt->buf[2 * k + 1];
        float amp = sqrtf(imag * imag + real * real);
        if (amp > 255.0f) {
            amp = 255.0f;
        }
        w->amp[w->head][k] = (uint8_t)(amp + 0.5f);
    }

    w->head = (w->head + 1) % CSI_WINDOW_PACKETS;
    if (w->count < CSI_WINDOW_PACKETS) {
        w->count++;
    }
    w->subcarriers = CSI_MAX_SUBCARRIERS;
    return true;
}

bool csi_window_ready(const csi_window_t *w)
{
    return w && w->count >= CSI_WINDOW_PACKETS;
}

void csi_window_copy(const csi_window_t *w, uint8_t *out)
{
    static const uint8_t zero[CSI_MAX_SUBCARRIERS];

    if (!w || !out) {
        return;
    }

    const uint16_t start = (w->head + CSI_WINDOW_PACKETS - w->count) % CSI_WINDOW_PACKETS;
    for (uint16_t i = 0; i < CSI_WINDOW_PACKETS; i++) {
        const uint8_t *src = (i < w->count) ? w->amp[(start + i) % CSI_WINDOW_PACKETS] : zero;
        memcpy(out + i * CSI_MAX_SUBCARRIERS, src, CSI_MAX_SUBCARRIERS);
    }
}

float csi_window_motion(const csi_window_t *w)
{
    if (!w || w->count < 2) {
        return 0.0f;
    }

    const uint16_t start = (w->head + CSI_WINDOW_PACKETS - w->count) % CSI_WINDOW_PACKETS;
    float sum = 0.0f;
    uint32_t count = 0;

    for (uint16_t i = 1; i < w->count; i++) {
        const uint8_t *prev = w->amp[(start + i - 1) % CSI_WINDOW_PACKETS];
        const uint8_t *cur = w->amp[(start + i) % CSI_WINDOW_PACKETS];
        for (uint16_t k = 0; k < CSI_MAX_SUBCARRIERS; k++) {
            sum += fabsf((float)cur[k] - (float)prev[k]);
            count++;
        }
    }

    return count ? (sum / (float)count) / 255.0f : 0.0f;
}
