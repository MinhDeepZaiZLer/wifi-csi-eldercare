#include "csi_ring.h"

#include <string.h>

#include "freertos/ringbuf.h"

#define CSI_RING_ITEMS 64

static RingbufHandle_t s_rb;
static volatile uint32_t s_pushed;
static volatile uint32_t s_dropped;

bool csi_ring_init(void)
{
    if (s_rb) {
        return true;
    }
    s_rb = xRingbufferCreate(CSI_RING_ITEMS * sizeof(csi_pkt_t), RINGBUF_TYPE_NOSPLIT);
    return s_rb != NULL;
}

bool csi_ring_push(const csi_pkt_t *pkt)
{
    if (!s_rb || !pkt) {
        return false;
    }
    if (xRingbufferSend(s_rb, pkt, sizeof(*pkt), 0) != pdTRUE) {
        __atomic_fetch_add(&s_dropped, 1, __ATOMIC_RELAXED);
        return false;
    }
    __atomic_fetch_add(&s_pushed, 1, __ATOMIC_RELAXED);
    return true;
}

bool csi_ring_pop(csi_pkt_t *pkt, TickType_t ticks_to_wait)
{
    if (!s_rb || !pkt) {
        return false;
    }
    size_t size = 0;
    void *item = xRingbufferReceive(s_rb, &size, ticks_to_wait);
    if (!item) {
        return false;
    }
    bool ok = (size == sizeof(*pkt));
    if (ok) {
        memcpy(pkt, item, size);
    }
    vRingbufferReturnItem(s_rb, item);
    return ok;
}

void csi_ring_stats(uint32_t *pushed, uint32_t *dropped)
{
    if (pushed) {
        *pushed = s_pushed;
    }
    if (dropped) {
        *dropped = s_dropped;
    }
}
