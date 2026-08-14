#include <stdio.h>
#include <string.h>

static const char *table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

void base64_encode(const unsigned char *data, int len, char *out) {
    int j = 0;
    for (int i = 0; i < len; i += 3) {
        int n = data[i] << 16;
        if (i + 1 < len) n |= data[i + 1] << 8;
        if (i + 2 < len) n |= data[i + 2];

        out[j++] = table[(n >> 18) & 0x3F];
        out[j++] = table[(n >> 12) & 0x3F];
        out[j++] = (i + 1 < len) ? table[(n >> 6) & 0x3F] : '=';
        out[j++] = (i + 2 < len) ? table[n & 0x3F] : '=';
    }
    out[j] = '\0';
}

int decode_char(char c) {
    return (int)(strchr(table, c) - table);
}

int base64_decode(const char *in, unsigned char *out) {
    int len = strlen(in);
    int j = 0;
    for (int i = 0; i < len; i += 4) {
        int n = (decode_char(in[i]) << 18) | (decode_char(in[i + 1]) << 12);
        if (in[i + 2] != '=') n |= decode_char(in[i + 2]) << 6;
        if (in[i + 3] != '=') n |= decode_char(in[i + 3]);

        out[j++] = (n >> 16) & 0xFF;
        if (in[i + 2] != '=') out[j++] = (n >> 8) & 0xFF;
        if (in[i + 3] != '=') out[j++] = n & 0xFF;
    }
    out[j] = '\0';
    return j;
}

int main() {
    const char *msg = "Hello, ASN.1!";
    char encoded[64];
    base64_encode((unsigned char *)msg, strlen(msg), encoded);
    printf("Encoded: %s\n", encoded);

    unsigned char decoded[64];
    base64_decode(encoded, decoded);
    printf("Decoded: %s\n", decoded);

    return 0;
}
