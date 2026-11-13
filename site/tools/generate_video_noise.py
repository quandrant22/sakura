"""
Generates Video 2: sakura-noise-handshake.mp4 and .webm
High-bitrate Full HD 1080p animation of Noise Protocol Handshake
(Noise_IK_25519_ChaChaPoly_BLAKE2s), cryptographic packet transmission,
anti-replay checks, and formal ProVerif proofs.
"""

import os
import math
import subprocess
import random
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OUT_DIR = "site/media/videos"
os.makedirs(OUT_DIR, exist_ok=True)

FONTS_DIR = r"C:\Windows\Fonts"
FONT_SANS = os.path.join(FONTS_DIR, "segoeui.ttf")
FONT_SANS_BOLD = os.path.join(FONTS_DIR, "segoeuib.ttf")
FONT_MONO = os.path.join(FONTS_DIR, "consola.ttf")
FONT_MONO_BOLD = os.path.join(FONTS_DIR, "consolab.ttf")

def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def generate_noise_video():
    W, H = 1920, 1080
    FPS = 30
    DURATION = 15 # seconds
    TOTAL_FRAMES = FPS * DURATION

    font_title = get_font(FONT_SANS_BOLD, 36)
    font_sub = get_font(FONT_SANS, 22)
    font_h2 = get_font(FONT_SANS_BOLD, 26)
    font_mono = get_font(FONT_MONO, 17)
    font_mono_bold = get_font(FONT_MONO_BOLD, 19)
    font_mono_large = get_font(FONT_MONO_BOLD, 24)

    mp4_path = os.path.join(OUT_DIR, "sakura-noise-handshake.mp4")
    cmd_mp4 = [
        FFMPEG, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}",
        "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", "12M",
        "-maxrate", "16M",
        "-bufsize", "24M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        mp4_path
    ]
    proc = subprocess.Popen(cmd_mp4, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    print(f"Rendering {TOTAL_FRAMES} frames for sakura-noise-handshake.mp4...")

    # Simulated hex packets
    hex_sample = "4e6f6973655f494b5f32353531395f436861436861506f6c795f424c414b4532732053616b757261"

    for frame_idx in range(TOTAL_FRAMES):
        t = frame_idx / float(FPS)

        img = Image.new("RGBA", (W, H), (11, 8, 19, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Dark matrix gradient
        draw.rectangle([0, 0, W, H], fill=(12, 9, 22, 255))

        # Cybernetic grid
        for gy in range(80, H, 50):
            draw.line([(0, gy), (W, gy)], fill=(25, 18, 42, 100), width=1)
        for gx in range(80, W, 80):
            draw.line([(gx, 0), (gx, H)], fill=(25, 18, 42, 100), width=1)

        # Header Title
        draw.text((100, 45), "NOISE_IK_25519_CHACHAPOLY_BLAKE2s: КРИПТОГРАФИЧЕСКИЙ КАНАЛ", fill=(255, 255, 255, 255), font=font_title)
        draw.text((100, 95), "Протокол securechannel/1 • Защита от прослушивания, подмены, повторов и MITM-атак", fill=(79, 216, 255, 230), font=font_sub)

        # Nodes Positions
        node_w, node_h = 420, 680
        lx, ly = 100, 180
        rx = W - 100 - node_w

        # Determine phase
        # 0.0 - 4.0s: Phase 1 (Client Handshake Request: -> e, es, s, ss)
        # 4.0 - 8.0s: Phase 2 (Server Handshake Reply: <- e, ee, se)
        # 8.0 - 12.0s: Phase 3 (Session Key Derivation & Split)
        # 12.0 - 15.0s: Phase 4 (SecureChannel Transport Streaming & ProVerif Green)

        # Client Node Card
        c_glow = (255, 106, 227, 80 if t < 4.0 or t >= 8.0 else 40)
        draw.rounded_rectangle([lx, ly, lx + node_w, ly + node_h], radius=16, fill=(18, 13, 33, 245), outline=(255, 106, 227, 220), width=2)
        draw.text((lx + 30, ly + 25), "DESKTOP CLIENT", fill=(255, 106, 227, 255), font=font_h2)
        draw.text((lx + 30, ly + 65), "Windows DPAPI Protected Store", fill=(200, 190, 220, 220), font=font_mono)

        # Client keys telemetry
        draw.rounded_rectangle([lx + 25, ly + 110, lx + node_w - 25, ly + 240], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((lx + 40, ly + 125), "Static Key s_c (X25519):", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 155), "0x8F3D...A12B (DPAPI Protected)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((lx + 40, ly + 185), "Ephemeral Key e_c:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 210), f"0x{hash(int(t*100)):08X}...RANDOM", fill=(16, 185, 129, 255), font=font_mono)

        # Client Anti-Replay status
        draw.rounded_rectangle([lx + 25, ly + 260, lx + node_w - 25, ly + 400], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((lx + 40, ly + 275), "Anti-Replay Window:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 305), f"Window Size: 64 bits [Sliding]", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((lx + 40, ly + 335), f"Frame Nonce: #{int(t * 42):05d}", fill=(255, 106, 227, 255), font=font_mono_bold)
        draw.text((lx + 40, ly + 365), "Replay Attacks: REJECTED", fill=(16, 185, 129, 255), font=font_mono)

        # Server Node Card
        draw.rounded_rectangle([rx, ly, rx + node_w, ly + node_h], radius=16, fill=(18, 13, 33, 245), outline=(79, 216, 255, 220), width=2)
        draw.text((rx + 30, ly + 25), "VPS CORE SERVER", fill=(79, 216, 255, 255), font=font_h2)
        draw.text((rx + 30, ly + 65), "FastAPI / WebSocket Hub / Zero-Trust", fill=(200, 190, 220, 220), font=font_mono)

        # Server keys telemetry
        draw.rounded_rectangle([rx + 25, ly + 110, rx + node_w - 25, ly + 240], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((rx + 40, ly + 125), "Static Key s_s (Server):", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 155), "0x3C9A...FE04 (Trusted Anchor)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((rx + 40, ly + 185), "Ephemeral Key e_s:", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 210), f"0x{hash(int(t*100) + 999):08X}...GENERATED", fill=(16, 185, 129, 255), font=font_mono)

        # Server Device Registry
        draw.rounded_rectangle([rx + 25, ly + 260, rx + node_w - 25, ly + 400], radius=10, fill=(26, 19, 45, 255), outline=(60, 45, 90, 200))
        draw.text((rx + 40, ly + 275), "Paired Device Registry:", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((rx + 40, ly + 305), "Fingerprint: SHA-256 (OK)", fill=(225, 220, 235, 240), font=font_mono)
        draw.text((rx + 40, ly + 335), "Device ID: #master-desktop-1", fill=(255, 207, 107, 255), font=font_mono)
        draw.text((rx + 40, ly + 365), "Session: ISOLATED (Secure)", fill=(16, 185, 129, 255), font=font_mono)

        # Central Animated Bus
        bus_x0 = lx + node_w + 30
        bus_x1 = rx - 30
        bus_w = bus_x1 - bus_x0
        draw.rounded_rectangle([bus_x0, ly, bus_x1, ly + 500], radius=16, fill=(16, 12, 30, 240), outline=(50, 35, 75, 255))

        # Bus Header
        draw.text((bus_x0 + 30, ly + 25), "КАНАЛ СВЯЗИ (WEBSOCKET ДВУНАПРАВЛЕННЫЙ ТРАНСПОРТ)", fill=(255, 255, 255, 255), font=font_mono_bold)

        # Animated Packet Movement
        track_y1 = ly + 120 # Client to Server
        track_y2 = ly + 260 # Server to Client
        track_y3 = ly + 400 # Bidirectional transport

        draw.line([(bus_x0 + 40, track_y1), (bus_x1 - 40, track_y1)], fill=(40, 30, 65, 255), width=3)
        draw.line([(bus_x0 + 40, track_y2), (bus_x1 - 40, track_y2)], fill=(40, 30, 65, 255), width=3)
        draw.line([(bus_x0 + 40, track_y3), (bus_x1 - 40, track_y3)], fill=(40, 30, 65, 255), width=3)

        if t < 4.0:
            # Phase 1: Client -> Server
            rel = (t % 2.0) / 2.0
            pkt_x = bus_x0 + 60 + int(rel * (bus_w - 200))
            draw.rounded_rectangle([pkt_x, track_y1 - 35, pkt_x + 160, track_y1 + 35], radius=10, fill=(255, 106, 227, 255))
            draw.text((pkt_x + 15, track_y1 - 18), "MSG 1: -> e, es, s, ss", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x + 15, track_y1 + 5), "DH(e, s_s) + Auth", fill=(40, 10, 30, 255), font=font_mono)

            phase_desc = "ФАЗА 1: Клиент генерирует эфемерный ключ e и шифрует свой статический ключ s_c через DH(e, s_server)"
            phase_color = (255, 106, 227)
        elif t < 8.0:
            # Phase 2: Server -> Client
            rel = ((t - 4.0) % 2.0) / 2.0
            pkt_x = bus_x1 - 60 - 160 - int(rel * (bus_w - 200))
            draw.rounded_rectangle([pkt_x, track_y2 - 35, pkt_x + 160, track_y2 + 35], radius=10, fill=(79, 216, 255, 255))
            draw.text((pkt_x + 15, track_y2 - 18), "MSG 2: <- e, ee, se", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x + 15, track_y2 + 5), "DH(e_s, e_c) Diffie", fill=(10, 30, 50, 255), font=font_mono)

            phase_desc = "ФАЗА 2: Сервер отвечает эфемерным ключом e_s. Вычисляются DH(e_s, e_c) и DH(s_c, e_s). Сессия завершена."
            phase_color = (79, 216, 255)
        else:
            # Phase 3 & 4: Transport Frames Streaming
            rel = (t * 2.5) % 1.0
            pkt_x1 = bus_x0 + 60 + int(rel * (bus_w - 180))
            pkt_x2 = bus_x1 - 60 - 160 - int(rel * (bus_w - 180))

            draw.rounded_rectangle([pkt_x1, track_y3 - 35, pkt_x1 + 140, track_y3 + 35], radius=8, fill=(16, 185, 129, 255))
            draw.text((pkt_x1 + 12, track_y3 - 16), "SK DATA ->", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x1 + 12, track_y3 + 5), "ChaCha20Poly", fill=(10, 40, 20, 255), font=font_mono)

            draw.rounded_rectangle([pkt_x2, track_y3 - 35, pkt_x2 + 140, track_y3 + 35], radius=8, fill=(255, 207, 107, 255))
            draw.text((pkt_x2 + 12, track_y3 - 16), "<- AUDIO CHUNK", fill=(0, 0, 0, 255), font=font_mono_bold)
            draw.text((pkt_x2 + 12, track_y3 + 5), "Encrypted Stream", fill=(40, 30, 10, 255), font=font_mono)

            phase_desc = "ФАЗА 3: Симметричный канал активен (k_in, k_out). Rekey каждые 10k кадров. Zero-Leakage."
            phase_color = (16, 185, 129)

        # Phase description bar in central card
        draw.rounded_rectangle([bus_x0 + 25, ly + 430, bus_x1 - 25, ly + 480], radius=8, fill=(24, 18, 42, 255), outline=phase_color, width=1)
        draw.text((bus_x0 + 40, ly + 448), phase_desc, fill=phase_color, font=font_mono_bold)

        # Bottom ProVerif Proofs High-Tech Terminal Card
        draw.rounded_rectangle([bus_x0, ly + 520, bus_x1, ly + node_h], radius=16, fill=(10, 35, 22, 255), outline=(16, 185, 129, 255), width=2)
        draw.text((bus_x0 + 30, ly + 535), "PROVERIF FORMAL VERIFICATION VERDICT (ik.pv & xxpsk3.pv):", fill=(255, 207, 107, 255), font=font_mono_bold)
        
        proofs = [
            ("RESULT not attacker(secret_client[]) is TRUE", "Математическое доказательство тайны данных клиента"),
            ("RESULT not attacker(secret_server[]) is TRUE", "Математическое доказательство тайны данных сервера"),
            ("RESULT inj-event(ServerAuth) ==> inj-event(ClientInit) is TRUE", "Гарантия взаимной подлинности участников")
        ]
        for pi, (p_res, p_desc) in enumerate(proofs):
            draw.text((bus_x0 + 30, ly + 570 + pi * 28), f"✅ {p_res}", fill=(16, 185, 129, 255), font=font_mono_bold)

        # Footer Status Pill
        draw.rounded_rectangle([100, H - 140, W - 100, H - 40], radius=14, fill=(18, 12, 32, 230), outline=(255, 106, 227, 200), width=1)
        draw.text((130, H - 115), "СПАРИВАНИЕ: 8-словная фраза или QR sakura-pair://1. Токены навсегда устранены из протокола Сакуры.", fill=(255, 255, 255, 255), font=font_sub)

        raw_bytes = img.convert("RGB").tobytes()
        proc.stdin.write(raw_bytes)

        if frame_idx % 60 == 0:
            print(f"  Frame {frame_idx}/{TOTAL_FRAMES} rendered ({frame_idx/TOTAL_FRAMES*100:.1f}%)")

    proc.stdin.close()
    proc.wait()
    print("Done rendering sakura-noise-handshake.mp4!")
    print(f"File size: {os.path.getsize(mp4_path) / 1024 / 1024:.2f} MB")

    # Generate WEBM
    webm_path = os.path.join(OUT_DIR, "sakura-noise-handshake.webm")
    print("Encoding WEBM version (VP9)...")
    cmd_webm = [
        FFMPEG, "-y",
        "-i", mp4_path,
        "-c:v", "libvpx-vp9",
        "-b:v", "8M",
        "-crf", "22",
        webm_path
    ]
    subprocess.run(cmd_webm, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Done rendering sakura-noise-handshake.webm!")
    if os.path.exists(webm_path):
        print(f"WebM size: {os.path.getsize(webm_path) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    generate_noise_video()
