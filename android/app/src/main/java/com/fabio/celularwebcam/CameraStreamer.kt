package com.fabio.celularwebcam

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Rect
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.util.Range
import android.util.Size
import android.view.Surface
import org.json.JSONObject
import kotlin.math.abs

/**
 * Abre a camera, manda a imagem para a tela do celular e para o encoder H.264,
 * e aplica os ajustes (zoom, brilho, foco...) vindos do celular ou do PC.
 *
 * Tudo que mexe na camera roda na thread "camera".
 */
class CameraStreamer(context: Context, private val listener: Listener) {

    interface Listener {
        fun onVideo(data: ByteArray, ptsUs: Long, keyFrame: Boolean, config: Boolean)
        fun onStateChanged(settings: CamSettings)
        fun onPreviewSize(width: Int, height: Int)
        fun onError(message: String)
    }

    private val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    val cameras: List<CameraCaps> = CameraCaps.loadAll(context)

    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val encThread = HandlerThread("encoder").apply { start() }
    private val encHandler = Handler(encThread.looper)

    /** So e alterado na thread "camera". Para ler de fora, use [snapshot]. */
    private var settings = CamSettings()
    @Volatile private var published = CamSettings()

    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    @Volatile private var encoder: MediaCodec? = null
    private var encoderSurface: Surface? = null
    private var previewSurface: Surface? = null
    private var previewTexture: SurfaceTexture? = null
    /** Falso com a tela apagada: a previa sai da captura e o encoder segue sozinho. */
    private var previewActive = true
    private var running = false
    private var opening = false

    /** Muda a cada sessao nova; callbacks de sessoes antigas sao ignorados. */
    @Volatile private var generation = 0

    /** SPS/PPS do encoder atual, reenviado a cada PC que conecta. */
    @Volatile var lastConfig: ByteArray? = null
        private set

    /** Rotacao da tela (graus), para calcular quanto girar a imagem no PC. */
    @Volatile var displayRotation = 90

    init {
        val cam = cameras.firstOrNull { it.facing == "back" } ?: cameras.firstOrNull()
        if (cam != null) {
            settings.cameraId = cam.id
            val preferred = cam.sizes.firstOrNull { it[0] == 1920 && it[1] == 1080 }
                ?: cam.sizes.firstOrNull { it[0] == 1280 && it[1] == 720 }
                ?: cam.sizes.first()
            settings.width = preferred[0]
            settings.height = preferred[1]
            settings.fps = 30
        }
        sanitize()
        published = settings.copy()
    }

    fun snapshot(): CamSettings = published.copy()

    fun caps(id: String = published.cameraId): CameraCaps? = cameras.firstOrNull { it.id == id }

    /** Quantos graus (sentido horario) girar a imagem para ela ficar em pe. */
    fun uprightRotation(): Int {
        val cam = caps() ?: return 0
        return if (cam.facing == "front") (cam.sensorOrientation + displayRotation) % 360
        else (cam.sensorOrientation - displayRotation + 360) % 360
    }

    fun start() {
        handler.post {
            running = true
            if (device == null) openCamera()
        }
    }

    fun stop() {
        handler.post {
            running = false
            closeAll()
        }
    }

    fun release() {
        stop()
        handler.post {
            thread.quitSafely()
            encThread.quitSafely()
        }
    }

    /** Quem chama entrega a textura: ela e liberada aqui, depois que a camera largar dela. */
    fun setPreviewTexture(texture: SurfaceTexture?) {
        handler.post {
            val old = previewTexture
            previewTexture = texture
            if (old !== texture) {
                if (running && device != null) restartSession()
                old?.release()
            }
        }
    }

    /**
     * Liga/desliga a previa sem refazer a sessao: o encoder nao para, entao o video
     * do PC nem pisca ao bloquear e desbloquear o celular.
     */
    fun setPreviewActive(active: Boolean) {
        handler.post {
            if (previewActive != active) {
                previewActive = active
                updateRequest()
            }
        }
    }

    /** Aplica um conjunto de ajustes (mesmo formato de [CamSettings.toJson]). */
    fun apply(patch: JSONObject) {
        handler.post {
            val old = settings.copy()
            settings.patch(patch)
            sanitize()
            if (running && device != null) {
                when {
                    settings.cameraId != old.cameraId -> {
                        closeAll()
                        openCamera()
                    }
                    settings.needsRestart(old) -> restartSession()
                    else -> {
                        if (settings.effectiveBitrate() != old.effectiveBitrate()) setLiveBitrate()
                        updateRequest()
                    }
                }
            } else if (running && !opening) {
                openCamera() // a camera tinha falhado: aproveita o pedido para tentar de novo
            }
            publish()
        }
    }

    fun requestKeyFrame() {
        encHandler.post {
            runCatching {
                encoder?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
            }
        }
    }

    private fun publish() {
        published = settings.copy()
        listener.onStateChanged(published.copy())
    }

    /** Garante que os ajustes estao dentro do que a camera escolhida aceita. */
    private fun sanitize() {
        val cam = caps(settings.cameraId) ?: cameras.firstOrNull() ?: return
        settings.cameraId = cam.id
        val s = settings

        if (cam.sizes.none { it[0] == s.width && it[1] == s.height }) {
            // Mesma proporcao e area mais parecida
            val aspect = s.width.toDouble() / s.height
            val area = s.width.toDouble() * s.height
            val best = cam.sizes.minByOrNull {
                abs(it[0].toDouble() / it[1] - aspect) * 10 + abs(it[0].toDouble() * it[1] - area) / area
            }!!
            s.width = best[0]
            s.height = best[1]
        }
        val fpsOpts = cam.fpsOptions(s.width, s.height)
        if (fpsOpts.isNotEmpty() && s.fps !in fpsOpts) {
            s.fps = fpsOpts.filter { it <= s.fps }.maxOrNull() ?: fpsOpts.first()
        }
        s.zoom = s.zoom.coerceIn(cam.zoomMin, cam.zoomMax)
        s.ev = s.ev.coerceIn(cam.evMin, cam.evMax)
        if (!cam.hasFlash) s.torch = false
        if (cam.minFocusDist <= 0f) s.afAuto = true
        s.focus = s.focus.coerceIn(0f, 1f)
        if (s.awb !in cam.awbModes) s.awb = "auto"
        if (!cam.manualSensor) s.aeManual = false
        s.iso = s.iso.coerceIn(cam.isoMin, cam.isoMax)
        s.shutterNs = s.shutterNs.coerceIn(cam.expMinNs, cam.expMaxNs)
        if (!cam.stabilization) s.stab = false
        s.bitrate = s.bitrate.coerceIn(0, 80_000_000)
    }

    @SuppressLint("MissingPermission")
    private fun openCamera() {
        if (opening || !running) return
        val id = settings.cameraId
        if (id.isEmpty()) {
            listener.onError("Nenhuma câmera encontrada")
            return
        }
        opening = true
        try {
            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    opening = false
                    if (!running || camera.id != settings.cameraId) {
                        camera.close()
                        if (running) openCamera()
                        return
                    }
                    device = camera
                    startSession()
                }

                override fun onDisconnected(camera: CameraDevice) {
                    opening = false
                    camera.close()
                    if (device == camera) {
                        stopSession()
                        device = null
                    }
                    listener.onError("Câmera ocupada por outro app; tentando de novo...")
                    retryOpen()
                }

                override fun onError(camera: CameraDevice, error: Int) {
                    opening = false
                    camera.close()
                    if (device == camera) {
                        stopSession()
                        device = null
                    }
                    listener.onError("Erro na câmera ($error); tentando de novo...")
                    retryOpen()
                }
            }, handler)
        } catch (e: Exception) {
            opening = false
            listener.onError("Não foi possível abrir a câmera: ${e.message}")
            retryOpen()
        }
    }

    /** Tenta abrir a camera de novo daqui a pouco (ex.: ainda presa por outro app). */
    private fun retryOpen() {
        handler.postDelayed({ if (running && device == null) openCamera() }, 1500)
    }

    private fun startSession() {
        val dev = device ?: return
        val gen = ++generation
        val s = settings.copy()

        val codec = try {
            createEncoder(s, gen)
        } catch (e: Exception) {
            Log.e(TAG, "encoder", e)
            listener.onError("O celular não conseguiu codificar ${s.width}x${s.height} a ${s.fps} FPS")
            return
        }
        encoder = codec
        val encSurface = codec.createInputSurface()
        encoderSurface = encSurface
        codec.start()

        val surfaces = mutableListOf(encSurface)
        previewTexture?.let { tex ->
            val ps = choosePreviewSize(dev.id, s.width, s.height)
            tex.setDefaultBufferSize(ps.width, ps.height)
            val surface = Surface(tex)
            previewSurface = surface
            surfaces += surface
            listener.onPreviewSize(ps.width, ps.height)
        }

        fun failed() {
            if (gen == generation) listener.onError("A câmera não aceitou ${s.width}x${s.height} a ${s.fps} FPS")
        }

        try {
            @Suppress("DEPRECATION")
            dev.createCaptureSession(surfaces, object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(sess: CameraCaptureSession) {
                    if (gen != generation) {
                        sess.close()
                        return
                    }
                    session = sess
                    updateRequest()
                    publish() // limpa o aviso de erro, se a camera acabou de se recuperar
                }

                override fun onConfigureFailed(sess: CameraCaptureSession) = failed()
            }, handler)
        } catch (e: Exception) {
            Log.e(TAG, "createSession", e)
            failed()
        }
    }

    private fun createEncoder(s: CamSettings, gen: Int): MediaCodec {
        val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, s.width, s.height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, s.effectiveBitrate())
            setInteger(MediaFormat.KEY_FRAME_RATE, s.fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2)
            setInteger(MediaFormat.KEY_PRIORITY, 0) // tempo real
            if (Build.VERSION.SDK_INT >= 29) {
                setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                setInteger(MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES, 1)
            }
        }
        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        codec.setCallback(object : MediaCodec.Callback() {
            override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {}

            override fun onOutputBufferAvailable(codec: MediaCodec, index: Int, info: MediaCodec.BufferInfo) {
                try {
                    if (gen == generation && info.size > 0) {
                        val buf = codec.getOutputBuffer(index)
                        if (buf != null) {
                            buf.position(info.offset)
                            buf.limit(info.offset + info.size)
                            val data = ByteArray(info.size)
                            buf.get(data)
                            val config = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                            val key = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                            if (config) lastConfig = data
                            listener.onVideo(data, info.presentationTimeUs, key, config)
                        }
                    }
                    codec.releaseOutputBuffer(index, false)
                } catch (_: IllegalStateException) {
                    // encoder ja foi parado
                }
            }

            override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                Log.e(TAG, "encoder error", e)
            }

            override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {}
        }, encHandler)
        try {
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        } catch (e: Exception) {
            codec.release()
            throw e
        }
        return codec
    }

    private fun setLiveBitrate() {
        val br = settings.effectiveBitrate()
        runCatching {
            encoder?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, br) })
        }
    }

    /** Tela do celular: mesma proporcao do video, no maximo 1080p. */
    private fun choosePreviewSize(cameraId: String, w: Int, h: Int): Size {
        val map = manager.getCameraCharacteristics(cameraId)
            .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val options = map?.getOutputSizes(SurfaceTexture::class.java) ?: return Size(w, h)
        val aspect = w.toDouble() / h
        return options
            .filter { abs(it.width.toDouble() / it.height - aspect) < 0.02 && it.width <= 1920 && it.height <= 1080 }
            .maxByOrNull { it.width * it.height }
            ?: Size(w, h)
    }

    private fun pickFpsRange(cam: CameraCaps, fps: Int, lowLight: Boolean): Range<Int> {
        val same = cam.fpsRanges.filter { it[1] == fps }
        val chosen = when {
            same.isEmpty() -> cam.fpsRanges.minByOrNull { abs(it[1] - fps) }
            // Pouca luz: deixa o FPS cair para expor mais tempo cada quadro
            lowLight -> same.minByOrNull { it[0] }
            else -> same.maxByOrNull { it[0] }
        } ?: intArrayOf(fps, fps)
        return Range(chosen[0], chosen[1])
    }

    private fun updateRequest() {
        val sess = session ?: return
        val dev = device ?: return
        val cam = caps(dev.id) ?: return
        val s = settings
        try {
            val b = dev.createCaptureRequest(CameraDevice.TEMPLATE_RECORD)
            encoderSurface?.let { b.addTarget(it) }
            if (previewActive) previewSurface?.let { b.addTarget(it) }

            b.set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO)
            b.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, pickFpsRange(cam, s.fps, s.lowLight))

            if (s.aeManual && cam.manualSensor) {
                val frameNs = 1_000_000_000L / s.fps
                b.set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_OFF)
                b.set(CaptureRequest.SENSOR_SENSITIVITY, s.iso)
                b.set(CaptureRequest.SENSOR_EXPOSURE_TIME, minOf(s.shutterNs, frameNs))
                b.set(CaptureRequest.SENSOR_FRAME_DURATION, frameNs)
            } else {
                val aeMode = if (s.lowLight && cam.lowLightBoost && !s.torch) CameraCaps.AE_MODE_LOW_LIGHT_BOOST
                else CameraMetadata.CONTROL_AE_MODE_ON
                b.set(CaptureRequest.CONTROL_AE_MODE, aeMode)
                b.set(CaptureRequest.CONTROL_AE_EXPOSURE_COMPENSATION, s.ev)
                b.set(CaptureRequest.CONTROL_AE_LOCK, s.aeLock)
            }
            b.set(CaptureRequest.FLASH_MODE, if (s.torch) CameraMetadata.FLASH_MODE_TORCH else CameraMetadata.FLASH_MODE_OFF)

            if (cam.minFocusDist > 0f) {
                if (s.afAuto) {
                    val af = if (CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO in cam.afModes)
                        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO else CameraMetadata.CONTROL_AF_MODE_AUTO
                    b.set(CaptureRequest.CONTROL_AF_MODE, af)
                } else {
                    b.set(CaptureRequest.CONTROL_AF_MODE, CameraMetadata.CONTROL_AF_MODE_OFF)
                    b.set(CaptureRequest.LENS_FOCUS_DISTANCE, s.focus * cam.minFocusDist)
                }
            }

            b.set(CaptureRequest.CONTROL_AWB_MODE, CameraCaps.awbFromName(s.awb))
            b.set(CaptureRequest.CONTROL_AWB_LOCK, s.awbLock)

            if (cam.stabilization) {
                b.set(
                    CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,
                    if (s.stab) CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_ON
                    else CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF,
                )
            }

            if (cam.zoomByRatio && Build.VERSION.SDK_INT >= 30) {
                b.set(CaptureRequest.CONTROL_ZOOM_RATIO, s.zoom)
            } else if (s.zoom > 1f) {
                val active = manager.getCameraCharacteristics(dev.id)
                    .get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
                if (active != null) {
                    val cw = (active.width() / s.zoom).toInt()
                    val chh = (active.height() / s.zoom).toInt()
                    val left = (active.width() - cw) / 2
                    val top = (active.height() - chh) / 2
                    b.set(CaptureRequest.SCALER_CROP_REGION, Rect(left, top, left + cw, top + chh))
                }
            }

            sess.setRepeatingRequest(b.build(), null, handler)
        } catch (e: Exception) {
            Log.e(TAG, "updateRequest", e)
        }
    }

    private fun stopSession() {
        generation++
        runCatching { session?.close() }
        session = null
        runCatching { encoder?.stop() }
        runCatching { encoder?.release() }
        encoder = null
        runCatching { encoderSurface?.release() }
        encoderSurface = null
        runCatching { previewSurface?.release() }
        previewSurface = null
        lastConfig = null
    }

    private fun restartSession() {
        stopSession()
        if (device != null) startSession()
    }

    private fun closeAll() {
        stopSession()
        runCatching { device?.close() }
        device = null
    }

    companion object {
        private const val TAG = "CameraStreamer"
    }
}
