#include <stdio.h>
#include <string.h>

// packs 2 decimal digits per byte, pads an odd trailing digit with nibble 0xF
void bcd_encode(const char *digits, unsigned char *out) {
    int len = strlen(digits);
    for (int i = 0; i < len; i += 2) {
        unsigned char hi = digits[i] - '0';
        unsigned char lo = (i + 1 < len) ? digits[i + 1] - '0' : 0xF;
        out[i / 2] = (hi << 4) | lo;
    }
}

void bcd_decode(const unsigned char *bcd, int nbytes, char *out) {
    int j = 0;
    for (int i = 0; i < nbytes; i++) {
        unsigned char hi = bcd[i] >> 4;
        unsigned char lo = bcd[i] & 0xF;
        out[j++] = '0' + hi;
        if (lo != 0xF) out[j++] = '0' + lo;
    }
    out[j] = '\0';
}

int main() {
    const char *digits = "123456789";
    unsigned char bcd[5];
    bcd_encode(digits, bcd);

    printf("BCD: ");
    for (int i = 0; i < 5; i++) printf("%02X ", bcd[i]);
    printf("\n");

    char decoded[16];
    bcd_decode(bcd, 5, decoded);
    printf("Decoded: %s\n", decoded);

    return 0;
}
