package app.sakura.mobile.voice;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;

/**
 * AudioTrack MODE_STREAM, PCM16 mono. Маршрут вывода — системный (динамик, гарнитура, BT).
 * Аудиофокус AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK на время хода. Только аудиопоток.
 */
final class AudioTrackSink implements PlaybackController.Sink {
    private final AudioManager audio;
    private final AudioAttributes attrs = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ASSISTANT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build();
    private final AudioFocusRequest focus;
    private AudioTrack track;
    private int rate;
    private long written;

    AudioTrackSink(Context context) {
        audio = context.getSystemService(AudioManager.class);
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(attrs)
                .setOnAudioFocusChangeListener(change -> { })
                .build();
    }

    @Override
    public void open(int sampleRate) {
        if (track == null || rate != sampleRate) {
            release();
            rate = sampleRate;
            int min = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
            track = new AudioTrack.Builder()
                    .setAudioAttributes(attrs)
                    .setAudioFormat(new AudioFormat.Builder()
                            .setSampleRate(rate)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .build())
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .setBufferSizeInBytes(Math.max(min * 4, rate))   // ~0,5 с
                    .build();
        } else {
            track.pause();
            track.flush();
        }
        written = 0;
        if (audio != null) {
            audio.requestAudioFocus(focus);
        }
    }

    @Override
    public void write(byte[] pcm) {
        if (track != null) {
            int n = track.write(pcm, 0, pcm.length, AudioTrack.WRITE_BLOCKING);
            if (n > 0) {
                written += n / 2;
            }
        }
    }

    @Override
    public void play() {
        if (track != null && track.getPlayState() != AudioTrack.PLAYSTATE_PLAYING) {
            track.play();
        }
    }

    @Override
    public void stop() {
        if (track != null) {
            track.pause();
            track.flush();
            written = 0;
        }
        abandon();
    }

    @Override
    public long pendingFrames() {
        if (track == null) {
            return 0;
        }
        long head = track.getPlaybackHeadPosition() & 0xFFFFFFFFL;
        long left = written - head;
        if (left <= 0) {
            abandon();
        }
        return left;
    }

    @Override
    public int underruns() {
        return track == null ? 0 : track.getUnderrunCount();
    }

    @Override
    public void release() {
        if (track != null) {
            track.release();
            track = null;
        }
        abandon();
    }

    private void abandon() {
        if (audio != null) {
            audio.abandonAudioFocusRequest(focus);
        }
    }
}
