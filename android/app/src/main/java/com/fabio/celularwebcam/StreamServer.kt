package com.fabio.celularwebcam

import android.util.Log
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Servidor TCP do celular. O PC conecta aqui (pelo Wi-Fi, ou pelo cabo usando
 * "adb forward"). Um PC por vez; se outro conectar, o anterior cai.
 *
 * Cada mensagem: tipo (1 byte) + tamanho (4 bytes, big-endian) + conteudo.
 *   1 = JSON (nos dois sentidos)
 *   3 = video H.264: pts em us (8 bytes) + flags (1 byte: 1=keyframe, 2=config) + dados
 *   4 = audio PCM 16 bits mono 48 kHz: pts em us (8 bytes) + amostras
 */
class StreamServer(private val port: Int, private val callbacks: Callbacks) {

    interface Callbacks {
        fun onClientConnected(client: Client)
        fun onClientDisconnected()
        fun onMessage(json: JSONObject)
        fun onKeyFrameNeeded()
    }

    private var serverSocket: ServerSocket? = null
    @Volatile private var client: Client? = null
    @Volatile private var running = false

    val clientName: String? get() = client?.name

    fun start() {
        running = true
        thread(name = "server-accept", isDaemon = true) {
            try {
                val ss = ServerSocket()
                ss.reuseAddress = true
                // A porta pode ainda estar presa por uma tela anterior do app que esta fechando
                var tentativas = 0
                while (true) {
                    try {
                        ss.bind(InetSocketAddress(port))
                        break
                    } catch (e: java.net.BindException) {
                        if (!running || ++tentativas >= 40) throw e
                        Thread.sleep(250)
                    }
                }
                serverSocket = ss
                if (!running) ss.close()
                while (running) {
                    val s = ss.accept()
                    client?.close()
                    val c = Client(s)
                    client = c
                    c.start()
                }
            } catch (e: Exception) {
                if (running) Log.e(TAG, "accept", e)
            }
        }
    }

    fun stop() {
        running = false
        runCatching { serverSocket?.close() }
        client?.close()
        client = null
    }

    fun sendJson(json: JSONObject) {
        client?.enqueue(Packet(TYPE_JSON, json.toString().toByteArray(Charsets.UTF_8)))
    }

    fun sendVideo(data: ByteArray, ptsUs: Long, keyFrame: Boolean, config: Boolean) {
        val c = client ?: return
        var flags = 0
        if (keyFrame) flags = flags or 1
        if (config) flags = flags or 2
        c.offerVideo(Packet(TYPE_VIDEO, data, ptsUs, flags))
    }

    fun sendAudio(data: ByteArray, length: Int, ptsUs: Long) {
        val c = client ?: return
        if (c.queuedBytes.get() > MAX_QUEUE_BYTES) return // atrasado: descarta audio
        c.enqueue(Packet(TYPE_AUDIO, data.copyOf(length), ptsUs, -1))
    }

    /** flags = -1 indica pacote sem byte de flags (audio). */
    class Packet(val type: Int, val data: ByteArray, val ptsUs: Long = 0, val flags: Int = 0)

    inner class Client(private val socket: Socket) {
        val name: String = socket.inetAddress?.hostAddress ?: "?"
        private val queue = LinkedBlockingQueue<Packet>()
        val queuedBytes = AtomicLong(0)
        @Volatile private var closed = false
        /** Fila cheia: descarta quadros ate o proximo keyframe. */
        private var waitingKeyFrame = false

        fun start() {
            socket.tcpNoDelay = true
            socket.sendBufferSize = 1 shl 20
            thread(name = "client-writer", isDaemon = true) { writeLoop() }
            thread(name = "client-reader", isDaemon = true) { readLoop() }
            callbacks.onClientConnected(this)
        }

        fun enqueue(p: Packet) {
            if (closed) return
            queuedBytes.addAndGet(p.data.size.toLong())
            queue.offer(p)
        }

        @Synchronized
        fun offerVideo(p: Packet) {
            if (closed) return
            val isConfig = p.flags and 2 != 0
            val isKey = p.flags and 1 != 0
            if (!isConfig) {
                if (queuedBytes.get() > MAX_QUEUE_BYTES) {
                    // Rede nao esta dando conta: pula quadros para nao acumular atraso
                    if (!waitingKeyFrame) callbacks.onKeyFrameNeeded()
                    waitingKeyFrame = true
                    return
                }
                if (waitingKeyFrame) {
                    if (!isKey) return
                    waitingKeyFrame = false
                }
            }
            enqueue(p)
        }

        private fun writeLoop() {
            try {
                val out = DataOutputStream(BufferedOutputStream(socket.getOutputStream(), 256 * 1024))
                while (!closed) {
                    val p = queue.take()
                    if (p.type == TYPE_CLOSE) break
                    val extra = when (p.type) {
                        TYPE_VIDEO -> 9
                        TYPE_AUDIO -> 8
                        else -> 0
                    }
                    out.writeByte(p.type)
                    out.writeInt(p.data.size + extra)
                    if (p.type == TYPE_VIDEO || p.type == TYPE_AUDIO) out.writeLong(p.ptsUs)
                    if (p.type == TYPE_VIDEO) out.writeByte(p.flags)
                    out.write(p.data)
                    queuedBytes.addAndGet(-p.data.size.toLong())
                    if (queue.isEmpty()) out.flush()
                }
            } catch (e: Exception) {
                Log.i(TAG, "writer: ${e.message}")
            }
            close()
        }

        private fun readLoop() {
            try {
                val input = DataInputStream(BufferedInputStream(socket.getInputStream()))
                while (!closed) {
                    val type = input.readUnsignedByte()
                    val len = input.readInt()
                    if (len < 0 || len > 1 shl 20) break
                    val buf = ByteArray(len)
                    input.readFully(buf)
                    if (type == TYPE_JSON) {
                        runCatching { callbacks.onMessage(JSONObject(String(buf, Charsets.UTF_8))) }
                            .onFailure { Log.w(TAG, "json invalido", it) }
                    }
                }
            } catch (e: Exception) {
                Log.i(TAG, "reader: ${e.message}")
            }
            close()
        }

        fun close() {
            if (closed) return
            closed = true
            queue.offer(Packet(TYPE_CLOSE, ByteArray(0)))
            runCatching { socket.close() }
            if (client === this) {
                client = null
                callbacks.onClientDisconnected()
            }
        }
    }

    companion object {
        private const val TAG = "StreamServer"
        const val TYPE_JSON = 1
        const val TYPE_VIDEO = 3
        const val TYPE_AUDIO = 4
        private const val TYPE_CLOSE = 99
        private const val MAX_QUEUE_BYTES = 3L * 1024 * 1024
    }
}
