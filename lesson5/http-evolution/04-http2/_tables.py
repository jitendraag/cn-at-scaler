"""RFC 7541 Appendix A (static table) and Appendix B (Huffman code).

Generated, not typed. Verified against the tables in RFC 7541:
  index 1 = :authority, index 61 = www-authenticate, 61 entries
  Huffman '0' = 0b00000 (5 bits), EOS = 0x3fffffff (30 bits), 257 symbols
"""

STATIC_TABLE = (
    (b':authority', b''),          # 1
    (b':method', b'GET'),          # 2
    (b':method', b'POST'),          # 3
    (b':path', b'/'),          # 4
    (b':path', b'/index.html'),          # 5
    (b':scheme', b'http'),          # 6
    (b':scheme', b'https'),          # 7
    (b':status', b'200'),          # 8
    (b':status', b'204'),          # 9
    (b':status', b'206'),          # 10
    (b':status', b'304'),          # 11
    (b':status', b'400'),          # 12
    (b':status', b'404'),          # 13
    (b':status', b'500'),          # 14
    (b'accept-charset', b''),          # 15
    (b'accept-encoding', b'gzip, deflate'),          # 16
    (b'accept-language', b''),          # 17
    (b'accept-ranges', b''),          # 18
    (b'accept', b''),          # 19
    (b'access-control-allow-origin', b''),          # 20
    (b'age', b''),          # 21
    (b'allow', b''),          # 22
    (b'authorization', b''),          # 23
    (b'cache-control', b''),          # 24
    (b'content-disposition', b''),          # 25
    (b'content-encoding', b''),          # 26
    (b'content-language', b''),          # 27
    (b'content-length', b''),          # 28
    (b'content-location', b''),          # 29
    (b'content-range', b''),          # 30
    (b'content-type', b''),          # 31
    (b'cookie', b''),          # 32
    (b'date', b''),          # 33
    (b'etag', b''),          # 34
    (b'expect', b''),          # 35
    (b'expires', b''),          # 36
    (b'from', b''),          # 37
    (b'host', b''),          # 38
    (b'if-match', b''),          # 39
    (b'if-modified-since', b''),          # 40
    (b'if-none-match', b''),          # 41
    (b'if-range', b''),          # 42
    (b'if-unmodified-since', b''),          # 43
    (b'last-modified', b''),          # 44
    (b'link', b''),          # 45
    (b'location', b''),          # 46
    (b'max-forwards', b''),          # 47
    (b'proxy-authenticate', b''),          # 48
    (b'proxy-authorization', b''),          # 49
    (b'range', b''),          # 50
    (b'referer', b''),          # 51
    (b'refresh', b''),          # 52
    (b'retry-after', b''),          # 53
    (b'server', b''),          # 54
    (b'set-cookie', b''),          # 55
    (b'strict-transport-security', b''),          # 56
    (b'transfer-encoding', b''),          # 57
    (b'user-agent', b''),          # 58
    (b'vary', b''),          # 59
    (b'via', b''),          # 60
    (b'www-authenticate', b''),          # 61
)

# (code, bit-length) for symbols 0..255 plus EOS at 256
HUFFMAN = (
    (0x00001ff8, 13),
    (0x007fffd8, 23),
    (0x0fffffe2, 28),
    (0x0fffffe3, 28),
    (0x0fffffe4, 28),
    (0x0fffffe5, 28),
    (0x0fffffe6, 28),
    (0x0fffffe7, 28),
    (0x0fffffe8, 28),
    (0x00ffffea, 24),
    (0x3ffffffc, 30),
    (0x0fffffe9, 28),
    (0x0fffffea, 28),
    (0x3ffffffd, 30),
    (0x0fffffeb, 28),
    (0x0fffffec, 28),
    (0x0fffffed, 28),
    (0x0fffffee, 28),
    (0x0fffffef, 28),
    (0x0ffffff0, 28),
    (0x0ffffff1, 28),
    (0x0ffffff2, 28),
    (0x3ffffffe, 30),
    (0x0ffffff3, 28),
    (0x0ffffff4, 28),
    (0x0ffffff5, 28),
    (0x0ffffff6, 28),
    (0x0ffffff7, 28),
    (0x0ffffff8, 28),
    (0x0ffffff9, 28),
    (0x0ffffffa, 28),
    (0x0ffffffb, 28),
    (0x00000014,  6),  #  32 ' '
    (0x000003f8, 10),  #  33 '!'
    (0x000003f9, 10),  #  34 '"'
    (0x00000ffa, 12),  #  35 '#'
    (0x00001ff9, 13),  #  36 '$'
    (0x00000015,  6),  #  37 '%'
    (0x000000f8,  8),  #  38 '&'
    (0x000007fa, 11),  #  39 "'"
    (0x000003fa, 10),  #  40 '('
    (0x000003fb, 10),  #  41 ')'
    (0x000000f9,  8),  #  42 '*'
    (0x000007fb, 11),  #  43 '+'
    (0x000000fa,  8),  #  44 ','
    (0x00000016,  6),  #  45 '-'
    (0x00000017,  6),  #  46 '.'
    (0x00000018,  6),  #  47 '/'
    (0x00000000,  5),  #  48 '0'
    (0x00000001,  5),  #  49 '1'
    (0x00000002,  5),  #  50 '2'
    (0x00000019,  6),  #  51 '3'
    (0x0000001a,  6),  #  52 '4'
    (0x0000001b,  6),  #  53 '5'
    (0x0000001c,  6),  #  54 '6'
    (0x0000001d,  6),  #  55 '7'
    (0x0000001e,  6),  #  56 '8'
    (0x0000001f,  6),  #  57 '9'
    (0x0000005c,  7),  #  58 ':'
    (0x000000fb,  8),  #  59 ';'
    (0x00007ffc, 15),  #  60 '<'
    (0x00000020,  6),  #  61 '='
    (0x00000ffb, 12),  #  62 '>'
    (0x000003fc, 10),  #  63 '?'
    (0x00001ffa, 13),  #  64 '@'
    (0x00000021,  6),  #  65 'A'
    (0x0000005d,  7),  #  66 'B'
    (0x0000005e,  7),  #  67 'C'
    (0x0000005f,  7),  #  68 'D'
    (0x00000060,  7),  #  69 'E'
    (0x00000061,  7),  #  70 'F'
    (0x00000062,  7),  #  71 'G'
    (0x00000063,  7),  #  72 'H'
    (0x00000064,  7),  #  73 'I'
    (0x00000065,  7),  #  74 'J'
    (0x00000066,  7),  #  75 'K'
    (0x00000067,  7),  #  76 'L'
    (0x00000068,  7),  #  77 'M'
    (0x00000069,  7),  #  78 'N'
    (0x0000006a,  7),  #  79 'O'
    (0x0000006b,  7),  #  80 'P'
    (0x0000006c,  7),  #  81 'Q'
    (0x0000006d,  7),  #  82 'R'
    (0x0000006e,  7),  #  83 'S'
    (0x0000006f,  7),  #  84 'T'
    (0x00000070,  7),  #  85 'U'
    (0x00000071,  7),  #  86 'V'
    (0x00000072,  7),  #  87 'W'
    (0x000000fc,  8),  #  88 'X'
    (0x00000073,  7),  #  89 'Y'
    (0x000000fd,  8),  #  90 'Z'
    (0x00001ffb, 13),  #  91 '['
    (0x0007fff0, 19),  #  92 '\\'
    (0x00001ffc, 13),  #  93 ']'
    (0x00003ffc, 14),  #  94 '^'
    (0x00000022,  6),  #  95 '_'
    (0x00007ffd, 15),  #  96 '`'
    (0x00000003,  5),  #  97 'a'
    (0x00000023,  6),  #  98 'b'
    (0x00000004,  5),  #  99 'c'
    (0x00000024,  6),  # 100 'd'
    (0x00000005,  5),  # 101 'e'
    (0x00000025,  6),  # 102 'f'
    (0x00000026,  6),  # 103 'g'
    (0x00000027,  6),  # 104 'h'
    (0x00000006,  5),  # 105 'i'
    (0x00000074,  7),  # 106 'j'
    (0x00000075,  7),  # 107 'k'
    (0x00000028,  6),  # 108 'l'
    (0x00000029,  6),  # 109 'm'
    (0x0000002a,  6),  # 110 'n'
    (0x00000007,  5),  # 111 'o'
    (0x0000002b,  6),  # 112 'p'
    (0x00000076,  7),  # 113 'q'
    (0x0000002c,  6),  # 114 'r'
    (0x00000008,  5),  # 115 's'
    (0x00000009,  5),  # 116 't'
    (0x0000002d,  6),  # 117 'u'
    (0x00000077,  7),  # 118 'v'
    (0x00000078,  7),  # 119 'w'
    (0x00000079,  7),  # 120 'x'
    (0x0000007a,  7),  # 121 'y'
    (0x0000007b,  7),  # 122 'z'
    (0x00007ffe, 15),  # 123 '{'
    (0x000007fc, 11),  # 124 '|'
    (0x00003ffd, 14),  # 125 '}'
    (0x00001ffd, 13),  # 126 '~'
    (0x0ffffffc, 28),
    (0x000fffe6, 20),
    (0x003fffd2, 22),
    (0x000fffe7, 20),
    (0x000fffe8, 20),
    (0x003fffd3, 22),
    (0x003fffd4, 22),
    (0x003fffd5, 22),
    (0x007fffd9, 23),
    (0x003fffd6, 22),
    (0x007fffda, 23),
    (0x007fffdb, 23),
    (0x007fffdc, 23),
    (0x007fffdd, 23),
    (0x007fffde, 23),
    (0x00ffffeb, 24),
    (0x007fffdf, 23),
    (0x00ffffec, 24),
    (0x00ffffed, 24),
    (0x003fffd7, 22),
    (0x007fffe0, 23),
    (0x00ffffee, 24),
    (0x007fffe1, 23),
    (0x007fffe2, 23),
    (0x007fffe3, 23),
    (0x007fffe4, 23),
    (0x001fffdc, 21),
    (0x003fffd8, 22),
    (0x007fffe5, 23),
    (0x003fffd9, 22),
    (0x007fffe6, 23),
    (0x007fffe7, 23),
    (0x00ffffef, 24),
    (0x003fffda, 22),
    (0x001fffdd, 21),
    (0x000fffe9, 20),
    (0x003fffdb, 22),
    (0x003fffdc, 22),
    (0x007fffe8, 23),
    (0x007fffe9, 23),
    (0x001fffde, 21),
    (0x007fffea, 23),
    (0x003fffdd, 22),
    (0x003fffde, 22),
    (0x00fffff0, 24),
    (0x001fffdf, 21),
    (0x003fffdf, 22),
    (0x007fffeb, 23),
    (0x007fffec, 23),
    (0x001fffe0, 21),
    (0x001fffe1, 21),
    (0x003fffe0, 22),
    (0x001fffe2, 21),
    (0x007fffed, 23),
    (0x003fffe1, 22),
    (0x007fffee, 23),
    (0x007fffef, 23),
    (0x000fffea, 20),
    (0x003fffe2, 22),
    (0x003fffe3, 22),
    (0x003fffe4, 22),
    (0x007ffff0, 23),
    (0x003fffe5, 22),
    (0x003fffe6, 22),
    (0x007ffff1, 23),
    (0x03ffffe0, 26),
    (0x03ffffe1, 26),
    (0x000fffeb, 20),
    (0x0007fff1, 19),
    (0x003fffe7, 22),
    (0x007ffff2, 23),
    (0x003fffe8, 22),
    (0x01ffffec, 25),
    (0x03ffffe2, 26),
    (0x03ffffe3, 26),
    (0x03ffffe4, 26),
    (0x07ffffde, 27),
    (0x07ffffdf, 27),
    (0x03ffffe5, 26),
    (0x00fffff1, 24),
    (0x01ffffed, 25),
    (0x0007fff2, 19),
    (0x001fffe3, 21),
    (0x03ffffe6, 26),
    (0x07ffffe0, 27),
    (0x07ffffe1, 27),
    (0x03ffffe7, 26),
    (0x07ffffe2, 27),
    (0x00fffff2, 24),
    (0x001fffe4, 21),
    (0x001fffe5, 21),
    (0x03ffffe8, 26),
    (0x03ffffe9, 26),
    (0x0ffffffd, 28),
    (0x07ffffe3, 27),
    (0x07ffffe4, 27),
    (0x07ffffe5, 27),
    (0x000fffec, 20),
    (0x00fffff3, 24),
    (0x000fffed, 20),
    (0x001fffe6, 21),
    (0x003fffe9, 22),
    (0x001fffe7, 21),
    (0x001fffe8, 21),
    (0x007ffff3, 23),
    (0x003fffea, 22),
    (0x003fffeb, 22),
    (0x01ffffee, 25),
    (0x01ffffef, 25),
    (0x00fffff4, 24),
    (0x00fffff5, 24),
    (0x03ffffea, 26),
    (0x007ffff4, 23),
    (0x03ffffeb, 26),
    (0x07ffffe6, 27),
    (0x03ffffec, 26),
    (0x03ffffed, 26),
    (0x07ffffe7, 27),
    (0x07ffffe8, 27),
    (0x07ffffe9, 27),
    (0x07ffffea, 27),
    (0x07ffffeb, 27),
    (0x0ffffffe, 28),
    (0x07ffffec, 27),
    (0x07ffffed, 27),
    (0x07ffffee, 27),
    (0x07ffffef, 27),
    (0x07fffff0, 27),
    (0x03ffffee, 26),
    (0x3fffffff, 30),  # 256 EOS
)
