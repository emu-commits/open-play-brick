/* Entry point on the ESP32-C3. See hal_espidf.c for the port's status. */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "app.h"

void hal_espidf_init(void);
void hal_espidf_radio_start(void (*handler)(const uint8_t *, int));

typedef struct { uint8_t len; uint8_t data[32]; } packet_t;
static QueueHandle_t radio_queue;

/* Runs in the Wi-Fi task: hand the packet to the main loop. */
static void on_radio(const uint8_t *data, int len)
{
    packet_t p;
    if (len <= 0 || len > (int)sizeof p.data) return;
    p.len = (uint8_t)len;
    memcpy(p.data, data, (size_t)len);
    xQueueSend(radio_queue, &p, 0);
}

void app_main(void)
{
    radio_queue = xQueueCreate(8, sizeof(packet_t));
    hal_espidf_init();
    hal_espidf_radio_start(on_radio);
    fw_init();
    for (;;) {
        packet_t p;
        while (xQueueReceive(radio_queue, &p, 0) == pdTRUE) fw_on_radio(p.data, p.len);
        fw_loop();
    }
}
