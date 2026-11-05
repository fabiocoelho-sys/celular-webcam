package com.fabio.celularwebcam

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import kotlin.concurrent.thread

/** Microfone do celular: PCM 16 bits, mono, 48 kHz, em blocos de 10 ms. */
class AudioStreamer(private val onAudio: (ByteArray, Int, Long) -> Unit) {

    @Volatile private var running = false
    private var worker: Thread? = null

    @SuppressLint("MissingPermission")
    @Synchronized
    fun start() {
        if (running) return
        running = true
        worker = thread(name = "audio", isDaemon = true) {
            val chunk = SAMPLE_RATE / 100 * 2 // 10 ms
            val minBuf = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            )
            var rec: AudioRecord? = null
            try {
                rec = AudioRecord(
                    MediaRecorder.AudioSource.MIC, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, chunk * 4),
                )
                rec.startRecording()
                val buf = ByteArray(chunk)
                while (running) {
                    val n = rec.read(buf, 0, buf.size)
                    if (n > 0) onAudio(buf, n, SystemClock.elapsedRealtimeNanos() / 1000)
                }
            } catch (e: Exception) {
                Log.e("AudioStreamer", "microfone", e)
            } finally {
                runCatching { rec?.stop() }
                runCatching { rec?.release() }
            }
        }
    }

    @Synchronized
    fun stop() {
        running = false
        worker?.join(500)
        worker = null
    }

    companion object {
        const val SAMPLE_RATE = 48000
    }
}
