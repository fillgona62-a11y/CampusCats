// Minimal ISO/IEC 18004 Byte-mode QR encoder (Versions 1-L..5-L, up to 106 UTF-8 bytes) and Canvas helpers.
const VERSIONS = [
    null,
    { size: 21, data: 19, ec: 7, align: [] },
    { size: 25, data: 34, ec: 10, align: [6, 18] },
    { size: 29, data: 55, ec: 15, align: [6, 22] },
    { size: 33, data: 80, ec: 20, align: [6, 26] },
    { size: 37, data: 108, ec: 26, align: [6, 30] },
];

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
    let x = 1;
    for (let i = 0; i < 255; i++) {
        EXP[i] = x;
        LOG[x] = i;
        x = (x << 1) ^ (x & 128 ? 0x11d : 0);
    }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
}

function gfMul(a, b) {
    return a && b ? EXP[LOG[a] + LOG[b]] : 0;
}

function reedSolomon(data, ecLen) {
    let gen = new Uint8Array([1]);
    for (let i = 0; i < ecLen; i++) {
        const next = new Uint8Array(gen.length + 1);
        const factor = EXP[i];
        for (let j = 0; j < gen.length; j++) {
            next[j] ^= gen[j];
            next[j + 1] ^= gfMul(gen[j], factor);
        }
        gen = next;
    }
    const rem = new Uint8Array(ecLen);
    for (const byte of data) {
        const lead = byte ^ rem[0];
        rem.copyWithin(0, 1);
        rem[ecLen - 1] = 0;
        for (let j = 0; j < ecLen; j++) rem[j] ^= gfMul(gen[j + 1], lead);
    }
    return rem;
}

function formatBits(mask) {
    // EC level L = 01
    const data = (0b01 << 3) | mask;
    let rem = data << 10;
    for (let i = 14; i >= 10; i--) {
        if ((rem >> i) & 1) rem ^= 0x537 << (i - 10);
    }
    return ((data << 10) | rem) ^ 0x5412;
}

export function qrMatrix(text) {
    const bytes = new TextEncoder().encode(String(text || ''));
    if (!bytes.length || bytes.length > 106) return null;
    let ver = 1;
    while (ver <= 5 && VERSIONS[ver].data < bytes.length + 2) ver++;
    if (ver > 5) return null;
    const spec = VERSIONS[ver];
    const n = spec.size;

    const bits = [];
    const pushBits = (val, len) => {
        for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1);
    };
    pushBits(0b0100, 4); // Byte mode
    pushBits(bytes.length, 8);
    for (const b of bytes) pushBits(b, 8);
    const maxBits = spec.data * 8;
    pushBits(0, Math.min(4, maxBits - bits.length));
    while (bits.length % 8) bits.push(0);
    const codewords = new Uint8Array(spec.data);
    for (let i = 0; i < bits.length / 8; i++) {
        let v = 0;
        for (let b = 0; b < 8; b++) v = (v << 1) | bits[i * 8 + b];
        codewords[i] = v;
    }
    for (let i = bits.length / 8, pad = 0; i < spec.data; i++, pad ^= 1) {
        codewords[i] = pad ? 0x11 : 0xec;
    }
    const ec = reedSolomon(codewords, spec.ec);
    const allBits = [];
    const appendByte = b => { for (let i = 7; i >= 0; i--) allBits.push((b >> i) & 1); };
    for (const b of codewords) appendByte(b);
    for (const b of ec) appendByte(b);

    const grid = Array.from({ length: n }, () => new Uint8Array(n));
    const reserved = Array.from({ length: n }, () => new Uint8Array(n));
    const setModule = (r, c, dark) => {
        if (r >= 0 && r < n && c >= 0 && c < n) {
            grid[r][c] = dark ? 1 : 0;
            reserved[r][c] = 1;
        }
    };
    const finder = (top, left) => {
        for (let r = -1; r <= 7; r++) {
            for (let c = -1; c <= 7; c++) {
                const inOuter = r >= 0 && r <= 6 && c >= 0 && c <= 6;
                const onBorder = r === 0 || r === 6 || c === 0 || c === 6;
                const inInner = r >= 2 && r <= 4 && c >= 2 && c <= 4;
                setModule(top + r, left + c, inOuter && (onBorder || inInner));
            }
        }
    };
    finder(0, 0);
    finder(0, n - 7);
    finder(n - 7, 0);

    for (const r of spec.align) {
        for (const c of spec.align) {
            if (reserved[r][c]) continue;
            for (let dr = -2; dr <= 2; dr++) {
                for (let dc = -2; dc <= 2; dc++) {
                    setModule(r + dr, c + dc, Math.max(Math.abs(dr), Math.abs(dc)) !== 1);
                }
            }
        }
    }
    for (let i = 8; i < n - 8; i++) {
        if (!reserved[6][i]) setModule(6, i, i % 2 === 0);
        if (!reserved[i][6]) setModule(i, 6, i % 2 === 0);
    }
    setModule(n - 8, 8, true);
    for (let i = 0; i < 9; i++) {
        if (!reserved[8][i]) reserved[8][i] = 1;
        if (!reserved[i][8]) reserved[i][8] = 1;
    }
    for (let i = 0; i < 8; i++) {
        reserved[8][n - 1 - i] = 1;
        reserved[n - 1 - i][8] = 1;
    }

    let bitIdx = 0;
    let upward = true;
    for (let right = n - 1; right >= 1; right -= 2) {
        if (right === 6) right = 5;
        for (let step = 0; step < n; step++) {
            const r = upward ? n - 1 - step : step;
            for (const c of [right, right - 1]) {
                if (!reserved[r][c]) {
                    grid[r][c] = bitIdx < allBits.length ? allBits[bitIdx++] : 0;
                }
            }
        }
        upward = !upward;
    }

    const masks = [
        (r, c) => (r + c) % 2 === 0,
        (r) => r % 2 === 0,
        (_, c) => c % 3 === 0,
        (r, c) => (r + c) % 3 === 0,
        (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
        (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
        (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
        (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
    ];

    const writeFormat = (target, maskId) => {
        const fmt = formatBits(maskId);
        const coordsA = [
            [8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8],
            [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8],
        ];
        for (let i = 0; i < 15; i++) {
            const bit = (fmt >> (14 - i)) & 1;
            const [r, c] = coordsA[i];
            target[r][c] = bit;
            if (i < 7) target[n - 1 - i][8] = bit;
            else target[8][n - 15 + i] = bit;
        }
    };

    const penalty = (m) => {
        let score = 0;
        for (let r = 0; r < n; r++) {
            let run = 1;
            for (let c = 1; c < n; c++) {
                if (m[r][c] === m[r][c - 1]) {
                    run++;
                    if (run === 5) score += 3;
                    else if (run > 5) score += 1;
                } else run = 1;
            }
        }
        for (let c = 0; c < n; c++) {
            let run = 1;
            for (let r = 1; r < n; r++) {
                if (m[r][c] === m[r - 1][c]) {
                    run++;
                    if (run === 5) score += 3;
                    else if (run > 5) score += 1;
                } else run = 1;
            }
        }
        for (let r = 0; r < n - 1; r++) {
            for (let c = 0; c < n - 1; c++) {
                const v = m[r][c];
                if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) score += 3;
            }
        }
        return score;
    };

    let bestGrid = null;
    let bestScore = Infinity;
    for (let maskId = 0; maskId < 8; maskId++) {
        const candidate = grid.map((row, r) =>
            row.map((v, c) => (!reserved[r][c] && masks[maskId](r, c) ? v ^ 1 : v))
        );
        writeFormat(candidate, maskId);
        const p = penalty(candidate);
        if (p < bestScore) {
            bestScore = p;
            bestGrid = candidate;
        }
    }
    return bestGrid;
}

export function drawQr(ctx, text, x, y, boxSize, dark = '#163f37', light = '#ffffff') {
    const matrix = qrMatrix(text);
    if (!matrix) return false;
    const quiet = 4;
    const total = matrix.length + quiet * 2;
    const cell = boxSize / total;
    ctx.fillStyle = light;
    ctx.fillRect(x, y, boxSize, boxSize);
    ctx.fillStyle = dark;
    for (let r = 0; r < matrix.length; r++) {
        for (let c = 0; c < matrix.length; c++) {
            if (matrix[r][c]) {
                const px = Math.round(x + (c + quiet) * cell);
                const py = Math.round(y + (r + quiet) * cell);
                const pw = Math.max(1, Math.round(x + (c + quiet + 1) * cell) - px);
                const ph = Math.max(1, Math.round(y + (r + quiet + 1) * cell) - py);
                ctx.fillRect(px, py, pw, ph);
            }
        }
    }
    return true;
}

export function fitText(ctx, text, maxWidth) {
    const str = String(text || '');
    if (ctx.measureText(str).width <= maxWidth) return str;
    let out = str;
    while (out.length > 1 && ctx.measureText(out + '…').width > maxWidth) {
        out = out.slice(0, -1);
    }
    return out + '…';
}
