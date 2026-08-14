#include <stdio.h>
#include <string.h>

// 1-byte type, 1-byte length, then value
int tlv_encode(unsigned char *out, unsigned char type, const unsigned char *value, unsigned char len) {
    out[0] = type;
    out[1] = len;
    memcpy(out + 2, value, len);
    return len + 2;
}

void tlv_decode(const unsigned char *in, unsigned char *type, unsigned char *value, unsigned char *len) {
    *type = in[0];
    *len = in[1];
    memcpy(value, in + 2, *len);
    value[*len] = '\0';
}

int main() {
    unsigned char buf[64];
    unsigned char val[] = "hello";
    int n = tlv_encode(buf, 0x01, val, strlen((char *)val));

    printf("TLV: ");
    for (int i = 0; i < n; i++) printf("%02X ", buf[i]);
    printf("\n");

    unsigned char type, len, value[64];
    tlv_decode(buf, &type, value, &len);
    printf("Type: %02X Len: %d Value: %s\n", type, len, value);

    return 0;
}
