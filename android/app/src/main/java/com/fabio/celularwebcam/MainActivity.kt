package com.fabio.celularwebcam

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Point
import android.graphics.RectF
import android.graphics.SurfaceTexture
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONObject
import java.net.Inet4Address
import java.net.NetworkInterface
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.min
import kotlin.math.roundToInt

class MainActivity : Activity(), WebcamEngine.Ui {

    private lateinit var engine: WebcamEngine
    private lateinit var streamer: CameraStreamer
    private lateinit var server: StreamServer

    private lateinit var textureView: TextureView
    private lateinit var statusText: TextView
    private lateinit var panelScroll: ScrollView
    private lateinit var panel: LinearLayout
    private lateinit var darkOverlay: View
    private lateinit var torchButton: Button

    private var previewW = 0
    private var previewH = 0
    private var panelCameraId: String? = null
    private var hasPermission = false

    /** Atualiza os controles do painel com o estado atual (sem disparar envio). */
    private val panelUpdaters = mutableListOf<(CamSettings) -> Unit>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        engine = WebcamEngine.get(this)
        streamer = engine.streamer
        server = engine.server
        engine.ui = this

        buildUi()
        engine.start()

        hasPermission = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        val wanted = mutableListOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)

        updateStatus()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        hasPermission = checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        if (hasPermission) {
            WebcamService.start(this)
            engine.onCameraPermissionGranted()
        }
        updateStatus()
    }

    override fun onStart() {
        super.onStart()
        // Motor encerrado pela notificacao enquanto esta tela estava parada
        if (WebcamEngine.peek() !== engine) {
            finishAndRemoveTask()
            return
        }
        if (hasPermission) WebcamService.start(this)
        updateDisplayRotation()
        engine.setUiVisible(true)
    }

    override fun onStop() {
        super.onStop()
        // Nao desliga a camera: quem decide e o motor, conforme houver PC conectado
        engine.setUiVisible(false)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (engine.ui === this) engine.ui = null
    }

    /**
     * O app so roda deitado. Ao desbloquear, o aparelho ainda pode estar em pe por um
     * instante: esse valor nao serve, pois giraria a imagem no PC sem motivo.
     */
    private fun updateDisplayRotation() {
        @Suppress("DEPRECATION")
        val display = windowManager.defaultDisplay
        val size = Point()
        @Suppress("DEPRECATION")
        display.getRealSize(size)
        if (size.x < size.y) return
        streamer.displayRotation = when (display.rotation) {
            Surface.ROTATION_90 -> 90
            Surface.ROTATION_180 -> 180
            Surface.ROTATION_270 -> 270
            else -> 0
        }
    }

    // ---------------------------------------------------------------- tela

    private fun dp(v: Int) = (v * resources.displayMetrics.density).roundToInt()

    private fun buildUi() {
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }

        textureView = TextureView(this)
        textureView.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
                streamer.setPreviewTexture(st)
            }

            override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) = applyPreviewTransform()

            override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
                streamer.setPreviewTexture(null)
                return false // quem libera e o CameraStreamer, depois de soltar a camera
            }

            override fun onSurfaceTextureUpdated(st: SurfaceTexture) {}
        }
        root.addView(textureView, FrameLayout.LayoutParams(-1, -1))

        statusText = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 15f
            setBackgroundColor(0x99000000.toInt())
            setPadding(dp(12), dp(8), dp(12), dp(8))
        }
        root.addView(statusText, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.START).apply {
            setMargins(dp(12), dp(12), 0, 0)
        })

        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        fun barButton(text: String, onClick: () -> Unit) = Button(this).apply {
            this.text = text
            isAllCaps = false
            setOnClickListener { onClick() }
            bar.addView(this, LinearLayout.LayoutParams(-2, -2).apply { marginEnd = dp(6) })
        }
        barButton("Trocar câmera") { switchCamera() }
        torchButton = barButton("Lanterna") {
            sendPatch(JSONObject().put("torch", !streamer.snapshot().torch))
        }
        barButton("Ajustes") {
            panelScroll.visibility = if (panelScroll.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }
        barButton("Tela escura") { setDark(true) }
        barButton("Encerrar") { WebcamService.stop(this) }
        root.addView(bar, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.START).apply {
            setMargins(dp(12), 0, 0, dp(12))
        })

        panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(10))
        }
        panelScroll = ScrollView(this).apply {
            setBackgroundColor(0xDD111111.toInt())
            visibility = View.GONE
            addView(panel)
        }
        root.addView(panelScroll, FrameLayout.LayoutParams(dp(340), -1, Gravity.END))

        darkOverlay = View(this).apply {
            setBackgroundColor(Color.BLACK)
            visibility = View.GONE
            setOnClickListener { setDark(false) }
        }
        root.addView(darkOverlay, FrameLayout.LayoutParams(-1, -1))

        setContentView(root)
    }

    private fun setDark(dark: Boolean) {
        darkOverlay.visibility = if (dark) View.VISIBLE else View.GONE
        window.attributes = window.attributes.apply {
            screenBrightness = if (dark) 0.01f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        }
    }

    private fun switchCamera() {
        val cams = streamer.cameras
        if (cams.size < 2) return
        val i = cams.indexOfFirst { it.id == streamer.snapshot().cameraId }
        sendPatch(JSONObject().put("camera", cams[(i + 1) % cams.size].id))
    }

    private fun sendPatch(patch: JSONObject) = streamer.apply(patch)

    private fun applyPreviewTransform() {
        val vw = textureView.width.toFloat()
        val vh = textureView.height.toFloat()
        if (vw == 0f || previewW == 0) return
        @Suppress("DEPRECATION")
        val rotation = windowManager.defaultDisplay.rotation
        val matrix = Matrix()
        val viewRect = RectF(0f, 0f, vw, vh)
        val cx = viewRect.centerX()
        val cy = viewRect.centerY()
        if (rotation == Surface.ROTATION_90 || rotation == Surface.ROTATION_270) {
            val bufferRect = RectF(0f, 0f, previewH.toFloat(), previewW.toFloat())
            bufferRect.offset(cx - bufferRect.centerX(), cy - bufferRect.centerY())
            matrix.setRectToRect(viewRect, bufferRect, Matrix.ScaleToFit.FILL)
            val scale = min(vh / previewH, vw / previewW)
            matrix.postScale(scale, scale, cx, cy)
            matrix.postRotate(90f * (rotation - 2), cx, cy)
        } else if (rotation == Surface.ROTATION_180) {
            matrix.postRotate(180f, cx, cy)
        }
        textureView.setTransform(matrix)
    }

    private fun localIps(): List<String> = runCatching {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .filterIsInstance<Inet4Address>()
            .map { it.hostAddress ?: "" }
            .filter { it.isNotEmpty() }
    }.getOrDefault(emptyList())

    private fun updateStatus() = runOnUiThread {
        val s = streamer.snapshot()
        val cam = streamer.caps()
        val lines = mutableListOf<String>()
        val ips = localIps()
        lines += if (ips.isEmpty()) "Sem Wi-Fi (use o cabo USB)" else "IP: ${ips.joinToString("  /  ")}"
        val client = server.clientName
        lines += when {
            client == null -> "Aguardando o PC..."
            client == "127.0.0.1" -> "Conectado pelo cabo USB"
            else -> "Conectado ao PC $client"
        }
        if (cam != null) {
            lines += "${cam.label} · ${s.width}x${s.height} · ${s.fps} FPS" + (if (s.audio) " · microfone" else "")
        }
        engine.lastError?.let { lines += "⚠ $it" }
        statusText.text = lines.joinToString("\n")
        torchButton.visibility = if (cam?.hasFlash == true) View.VISIBLE else View.GONE
        torchButton.text = if (s.torch) "Lanterna: ligada" else "Lanterna"
    }

    // ---------------------------------------------------------------- painel de ajustes

    private fun rebuildPanel(cam: CameraCaps) {
        panel.removeAllViews()
        panelUpdaters.clear()
        panelCameraId = cam.id

        fun title(text: String) = TextView(this).apply {
            this.text = text
            setTextColor(0xFFB0BEC5.toInt())
            textSize = 13f
            setPadding(0, dp(10), 0, dp(2))
            panel.addView(this)
        }

        fun spinner(label: String, items: List<String>, current: (CamSettings) -> Int, onPick: (Int) -> Unit) {
            title(label)
            val sp = Spinner(this)
            sp.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, items)
            sp.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                    (view as? TextView)?.setTextColor(Color.WHITE)
                    if (pos != current(streamer.snapshot())) onPick(pos)
                }

                override fun onNothingSelected(parent: AdapterView<*>?) {}
            }
            panel.addView(sp)
            panelUpdaters += { s -> current(s).let { if (it >= 0 && sp.selectedItemPosition != it) sp.setSelection(it) } }
        }

        fun slider(
            label: String,
            max: Int,
            toProgress: (CamSettings) -> Int,
            format: (Int) -> String,
            onChange: (Int) -> Unit,
            enabled: (CamSettings) -> Boolean = { true },
        ) {
            val t = title(label)
            val sb = SeekBar(this)
            sb.max = max
            sb.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(bar: SeekBar, p: Int, fromUser: Boolean) {
                    t.text = "$label: ${format(p)}"
                    if (fromUser) onChange(p)
                }

                override fun onStartTrackingTouch(bar: SeekBar) {}
                override fun onStopTrackingTouch(bar: SeekBar) {}
            })
            panel.addView(sb)
            panelUpdaters += { s ->
                val p = toProgress(s)
                if (sb.progress != p && !sb.isPressed) sb.progress = p
                t.text = "$label: ${format(p)}"
                sb.isEnabled = enabled(s)
            }
        }

        fun check(label: String, get: (CamSettings) -> Boolean, key: String, enabled: (CamSettings) -> Boolean = { true }) {
            val cb = CheckBox(this)
            cb.text = label
            cb.setTextColor(Color.WHITE)
            cb.setOnCheckedChangeListener { _, checked ->
                if (checked != get(streamer.snapshot())) sendPatch(JSONObject().put(key, checked))
            }
            panel.addView(cb)
            panelUpdaters += { s ->
                if (cb.isChecked != get(s)) cb.isChecked = get(s)
                cb.isEnabled = enabled(s)
            }
        }

        // Resolucao e FPS
        val sizes = cam.sizes
        spinner(
            "Resolução", sizes.map { "${it[0]} x ${it[1]}" },
            { s -> sizes.indexOfFirst { it[0] == s.width && it[1] == s.height } },
        ) { i -> sendPatch(JSONObject().put("width", sizes[i][0]).put("height", sizes[i][1])) }

        // A lista de FPS depende da resolucao: recalculada quando o estado muda
        title("FPS")
        val fpsSpinner = Spinner(this)
        var fpsItems = listOf<Int>()
        fpsSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                (view as? TextView)?.setTextColor(Color.WHITE)
                val fps = fpsItems.getOrNull(pos) ?: return
                if (fps != streamer.snapshot().fps) sendPatch(JSONObject().put("fps", fps))
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        panel.addView(fpsSpinner)
        val fpsNote = TextView(this).apply {
            setTextColor(0xFF90A4AE.toInt())
            textSize = 12f
        }
        panel.addView(fpsNote)
        panelUpdaters += { s ->
            val opts = cam.fpsOptions(s.width, s.height)
            if (opts != fpsItems) {
                fpsItems = opts
                fpsSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, opts.map { "$it FPS" })
            }
            val i = opts.indexOf(s.fps)
            if (i >= 0 && fpsSpinner.selectedItemPosition != i) fpsSpinner.setSelection(i)
            fpsNote.text = if (60 !in opts) {
                "Este celular libera até ${opts.maxOrNull() ?: 30} FPS para outros apps nesta resolução."
            } else ""
            fpsNote.visibility = if (fpsNote.text.isEmpty()) View.GONE else View.VISIBLE
        }

        spinner(
            "Qualidade (taxa de bits)", QUALITY.map { it.first },
            { s -> QUALITY.indexOfFirst { it.second == s.bitrate }.let { if (it < 0) 0 else it } },
        ) { i -> sendPatch(JSONObject().put("bitrate", QUALITY[i].second)) }

        if (cam.zoomMax > cam.zoomMin) {
            slider(
                "Zoom", 1000,
                { s -> ((s.zoom - cam.zoomMin) / (cam.zoomMax - cam.zoomMin) * 1000).roundToInt() },
                { p -> "%.1fx".format(cam.zoomMin + (cam.zoomMax - cam.zoomMin) * p / 1000f) },
                { p -> sendPatch(JSONObject().put("zoom", (cam.zoomMin + (cam.zoomMax - cam.zoomMin) * p / 1000f).toDouble())) },
            )
        }

        if (cam.evMax > cam.evMin) {
            slider(
                "Brilho", cam.evMax - cam.evMin,
                { s -> s.ev - cam.evMin },
                { p -> "%+.1f".format((p + cam.evMin) * cam.evStep) },
                { p -> sendPatch(JSONObject().put("ev", p + cam.evMin)) },
                { s -> !s.aeManual },
            )
        }

        if (cam.lowLightBoost || cam.fpsRanges.any { it[0] < it[1] }) {
            check("Modo pouca luz", { it.lowLight }, "lowLight")
        }
        check("Travar exposição", { it.aeLock }, "aeLock", { !it.aeManual })

        if (cam.minFocusDist > 0f) {
            check("Foco automático", { it.afAuto }, "afAuto")
            slider(
                "Foco", 1000,
                { s -> (s.focus * 1000).roundToInt() },
                { p -> if (p == 0) "infinito" else "${p / 10}%" },
                { p -> sendPatch(JSONObject().put("focus", p / 1000.0)) },
                { s -> !s.afAuto },
            )
        }

        if (cam.awbModes.size > 1) {
            spinner(
                "Balanço de branco", cam.awbModes.map { AWB_LABELS[it] ?: it },
                { s -> cam.awbModes.indexOf(s.awb) },
            ) { i -> sendPatch(JSONObject().put("awb", cam.awbModes[i])) }
        }
        check("Travar cor", { it.awbLock }, "awbLock")

        if (cam.manualSensor) {
            check("Exposição manual (ISO / obturador)", { it.aeManual }, "aeManual")
            slider(
                "ISO", 1000,
                { s -> ((s.iso - cam.isoMin).toFloat() / (cam.isoMax - cam.isoMin) * 1000).roundToInt() },
                { p -> "${cam.isoMin + (cam.isoMax - cam.isoMin) * p / 1000}" },
                { p -> sendPatch(JSONObject().put("iso", cam.isoMin + (cam.isoMax - cam.isoMin) * p / 1000)) },
                { s -> s.aeManual },
            )
            val expMax = minOf(cam.expMaxNs, 100_000_000L) // ate 1/10 s
            val lnMin = ln(cam.expMinNs.toDouble())
            val lnMax = ln(expMax.toDouble())
            fun nsFromProgress(p: Int) = exp(lnMin + (lnMax - lnMin) * p / 1000.0).toLong()
            slider(
                "Obturador", 1000,
                { s -> ((ln(s.shutterNs.toDouble()) - lnMin) / (lnMax - lnMin) * 1000).roundToInt().coerceIn(0, 1000) },
                { p -> "1/${(1_000_000_000.0 / nsFromProgress(p)).roundToInt()} s" },
                { p -> sendPatch(JSONObject().put("shutterNs", nsFromProgress(p))) },
                { s -> s.aeManual },
            )
        }

        if (cam.stabilization) check("Estabilização (aumenta o atraso)", { it.stab }, "stab")
        check("Enviar microfone do celular", { it.audio }, "audio")

        val note = TextView(this).apply {
            text = "Pode bloquear o celular: a câmera continua enviando para o PC e gasta menos bateria. " +
                "Para desligar de vez, use Encerrar aqui ou na notificação."
            setTextColor(0xFF90A4AE.toInt())
            textSize = 12f
            setPadding(0, dp(14), 0, dp(4))
        }
        panel.addView(note, ViewGroup.LayoutParams(-1, -2))
    }

    private fun refreshPanel(s: CamSettings) = runOnUiThread {
        val cam = streamer.caps(s.cameraId) ?: return@runOnUiThread
        if (panelCameraId != cam.id) rebuildPanel(cam)
        panelUpdaters.forEach { it(s) }
    }

    // ---------------------------------------------------------------- avisos do motor

    override fun onEngineChanged(settings: CamSettings) {
        refreshPanel(settings)
        updateStatus()
    }

    override fun onPreviewSize(width: Int, height: Int) = runOnUiThread {
        previewW = width
        previewH = height
        applyPreviewTransform()
    }

    override fun onEngineClosed() = runOnUiThread { finishAndRemoveTask() }

    // ----------------------------------------------------------------

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) refreshPanel(streamer.snapshot())
    }

    companion object {
        val QUALITY = listOf(
            "Automática" to 0,
            "Baixa (4 Mbps)" to 4_000_000,
            "Média (8 Mbps)" to 8_000_000,
            "Alta (16 Mbps)" to 16_000_000,
            "Muito alta (30 Mbps)" to 30_000_000,
        )

        val AWB_LABELS = mapOf(
            "auto" to "Automático",
            "daylight" to "Luz do dia",
            "cloudy" to "Nublado",
            "fluorescent" to "Fluorescente",
            "incandescent" to "Incandescente (amarelada)",
            "warm" to "Fluorescente quente",
            "shade" to "Sombra",
            "twilight" to "Crepúsculo",
        )
    }
}
