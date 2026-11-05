package com.fabio.celularwebcam

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import org.json.JSONArray
import org.json.JSONObject

/**
 * O "motor" da webcam: camera, encoder, servidor, busca na rede, microfone e as
 * travas de energia. Vive fora da tela, para continuar funcionando com o celular
 * bloqueado; a tela (MainActivity) so mostra a previa e o painel.
 *
 * A camera fica ligada enquanto a tela do app estiver visivel OU houver um PC
 * conectado. Fora disso, ela desliga para poupar bateria, e o app so continua
 * esperando o PC, por no maximo [IDLE_LIMIT_MS].
 */
class WebcamEngine private constructor(context: Context) : CameraStreamer.Listener, StreamServer.Callbacks {

    /** O que a tela precisa saber. Pode ser chamado de qualquer thread. */
    interface Ui {
        fun onEngineChanged(settings: CamSettings)
        fun onPreviewSize(width: Int, height: Int)
        fun onEngineClosed()
    }

    private val app = context.applicationContext
    private val main = Handler(Looper.getMainLooper())

    val deviceName = "${Build.MANUFACTURER} ${Build.MODEL}".replaceFirstChar { it.uppercase() }
    val streamer = CameraStreamer(app, this)
    val server = StreamServer(STREAM_PORT, this)
    private val discovery = Discovery(DISCOVERY_PORT, STREAM_PORT, deviceName)
    private val audio = AudioStreamer { data, len, pts -> server.sendAudio(data, len, pts) }

    private var wifiLocks = emptyList<WifiManager.WifiLock>()
    private var multicastLock: WifiManager.MulticastLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    @Volatile var ui: Ui? = null
    @Volatile var lastError: String? = null
        private set

    /** Avisa o servico quando o PC conecta ou desconecta (para atualizar a notificacao). */
    @Volatile var onClientChanged: (() -> Unit)? = null

    private var started = false
    @Volatile private var uiVisible = false

    private val idleStop = Runnable { WebcamService.stop(app) }

    @SuppressLint("WakelockTimeout")
    @Synchronized
    fun start() {
        if (started) return
        started = true

        val wifi = app.getSystemService(Context.WIFI_SERVICE) as WifiManager
        // O modo de baixa latencia so vale com a tela ligada; com ela desligada,
        // quem mantem o Wi-Fi fora da economia de energia e o HIGH_PERF.
        @Suppress("DEPRECATION")
        val modes = listOfNotNull(
            WifiManager.WIFI_MODE_FULL_HIGH_PERF,
            if (Build.VERSION.SDK_INT >= 29) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else null,
        )
        wifiLocks = modes.map { wifi.createWifiLock(it, "celular-webcam:$it").apply { acquire() } }
        multicastLock = wifi.createMulticastLock("celular-webcam").apply { acquire() }
        // Sem isto a CPU dorme quando a tela apaga
        wakeLock = (app.getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "celular-webcam:stream").apply { acquire() }

        server.start()
        discovery.start()
        syncCamera()
    }

    /** A tela do app apareceu ou sumiu (bloqueio, botao Inicio...). */
    fun setUiVisible(visible: Boolean) {
        uiVisible = visible
        streamer.setPreviewActive(visible)
        syncCamera()
    }

    fun onCameraPermissionGranted() = syncCamera()

    private fun hasPermission(permission: String) =
        app.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    private fun syncCamera() {
        val hasClient = server.clientName != null
        if ((uiVisible || hasClient) && hasPermission(Manifest.permission.CAMERA)) streamer.start() else streamer.stop()
        main.removeCallbacks(idleStop)
        if (!uiVisible && !hasClient) main.postDelayed(idleStop, IDLE_LIMIT_MS)
    }

    private fun syncAudio(s: CamSettings) {
        if (s.audio && hasPermission(Manifest.permission.RECORD_AUDIO) && server.clientName != null) audio.start()
        else audio.stop()
    }

    private fun stateMessage(type: String): JSONObject {
        val msg = JSONObject()
            .put("t", type)
            .put("s", streamer.snapshot().toJson())
            .put("rot", streamer.uprightRotation())
        if (type == "hello") {
            msg.put("name", deviceName)
            msg.put("cameras", JSONArray(streamer.cameras.map { it.toJson() }))
        }
        return msg
    }

    /** Desliga tudo. Depois disto, [get] cria um motor novo. */
    @Synchronized
    fun shutdown() {
        main.removeCallbacks(idleStop)
        synchronized(Companion) { if (instance === this) instance = null }
        audio.stop()
        discovery.stop()
        server.stop()
        streamer.release()
        wifiLocks.forEach { runCatching { it.release() } }
        wifiLocks = emptyList()
        runCatching { multicastLock?.release() }
        runCatching { if (wakeLock?.isHeld == true) wakeLock?.release() }
        started = false
        ui?.onEngineClosed()
    }

    // CameraStreamer.Listener

    override fun onVideo(data: ByteArray, ptsUs: Long, keyFrame: Boolean, config: Boolean) =
        server.sendVideo(data, ptsUs, keyFrame, config)

    override fun onStateChanged(settings: CamSettings) {
        lastError = null
        server.sendJson(stateMessage("state"))
        syncAudio(settings)
        ui?.onEngineChanged(settings)
    }

    override fun onPreviewSize(width: Int, height: Int) {
        ui?.onPreviewSize(width, height)
    }

    override fun onError(message: String) {
        lastError = message
        ui?.onEngineChanged(streamer.snapshot())
        server.sendJson(JSONObject().put("t", "error").put("msg", message))
    }

    // StreamServer.Callbacks

    override fun onClientConnected(client: StreamServer.Client) {
        syncCamera()
        server.sendJson(stateMessage("hello"))
        streamer.lastConfig?.let { server.sendVideo(it, 0, false, true) }
        streamer.requestKeyFrame()
        syncAudio(streamer.snapshot())
        ui?.onEngineChanged(streamer.snapshot())
        onClientChanged?.invoke()
    }

    override fun onClientDisconnected() {
        audio.stop()
        syncCamera()
        ui?.onEngineChanged(streamer.snapshot())
        onClientChanged?.invoke()
    }

    override fun onMessage(json: JSONObject) {
        when (json.optString("t")) {
            "set" -> json.optJSONObject("s")?.let { streamer.apply(it) }
            "keyframe" -> streamer.requestKeyFrame()
        }
    }

    override fun onKeyFrameNeeded() = streamer.requestKeyFrame()

    companion object {
        const val STREAM_PORT = 27183
        const val DISCOVERY_PORT = 27184
        private const val IDLE_LIMIT_MS = 10 * 60 * 1000L

        private var instance: WebcamEngine? = null

        @Synchronized
        fun get(context: Context): WebcamEngine =
            instance ?: WebcamEngine(context).also { instance = it }

        @Synchronized
        fun peek(): WebcamEngine? = instance
    }
}
