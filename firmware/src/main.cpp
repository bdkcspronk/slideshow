#include <Arduino.h>
#include "esp_wifi.h"
#include "nvs_flash.h"

int currentChannel = 1;
unsigned long lastChannelChange = 0;

const uint32_t HOP_INTERVAL = 5000;  // 5 seconds per channel

void sniffer_callback(void* buf, wifi_promiscuous_pkt_type_t type)
{
    wifi_promiscuous_pkt_t* pkt =
        (wifi_promiscuous_pkt_t*)buf;

    if (pkt->rx_ctrl.sig_len <= 28) {
        return;
    }

    uint8_t* payload = pkt->payload;

    // Transmitter address in a standard 802.11 frame
    uint8_t* sender_mac = payload + 10;

    int rssi = pkt->rx_ctrl.rssi;

    // Channel on which this packet was received
    int channel = currentChannel;

    Serial.printf(
        "%02X:%02X:%02X:%02X:%02X:%02X,%d,%d\n",
        sender_mac[0],
        sender_mac[1],
        sender_mac[2],
        sender_mac[3],
        sender_mac[4],
        sender_mac[5],
        rssi,
        channel
    );
}

void setup()
{
    Serial.begin(115200);
    delay(100);

    esp_err_t ret = nvs_flash_init();

    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        nvs_flash_erase();
        nvs_flash_init();
    }

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();

    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_NULL);
    esp_wifi_start();

    esp_wifi_set_promiscuous_rx_cb(sniffer_callback);
    esp_wifi_set_promiscuous(true);

    esp_wifi_set_channel(
        currentChannel,
        WIFI_SECOND_CHAN_NONE
    );

    lastChannelChange = millis();
}

void loop()
{
    unsigned long now = millis();

    if (now - lastChannelChange >= HOP_INTERVAL)
    {
        currentChannel++;

        if (currentChannel > 11) {
            currentChannel = 1;
        }

        esp_wifi_set_channel(
            currentChannel,
            WIFI_SECOND_CHAN_NONE
        );

        lastChannelChange = now;
    }
}
