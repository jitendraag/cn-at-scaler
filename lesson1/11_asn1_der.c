#include <stdio.h>
#include <string.h>

// DER INTEGER: tag 0x02, then length, then the value.
// A leading 0x00 is needed when the high bit is set, so the value
// isn't misread as negative two's-complement.
int asn1_encode_integer(unsigned char *out, int value) {
    unsigned char val = value & 0xFF;
    unsigned char content[2];
    int len = 1;

    if (val & 0x80) {
        content[0] = 0x00;
        content[1] = val;
        len = 2;
    } else {
        content[0] = val;
    }

    out[0] = 0x02;
    out[1] = len;
    memcpy(out + 2, content, len);
    return len + 2;
}

// DER SEQUENCE: tag 0x30, then length, then the concatenated child TLVs
int asn1_encode_sequence(unsigned char *out, const unsigned char *content, int content_len) {
    out[0] = 0x30;
    out[1] = content_len;
    memcpy(out + 2, content, content_len);
    return content_len + 2;
}

int main() {
    unsigned char a[4], b[4], seq_content[8], out[16];

    int na = asn1_encode_integer(a, 5);
    int nb = asn1_encode_integer(b, 200); // high bit set -> needs the leading 0x00

    memcpy(seq_content, a, na);
    memcpy(seq_content + na, b, nb);
    int n = asn1_encode_sequence(out, seq_content, na + nb);

    printf("DER SEQUENCE: ");
    for (int i = 0; i < n; i++) printf("%02X ", out[i]);
    printf("\n");

    return 0;
}
