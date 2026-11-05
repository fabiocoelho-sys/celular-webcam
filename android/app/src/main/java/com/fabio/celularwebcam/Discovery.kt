package com.fabio.celularwebcam

import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import kotlin.concurrent.thread

/**
 * Responde ao "tem algum celular ai?" que o PC manda por broadcast UDP,
 * para o celular aparecer sozinho na lista do programa do PC.
 */
class Discovery(private val discoveryPort: Int, private val streamPort: Int, private val deviceName: String) {

    @Volatile private var socket: DatagramSocket? = null

    fun start() {
        thread(name = "discovery", isDaemon = true) {
            try {
                val s = DatagramSocket(null)
                s.reuseAddress = true
                s.broadcast = true
                socket = s
                var tentativas = 0
                while (true) {
                    try {
                        s.bind(InetSocketAddress(discoveryPort))
                        break
                    } catch (e: java.net.BindException) {
                        if (socket !== s || ++tentativas >= 40) throw e
                        Thread.sleep(250)
                    }
                }
                val buf = ByteArray(256)
                while (true) {
                    val p = DatagramPacket(buf, buf.size)
                    s.receive(p)
                    val msg = String(p.data, 0, p.length, Charsets.UTF_8)
                    if (msg.startsWith(QUERY)) {
                        val reply = JSONObject()
                            .put("app", "celular-webcam")
                            .put("name", deviceName)
                            .put("port", streamPort)
                            .toString().toByteArray(Charsets.UTF_8)
                        s.send(DatagramPacket(reply, reply.size, p.address, p.port))
                    }
                }
            } catch (e: Exception) {
                Log.i("Discovery", "parou: ${e.message}")
            }
        }
    }

    fun stop() {
        runCatching { socket?.close() }
        socket = null
    }

    companion object {
        const val QUERY = "CELWEBCAM?"
    }
}
