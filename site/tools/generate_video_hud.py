"""
Generates Video 1: sakura-hud-voice-core.mp4 and .webm
High-bitrate Full HD 1080p animation of Sakura's reactive HUD, glowing core,
sakura petals, audio waveform, and state transitions.
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

def generate_hud_video():
    W, H = 1920, 1080
    FPS = 30
    DURATION = 15 # seconds
    TOTAL_FRAMES = FPS * DURATION

    font_title = get_font(FONT_SANS_BOLD, 36)
    font_sub = get_font(FONT_SANS, 22)
    font_state = get_font(FONT_SANS_BOLD, 44)
    font_kana = get_font(FONT_SANS_BOLD, 28)
    font_mono = get_font(FONT_MONO, 18)
    font_mono_bold = get_font(FONT_MONO_BOLD, 20)
    font_quote = get_font(FONT_SANS, 26)

    # Petals state
    random.seed(42)
    petals = []
    for _ in range(45):
        petals.append({
            'x': random.uniform(0, W),
            'y': random.uniform(-100, H),
            'speed_y': random.uniform(2.5, 5.0),
            'speed_x': random.uniform(-1.0, 1.5),
            'size': random.uniform(6, 14),
            'rot': random.uniform(0, 360),
            'rot_speed': random.uniform(1.5, 4.0),
            'alpha': random.randint(140, 240)
        })

    # Prepare ffmpeg pipe for MP4
    mp4_path = os.path.join(OUT_DIR, "sakura-hud-voice-core.mp4")
    # High bitrate 10-12 Mbps for crystal-clear 1080p quality (~20 MB for 15s)
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

    print(f"Rendering {TOTAL_FRAMES} frames for sakura-hud-voice-core.mp4...")

    for frame_idx in range(TOTAL_FRAMES):
        t = frame_idx / float(FPS)

        # Determine state
        # 0.0 - 3.5s: LISTENING (Cyan)
        # 3.5 - 6.5s: THINKING (Gold)
        # 6.5 - 12.5s: SPEAKING (Pink)
        # 12.5 - 15.0s: IDLE (Sakura Magenta)
        if t < 3.5:
            state_key = "LISTENING"
            state_label = "СЛУШАЮ..."
            state_kana = "聴取中"
            state_color = (79, 216, 255)
            glow_color = (79, 216, 255, 60)
            subtitle = "«Сакура, включи утренний плейлист и проверь расписание пар»"
            audio_level = 0.35 + 0.35 * math.sin(t * 8.0) * math.cos(t * 3.5)
        elif t < 6.5:
            state_key = "THINKING"
            state_label = "ОБРАБОТКА..."
            state_kana = "思考中"
            state_color = (255, 207, 107)
            glow_color = (255, 207, 107, 60)
            subtitle = "NLU: v3_fast_path matched music.wave & schedule.today [1.8 ms]"
            audio_level = 0.15 + 0.1 * math.sin(t * 15.0)
        elif t < 12.5:
            state_key = "SPEAKING"
            state_label = "ОТВЕЧАЮ..."
            state_kana = "発話中"
            state_color = (255, 106, 227)
            glow_color = (255, 106, 227, 80)
            subtitle = "«Включаю Мою Волну в Яндекс Музыке. Первая пара по расписанию в 10:40.»"
            audio_level = 0.5 + 0.45 * abs(math.sin(t * 12.0) * math.sin(t * 5.3))
        else:
            state_key = "IDLE"
            state_label = "ОЖИДАНИЕ"
            state_kana = "待機中"
            state_color = (255, 126, 185)
            glow_color = (255, 126, 185, 45)
            subtitle = "Sakura AI • Готова к командам • SecureChannel/1 OK"
            audio_level = 0.08 + 0.04 * math.sin(t * 2.0)

        # Base Image
        img = Image.new("RGBA", (W, H), (11, 8, 19, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Background gradient with subtle pulse
        bg_r = int(14 + 4 * math.sin(t * 1.5))
        bg_g = int(10 + 2 * math.sin(t * 1.5))
        bg_b = int(26 + 6 * math.sin(t * 1.5))
        draw.rectangle([0, 0, W, H], fill=(bg_r, bg_g, bg_b, 255))

        # Perspective Cyber Grid at the bottom
        horizon_y = 650
        grid_color = (35, 25, 55, 140)
        for gy in range(horizon_y, H, 28):
            draw.line([(0, gy), (W, gy)], fill=grid_color, width=1)
        for gx in range(-W, 2 * W, 80):
            # Vanishing point perspective
            draw.line([(W // 2 + (gx - W // 2) // 4, horizon_y), (gx, H)], fill=grid_color, width=1)

        # Update & Draw Petals
        for p in petals:
            p['y'] += p['speed_y']
            p['x'] += p['speed_x'] + 0.8 * math.sin(t * 2.0 + p['y'] * 0.01)
            p['rot'] += p['rot_speed']
            if p['y'] > H + 50:
                p['y'] = -20
                p['x'] = random.uniform(0, W)
            
            # Draw petal oval
            rad = p['size']
            px, py = int(p['x']), int(p['y'])
            draw.ellipse([px - rad, py - rad * 0.6, px + rad, py + rad * 0.6], fill=(255, 182, 193, p['alpha']))

        # Central Glowing Sakura Core Orb
        cx, cy = W // 2, 420

        # Radial Glow Rings
        for r_step in range(4, 0, -1):
            ring_r = int(110 + r_step * 28 + 20 * audio_level)
            draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], outline=(state_color[0], state_color[1], state_color[2], int(40 / r_step)), width=3)

        # Concentric pulsing rings
        pulse_r1 = int(120 + 25 * math.sin(t * 3.0 + 1.0) + 15 * audio_level)
        pulse_r2 = int(90 + 15 * math.sin(t * 4.0) + 20 * audio_level)
        draw.ellipse([cx - pulse_r1, cy - pulse_r1, cx + pulse_r1, cy + pulse_r1], outline=(state_color[0], state_color[1], state_color[2], 180), width=2)
        draw.ellipse([cx - pulse_r2, cy - pulse_r2, cx + pulse_r2, cy + pulse_r2], outline=(255, 255, 255, 220), width=2)

        # Orbiting Satellites (3 particles)
        for sat_i in range(3):
            sat_ang = t * 2.2 + sat_i * (2 * math.pi / 3)
            sat_dist = 145 + 10 * math.sin(t * 4.0 + sat_i)
            sx = int(cx + sat_dist * math.cos(sat_ang))
            sy = int(cy + (sat_dist * 0.45) * math.sin(sat_ang))
            draw.ellipse([sx - 7, sy - 7, sx + 7, sy + 7], fill=(255, 255, 255, 255), outline=state_color, width=2)

        # Central Liquid Drop
        core_r = int(60 + 25 * audio_level)
        draw.ellipse([cx - core_r - 8, cy - core_r - 8, cx + core_r + 8, cy + core_r + 8], fill=(state_color[0], state_color[1], state_color[2], 90))
        draw.ellipse([cx - core_r, cy - core_r, cx + core_r, cy + core_r], fill=(state_color[0], state_color[1], state_color[2], 230), outline=(255, 255, 255, 255), width=3)
        # Inner specular highlight
        draw.ellipse([cx - 22, cy - 25, cx + 8, cy - 5], fill=(255, 255, 255, 200))

        # Bottom Audio Spectrum Equalizer (48 bars)
        spec_x0 = W // 2 - 420
        spec_y_base = 740
        num_bars = 48
        bar_w = 12
        bar_gap = 6
        for bi in range(num_bars):
            bx = spec_x0 + bi * (bar_w + bar_gap)
            dist_from_center = abs(bi - num_bars / 2) / (num_bars / 2)
            wave_mod = math.sin(t * 10.0 + bi * 0.4) * math.cos(t * 4.0 - bi * 0.2)
            bar_h = int(12 + audio_level * 110 * (1.0 - 0.4 * dist_from_center) * max(0.1, abs(wave_mod)))
            
            # Gradient bar
            c_r = int(state_color[0] * (1 - dist_from_center) + 79 * dist_from_center)
            c_g = int(state_color[1] * (1 - dist_from_center) + 216 * dist_from_center)
            c_b = int(state_color[2] * (1 - dist_from_center) + 255 * dist_from_center)
            draw.rounded_rectangle([bx, spec_y_base - bar_h, bx + bar_w, spec_y_base], radius=4, fill=(c_r, c_g, c_b, 240))

        # Oscilloscope Waveform overlay
        wave_pts = []
        for wx in range(spec_x0 - 60, spec_x0 + num_bars * (bar_w + bar_gap) + 60, 8):
            rel = (wx - W // 2) / 450.0
            wy = spec_y_base - 140 - int(35 * audio_level * math.sin(wx * 0.03 + t * 14.0) * math.exp(-rel*rel*2.5))
            wave_pts.append((wx, wy))
        if len(wave_pts) > 1:
            draw.line(wave_pts, fill=(255, 255, 255, 190), width=2)

        # State Header Card
        draw.rounded_rectangle([W // 2 - 200, 180, W // 2 + 200, 245], radius=14, fill=(20, 14, 35, 230), outline=state_color, width=2)
        draw.text((W // 2 - 170, 192), state_label, fill=(255, 255, 255, 255), font=font_state)
        draw.text((W // 2 + 80, 198), state_kana, fill=state_color, font=font_kana)

        # Subtitle Prompt Pill
        draw.rounded_rectangle([W // 2 - 500, 780, W // 2 + 500, 845], radius=12, fill=(18, 12, 32, 245), outline=(60, 45, 90, 255), width=2)
        draw.text((W // 2 - 470, 796), subtitle, fill=(255, 255, 255, 240), font=font_quote)

        # HUD Corner Cards:
        # Top-Left: System Telemetry
        draw.rounded_rectangle([50, 40, 480, 150], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((70, 52), "SAKURA AI CORE v3.8.4", fill=(255, 106, 227, 255), font=font_mono_bold)
        draw.text((70, 80), "SECURECHANNEL/1: NOISE_IK (OK)", fill=(16, 185, 129, 255), font=font_mono)
        draw.text((70, 105), "AUDIO: WASAPI 48kHz -> 16kHz", fill=(79, 216, 255, 255), font=font_mono)

        # Top-Right: Latency & VAD
        draw.rounded_rectangle([W - 480, 40, W - 50, 150], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((W - 460, 52), f"SILERO VAD: {'ACTIVE' if audio_level > 0.2 else 'LISTENING'}", fill=(255, 207, 107, 255), font=font_mono_bold)
        draw.text((W - 460, 80), "END-TO-END LATENCY: 142 ms", fill=(16, 185, 129, 255), font=font_mono)
        draw.text((W - 460, 105), "CAPABILITIES: 140 ACTIVE", fill=(255, 106, 227, 255), font=font_mono)

        # Bottom-Left: TTS Chunk Stream
        draw.rounded_rectangle([50, H - 150, 480, H - 40], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((70, H - 138), "TTS: PRODUCER-CONSUMER LIVE", fill=(79, 216, 255, 255), font=font_mono_bold)
        draw.text((70, H - 110), "STREAM BUFFER: 80-200 CHARS", fill=(220, 215, 235, 230), font=font_mono)
        draw.text((70, H - 85), "UNDERRUNS / CLIPPING: 0 (ZERO)", fill=(16, 185, 129, 255), font=font_mono)

        # Bottom-Right: Test Status
        draw.rounded_rectangle([W - 480, H - 150, W - 50, H - 40], radius=12, fill=(18, 12, 32, 220), outline=(60, 45, 95, 200), width=1)
        draw.text((W - 460, H - 138), "REGRESSION TESTS: 3 297 PASSED", fill=(16, 185, 129, 255), font=font_mono_bold)
        draw.text((W - 460, H - 110), "FORMAL PROVERIF: THEOREMS TRUE", fill=(255, 207, 107, 255), font=font_mono)
        draw.text((W - 460, H - 85), f"FRAME: {frame_idx:03d}/{TOTAL_FRAMES} (30 FPS)", fill=(160, 150, 180, 200), font=font_mono)

        # Write RGB bytes to ffmpeg pipe
        raw_bytes = img.convert("RGB").tobytes()
        proc.stdin.write(raw_bytes)

        if frame_idx % 60 == 0:
            print(f"  Frame {frame_idx}/{TOTAL_FRAMES} rendered ({frame_idx/TOTAL_FRAMES*100:.1f}%)")

    proc.stdin.close()
    proc.wait()
    print("Done rendering sakura-hud-voice-core.mp4!")
    print(f"File size: {os.path.getsize(mp4_path) / 1024 / 1024:.2f} MB")

    # Generate WEBM version
    webm_path = os.path.join(OUT_DIR, "sakura-hud-voice-core.webm")
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
    print("Done rendering sakura-hud-voice-core.webm!")
    if os.path.exists(webm_path):
        print(f"WebM size: {os.path.getsize(webm_path) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    generate_hud_video()
